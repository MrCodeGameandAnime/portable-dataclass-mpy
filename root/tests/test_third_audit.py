import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from portable_dataclass_metadata import generator


class ThirdAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=str(ROOT / 'tests'))
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'src'
        self.source.mkdir()
        self.compat = self.source / 'compat.py'
        self.compat.write_text('from dataclasses import dataclass, field, make_dataclass\n')

    def discover(self):
        return generator.discover_native_dataclasses(self.source, ['models.py'])

    def test_scoping_allows_dependencies_and_checks_consumers_and_helper_fields(self):
        (self.source / 'vendor.py').write_text(
            'from dataclasses import dataclass, field\n@dataclass(slots=True)\nclass Vendor:\n'
            '    x: int = field(default=1, repr=False)\n')
        model = self.source / 'models.py'
        model.write_text('import vendor\nfrom compat import dataclass\n@dataclass\nclass R:\n    x: int\n')
        self.assertEqual(self.discover(), ((('models', 'R'), ('x',)),))
        for option in ('slots=True', 'eq=True'):
            model.write_text('import vendor\nfrom compat import dataclass\n@dataclass(' + option + ')\nclass R:\n    x: int\n')
            with self.assertRaisesRegex(ValueError, 'unsupported dataclass.*models.R'):
                self.discover()
        self.compat.write_text('from dataclasses import dataclass, field\n'
                               'F = field(default=1, repr=True)\n'
                               'def mk(cls):\n    return dataclass(cls, eq=True)\n')
        for source in ('from compat import dataclass, F\n@dataclass\nclass R:\n    x: int = F\n',
                       'from compat import mk\n@mk\nclass R:\n    x: int\n'):
            model.write_text(source)
            with self.assertRaisesRegex(ValueError, 'unsupported (field|dataclass).*models.R'):
                self.discover()

    def test_transport_uses_system_temp(self):
        (self.source / 'models.py').write_text('from compat import dataclass\n@dataclass\nclass R:\n    x: int\n')
        original = tempfile.TemporaryDirectory
        with mock.patch.object(generator.tempfile, 'TemporaryDirectory', wraps=original) as created:
            self.assertEqual(self.discover(), ((('models', 'R'), ('x',)),))
        self.assertNotIn('dir', created.call_args.kwargs)

    @unittest.skipIf(os.name == 'nt' or (hasattr(os, 'geteuid') and os.geteuid() == 0),
                     'POSIX permissions require non-root Unix')
    def test_unwritable_parent(self):
        (self.source / 'models.py').write_text('from compat import dataclass\n@dataclass\nclass R:\n    x: int\n')
        mode = self.root.stat().st_mode & 0o777
        self.root.chmod(0o555)
        try:
            self.assertEqual(self.discover(), ((('models', 'R'), ('x',)),))
        finally:
            self.root.chmod(mode)

    def test_reexported_unsupported_definitions_fail_loudly(self):
        cases = (
            'from compat import dataclass\nclass Outer:\n    @dataclass\n    class R:\n        x: int\n',
            'from compat import dataclass\ndef make():\n    @dataclass\n    class R:\n        x: int\n',
            'from compat import dataclass\nclass R:\n    x: int\nR = dataclass(R)\n',
            'import compat\nR = compat.make_dataclass("R", ["x"])\n',
        )
        for source in cases:
            with self.subTest(source=source):
                (self.source / 'models.py').write_text(source)
                with self.assertRaisesRegex(ValueError, 'nested|function-local|decorator syntax'):
                    self.discover()


if __name__ == '__main__':
    unittest.main()
