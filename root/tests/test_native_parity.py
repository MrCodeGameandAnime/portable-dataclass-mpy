import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from portable_dataclass_metadata import discover_native_dataclasses, write_manifest
import test_runtime_contract

ERROR_HELPER = '''
def error_of(call):
    try:
        call()
    except Exception as error:
        return type(error).__name__
    return 'none'
'''


class NativeParityTests(unittest.TestCase):
    def compare(self, definitions, observations, expected, import_error=False):
        with tempfile.TemporaryDirectory(dir=str(ROOT / 'tests')) as temp:
            workspace = Path(temp)
            consumer = workspace / 'consumer'
            consumer.mkdir()
            (consumer / 'parity_models.py').write_text(
                'from dataclasses import dataclass, field\n' + definitions,
                encoding='utf-8',
            )
            device = workspace / 'device'
            device.mkdir()
            if import_error:
                records = ((('parity_models', 'Record'), ('x',)),)
            else:
                records = discover_native_dataclasses(consumer, [consumer])
            write_manifest(records, device / '_dataclass_fields.py')
            shutil.copyfile(ROOT / 'src/portable_dataclass_metadata/micropython/dataclasses.py',
                            device / 'dataclasses.py')
            paths = [consumer.as_posix()]
            program = ERROR_HELPER + '''
try:
    import parity_models as m
except Exception as error:
    result = [type(error).__name__]
else:
''' + '\n'.join('    ' + line for line in observations.splitlines()) + '\nprint(json.dumps(result))\n'
            env = os.environ.copy()
            env.pop('PYTHONPATH', None)
            env['PYTHONDONTWRITEBYTECODE'] = '1'

            def run(executable, overlay, micropython=False):
                search = ([device.as_posix()] if overlay else []) + paths
                bootstrap = 'import sys\nsys.path[:0] = %r\nimport json, dataclasses\n' % search
                if micropython:
                    bootstrap += ("if sys.implementation.name != 'micropython' or "
                                  "sys.implementation.version[:3] != (1, 29, 0):\n"
                                  "    raise RuntimeError('wrong MicroPython runtime')\n")
                if overlay:
                    bootstrap += "if dataclasses.__file__.replace('\\\\', '/') != %r:\n    raise RuntimeError('wrong overlay')\n" % (device / 'dataclasses.py').as_posix()
                else:
                    bootstrap += "if 'portable_dataclass_metadata' in dataclasses.__file__:\n    raise RuntimeError('wrong native reference')\n"
                args = [executable] + ([] if micropython else ['-S']) + ['-c', bootstrap + program]
                completed = subprocess.run(args, env=env, cwd=str(workspace), capture_output=True,
                                           text=True, timeout=30)
                self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
                return json.loads(completed.stdout.strip())

            reference = run(sys.executable, False)
            self.assertEqual(reference, expected, 'native characterization changed')
            self.assertEqual(run(sys.executable, True), reference, 'CPython overlay differs from native')
            runtime = os.environ.get('MICROPYTHON_EXECUTABLE')
            if runtime:
                self.assertEqual(run(runtime, True, True), reference, 'MicroPython differs from native')

    def test_custom_constructor_equality_and_hash_are_preserved(self):
        for frozen in (False, True):
            with self.subTest(frozen=frozen):
                self.compare('''
events = []
def own_init(self, text):
    events.append('init')
    object.__setattr__(self, 'x', int(text) + 10)
def own_eq(self, other):
    return isinstance(other, Record) and self.x %% 10 == other.x %% 10
def own_hash(self):
    return 200 + self.x %% 10
@dataclass(frozen=%r)
class Record:
    x: int
    __init__ = own_init
    __eq__ = own_eq
    __hash__ = own_hash
    def __post_init__(self):
        events.append('post')
''' % frozen, '''
a = m.Record('3')
b = m.Record('13')
result = [a.x, b.x, a == b, hash(a),
          m.Record.__init__ is m.own_init, m.Record.__eq__ is m.own_eq,
          m.Record.__hash__ is m.own_hash, m.events]
''', [13, 23, True, 203, True, True, True, ['init', 'init']])

    def test_hash_rules_cover_explicit_none_and_implicit_none_from_custom_eq(self):
        for frozen in (False, True):
            for custom_eq in (False, True):
                for hash_kind in ('absent', 'none', 'method'):
                    with self.subTest(frozen=frozen, custom_eq=custom_eq, hash_kind=hash_kind):
                        eq = '    def __eq__(self, other):\n        return self.x == other.x\n' if custom_eq else ''
                        hash_body = {'absent': '', 'none': '    __hash__ = None\n',
                                     'method': '    def __hash__(self):\n        return 83\n'}[hash_kind]
                        hashable = hash_kind == 'method' or (frozen and (hash_kind == 'absent' or custom_eq))
                        self.compare('@dataclass(frozen=%r)\nclass Record:\n    x: int\n' % frozen + eq + hash_body,
                                     '''
a = m.Record(1)
hashable = error_of(lambda: hash(a)) == 'none'
custom = hash(a) == 83 if hashable and %r else False
result = [hashable, custom, m.Record.__dict__.get('__hash__') is None]
''' % (hash_kind == 'method'), [hashable, hash_kind == 'method', not hashable])

    def test_inherited_methods_are_replaced_by_generated_methods(self):
        self.compare('''
class Parent:
    def __init__(self, x):
        self.x = -100
    def __eq__(self, other):
        return True
    def __hash__(self):
        return 83
@dataclass
class Record(Parent):
    x: int
''', '''
a = m.Record(2)
result = [a.x, a == m.Record(3), error_of(lambda: hash(a)),
          m.Record.__init__ is m.Parent.__init__, m.Record.__eq__ is m.Parent.__eq__]
''', [2, False, 'TypeError', False, False])

    def test_mutable_initialization_calls_custom_setattr(self):
        self.compare('''
events = []
@dataclass
class Record:
    x: str
    y: int = 2
    def __setattr__(self, name, value):
        events.append((name, value))
        if name == 'x':
            value = value.strip().upper()
        if name == 'y' and value < 0:
            raise ValueError('negative')
        object.__setattr__(self, name, value)
''', '''
a = m.Record(' hi ')
events = list(m.events)
result = [a.x, a.y, events, error_of(lambda: m.Record('bad', -1))]
''', ['HI', 2, [['x', ' hi '], ['y', 2]], 'ValueError'])

    def test_post_init_is_selected_at_decoration_and_dispatched_at_construction(self):
        for has_hook in (False, True):
            for late_hook in (False, True):
                with self.subTest(has_hook=has_hook, late_hook=late_hook):
                    hook = ("    def __post_init__(self):\n        events.append('base')\n        self.x += 1\n"
                            if has_hook else '')
                    late = 'Record.__post_init__ = late\n' if late_hook else ''
                    self.compare('''
events = []
def late(self):
    events.append('late')
    self.x += 100
@dataclass
class Record:
    x: int
''' + hook + '''
class Child(Record):
    def __post_init__(self):
        events.append('child')
        self.x += 10
''' + late, '''
a = m.Record(1)
b = m.Child(1)
result = [a.x, b.x, m.events]
''', [101 if late_hook else 2, 11, ['late' if late_hook else 'base', 'child']]
                        if has_hook else [1, 1, []])

    def test_frozen_subclass_extra_attributes_delegate_to_parent_hooks(self):
        self.compare('''
events = []
class Parent:
    def __setattr__(self, name, value):
        events.append(('set', name))
        object.__setattr__(self, name, value.upper())
    def __delattr__(self, name):
        events.append(('del', name))
        object.__delattr__(self, name)
@dataclass(frozen=True)
class Record(Parent):
    x: int
class Child(Record):
    pass
''', '''
base = m.Record(1)
child = m.Child(1)
child.tag = 'hi'
tag = child.tag
del child.tag
result = [tag, hasattr(child, 'tag'), error_of(lambda: setattr(child, 'x', 5)),
          error_of(lambda: delattr(child, 'x')), error_of(lambda: setattr(base, 'new', 'v')),
          error_of(lambda: delattr(base, 'missing')), m.events]
''', ['HI', False, 'FrozenInstanceError', 'FrozenInstanceError', 'FrozenInstanceError',
      'FrozenInstanceError', [['set', 'tag'], ['del', 'tag']]])

    def test_decorated_frozen_child_blocks_all_fields_but_allows_undecorated_extra_attributes(self):
        self.compare('''
@dataclass(frozen=True)
class Record:
    x: int
@dataclass(frozen=True)
class Child(Record):
    y: int = 2
class Grandchild(Child):
    pass
''', '''
a = m.Child(1)
b = m.Grandchild(1)
b.tag = 'ok'
result = [a.x, a.y, a == m.Child(1), error_of(lambda: hash(a)), b.tag,
          error_of(lambda: setattr(a, 'new', 0)), error_of(lambda: setattr(b, 'x', 3)),
          error_of(lambda: setattr(b, 'y', 4))]
''', [1, 2, True, 'none', 'ok', 'FrozenInstanceError', 'FrozenInstanceError', 'FrozenInstanceError'])

    def test_frozen_custom_setattr_or_delattr_is_rejected_like_native(self):
        for method in ('__setattr__', '__delattr__'):
            with self.subTest(method=method):
                self.compare('@dataclass(frozen=True)\nclass Record:\n    x: int\n'
                             '    def %s(self, *args):\n        pass\n' % method,
                             'result = ["accepted"]', ['TypeError'], import_error=True)

    def test_optimized_runtime_checks_detect_deliberately_broken_equality(self):
        with tempfile.TemporaryDirectory(dir=str(ROOT / 'tests')) as temp:
            overlay = Path(temp)
            original = (test_runtime_contract.OVERLAY_ROOT / 'dataclasses.py').read_text(encoding='utf-8')
            (overlay / 'dataclasses.py').write_text(original.replace('return all(', 'return False and all('), encoding='utf-8')
            with mock.patch.dict(os.environ, {'PYTHONOPTIMIZE': '1'}), \
                 mock.patch.object(test_runtime_contract, 'OVERLAY_ROOT', overlay):
                result = test_runtime_contract.run_overlay('''
import sys, dataclasses
if sys.flags.optimize != 1:
    raise RuntimeError('optimization probe did not run optimized')
@dataclasses.dataclass
class Record:
    name: str
    count: int = 2
    items: list = dataclasses.field(default_factory=list)
assert Record('a') == Record('a')
''')
            self.assertNotEqual(result.returncode, 0, 'broken equality escaped optimized checks')
            self.assertIn('AssertionError', result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
