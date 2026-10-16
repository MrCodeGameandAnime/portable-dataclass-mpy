"""MicroPython dataclasses overlay consuming a generated field manifest."""

from _dataclass_fields import FIELD_MANIFEST, IDENTITY_MODE

if IDENTITY_MODE != "qualified_name":
    raise RuntimeError("unsupported portable dataclass manifest identity mode")


_MISSING = object()


class FrozenInstanceError(AttributeError):
    """An attempt to assign or delete a frozen record attribute."""


class _FieldSpec:
    def __init__(self, default=_MISSING, default_factory=_MISSING):
        if default is not _MISSING and default_factory is not _MISSING:
            raise TypeError("field cannot define both default and default_factory")
        if default_factory is not _MISSING and not callable(default_factory):
            raise TypeError("default_factory must be callable")
        self.default = default
        self.default_factory = default_factory


def field(*args, **kwargs):
    if args:
        raise TypeError("field accepts keyword arguments only")
    unknown = set(kwargs) - {"default", "default_factory"}
    if unknown:
        raise TypeError("unsupported field arguments: %s" % sorted(unknown))
    return _FieldSpec(
        default=kwargs.get("default", _MISSING),
        default_factory=kwargs.get("default_factory", _MISSING),
    )


def _manifest_key(cls):
    module_name = getattr(cls, "__module__", None)
    qualified_name = getattr(cls, "__qualname__", None)
    if not isinstance(module_name, str) or not isinstance(qualified_name, str):
        raise RuntimeError("portable dataclass class identity is unavailable")
    key = (module_name, qualified_name)
    if key not in FIELD_MANIFEST:
        raise RuntimeError(
            "missing portable dataclass metadata for %s.%s"
            % (module_name, qualified_name)
        )
    return key


def _field_specs(cls, field_names):
    inherited = {}
    for base in reversed(cls.__bases__):
        inherited.update(getattr(base, "__portable_dataclass_specs__", {}))
    specs = []
    for name in field_names:
        if name not in cls.__dict__ and name in inherited:
            specs.append(inherited[name])
            continue
        default = getattr(cls, name, _MISSING)
        if isinstance(default, _FieldSpec):
            specs.append(default)
            if name in cls.__dict__:
                if default.default is _MISSING:
                    delattr(cls, name)
                else:
                    setattr(cls, name, default.default)
        elif default is _MISSING:
            specs.append(_FieldSpec())
        else:
            specs.append(_FieldSpec(default=default))
    return tuple(specs)


def _make_init(cls, field_names, specs, frozen):
    has_post_init = hasattr(cls, "__post_init__")
    assign = object.__setattr__ if frozen else setattr

    def __init__(self, *args, **kwargs):
        if len(args) > len(field_names):
            raise TypeError("too many positional arguments")

        values = {}
        for index, value in enumerate(args):
            values[field_names[index]] = value

        for name in field_names:
            if name in kwargs:
                if name in values:
                    raise TypeError("multiple values for %s" % name)
                values[name] = kwargs.pop(name)
        if kwargs:
            raise TypeError("unexpected keyword arguments: %s" % sorted(kwargs))

        for name, spec in zip(field_names, specs):
            if name not in values:
                if spec.default_factory is not _MISSING:
                    values[name] = spec.default_factory()
                elif spec.default is not _MISSING:
                    values[name] = spec.default
                else:
                    raise TypeError("missing required argument: %s" % name)
            assign(self, name, values[name])

        if has_post_init:
            self.__post_init__()

    return __init__


def _make_eq(cls, field_names):
    def __eq__(self, other):
        if other.__class__ is not self.__class__:
            return NotImplemented
        return all(
            getattr(self, name) == getattr(other, name) for name in field_names
        )

    return __eq__


def _make_hash(field_names):
    def __hash__(self):
        return hash(tuple(getattr(self, name) for name in field_names))
    return __hash__


def _make_frozen_setattr(cls, field_names):
    def __setattr__(self, name, value):
        if type(self) is cls or name in field_names:
            raise FrozenInstanceError("cannot assign to a frozen dataclass")
        super(cls, self).__setattr__(name, value)
    return __setattr__


def _make_frozen_delattr(cls, field_names):
    def __delattr__(self, name):
        if type(self) is cls or name in field_names:
            raise FrozenInstanceError("cannot delete from a frozen dataclass")
        super(cls, self).__delattr__(name)
    return __delattr__


def _decorate(cls, frozen):
    key = _manifest_key(cls)
    field_names = tuple(FIELD_MANIFEST[key])
    own_members = cls.__dict__
    own_hash = own_members.get("__hash__", _MISSING)
    explicit_hash = not (
        own_hash is _MISSING
        or (own_hash is None and "__eq__" in own_members)
    )
    if frozen:
        for method in ("__setattr__", "__delattr__"):
            if method in own_members:
                raise TypeError("cannot overwrite %s in frozen dataclass" % method)
    specs = _field_specs(cls, field_names)

    setattr(cls, "__portable_dataclass_specs__", dict(zip(field_names, specs)))
    setattr(cls, "__dataclass_fields__", field_names)
    if "__init__" not in own_members:
        setattr(cls, "__init__", _make_init(cls, field_names, specs, frozen))
    if "__eq__" not in own_members:
        setattr(cls, "__eq__", _make_eq(cls, field_names))
    if not explicit_hash:
        setattr(cls, "__hash__", _make_hash(field_names) if frozen else None)
    if frozen:
        setattr(cls, "__setattr__", _make_frozen_setattr(cls, field_names))
        setattr(cls, "__delattr__", _make_frozen_delattr(cls, field_names))
    return cls


def dataclass(cls=None, frozen=False, **kwargs):
    if kwargs:
        raise TypeError("unsupported dataclass options: %s" % sorted(kwargs))
    if cls is None:
        return lambda target: _decorate(target, frozen)
    return _decorate(cls, frozen)


__all__ = ["dataclass", "field", "FrozenInstanceError"]
