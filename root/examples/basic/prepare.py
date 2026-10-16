"""Host-only preparation of the basic MicroPython example."""

import argparse
import shutil
from pathlib import Path

import portable_dataclass_metadata
from portable_dataclass_metadata.generator import main as generate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("root/build/basic-device"))
    args = parser.parse_args()
    source = Path(__file__).resolve().parent
    output = args.output.resolve()
    manifest = output / "_dataclass_fields.py"
    arguments = ["--source-root", str(source), "--scan-root", "models.py",
                 "--output", str(manifest)]
    status = generate(arguments)
    if status:
        return status
    status = generate(arguments + ["--check"])
    if status:
        return status
    package = Path(portable_dataclass_metadata.__file__).resolve().parent
    shutil.copyfile(package / "micropython/dataclasses.py", output / "dataclasses.py")
    for name in ("models.py", "demo.py"):
        shutil.copyfile(source / name, output / name)
    print("Prepared MicroPython example: %s" % output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
