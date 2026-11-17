# Code signing and the Windows SmartScreen warning

The installer is currently **unsigned**. Windows SmartScreen therefore shows "Windows protected your PC"
(More info, then Run anyway). That screen means the file has no verified publisher and little download
history. It is not a malware verdict.

## What does and does not work

Per Microsoft's [code signing options](https://learn.microsoft.com/windows/apps/package-and-deploy/code-signing-options)
and [SmartScreen reputation](https://learn.microsoft.com/windows/apps/package-and-deploy/smartscreen-reputation)
pages (checked 2026-11-16):

| Option | Cost | Notes |
| --- | --- | --- |
| **SignPath Foundation** | Free for qualifying open-source projects | Signs from GitHub Actions; the project applies and is reviewed. Best fit for this repository. |
| **OV certificate** (DigiCert, Sectigo, GlobalSign …) | About $150–300 per year | Available worldwide. The private key must live on a hardware token or HSM. |
| **EV certificate** | $400+ per year | Since 2024 it no longer bypasses SmartScreen, so it is not worth buying for this alone. |
| **Azure Artifact Signing** | About $10 per month | Individuals only in the USA and Canada; organizations in the USA, Canada, EU and UK. |
| **Microsoft Store (MSIX)** | Free | Microsoft signs the package, so users see no SmartScreen warning. A different packaging path from the Inno Setup installer. |
| **Self-signed** | Free | Still blocked for the public. Only useful inside a company that deploys the certificate itself. |

No paid option removes the warning on day one. A signed file starts with no reputation too; the warning
fades after many clean downloads, and later releases signed by the same identity inherit that trust.
Nothing in this repository, and no trick on the user's PC, can honestly "bypass" SmartScreen.

## Recommended path

1. Apply to [SignPath Foundation](https://signpath.org/) for open-source signing, or buy an OV certificate.
2. Keep the signing key in the signing service or a hardware token, never in the repository.
3. Add a signing step to the `build` job of `release.yml` after the installer is built, before the checksum is written.
   The updater already verifies SHA-256 and the GitHub asset digest, so signing the final file keeps
   those checks valid.
4. Keep signing with the same identity for every release so reputation carries forward.

## What users can do today

- Compare the installer's SHA-256 with the value on the release page.
- Click **More info**, then **Run anyway**.
- Organizations can allow the file through their endpoint-management tool.
