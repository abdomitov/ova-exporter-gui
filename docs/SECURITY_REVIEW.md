# Security review — 2026-11-11

Scope: security changes prepared for OVA Exporter GUI 2.3.5, reviewed against commit
`5cf24040a5ff1e2f5395c71b51e9c158e89fb97f`, plus the local security fixes described
below. This is a source review and bounded adversarial test exercise, not a
penetration test of a VMware installation. No critical or high-severity exploit
was confirmed in this scope. This does not establish that the application has
no vulnerabilities.

## Confirmed findings and fixes

| ID | Severity | Finding and prerequisites | Resolution |
| --- | --- | --- | --- |
| SEC-01 | Medium | First-use and changed-certificate trust prompts did not explicitly default to No. An attacker able to intercept a connection still needed user approval, but Enter could approve the attacker's certificate unintentionally. | Both prompts now default to No. Declining sends no login, preserves an existing pin and clears the password field. |
| SEC-02 | Medium, availability | Streaming OVA disk hashes did not bound TAR extension metadata before the standard parser requested it into memory. A malicious/corrupt package reaching verification could exhaust memory or spend excessive time parsing metadata. The UI exports through a separately installed OVF Tool; it does not provide arbitrary archive import. | Limit each extension header to 2,000,000 bytes, total metadata to 4,000,000 bytes, all headers to 10,000, and nested extensions to 32. Reject unsupported sparse encodings before sparse-map allocation. Regular large VMDKs remain streamed. |

Reproduction uses synthetic certificates and 512-byte TAR headers, with an
instrumented stream refusing oversized reads. No memory exhaustion attack was
run. Tests also cover cumulative limits, nested headers, sparse formats and
successful ordinary PAX/GNU long-name archives. Python's internal TAR processing
hooks are covered on the local Python runtime; compatibility CI must be rerun
before packaging these source changes.

## Remaining risks and repository configuration

| Severity | Finding | Practical next step |
| --- | --- | --- |
| Medium, defense in depth | Installers are unsigned and updates rely on GitHub HTTPS, exact repository URLs and hashes from the same release. Compromise of release-publishing access could replace both installer and checksum; hashes are not an independent publisher signature. | Protect publisher accounts with strong MFA/passkeys, restrict publishing, introduce independent code signing and/or verified build attestations with a suitable source/builder policy. No signing key or paid service was configured during this review. |
| Medium, repository configuration | The GitHub API reports `main` as unprotected and no repository rulesets. A principal with write access can bypass PR checks. | Require PR review and successful CI for main; restrict force pushes and deletion, with an intentional administrative bypass policy. |
| Low, maintenance | GitHub reports automatic Dependabot security updates disabled. The existing pip-audit CI runs on pushes/PRs rather than continuously while the project is idle. | Enable security updates and scheduled dependency/action reviews or a scheduled advisory audit. |
| Informational | Session tickets are passed as arguments to OVF Tool, not passwords. Another process under the same Windows account can inspect process arguments/memory and decrypt current-user DPAPI data. | Treat the Windows account as the local trust boundary and use a least-privilege VMware export account. This app is not isolation from malware already running as the user. |

GitHub secret scanning and secret-scanning push protection are enabled. No
repository settings were changed. Account MFA, collaborator permissions,
organization policy, proprietary OVF Tool binaries and native dependency CVEs
were not comprehensively audited.

## Checks and evidence

- 166 guarded offline tests pass on local Python 3.14.5, including 20 new
  adversarial tests. Real network connections, external process creation and real
  connection-profile access remain blocked by the runner. Initial failures were
  reproduced before the fixes; a separate sandbox run also encountered Windows
  temporary-file ACL restrictions and is not used as the product verdict.
- Attack fixtures cover certificate substitution before credentials/cookies,
  certificate discovery without authentication, XML injection in credentials,
  unsafe update redirects, response URL revalidation, malformed release paths,
  mismatched checksum filenames, oversized metadata, shell metacharacters,
  secret redaction, forbidden stored credential fields, traversal through PAX,
  archive links/devices and TAR resource limits.
- Existing regressions cover UTF-8/UTF-16 DTD refusal, bounded SOAP responses,
  native DPAPI tamper/purpose checks, installer tampering and cancellation
  confirmation/process ownership. They are synthetic tests, not proof of live
  ESXi lease cleanup.
- Refreshed pip-audit checks report no known vulnerabilities for six resolved
  requirement packages and eight packages in the actual local build-tool folder.
  This is not a native-runtime or OVF Tool vulnerability audit.
- Configured Ruff rules and the guarded fake-UI check pass.
- Bandit application scan has no unsuppressed medium/high findings and ten low
  heuristic findings. Manual review covers deliberate TOFU certificate discovery,
  exact certificate pinning before authenticated requests, bounded DTD-refusing
  XML parsing, argument-list process creation and best-effort logout. The wider
  tools scan reports two medium B310 heuristics: the hosted installer checker
  uses a constant HTTPS baseline URL with a pinned SHA-256; license collection
  uses constant HTTPS upstream hosts and validated numeric version tags, writing
  text only. Neither was confirmed as arbitrary URL/code execution.
- A separate value-redacting scan found zero matches in 13 project-reachable
  commits (756 text file versions). It checks for
  GitHub/Slack tokens, AWS key IDs and PEM private-key patterns. Its result is in
  the ignored evidence directory; pattern scanning is not exhaustive secret
  detection and does not inspect Windows/GitHub credential stores.

Detailed scanner JSON, reproduction logs, final regression output and secret
scan counts remain under ignored `artifacts/security-2026-11-11/` locally.
No real VMware system, installed app, public release, GitHub protection setting
or production deployment was changed. The earlier 2.3.4 candidate installer does not contain these fixes. Version 2.3.5
release CI builds and checks a new installer before publication.

## Reproduce safely

```powershell
python tools/offline_tests.py
python tools/preview_ui.py --check
```

With the separate QA tools installed:

```powershell
python -m ruff check src tests tools launch.pyw
python -m bandit -r src launch.pyw -ll
python -m pip_audit -r requirements-build.txt --progress-spinner off
```

Live server authorization, permissions, cancellation recovery, large export
behavior, importing/booting an exported VM and Windows 10 require a separately
authorized disposable lab. For version 2.3.5, the exact build manifest and linked GitHub Actions run record
Python compatibility and installer lifecycle results. Earlier QA CI applies only
to its recorded candidate commit.

References: [Python TAR security guidance](https://docs.python.org/3/library/tarfile.html#hints-for-further-verification),
[GitHub build attestations](https://docs.github.com/en/actions/how-tos/secure-your-work/use-artifact-attestations/use-artifact-attestations).
