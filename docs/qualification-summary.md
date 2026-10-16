# Qualification summary

The results below cover the audited implementation and earlier release artifacts.
They predate the repository layout changes; rebuilt packages require fresh verification.

## Locally executed

- CPython 3.12.14 on Windows; MicroPython 1.29.0 Windows port.
- Normal and PYTHONOPTIMIZE=1 clean-archive release runs: 72 checks each,
  71 passed, zero failures, one Unix-only permission check skipped.
- Twenty-four native-reference scenarios compare native CPython with the overlay
  on CPython and on actual MicroPython: custom methods, hash policy, assignment
  hooks, post-init timing, and frozen/undecorated subclass behavior.
- Offline wheel installation, installed CLI generation/checks, device deployment,
  and optimized broken-equality detection were executed.

## Independent audit evidence

An independent auditor reports building the real MicroPython 1.29.0 Unix port from
the v1.29.0 tag and running the supplied suite: 72 checks, 70 passed, two skipped.
That run includes the native parity matrix. The auditor separately verified system
temp transport with an unwritable source parent as a non-root user. Packaging was
not included in the source/tests-only audit archive and was verified locally instead.
No new medium-or-higher findings were reported in the final independent re-audit.

## Scope

These are the tested configurations, not blanket support for all MicroPython boards
or compile options. Frozen behavior requires custom attribute interception support.
Other host versions remain unqualified despite the library's Python >=3.8 metadata.
README.md documents the supported subset and remaining detection limitations.
