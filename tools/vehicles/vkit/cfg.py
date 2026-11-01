"""The active vehicle spec.

One Blender process builds one vehicle: build.py loads `specs/<name>.py` and calls
`use(SPEC)`. Kit modules read the numbers they need from `cfg.V` at call time, so
every literal of the original Tsubame-4 builder is now a spec field (the Tsubame
spec carries those exact values, which keeps its output identical).
"""


class AD(dict):
    """dict with attribute access, recursively; missing keys raise AttributeError."""

    def __getattr__(self, k):
        try:
            return self[k]
        except KeyError:
            raise AttributeError(k) from None

    def __setattr__(self, k, v):
        self[k] = v

    def get_(self, k, default):
        return self.get(k, default)


def wrap(x):
    if isinstance(x, dict) and not isinstance(x, AD):
        return AD({k: wrap(v) for k, v in x.items()})
    if isinstance(x, list):
        return [wrap(v) for v in x]
    return x


V = None
MODULE = None


def use(spec, module=None):
    """Make `spec` (a dict, see specs/README in tools/vehicles/specs/__init__.py) the active vehicle."""
    global V, MODULE
    V = wrap(spec)
    MODULE = module
    return V
