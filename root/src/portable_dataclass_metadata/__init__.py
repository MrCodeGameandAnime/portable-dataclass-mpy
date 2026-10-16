"""Host-side metadata tools for the portable MicroPython dataclass overlay."""

__all__ = ["UnsafeImportError", "build_manifest", "discover_native_dataclasses",
           "render_manifest", "write_manifest", "manifest_is_current", "main"]


def __getattr__(name):
    if name in __all__:
        from . import generator
        return getattr(generator, name)
    raise AttributeError("module %r has no attribute %r" % (__name__, name))
