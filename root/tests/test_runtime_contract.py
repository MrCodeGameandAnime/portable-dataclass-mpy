import os
from pathlib import Path
import subprocess
import sys
import unittest
from _checks import checked_source


EXTRACTION_ROOT = Path(__file__).resolve().parents[1]
OVERLAY_ROOT = EXTRACTION_ROOT / "src" / "portable_dataclass_metadata" / "micropython"
FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "micropython"


def run_overlay(source, executable=sys.executable, micropython=False):
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join((str(FIXTURE_ROOT), str(OVERLAY_ROOT)))
    env["EXPECTED_OVERLAY"] = str(OVERLAY_ROOT / "dataclasses.py")
    bootstrap = "import sys\nsys.path[:0] = %r\n" % [
        FIXTURE_ROOT.as_posix(), OVERLAY_ROOT.as_posix()
    ]
    if micropython:
        bootstrap += (
            "assert sys.implementation.name == 'micropython'\n"
            "assert sys.implementation.version[:3] == (1, 29, 0)\n"
        )
    bootstrap += "import dataclasses\nassert dataclasses.__file__.replace('\\\\', '/') == %r\n" % (
        OVERLAY_ROOT / "dataclasses.py"
    ).as_posix()
    arguments = [executable]
    if not micropython:
        arguments.append("-S")
    arguments.extend(("-c", checked_source(bootstrap + source)))
    return subprocess.run(
        arguments,
        cwd=str(EXTRACTION_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


class RuntimeContractTests(unittest.TestCase):
    executable = sys.executable
    micropython = False

    def assertOverlayPasses(self, source):
        result = run_overlay(source, self.executable, self.micropython)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_positional_keyword_defaults_factories_and_ordered_fields(self):
        self.assertOverlayPasses("""
import dataclasses

@dataclasses.dataclass
class Record:
    name: str
    count: int = 2
    items: list = dataclasses.field(default_factory=list)

first = Record('  A  ')
second = Record(name='B')
assert first.name == '  A  '
assert first.count == 2
assert first.items == []
assert first == Record('  A  ', 2, [])
assert first != second
first.items.append('only first')
assert second.items == []
assert Record.__dataclass_fields__ == ('name', 'count', 'items')
""")

    def test_frozen_assignment_and_post_init_normalization(self):
        self.assertOverlayPasses("""
import dataclasses

@dataclasses.dataclass(frozen=True)
class FrozenRecord:
    code: str
    normalized: str

    def __post_init__(self):
        object.__setattr__(self, 'normalized', self.normalized.strip().upper())

record = FrozenRecord('x', '  value  ')
assert record.normalized == 'VALUE'
try:
    record.code = 'changed'
except dataclasses.FrozenInstanceError as error:
    assert isinstance(error, AttributeError)
    pass
else:
    raise AssertionError('frozen assignment was accepted')
try:
    del record.code
except dataclasses.FrozenInstanceError as error:
    assert isinstance(error, AttributeError)
    pass
else:
    raise AssertionError('frozen deletion was accepted')
""")

    def test_constructor_and_field_reject_unsupported_inputs(self):
        self.assertOverlayPasses("""
import dataclasses

@dataclasses.dataclass
class ErrorRecord:
    required: int
    optional: int = 4

def raises_type_error(call):
    try:
        call()
    except TypeError:
        return
    raise AssertionError('expected TypeError')

raises_type_error(lambda: ErrorRecord())
raises_type_error(lambda: ErrorRecord(1, 2, 3))
raises_type_error(lambda: ErrorRecord(1, required=2))
raises_type_error(lambda: ErrorRecord(1, unknown=2))
raises_type_error(lambda: dataclasses.field(1))
raises_type_error(lambda: dataclasses.field(default=1, default_factory=list))
raises_type_error(lambda: dataclasses.field(unsupported=True))
raises_type_error(lambda: dataclasses.dataclass(frozen=True, order=True))
""")

    def test_value_hashing_and_mutable_unhashability(self):
        self.assertOverlayPasses("""
import dataclasses
@dataclasses.dataclass(frozen=True)
class FrozenRecord:
    code: str
    normalized: str
a = FrozenRecord('a', 'b')
b = FrozenRecord('a', 'b')
assert a == b and hash(a) == hash(b)
assert len({a, b}) == 1
assert {a: 42}[b] == 42
@dataclasses.dataclass
class Record:
    name: str
    count: int = 2
    items: list = dataclasses.field(default_factory=list)
for value in (Record('a'), FrozenRecord([], 'b')):
    try:
        hash(value)
    except TypeError:
        pass
    else:
        raise AssertionError('unhashable record accepted')
""")

    def test_foreign_equality_and_factory_class_attributes(self):
        self.assertOverlayPasses("""
import dataclasses
@dataclasses.dataclass
class Record:
    name: str
    count: int = dataclasses.field(default=2)
    items: list = dataclasses.field(default_factory=list)
assert Record.count == 2
assert not hasattr(Record, 'items')
assert Record('x').__eq__(object()) is NotImplemented
""")

    def test_identity_must_exist_in_the_supplied_manifest(self):
        self.assertOverlayPasses("""
import dataclasses

try:
    @dataclasses.dataclass
    class Missing:
        value: int
except RuntimeError as error:
    assert 'missing portable dataclass metadata' in str(error)
else:
    raise AssertionError('class without manifest metadata was accepted')
""")


class MicroPythonRuntimeContractTests(RuntimeContractTests):
    micropython = True

    @classmethod
    def setUpClass(cls):
        cls.executable = os.environ.get("MICROPYTHON_EXECUTABLE")
        if not cls.executable:
            raise unittest.SkipTest("set MICROPYTHON_EXECUTABLE to the pinned 1.29.0 runtime")


if __name__ == "__main__":
    unittest.main()
