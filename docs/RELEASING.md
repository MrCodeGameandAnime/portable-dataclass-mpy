# Releasing Portable Dataclass MPY

Publisher and maintainer: **404 Builds**. Original author and copyright holder:
**MrCodeGameAndAnime**. Package: `portable-dataclass-mpy`.

## Build

Use Python 3.12. Run from the repository directory:

```sh
python -m pip install build twine
python -m build root --outdir root/dist
python -m twine check --strict root/dist/portable_dataclass_mpy-0.1.0-py3-none-any.whl root/dist/portable_dataclass_mpy-0.1.0.tar.gz
```

The backend copies `docs/` and `LICENSE.md` into the ignored
`root/_release_docs/` build directory. Edit the originals. The source archive
includes those copies, source, tests, fixtures, and examples; the wheel includes
the host package, device overlay, CLI entry point, README metadata, and MIT notice.

## Verify

Follow [testing.md](testing.md) with `MICROPYTHON_EXECUTABLE` and `LIBRARY_WHEEL`
set. Run normal and optimized verification against the exact wheel.

Extract the source archive and rebuild with `python -m build` from its directory.
Run `python -B tests/verify_release.py` there against the rebuilt wheel, normally
and with `PYTHONOPTIMIZE=1`. In the extracted archive, source, tests, and examples
are directly under `src/`, `tests/`, and `examples/`.

Install each wheel in a fresh environment and run the preparation example and
device demo. Record SHA256 checksums of the distributions to publish.

## Publish

1. Commit and push the reviewed files to `main` on
   [GitHub](https://github.com/MrCodeGameAndAnime/portable-dataclass-mpy).
2. Create the `v0.1.0` tag and GitHub release using
   [the release notes](releases/0.1.0.md). Attach the verified wheel and source archive.
3. Upload the same files using an authenticated publishing environment:

   ```sh
   python -m twine upload root/dist/portable_dataclass_mpy-0.1.0-py3-none-any.whl root/dist/portable_dataclass_mpy-0.1.0.tar.gz
   ```

4. Check the published version, metadata, and checksums on PyPI and GitHub.
   Install from PyPI in a fresh environment and confirm the CLI and example.
