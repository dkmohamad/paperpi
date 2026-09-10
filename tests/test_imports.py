"""Guards for the conventions no linter can express.

Both checks walk the AST, so each is also run against a synthetic offender: a
detector with a bug in its walk reports a clean package exactly as a working
one does, and would go on doing so forever.
"""

import ast
import pathlib

import paperpi

PACKAGE = pathlib.Path(paperpi.__file__).parent


def absolute_self_imports(source: str, filename: str = "<test>") -> list[str]:
    """Report imports of the package by its absolute name.

    Args:
        source: Python source to inspect.
        filename: Name used in the reported location.

    Returns:
        One entry per offending import.
    """
    offenders: list[str] = []
    tree = ast.parse(source, filename=filename)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.level == 0 and (node.module or "").startswith("paperpi"):
                offenders.append(f"{filename}:{node.lineno} from {node.module}")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("paperpi"):
                    offenders.append(f"{filename}:{node.lineno} import {alias.name}")
    return offenders


def declares_all(source: str) -> bool:
    """Whether a module assigns `__all__` at its top level."""
    tree = ast.parse(source)
    names = {
        target.id
        for node in tree.body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    } | {
        node.target.id
        for node in tree.body
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
    }
    return "__all__" in names


def test_the_import_detector_should_catch_an_absolute_self_import():
    """Prove the detector can fail before trusting it to say the package is clean.

    Without this, a bug in the AST walk -- the wrong node type, iterating
    tree.body instead of walking -- reads exactly like a clean package.
    """
    assert absolute_self_imports("from paperpi.models import Rgb")
    assert absolute_self_imports("import paperpi.config")
    assert not absolute_self_imports("from .models import Rgb")
    assert not absolute_self_imports("from ..config import SCAN_DIR")
    assert not absolute_self_imports("import pathlib")


def test_the_all_detector_should_catch_a_module_without_all():
    """Same reasoning: the __all__ check is proved able to fail."""
    assert not declares_all('"""A module."""\n\nX = 1\n')
    assert declares_all('__all__ = ["X"]\nX = 1\n')
    assert declares_all("__all__: list[str] = []\n")


def test_package_modules_should_import_siblings_relatively():
    """No module reaches for the package by its absolute name.

    The package must stay relocatable, and relative imports are what make an
    internal dependency distinguishable from an external one at a glance. ruff
    cannot require this: TID251 resolves relative imports to their absolute
    form and would ban both spellings.
    """
    offenders: list[str] = []
    for path in sorted(PACKAGE.rglob("*.py")):
        offenders.extend(absolute_self_imports(path.read_text(), path.name))
    assert not offenders, f"absolute self-imports: {offenders}"


def test_every_module_should_declare_all():
    """Every module states its public surface explicitly.

    ruff's RUF022 only sorts an `__all__` that already exists, so its absence
    is invisible to the linter and has to be asserted here.
    """
    missing = [
        str(path.relative_to(PACKAGE))
        for path in sorted(PACKAGE.rglob("*.py"))
        if not declares_all(path.read_text())
    ]
    assert not missing, f"modules without __all__: {missing}"
