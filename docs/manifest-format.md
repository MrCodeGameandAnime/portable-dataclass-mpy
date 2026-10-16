# Manifest format

The generated module is named _dataclass_fields.py and contains:

- IDENTITY_MODE = "qualified_name"
- FIELD_MANIFEST, mapping (module_name, qualified_name) to an ordered tuple
  of field names.

The class identity uses CPython's __module__ and __qualname__. This avoids
ambiguous bare-name matching. Only module-level decorated classes are supported;
nested and function-local classes are rejected during generation because
MicroPython does not preserve their host identity. The overlay checks
IDENTITY_MODE and rejects an incompatible manifest. A consumer's
MicroPython overlay raises a runtime error if a decorated class has no matching
manifest entry.

The manifest intentionally contains field names only. Ordinary defaults remain
on the class, and field(default_factory=...) markers are resolved by the
runtime overlay. Do not edit generated files by hand. Regenerate them with
portable-dataclass-metadata and use --check to verify freshness.
