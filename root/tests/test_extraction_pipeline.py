import contextlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from _checks import checked_source


EXTRACTION_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = EXTRACTION_ROOT / "src"
OVERLAY_ROOT = SOURCE_ROOT / "portable_dataclass_metadata" / "micropython"
sys.path.insert(0, str(SOURCE_ROOT))

from portable_dataclass_metadata.generator import main  # noqa: E402


class ExtractionPipelineTests(unittest.TestCase):
    def test_generated_manifest_drives_isolated_overlay(self):
        self.run_generated_manifest_pipeline(sys.executable)

    def test_generated_manifest_drives_pinned_micropython_overlay(self):
        executable = os.environ.get("MICROPYTHON_EXECUTABLE")
        if not executable:
            self.skipTest("set MICROPYTHON_EXECUTABLE to the pinned 1.29.0 runtime")
        self.run_generated_manifest_pipeline(executable, micropython=True)

    def run_generated_manifest_pipeline(self, executable, micropython=False):
        with tempfile.TemporaryDirectory(dir=str(Path(__file__).resolve().parent)) as temp:
            workspace = Path(temp)
            consumer_root = workspace / "consumer_src"
            package_root = consumer_root / "sample_models"
            package_root.mkdir(parents=True)
            (package_root / "__init__.py").write_text("", encoding="utf-8")
            (package_root / "compat.py").write_text(
                "from dataclasses import dataclass, field\n", encoding="utf-8"
            )
            (package_root / "models.py").write_text(
                "from .compat import dataclass, field\n"
                "NOTES = field(default_factory=list)\n"
                "@dataclass\n"
                "class Sample:\n"
                "    value: int\n"
                "    notes: list = NOTES\n"
                "@dataclass\n"
                "class Child(Sample):\n"
                "    extra: int = 9\n"
                "class Undecorated(Sample):\n"
                "    pass\n",
                encoding="utf-8",
            )
            manifest_root = workspace / "manifest"
            manifest_path = manifest_root / "_dataclass_fields.py"

            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(
                    main(
                        [
                            "--source-root", str(consumer_root),
                            "--scan-root", str(package_root),
                            "--output", str(manifest_path),
                        ]
                    ),
                    0,
                )

            env = os.environ.copy()
            env["PYTHONPATH"] = os.pathsep.join(
                (str(manifest_root), str(OVERLAY_ROOT), str(consumer_root))
            )
            env["EXPECTED_OVERLAY"] = str(OVERLAY_ROOT / "dataclasses.py")
            bootstrap = "import sys\nsys.path[:0] = %r\n" % [
                path.as_posix()
                for path in (manifest_root, OVERLAY_ROOT, consumer_root)
            ]
            if micropython:
                bootstrap += (
                    "assert sys.implementation.name == 'micropython'\n"
                    "assert sys.implementation.version[:3] == (1, 29, 0)\n"
                )
            checks = """
import dataclasses
from sample_models.models import Sample, Child, Undecorated
first = Sample(7)
second = Sample(value=8)
first.notes.append('first')
assert first.value == 7
assert second.notes == []
assert first == Sample(7, ['first'])
assert Sample.__dataclass_fields__ == ('value', 'notes')
child = Child(3)
other = Child(4)
child.notes.append('child')
assert other.notes == [] and child.extra == 9
assert child == Child(3, ['child'], 9)
assert Child.__dataclass_fields__ == ('value', 'notes', 'extra')
assert Undecorated(3) == Undecorated(3)
assert Undecorated(3) != Sample(3)
assert Sample(3) != Undecorated(3)
print('generated manifest and overlay: PASS')
"""
            bootstrap += "import dataclasses\nassert dataclasses.__file__.replace('\\\\', '/') == %r\n" % (
                OVERLAY_ROOT / "dataclasses.py"
            ).as_posix()
            arguments = [executable]
            if not micropython:
                arguments.append("-S")
            arguments.extend(("-c", checked_source(bootstrap + checks)))
            result = subprocess.run(
                arguments,
                cwd=str(EXTRACTION_ROOT),
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
