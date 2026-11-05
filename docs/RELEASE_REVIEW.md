# Release review — 2026-11-05

## 2.2.0 dependency-setup update

The installer now displays the OVF Tool requirement before installation and at
completion. The app checks for the executable at startup and before new export
setup. Missing/inaccessible locations show a red status and block new exports.
A custom ovftool.exe can be selected; its path is protected with current-user
DPAPI. Auto-detect clears the custom selection and checks default folders/PATH.
Tool changes are blocked while tasks are active. Existing export processes are
not cancelled or restarted by these checks. Found status confirms file presence;
it is not a complete DLL, version, compatibility or server-connectivity test.

New offline regressions cover missing-tool blocking, custom selection/remembering,
automatic recovery, active-task protection, encrypted persistence, environment
override precedence and inaccessible files. The red banner and blocking message
were visually inspected with fake data. No vendor binary is redistributed.
The final guarded suite passes 83 tests, and the frozen executable's fake-only
self-test passes. Clean-machine installer testing and real VMware validation
remain outside these checks.

Target: Windows users exporting powered-off VMware VMs to a local verified OVA.
Decision: suitable for a source preview release after the local checks below;
not certified for unrestricted production use without disposable-lab validation.

## Scope and coordination

The lead coordinated independent QA, design/accessibility and security/deployment
reviews. Production changes were owned by the lead; QA owned test changes.
Reviewed startup/configuration, certificate review, login/session handling,
inventory selection, filename validation, scheduler, progress, verification,
cancellation/exit, encrypted hints, and source packaging. The review covered the core user journeys end to end.
Only fake clients, fake UI data and temporary local files were used. No real
VMware login, export, VM power operation or host-service restart was performed.

## Confirmed issues and changes

| Severity | Issue and impact | Fix / verification |
| --- | --- | --- |
| Medium | Duplicate TAR members overwrote earlier digests; unverified first descriptor could be labelled verified. | Reject duplicate/case/path-alias entries before hashing. Security reviewer independently reproduced the bypass and confirmed the fix. Regression fixtures cover duplicates, duplicate manifests and unsafe paths. |
| Medium | Keyboard focus could land on invisible controls in a small wizard. Ancestor FocusIn events could undo scrolling. | Scroll only the actual focused descendant into view; avoid re-entrant layout pumping. Native focus regression passes. |
| Medium | Dark buttons and text over progress fill had insufficient normal-text contrast; password eye lacked a focus cue. | Darker accent, high-contrast progress text, restored focus element/background. Calculated text ratios reviewed; no formal accessibility certification. |
| Low | Reserved Windows device filenames were accepted until export failed. | Shared UI/worker validation rejects device names, invalid characters and non-OVA extensions. |
| Low | Invalid explicit OVFTOOL_PATH could select an unrelated installation. | Honor the exact configured path; report missing tool instead of silently falling back. |
| Test infrastructure | Deferred pane layout and Tcl callback cleanup caused false/cascading UI failures. | Wait for layout in the wheel test; cancel Tcl callbacks without deleting another widget's command registry. |
| Release process | No repeatable guarded suite runner or CI definition. | Added tools/offline_tests.py and Windows Python 3.10/3.14 workflow. CI is configured, not remotely executed in this review. |

## Security/deployment evidence

- Certificate bytes are compared before SOAP credentials/cookies are sent.
- Settings accept only hint/pin fields. Passwords are not persisted. Native DPAPI
  roundtrip, wrong-purpose rejection and modified-ciphertext rejection passed on
  fabricated in-memory data, independently checked by the security reviewer.
- No shell command interpolation is used for OVF Tool execution. Force-stop is
  restricted to the owned process handle. Archive verification never extracts TAR
  files to disk. Code checks do not replace a penetration test.
- Source packaging uses an explicit allowlist and SHA-256 sidecar. VMware runtime,
  real settings, caches, exports and local history are excluded.
- Windows sandbox temporary-directory ACL failures were environmental; the suite
  was rerun outside that sandbox with network/process/profile guards retained.

Final executed results on Windows/Python 3.14:

- Guarded regression suite: **77 passed, zero failures/errors/skips**, independently
  repeated by QA and from the clean extracted 2.0.2 source ZIP.
- Fake preview self-check: passed in the working checkout and clean extraction.
- All packaged Python sources compiled; ZIP CRC, exact 49-file allowlist,
  SHA-256 sidecar and source-byte comparison passed; no vendor/user-data files.
- Designer visually inspected current dark/light dashboards and VM selection,
  inventory wheel scrolling and a visible keyboard focus outline. The owned
  fake preview was closed after inspection. Manual border resizing did not work
  in automation; minimum-size focus reveal is verified by the isolated fixture.
- Existing full-suite baseline: 71 tests with two failures and one cleanup error
  outside the filesystem sandbox. Final fixes eliminated those failures and
  added six meaningful regressions. Additional restricted-sandbox temp-directory
  failures were not treated as application failures or concealed as passes.

Logs: artifacts/qa-verified-results.txt and the fresh release-check folder in the
working checkout. The artifact directory is excluded from public distribution.

## Remaining release gates

1. Authorize a disposable ESXi/vCenter lab: test actual ticket-based export,
   least-privilege permissions, insufficient disk space/network interruptions,
   server aliases and cancellation behavior. Never reproduce the known export
   state defect on a production VM. A UI warning cannot fix that server defect.
2. Run the configured CI after pushing. Python 3.10 and a clean Windows install
   were not available for local validation; verify both launchers there.
3. Verify Narrator/NVDA, high DPI and Windows high-contrast mode. Canvas metrics
   are not yet a fully accessible native status surface.
4. Public executable/installer signing, update delivery, and recovery/resume are
   not implemented. The source release requires separate Python/Tk and OVF Tool.
5. Same-Windows-user software can decrypt DPAPI data and inspect transient process
   arguments, including the single-use clone ticket. Cross-account DPAPI isolation
   was not separately exercised. This is not an app-only secrets vault.

## Reproduce and run

From the extracted project folder in PowerShell:

```powershell
py -3 tools/offline_tests.py
py -3 tools/preview_ui.py --check
py -3 tools/package_source.py
py -3 launch.pyw
```

Install Python 3.10+ with Tkinter and the Windows launcher, then install VMware
OVF Tool separately. For a nonstandard installation set OVFTOOL_PATH to the full
ovftool.exe path before starting. The VBS launcher starts without a console; use
the CMD launcher for startup diagnostics. Review fingerprints on first use/change.
Do not upload the private Desktop runtime directory; publish the source ZIP.
