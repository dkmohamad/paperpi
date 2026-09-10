"""Status display and scan control for the home scanner/printer Pi.

The package is layered so the hardware sits at the edge: `models` holds the
vocabulary, `ports` and `protocols` hold the contracts, `screens` and `render`
turn state into pixels, and `adapters` supplies the two implementations of each
port -- one for the Pi, one for a desktop preview. Only `__main__` knows which
pair is in use.
"""

__all__: list[str] = []
