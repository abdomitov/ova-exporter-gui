# QA review — 2.3.4 candidate, 2026-11-11

This review covers the current UI work and the export/update implementation.
Tests use synthetic VM names, documentation-only addresses, mocked VMware
sessions/processes and small local fixture archives. No real VMware server,
credential, VM export, cancellation, power operation or service was exercised.

## Findings fixed

| Severity | Reproduction and impact | Change |
| --- | --- | --- |
| Medium | Clear Save folder and export: an empty path became the process working directory. | Reject blank input before session preparation. |
| Medium | Remove/disconnect a destination while its free space is checked: an uncaught OS error leaves no useful UI explanation. | Report the destination error and keep setup usable without starting an export. |
| Medium | Enter a long output name: it may fit as a final name but exceed Windows' component limit after adding the incomplete suffix. | Validate UTF-16 length with space reserved for the 12-character export ID and temporary suffix. UI and worker share the validation. |
| Medium, hardening | A trusted endpoint can return unbounded XML or a DTD/entity payload. | Bound each SOAP reply to 32 MiB and reject DTDs through the parser target, including UTF-16 XML. No runtime dependency was added. |
| Low | Enter port 0: it silently became 443. | Reject the invalid port explicitly. |
| QA reliability | Tk callback exceptions could be printed while ordinary tests remained green. | Make unexpected default Tk callback errors fail the guarded test runner; existing per-test callback assertions remain. |
| Low, maintenance | Configured lint reported unused imports/variables and compressed test statements. | Remove unused code, format the affected tests/helpers, and document necessary standalone-script import-order exceptions. |

The cases were first reproduced against the earlier candidate. Their regressions
pass after the fixes. Export/power eligibility, warning/confirmation boundaries,
session isolation, cancellation cleanup and no-automatic-service-restart behavior
were preserved.

## Local checks

- 146 guarded offline tests pass on Python 3.14.5. Real network, external process
  creation and real saved-connection access are denied by the runner.
- The added pipeline fixture exercises the actual worker's argument construction,
  progress parsing, temporary package writing, checksum verification, final rename,
  cleanup follow-up and logout, with only the process and VMware API replaced.
  Tool failure, checksum corruption and preservation of an existing destination
  are also checked.
- Native Windows DPAPI encrypt/decrypt, purpose binding and tamper rejection pass
  using synthetic bytes entirely in memory, without reading or writing settings.
- Coverage reports 86% of statements and 73% of branches, 83% combined. Coverage
  is diagnostic evidence, not a claim that every behavior has been proven.
- Ruff passes the configured rules. Necessary imports after path/guard bootstrap
  have local, explained E402 exceptions.
- Bandit medium/high checks pass after manual triage. Certificate discovery is
  intentionally separate from trust, and every authenticated request compares the
  exact pinned certificate before sending its body/cookie. Those two B323 cases
  have documented exceptions. The XML parser's DTD-refusal target is tested and
  documents its B314 exception.
- Dependency advisory checks report no known vulnerabilities for the six resolved
  requirements-file packages and eight packages in the actual build-tool folder.
  These are build dependencies; the app still uses the standard-library runtime.

Local logs, detailed coverage, scan output and visual evidence stay in ignored
`artifacts/qa-*` paths. Reproduce the core checks with:

```powershell
python tools/offline_tests.py
python tools/preview_ui.py --check
python tools/benchmark_ui.py --output artifacts/ui-benchmark.json
python tools/package_source.py
```

With separate QA tools installed, the configured lint command is
`python -m ruff check src tests tools launch.pyw`.

## Installer and CI boundary

The existing release-candidate workflow checks Python 3.10/3.14, builds the real
Windows application and installer, runs the frozen fake-UI check, and tests real
installation, upgrade, parent-exit waiting, reopening and uninstall on a fresh
GitHub-hosted Windows runner. The installation test refuses local and self-hosted
execution. Its current run and exact source commit are available in
[GitHub Actions](https://github.com/abdomitov/ova-exporter-gui/actions/workflows/release-build.yml).
This local review alone does not establish the result of that separate run.

Source archives are allowlisted and checked against the checkout, with CRC,
compilation and SHA-256 verification. VMware binaries, local settings, exports,
QA dependencies and private artifacts are excluded. Installers remain unsigned.
This candidate is not an automatic app update: publication remains a separate
review/approval step.

## Remaining verification

- Real ESXi/vCenter login, permissions, export throughput, large inventories,
  cancellation/lease release and import/boot of a resulting VM need an explicitly
  authorized disposable VMware lab. The known ESXi export-state issue cannot be
  ruled out by mocked tests, and the app does not restart host services.
- Hosted Windows runner checks do not prove every Windows 10/11, DPI, storage,
  antivirus or corporate-policy configuration. macOS/Linux builds remain outside
  this Windows release.
- OVA verification checks archive integrity and manifest coverage; it is not a
  substitute for importing and booting the VM or application-level validation.
- No live server credentials or production deployment are needed for the checks
  completed here. No public release is implied by passing tests or a build.
