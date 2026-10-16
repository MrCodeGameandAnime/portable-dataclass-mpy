# Security policy

## Reporting a vulnerability

Send suspected vulnerabilities privately to
[support@404builds.com](mailto:support@404builds.com), with a subject beginning
`[portable-dataclass-mpy security]`. Please avoid public issues or pull requests
that disclose an unaddressed vulnerability.

Include the affected package version, host and MicroPython versions, relevant
port/build details, impact, and a minimal reproduction. Explain any prerequisites
or trust boundaries involved. Remove credentials and personal data from examples.

Maintainers will review the report, request clarification when needed, and
coordinate a fix and disclosure where appropriate. Response and release times
depend on availability and the issue; no fixed service-level commitment is offered.
Please coordinate publication of sensitive details while a report is being assessed.

## Versions

Reports for any version are welcome. Security fixes target the latest released
version; users of older releases may need to upgrade. See the
[release history](https://github.com/MrCodeGameandAnime/portable-dataclass-mpy/releases)
for available versions. Tested environments are listed in [README.md](README.md#verification).

## Trust boundaries

The host generator imports consumer code. Its subprocess isolation, closed stdin,
and timeout are operational safeguards, not a security sandbox. Generate metadata
only from code you trust, including that code's imported dependencies. Do not use
the generator to inspect untrusted submissions in a privileged environment.

The device overlay trusts the deployed Python code and manifest. It is not a
sandbox, and type annotations do not validate runtime values. Run the host CLI
with `--check` before deployment to detect stale metadata; this is a consistency
check, not a guarantee that deployed code is safe.
