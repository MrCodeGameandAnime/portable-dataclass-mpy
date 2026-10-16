# Testing

## Continuous integration

GitHub Actions runs `.github/workflows/ci.yml` on pushes and pull requests,
and can be started manually. It uses CPython 3.12 on Ubuntu and builds the
MicroPython 1.29.0 standard Unix port from its release tag. The required release
runner checks the checkout and extracted source archive, each normally and with
optimization, including installed-wheel deployment. Missing device or wheel
prerequisites fail the job.

CI validates package metadata, packaged documentation, the license, and maintainer
contact details. Successful runs provide wheel/source distributions and checksums
as downloadable artifacts. Verification logs are retained for 14 days. This
workflow does not publish releases or upload to PyPI.

## Local checks

Use CPython 3.12 for the development suite (the test helper uses ast.unparse).
From the repository root:

```sh
python -B -m unittest discover -s root/tests -v
```

This supported invocation adds root/tests/ to the import path. Dotted invocations such
as `python -m unittest tests.test_native_parity` are outside the supported setup.
Tests use temporary synthetic consumers under root/tests/ and clean them on completion;
read-only checkout test execution is not supported.

## Full release verification

Build distributions as described in RELEASING.md. Set these environment variables:

- MICROPYTHON_EXECUTABLE: a path or PATH command for MicroPython 1.29.0.
- LIBRARY_WHEEL: an absolute path to the exact wheel being verified.

```sh
python -B root/tests/verify_release.py
```

On PowerShell:

```powershell
$env:MICROPYTHON_EXECUTABLE = 'C:/tools/micropython.exe'
$env:LIBRARY_WHEEL = (Resolve-Path 'root/dist/portable_dataclass_mpy-0.1.0-py3-none-any.whl').Path
python -B root/tests/verify_release.py
$env:PYTHONOPTIMIZE = '1'
python -B root/tests/verify_release.py
Remove-Item Env:PYTHONOPTIMIZE
```

On Unix, export equivalent variables; run `PYTHONOPTIMIZE=1 python -B root/tests/verify_release.py`
for the optimized pass. Full verification refuses missing runtime/wheel prerequisites
and skipped required checks. It permits only unavailable symlink creation and a
POSIX read-only-parent test that cannot run on Windows or as root. Host-only discovery
can skip runtime and wheel checks and is not release qualification.

The suite covers the generator, CLI, manifests, installed-wheel deployment, and a
24-scenario native-reference matrix. The matrix checks native expected results,
then the CPython overlay and actual MicroPython. Embedded checks use explicit raises;
a deliberately broken equality must still be detected with optimization enabled.

The wheel test installs offline into a fresh venv, generates/checks consumer metadata
through the installed CLI, and deploys the installed overlay onto MicroPython.
The source distribution must also be extracted and tested; it includes all helpers,
fixtures, examples, and public documentation. See qualification-summary.md for the
recorded audit environments; evidence does not imply support for every board/build.
