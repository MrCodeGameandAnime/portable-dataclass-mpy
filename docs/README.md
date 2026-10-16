# Portable Dataclass MPY

Published and maintained by **404 Builds**. Created by **MrCodeGameAndAnime**.

A small MicroPython dataclass runtime with field metadata generated on host CPython.
Write ordinary module-level dataclasses, generate their ordered field manifest on
CPython, then copy the runtime and manifest onto MicroPython.

The host package uses native CPython dataclasses. Only the deployed device overlay
replaces `dataclasses`; keep it off normal CPython import paths.

## Install

Install a released version from PyPI:

```sh
python -m pip install portable-dataclass-mpy==0.1.0
```

To install a downloaded wheel or a source checkout:

```sh
python -m pip install path/to/portable_dataclass_mpy-0.1.0-py3-none-any.whl
# From a checkout:
python -m pip install ./root
```

Host library requirement: Python 3.8 or later. Development/tests use Python 3.12.
The package includes the host CLI and the device runtime as package data;
installing it does not replace the host's standard-library dataclasses.

## Quick start

In `root/examples/basic/models.py`:

```python
from dataclasses import dataclass, field

@dataclass
class Reading:
    value: int
    unit: str = "C"
    notes: list = field(default_factory=list)
```

From the repository root, prepare a self-contained device directory:

```sh
python root/examples/basic/prepare.py --output root/build/basic-device
```

This runs the generator and copies the installed runtime, model, and demo into
`root/build/basic-device`. It also checks that the generated manifest is current.

With MicroPython 1.29.0 on PATH:

```sh
micropython -c "import sys; sys.path.insert(0, 'root/build/basic-device'); import demo; demo.main()"
```

Expected output:

```text
21 C ['bench']
[]
```

Use your executable's path if it is not on PATH. On a board, copy the four prepared
files (`dataclasses.py`, `_dataclass_fields.py`, `models.py`, `demo.py`) to a device
import directory and run `demo.main()`. Qualify your board/build separately.

## Generate metadata for your project

```sh
portable-dataclass-metadata --source-root src --scan-root my_package --output device/_dataclass_fields.py
portable-dataclass-metadata --source-root src --scan-root my_package --output device/_dataclass_fields.py --check
```

Scan every deployed module that declares a dataclass. Repeat `--scan-root` for
multiple packages or files. Relative scan roots prefer `--source-root`, with an
existing working-directory-relative path as fallback; absolute paths also work.
The import root should be the parent of the consumer package.

Use repeated source-relative `--exclude` globs for unrelated files, for example
`--exclude "tests/**" --exclude "legacy.py"`. Patterns match the complete relative
path, not gitignore rules; use `**/test_*.py` for nested test names. Backslashes
are normalized. Recursive scans omit directories named `.venv`, `venv`, and
`__pycache__`. Excluded dependencies still execute if a candidate imports them.
Selected invalid Python remains an error. Broad decorated-class/name detection
can select unrelated code; narrow scan roots or exclusions handle that case.

The generator imports **trusted code** in a fresh process. Bytecode writes and
terminal input are disabled; `--timeout SECONDS` changes the 30-second default.
This is not a security sandbox. Transport uses system temp storage, so consumer
roots and their parents need not be writable.

Exit codes: **0** success/current, **1** missing/stale metadata in check mode,
**2** discovery, validation, timeout, or output errors. Discovery failure preserves
existing output. Replacement is atomic; containing-directory crash durability is
not promised. Run host `--check` before every deployment.

Copy `portable_dataclass_metadata/micropython/dataclasses.py` from the installed
package beside the generated `_dataclass_fields.py`, with that directory ahead
of device imports. The preparation example shows the complete procedure.

## Supported subset

- Module-level `@dataclass` and `@dataclass(frozen=True)`.
- Positional/keyword construction, required fields, defaults, and
  `field(default=...)` or `field(default_factory=...)` (never both).
- Ordered field names, same-class value equality, inherited fields/defaults/factories.
- Class-defined custom constructors/equality/hashes follow native preservation rules;
  inherited implementations are replaced by generated methods as native dataclasses do.
- Frozen value hashing by default; mutable default unhashability and native explicit/
  implicit hash rules. Explicit custom hashes are retained.
- Mutable initialization respects `__setattr__`; frozen initialization uses the
  object setter. Post-init presence is captured at decoration, with normal hook
  dispatch at construction. Custom constructors control their own post-init calls.
- Frozen exact instances and declared fields reject changes with
  `FrozenInstanceError(AttributeError)`. Undecorated subclasses may add/delete
  other attributes through parent hooks. Frozen decorators reject class-defined
  `__setattr__`/`__delattr__`.

Unscanned dependencies retain native dataclass options. Consumer decorator/field
calls are checked, including module-level re-exports and Field specifications
supplied by helpers. Other explicit options are rejected even if they spell a
CPython default, such as `eq=True` or `field(repr=True)`.

## Known limitations

- This is a subset, with no generated repr or public `fields`, `asdict`, `replace`,
  `is_dataclass`, or `MISSING`. `__dataclass_fields__` is an ordered tuple of names,
  not CPython's Field dictionary. Type annotations are not validated at runtime.
- ClassVar, InitVar, keyword-only/compare/init field options, and removing an
  inherited factory are unsupported. Nested/function-local classes, original-name
  functional decoration, and `make_dataclass` are unsupported and rejected when detected.
- **Aliased functional re-exports and dormant local definitions using aliased
  decorators may evade discovery.** Use module-level decorator syntax. Duplicate
  decorated names, including conditional redefinitions, are rejected.
- Empty scans can succeed with an empty manifest. Choose scan roots deliberately.
- Runtime schema freshness cannot be recovered from stripped MicroPython annotations;
  host `--check` is required. The runtime validates manifest identity mode and missing keys.
- Frozen interception requires a MicroPython build supporting custom setattr/delattr
  and object setters. Other ports and embedded boards need their own qualification.

## Verification

| Environment | Evidence |
| --- | --- |
| CPython 3.12.14, Windows | Full normal/optimized suite, native-reference comparisons, wheel deployment |
| MicroPython 1.29.0, Windows port | Runtime/parity matrix and installed-wheel deployment |
| MicroPython 1.29.0, Unix port | Independent auditor built v1.29.0 and reports parity/suite verification |

The recorded local qualification has 72 checks: 71 passed and one Unix-only permission check
skipped, both normally and with `PYTHONOPTIMIZE=1`. The independent Unix audit reports
70 passed/two skipped and separately verifies an unwritable parent as non-root;
it did not test packaging. Other host Python versions remain unqualified.

From a checkout:

```sh
python -B -m unittest discover -s root/tests -v
```

For full release verification, set `MICROPYTHON_EXECUTABLE` and `LIBRARY_WHEEL`, then:

```sh
python -B root/tests/verify_release.py
```

Host-only discovery can skip device/wheel checks. Release verification requires them;
only unavailable symlink creation and inapplicable POSIX permission checks may skip.
Dotted test-module invocation is not supported. Embedded checks survive optimization.

These results predate the repository layout changes. Current packaging must be
rebuilt and verified before publication.

## More information

- [Manifest format](https://github.com/MrCodeGameAndAnime/portable-dataclass-mpy/blob/main/docs/manifest-format.md)
- [Testing and qualification](https://github.com/MrCodeGameAndAnime/portable-dataclass-mpy/blob/main/docs/testing.md)
- [Release notes](https://github.com/MrCodeGameAndAnime/portable-dataclass-mpy/blob/main/docs/releases/0.1.0.md)
- [Issue tracker](https://github.com/MrCodeGameAndAnime/portable-dataclass-mpy/issues)

MIT License. Copyright 2026 MrCodeGameAndAnime. See [LICENSE.md](../LICENSE.md) for the full notice.
