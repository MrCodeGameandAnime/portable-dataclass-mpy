# Contributing

Bug reports, documentation improvements, tests, and focused patches are welcome.
Please follow the [code of conduct](CODE_OF_CONDUCT.md). For security concerns,
use the private reporting process in [SECURITY.md](SECURITY.md).

## Before opening an issue

Read the [supported subset and known limitations](README.md#supported-subset)
and search existing issues. Include a small, standalone reproduction rather than
application code or credentials. For a new feature or a change to the supported
subset, open an issue to discuss the use case and device costs before a large patch.

Include the package version, host Python version, and, when relevant, the exact
MicroPython version, port, board, and build options. Show the generator command,
expected behavior, actual behavior, and complete relevant error output.

## Repository layout

- `docs/`: public documentation and community policies.
- `root/src/portable_dataclass_metadata/`: host generator and package code.
- `root/src/portable_dataclass_metadata/micropython/dataclasses.py`: device overlay.
- `root/tests/`: generator, runtime, parity, and packaging checks.
- `root/examples/`: standalone examples.
- `root/pyproject.toml` and `root/MANIFEST.in`: packaging configuration.
- `.github/`: workflows and issue templates.

Keep generated builds and distributions under `root/`. Keep the device overlay
off the host's normal import path so it does not replace native CPython dataclasses.

## Development and verification

Use CPython 3.12 for development. From the repository root, run:

```sh
python -B -m unittest discover -s root/tests -v
```

This command may skip MicroPython and wheel checks when their prerequisites are
missing. Report those skips; a host-only pass is not full release qualification.

For full verification, build a wheel, set `MICROPYTHON_EXECUTABLE` to MicroPython
1.29.0 and `LIBRARY_WHEEL` to the wheel's absolute path, then run:

```sh
python -B root/tests/verify_release.py
```

See [testing.md](testing.md) for environment setup, optimized execution, and the
source-archive rebuild. CI performs full verification, including wheel deployment
and source-archive checks. Other device ports and builds need separate qualification.

## Pull requests

Keep each pull request focused and explain its purpose and user-visible effects.
Link related issues and state the verification performed, including versions and
skips. Update documentation when behavior, commands, or supported options change.

Behavior changes should include focused regression coverage. Runtime changes should
compare the supported behavior with native CPython and exercise the actual
MicroPython runtime. Preserve deterministic manifest output, generator/runtime
agreement, and the documented host/device boundary. Unsupported consumer behavior
should fail clearly rather than generate metadata the device cannot use.

Do not include credentials, bytecode, build outputs, or unrelated formatting changes.
Retain attribution for any borrowed work. Contributions are provided under the
project's [MIT license](../LICENSE.md).
