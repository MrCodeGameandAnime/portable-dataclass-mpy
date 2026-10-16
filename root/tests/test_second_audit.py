import contextlib
import io
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from portable_dataclass_metadata import generator

MODEL = 'from dataclasses import dataclass\n@dataclass\nclass R:\n    x: int\n'


class SecondAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=str(ROOT / 'tests'))
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'src'
        self.source.mkdir()

    def write(self, name, text):
        path = self.source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
        return path

    def test_large_candidate_set(self):
        for index in range(800):
            self.write('model_%04d_%s.py' % (index, 'x' * 30), MODEL)
        self.assertEqual(len(generator.discover_native_dataclasses(self.source, [self.source])), 800)

    def test_worker_result_survives_raw_and_exit_output(self):
        self.write('models.py', MODEL + 'import os, sys, atexit\nos.write(1, b"raw output\\n")\n'
                   'sys.__stdout__.write("original stdout\\n")\natexit.register(print, "exit output")\n')
        self.assertEqual(generator.discover_native_dataclasses(self.source, [self.source]),
                         ((('models', 'R'), ('x',)),))

    def test_reexported_decorator_and_field(self):
        self.write('pkg/__init__.py', '')
        self.write('pkg/compat.py', 'from dataclasses import dataclass, field\n')
        self.write('pkg/models.py', 'from .compat import dataclass, field\n@dataclass\nclass R:\n'
                   '    x: int = field(default=1)\n')
        self.assertEqual(generator.discover_native_dataclasses(self.source, [self.source]),
                         ((('pkg.models', 'R'), ('x',)),))
        self.write('pkg/models.py', 'from .compat import dataclass\n@dataclass(eq=True)\nclass R:\n    x: int\n')
        with self.assertRaisesRegex(ValueError, 'unsupported dataclass'):
            generator.discover_native_dataclasses(self.source, [self.source])

    def test_external_field_options_rejected(self):
        for option in ('repr=False', 'hash=False', 'metadata={}'):
            self.write('models.py', 'from dataclasses import dataclass, field\n'
                       'F = field(default=1, ' + option + ')\n@dataclass\nclass R:\n    x: int = F\n')
            with self.assertRaisesRegex(ValueError, 'unsupported field'):
                generator.discover_native_dataclasses(self.source, [self.source])

    def test_irrelevant_helpers_and_shadow_file_do_not_abort(self):
        self.write('helper.py', 'from dataclasses import *\ndef mk(cls):\n    return dataclass(cls)\n')
        self.write('pkg.py', 'LEGACY = 1\n')
        self.write('pkg/__init__.py', MODEL)
        self.assertEqual(generator.discover_native_dataclasses(self.source, [self.source]),
                         ((('pkg', 'R'), ('x',)),))

    def test_excluded_paths_and_virtual_environment(self):
        self.write('models.py', MODEL)
        self.write('legacy.py', 'invalid syntax !')
        self.write('test_dynamic.py', 'from dataclasses import make_dataclass\nR = make_dataclass("R", ["x"])\n')
        self.write('.venv/broken.py', 'invalid syntax !')
        self.assertEqual(generator.discover_native_dataclasses(self.source, [self.source],
                         exclude=['legacy.py', 'test_*.py']), ((('models', 'R'), ('x',)),))

    def test_corrupt_manifest_is_stale(self):
        self.write('models.py', MODEL)
        output = self.root / 'manifest.py'
        output.write_bytes(b'\xff\xfe')
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(generator.main(['--source-root', str(self.source), '--scan-root', 'models.py',
                                            '--output', str(output), '--check']), 1)

    def test_cli_relative_path_compatibility_and_timeout(self):
        self.write('pkg/models.py', MODEL)
        self.write('pkg/__init__.py', '')
        env = dict(os.environ, PYTHONPATH=str(ROOT / 'src'), PYTHONDONTWRITEBYTECODE='1')
        for scan in ('pkg', 'src/pkg'):
            result = subprocess.run([sys.executable, '-B', '-m', 'portable_dataclass_metadata.generator',
                                     '--source-root', 'src', '--scan-root', scan, '--timeout', '10',
                                     '--output', 'out.py'], cwd=str(self.root), env=env,
                                    capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_diagnostics_and_unsafe_error_compatibility(self):
        self.assertTrue(issubclass(generator.UnsafeImportError, RuntimeError))
        self.write('models.py', MODEL + 'import sys\nprint("log before failure", file=sys.stderr)\nraise KeyError("boom")\n')
        with self.assertRaisesRegex(ValueError, "KeyError: 'boom'") as caught:
            generator.discover_native_dataclasses(self.source, [self.source])
        self.assertIn('log before failure', str(caught.exception))

    def test_release_runner_accepts_path_commands_and_only_optional_symlink_skip(self):
        spec = importlib.util.spec_from_file_location('release_verification', ROOT / 'tests' / 'verify_release.py')
        runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runner)
        executable = self.root / ('micropython.exe' if os.name == 'nt' else 'micropython')
        executable.write_text('#!/bin/sh\nexit 0\n')
        executable.chmod(0o755)
        with mock.patch.dict(os.environ, {'PATH': str(self.root)}):
            self.assertEqual(Path(runner.resolve_runtime(executable.name)).resolve(), executable.resolve())
        symlink_case = unittest.FunctionTestCase(lambda: None)
        with mock.patch.object(symlink_case, 'id', return_value='tests.GeneratorContractTests.test_scan_root_symlink_is_rejected'):
            self.assertTrue(runner.optional_capability_skip(symlink_case, 'directory symlinks unavailable: denied'))
            self.assertFalse(runner.optional_capability_skip(symlink_case, 'set MICROPYTHON_EXECUTABLE'))
        self.assertFalse(runner.optional_capability_skip(self, 'directory symlinks unavailable: denied'))

    def test_cli_exclusion_and_configurable_timeout(self):
        self.write('models.py', MODEL)
        self.write('legacy.py', 'broken syntax !')
        env = dict(os.environ, PYTHONPATH=str(ROOT / 'src'), PYTHONDONTWRITEBYTECODE='1')
        result = subprocess.run([sys.executable, '-B', '-m', 'portable_dataclass_metadata.generator',
                                 '--source-root', str(self.source), '--scan-root', '.', '--exclude', 'legacy.py',
                                 '--output', str(self.root / 'out.py')], env=env, cwd=str(self.root),
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.write('models.py', MODEL + 'import time\ntime.sleep(2)\n')
        with self.assertRaisesRegex(ValueError, 'exceeded'):
            generator.discover_native_dataclasses(self.source, ['models.py'], timeout=0.2)
        for timeout in (0, -1, float('nan')):
            with self.assertRaisesRegex(ValueError, 'positive finite'):
                generator.discover_native_dataclasses(self.source, ['models.py'], timeout=timeout)


if __name__ == '__main__':
    unittest.main()
