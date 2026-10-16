"""Run all extraction checks, refusing missing release prerequisites or skips."""

import os
import shutil
import sys
import unittest
from pathlib import Path


def resolve_runtime(value):
    if not value:
        return None
    if Path(value).is_file():
        return str(Path(value).resolve())
    return shutil.which(value)


def optional_capability_skip(test, reason):
    if (test.id().endswith('.test_unwritable_parent')
            and reason == 'POSIX permissions require non-root Unix'):
        return True
    return (test.id().endswith('.test_scan_root_symlink_is_rejected')
            and reason.startswith('directory symlinks unavailable:'))


def main():
    runtime = resolve_runtime(os.environ.get('MICROPYTHON_EXECUTABLE'))
    if not runtime:
        print('release verification requires an existing MICROPYTHON_EXECUTABLE or command on PATH', file=sys.stderr)
        return 2
    wheel = os.environ.get('LIBRARY_WHEEL')
    if not wheel or not Path(wheel).is_file():
        print('release verification requires an existing LIBRARY_WHEEL', file=sys.stderr)
        return 2
    os.environ['MICROPYTHON_EXECUTABLE'] = runtime
    suite = unittest.defaultTestLoader.discover(str(Path(__file__).resolve().parent))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    required_skips = [(test, reason) for test, reason in result.skipped
                      if not optional_capability_skip(test, reason)]
    if required_skips:
        print('release verification refuses skipped required checks', file=sys.stderr)
        return 1
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
