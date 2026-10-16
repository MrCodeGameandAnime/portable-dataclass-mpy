import contextlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from portable_dataclass_metadata.generator import discover_native_dataclasses, main, write_manifest
from portable_dataclass_metadata import generator, render_manifest


class AuditRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=str(ROOT / 'tests'))
        self.root = Path(self.temp.name)
        self.source = self.root / 'consumer'
        self.source.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def model(self, text):
        path = self.source / 'models.py'
        path.write_text(text, encoding='utf-8')
        return path

    def discover(self):
        return discover_native_dataclasses(self.source, [self.source])

    def test_nested_and_local_classes_rejected(self):
        for wrapper in ('class Outer:', 'def factory():'):
            with self.subTest(wrapper=wrapper):
                self.model('from dataclasses import dataclass\n' + wrapper +
                           '\n    @dataclass\n    class Record:\n        value: int\n')
                with self.assertRaisesRegex(ValueError, 'nested|function-local'):
                    self.discover()

    def test_explicit_unsupported_options_rejected(self):
        for option in ('repr=False', 'eq=True', 'init=True', 'unsafe_hash=True', 'slots=True'):
            with self.subTest(option=option):
                self.model('from dataclasses import dataclass\n@dataclass(' + option +
                           ')\nclass Record:\n    value: int\n')
                with self.assertRaisesRegex(ValueError, 'unsupported dataclass'):
                    self.discover()
        for option in ('repr=False', 'hash=False', 'metadata={}', 'init=False', 'compare=False'):
            with self.subTest(option=option):
                self.model('from dataclasses import dataclass, field\n@dataclass\nclass Record:\n'
                           '    value: int = field(default=1, ' + option + ')\n')
                with self.assertRaisesRegex(ValueError, 'unsupported field'):
                    self.discover()

    def test_crashes_and_systemexit_are_errors_and_preserve_output(self):
        output = self.root / 'manifest.py'
        output.write_text('sentinel', encoding='utf-8')
        for failure in ('raise TypeError("broken import")', 'raise SystemExit(0)'):
            self.model('from dataclasses import dataclass\n@dataclass\nclass R:\n    x: int\n' + failure + '\n')
            for check in ([], ['--check']):
                with contextlib.redirect_stderr(io.StringIO()):
                    code = main(['--source-root', str(self.source), '--scan-root', str(self.source),
                                 '--output', str(output)] + check)
                self.assertEqual(code, 2)
                self.assertEqual(output.read_text(), 'sentinel')

    def test_conditional_aliases_and_encodings(self):
        text = 'if True:\n    import dataclasses as dc\n@dc.dataclass\nclass R:\n    x: int\n'
        path = self.model(text)
        for data in (b'\xef\xbb\xbf' + text.encode(),
                     ('# coding: latin-1\n# caf\xe9\n' + text).encode('latin-1')):
            path.write_bytes(data)
            self.assertEqual(self.discover(), ((('models', 'R'), ('x',)),))

    def test_dynamic_forms_rejected(self):
        for text in ('from dataclasses import make_dataclass\nR = make_dataclass("R", ["x"])\n',
                     'from dataclasses import dataclass\nclass R:\n    x: int\nR = dataclass(R)\n'):
            self.model(text)
            with self.assertRaisesRegex(ValueError, 'decorator syntax'):
                self.discover()

    def test_root_initializer_and_shadowing_rejected(self):
        text = 'from dataclasses import dataclass\n@dataclass\nclass R:\n    x: int\n'
        (self.source / '__init__.py').write_text(text)
        with self.assertRaisesRegex(ValueError, 'source root.*__init__'):
            self.discover()
        (self.source / '__init__.py').unlink()
        self.model(text)
        package = self.source / 'models'
        package.mkdir()
        (package / '__init__.py').write_text('')
        with self.assertRaisesRegex(ValueError, 'multiple files map'):
            self.discover()

    def test_dynamic_helpers_do_not_leak_and_no_bytecode_is_written(self):
        self.model('import importlib\nfrom dataclasses import dataclass\n'
                   'Base = importlib.import_module("helper").Base\n@dataclass\nclass R(Base):\n    pass\n')
        helper = self.source / 'helper.py'
        for name in ('first', 'other'):
            helper.write_text('from dataclasses import dataclass\n@dataclass\nclass Base:\n    ' + name + ': int\n')
            self.assertEqual(self.discover()[1][1], (name,))
        self.assertEqual(list(self.source.rglob('*.pyc')), [])

    def test_input_in_helpers_is_blocked_but_custom_input_is_allowed(self):
        self.model('from dataclasses import dataclass\nimport helper\n@dataclass\nclass R:\n    x: int\n')
        helper = self.source / 'helper.py'
        for call in ('input()', 'import builtins\nf = builtins.input\nf()',
                     'import sys\nsys.stdin.readline()'):
            helper.write_text(call)
            with self.assertRaisesRegex(ValueError, 'terminal input'):
                self.discover()
        helper.write_text('def input():\n    return 1\nx = input()\n')
        self.assertEqual(self.discover(), ((('models', 'R'), ('x',)),))

    def test_undecorated_subclass_is_not_recorded(self):
        self.model('from dataclasses import dataclass\n@dataclass\nclass Base:\n    x: int\nclass Child(Base):\n    pass\n')
        self.assertEqual(self.discover(), ((('models', 'Base'), ('x',)),))

    def test_relative_scan_root_and_module_cli_without_warning(self):
        path = self.model('from dataclasses import dataclass\n@dataclass\nclass R:\n    x: int\n')
        self.assertEqual(discover_native_dataclasses(self.source, ['models.py']), ((('models', 'R'), ('x',)),))
        env = dict(os.environ, PYTHONPATH=str(ROOT / 'src'), PYTHONDONTWRITEBYTECODE='1')
        result = subprocess.run([sys.executable, '-W', 'error', '-m',
                                 'portable_dataclass_metadata.generator', '--source-root', str(self.source),
                                 '--scan-root', str(path), '--output', str(self.root / 'out.py')],
                                env=env, capture_output=True, text=True, timeout=35)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, '')

    def test_validation_has_no_directory_side_effect(self):
        output = self.root / 'absent' / 'out.py'
        with self.assertRaises(ValueError):
            write_manifest(((('models', 'R'), ('x', 'x')),), output)
        self.assertFalse(output.parent.exists())

    def test_discovery_timeout_and_consumer_prints(self):
        self.model('from dataclasses import dataclass\nprint("consumer output")\n'
                   '@dataclass\nclass R:\n    x: int\n')
        self.assertEqual(self.discover(), ((('models', 'R'), ('x',)),))
        self.model('from dataclasses import dataclass\n@dataclass\nclass R:\n    x: int\nwhile True: pass\n')
        with mock.patch.object(generator, 'DISCOVERY_TIMEOUT', 0.2):
            with self.assertRaisesRegex(ValueError, 'exceeded'):
                self.discover()

    def test_duplicate_definition_rejected(self):
        text = 'from dataclasses import dataclass\n@dataclass\nclass R:\n    x: int\n'
        self.model(text + '@dataclass\nclass R:\n    y: int\n')
        with self.assertRaisesRegex(ValueError, 'duplicate dataclass identity'):
            self.discover()

    def test_fixture_matches_generated_format(self):
        records = ((('__main__', 'Record'), ('name', 'count', 'items')),
                   (('__main__', 'FrozenRecord'), ('code', 'normalized')),
                   (('__main__', 'ErrorRecord'), ('required', 'optional')))
        fixture = ROOT / 'tests' / 'fixtures' / 'micropython' / '_dataclass_fields.py'
        self.assertEqual(fixture.read_text(encoding='utf-8'), render_manifest(records))

    def test_atomic_write_permissions_and_cleanup(self):
        records = ((('models', 'R'), ('x',)),)
        output = self.root / 'out.py'
        if os.name == 'posix':
            mask = os.umask(0o022)
            self.addCleanup(os.umask, mask)
        write_manifest(records, output)
        self.assertEqual(output.read_text(), render_manifest(records))
        if os.name == 'posix':
            self.assertEqual(output.stat().st_mode & 0o777, 0o644)
            output.chmod(0o640)
            write_manifest(records, output)
            self.assertEqual(output.stat().st_mode & 0o777, 0o640)
        with mock.patch.object(generator.os, 'replace', side_effect=OSError('replace failed')):
            with self.assertRaisesRegex(OSError, 'replace failed'):
                write_manifest(records, output)
        self.assertEqual(output.read_text(), render_manifest(records))
        self.assertEqual(list(self.root.glob('*.tmp')), [])

    def test_implicit_inherited_factory_removal_rejected(self):
        self.model('from dataclasses import dataclass, field\n@dataclass\nclass Base:\n'
                   '    x: list = field(default_factory=list)\n@dataclass\nclass Child(Base):\n    x: list\n')
        with self.assertRaisesRegex(ValueError, 'inherited default_factory'):
            self.discover()

    def test_release_runner_requires_prerequisites(self):
        env = os.environ.copy()
        env.pop('MICROPYTHON_EXECUTABLE', None)
        env.pop('LIBRARY_WHEEL', None)
        result = subprocess.run([sys.executable, '-B', str(ROOT / 'tests' / 'verify_release.py')],
                                env=env, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 2)
        self.assertIn('MICROPYTHON_EXECUTABLE', result.stderr)

    def test_manifest_identity_mode_is_validated_on_both_runtimes(self):
        manifest = self.root / '_dataclass_fields.py'
        manifest.write_text('IDENTITY_MODE = "bare_name"\nFIELD_MANIFEST = {}\n')
        overlay = ROOT / 'src' / 'portable_dataclass_metadata' / 'micropython'
        code = 'import sys\nsys.path[:0] = %r\nimport dataclasses\n' % [
            self.root.as_posix(), overlay.as_posix()]
        executables = [sys.executable]
        if os.environ.get('MICROPYTHON_EXECUTABLE'):
            executables.append(os.environ['MICROPYTHON_EXECUTABLE'])
        for executable in executables:
            arguments = [executable]
            if executable == sys.executable:
                arguments.append('-S')
            result = subprocess.run(arguments + ['-c', code], capture_output=True,
                                    text=True, timeout=30)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('unsupported portable dataclass manifest identity mode', result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
