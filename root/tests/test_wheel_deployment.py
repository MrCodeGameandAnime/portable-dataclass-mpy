import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from _checks import checked_source


EXTRACTION_ROOT = Path(__file__).resolve().parents[1]


class WheelDeploymentTests(unittest.TestCase):
    def run_command(self, arguments, cwd):
        arguments = list(arguments)
        if '-c' in arguments:
            source_index = arguments.index('-c') + 1
            arguments[source_index] = checked_source(arguments[source_index])
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        env.pop("PYTHONHOME", None)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        result = subprocess.run(
            [str(argument) for argument in arguments],
            cwd=str(cwd), env=env, capture_output=True, text=True, timeout=120,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def test_installed_wheel_generates_and_deploys_to_micropython(self):
        wheel = os.environ.get("LIBRARY_WHEEL")
        micropython = os.environ.get("MICROPYTHON_EXECUTABLE")
        if not wheel or not micropython:
            self.skipTest("set LIBRARY_WHEEL and MICROPYTHON_EXECUTABLE")
        wheel = Path(wheel).resolve()
        self.assertTrue(wheel.is_file(), str(wheel))

        with tempfile.TemporaryDirectory(dir=str(EXTRACTION_ROOT / "tests")) as temp:
            workspace = Path(temp)
            environment = workspace / "venv"
            self.run_command([sys.executable, "-m", "venv", environment], workspace)
            scripts = environment / ("Scripts" if os.name == "nt" else "bin")
            python = scripts / ("python.exe" if os.name == "nt" else "python")
            cli = scripts / (
                "portable-dataclass-metadata.exe" if os.name == "nt"
                else "portable-dataclass-metadata"
            )
            self.run_command(
                [python, "-m", "pip", "install", "--no-index", "--no-deps", wheel],
                workspace,
            )
            package_check = self.run_command(
                [python, "-I", "-c", (
                    "from pathlib import Path; import dataclasses; "
                    "import portable_dataclass_metadata as package; "
                    "root=Path(%r).resolve(); "
                    "assert root in Path(package.__file__).resolve().parents; "
                    "assert 'portable_dataclass_metadata' not in dataclasses.__file__; "
                    "print(Path(package.__file__).parent / 'micropython' / 'dataclasses.py')"
                ) % str(environment)], workspace,
            )
            installed_overlay = Path(package_check.stdout.strip())
            self.assertTrue(installed_overlay.is_file())

            consumer_root = workspace / "consumer_src"
            package_root = consumer_root / "wheel_consumer"
            package_root.mkdir(parents=True)
            (package_root / "__init__.py").write_text("", encoding="utf-8")
            (package_root / "models.py").write_text(
                "from dataclasses import dataclass, field\n"
                "@dataclass\nclass Sample:\n"
                "    value: int\n"
                "    notes: list = field(default_factory=list)\n"
                "@dataclass\nclass Custom:\n"
                "    value: int\n"
                "    def __init__(self, value):\n        self.value = value + 100\n"
                "    def __eq__(self, other):\n        return isinstance(other, Custom) and self.value == other.value\n"
                "    def __hash__(self):\n        return self.value\n",
                encoding="utf-8",
            )
            device = workspace / "device"
            device.mkdir()
            shutil.copyfile(installed_overlay, device / "dataclasses.py")
            manifest = device / "_dataclass_fields.py"
            generation = [
                cli, "--source-root", consumer_root, "--scan-root", package_root,
                "--output", manifest,
            ]
            self.run_command(generation, workspace)
            self.run_command(generation + ["--check"], workspace)
            self.assertTrue(manifest.is_file())
            shutil.copytree(package_root, device / "wheel_consumer")

            self.run_command(
                [micropython, "-c", (
                    "import sys\n"
                    "assert sys.implementation.name == 'micropython'\n"
                    "assert sys.implementation.version[:3] == (1, 29, 0)\n"
                    "sys.path.insert(0, %r)\n"
                    "import dataclasses\n"
                    "assert dataclasses.__file__.replace('\\\\', '/') == %r\n"
                    "from wheel_consumer.models import Sample, Custom\n"
                    "first = Sample(7)\n"
                    "second = Sample(value=8)\n"
                    "first.notes.append('first')\n"
                    "assert second.notes == []\n"
                    "assert first == Sample(7, ['first'])\n"
                    "assert Sample.__dataclass_fields__ == ('value', 'notes')\n"
                    "custom = Custom(1)\n"
                    "assert custom.value == 101\n"
                    "assert custom == Custom(1)\n"
                    "assert hash(custom) == 101\n"
                    "print('installed wheel deployment: PASS')\n"
                ) % (device.as_posix(), (device / "dataclasses.py").as_posix())],
                workspace,
            )


if __name__ == "__main__":
    unittest.main()
