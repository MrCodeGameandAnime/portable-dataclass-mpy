import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path


EXTRACTION_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = EXTRACTION_ROOT / "src"
sys.path.insert(0, str(SOURCE_ROOT))

from portable_dataclass_metadata.generator import main  # noqa: E402


class ManifestOutputTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=str(Path(__file__).resolve().parent))
        self.root = Path(self.temp.name)
        self.source_root = self.root / "consumer_src"
        self.package_root = self.source_root / "sample_models"
        self.package_root.mkdir(parents=True)
        (self.package_root / "__init__.py").write_text("", encoding="utf-8")
        self.module = self.package_root / "models.py"
        self.output = self.root / "overlay" / "_dataclass_fields.py"

    def tearDown(self):
        self.temp.cleanup()

    def args(self, check=False):
        result = [
            "--source-root", str(self.source_root),
            "--scan-root", str(self.package_root),
            "--output", str(self.output),
        ]
        if check:
            result.append("--check")
        return result

    def test_cli_generates_and_checks_manifest(self):
        self.module.write_text(
            "from dataclasses import dataclass\n"
            "@dataclass\n"
            "class Sample:\n"
            "    first: int\n"
            "    second: str = 'default'\n",
            encoding="utf-8",
        )

        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(self.args()), 0)
            self.assertTrue(self.output.exists())
            generated = self.output.read_text(encoding="utf-8")
            self.assertIn("('sample_models.models', 'Sample')", generated)
            self.assertEqual(main(self.args(check=True)), 0)

            self.output.write_text("stale", encoding="utf-8")
            self.assertEqual(main(self.args(check=True)), 1)
            self.assertEqual(self.output.read_text(encoding="utf-8"), "stale")

    def test_failed_discovery_preserves_existing_output(self):
        self.module.write_text(
            "from dataclasses import dataclass\n"
            "@dataclass\n"
            "class Sample:\n"
            "    value: int\n"
            "def ask():\n"
            "    return input('unsafe')\n"
            "ask()\n",
            encoding="utf-8",
        )
        self.output.parent.mkdir(parents=True)
        self.output.write_text("existing manifest", encoding="utf-8")

        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(self.args()), 2)
        self.assertEqual(
            self.output.read_text(encoding="utf-8"),
            "existing manifest",
        )


if __name__ == "__main__":
    unittest.main()
