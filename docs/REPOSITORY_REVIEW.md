# Repository review — 2026-11-12

Reviewed the application source, tests, installer/build helpers, GitHub workflows,
README, contribution/security/license notices and all developer documents. The
application remains version 2.3.5; this repository maintenance does not replace
the published installer or announce a new app update.

## Changes

- Replaced all six screenshots with actual captures from the guarded 2.3.5
  preview. Added the VM-selection image to the README gallery. Captures contain
  invented names, documentation-only addresses, empty credential fields and
  synthetic progress. No real server was contacted and no export was started.
- Corrected obsolete installer-validation statements. The release's hosted
  installer lifecycle passed; Windows 10, all end-user configurations and live
  VMware operation remain unverified.
- Clarified that users without the updater can install the current release
  directly, without installing an intermediate version.
- Updated the DevOps guide to describe both fresh-candidate installation and
  the separate upgrade check.
- Fixed the publish helper's draft lookup. The published-tag endpoint returned
  404 for the unpublished 2.3.5 draft; the helper now uses the authenticated
  release list and requires exactly one matching tag, explicit draft state and
  exact target commit. Missing/duplicate/published/mismatched drafts fail closed.
  The lookup considers the 100 most recent releases. Commit, hash, successful
  build and explicit publish-confirmation checks remain in place.
- The publish gate now also requires the recorded fresh installed-app startup
  and fresh-uninstall checks, matching the build gate's lifecycle requirements.

## Screenshot provenance

Captured with the Windows computer-use tool from `tools/preview_ui.py`:

| File | Preview argument |
| --- | --- |
| `images/dashboard-dark.jpg` | Default |
| `images/dashboard-light.jpg` | `--light` |
| `images/dashboard-compact.jpg` | `--compact` |
| `images/new-export-dark.jpg` | `--wizard-connect` |
| `images/vm-selection-dark.jpg` | `--wizard-selection`; selected the illustrative Atlas Maps row |
| `images/tool-missing.jpg` | `--missing-tool` |

The preview blocks sockets, external processes, persistent settings and VMware
API construction. The forms are illustrative UI states, not authenticated server
sessions. Preview windows were closed after capture. These are real UI captures,
not generated mockups.

## Verification and limits

168 guarded offline tests pass locally, including exact draft lookup and rejection
cases. Image decoding, local documentation targets, configured lint, source ZIP
allowlisting/CRC/source matching and Python compilation are checked as part of
this maintenance. GitHub's Python 3.10/3.14 and dependency-check results are
recorded in the maintenance PR.

No runtime dependency, VMware behavior, cancellation policy, credential policy,
published installer, GitHub protection setting or release visibility was changed.
The corrected publisher has offline regression coverage; a future authorized new
release must exercise actual draft-to-public publication end to end. The already
public 2.3.5 release is not republished to test automation.

Remaining priorities: independent publisher signing/provenance, main-branch
protection, dependency maintenance and an explicitly authorized disposable VMware
integration lab. See [security findings](SECURITY_REVIEW.md),
[QA scope](QA_REVIEW.md) and [release evidence](https://github.com/abdomitov/ova-exporter-gui/actions/runs/43019403203).
