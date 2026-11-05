# OVA Exporter GUI

<img src="assets/logo.svg" width="96" height="96" alt="OVA Exporter GUI cube and export arrow logo">

**A Windows GUI for VMware OVF Tool.** Browse powered-off virtual machines on ESXi or vCenter and export verified OVA packages without writing shell commands.

Independent community project. Not affiliated with or endorsed by Broadcom or VMware.

**[Download the Windows x64 installer](https://github.com/abdomitov/ova-exporter-gui/releases/tag/v2.1.0)**

This is a preview release for Windows 10/11 x64. Python/Tk are included in the
installer; VMware OVF Tool is a separate requirement. The installer is unsigned,
and clean-machine installation/live VMware validation remain release checks.
macOS and Linux downloads are not available yet.

## Features

- Compact export dashboard; select a task to see its full progress and speed history.
- Light and dark themes, resizable windows, keyboard navigation and mouse-wheel scrolling.
- ESXi and vCenter connections with a fresh password for each new setup session.
- Powered-off VM filter, search, destination selection and filename validation.
- Up to three concurrent exports across server addresses; one active export per address.
- Approximate time remaining, output-file write rate, elapsed time and peak speed.
- Manifest checksum verification before an `.incomplete` package becomes the final `.ova`.
- Optional remembered addresses/usernames and trusted certificate fingerprints, protected with Windows current-user DPAPI. Passwords are never saved.

This release supports exporting to a local OVA. It does not implement VM deployment, live migration, snapshot backups or resumable transfers.

## Screenshots

All screenshots use invented VM names and documentation-only server addresses.

![Dark dashboard showing OVA export progress and transfer speed history](docs/images/dashboard-dark.jpg)

<details>
<summary>Light theme, compact layout and connection form</summary>

![Light dashboard](docs/images/dashboard-light.jpg)

![Compact dashboard at 640 by 420 pixels](docs/images/dashboard-compact.jpg)

![Connection form with a masked-by-default password input](docs/images/new-export-dark.jpg)

</details>

## Requirements

- Windows 10/11 and Python 3.10 or newer with Tkinter. No third-party Python packages are required.
- [VMware OVF Tool](https://developer.broadcom.com/tools/open-virtualization-format-ovf-tool/latest/), installed separately under its own license.
- Access to the required VMware management and export endpoints and an account permitted to read inventory and export the chosen VM.
- A powered-off VM and sufficient free space for the export. The initial free-space check cannot predict the final compressed size.

## Run

**Windows users:** use the Windows x64 Setup executable from the project's
Releases when available. It includes Python/Tk and creates application shortcuts.
VMware OVF Tool is installed separately. See [installer details](docs/WINDOWS_INSTALLER.md).

**Developers/source users:**

1. Install Python with its Windows launcher and Tkinter support.
2. Install VMware OVF Tool.
3. Download/extract this source folder and double-click **Start OVA Exporter.vbs**.

If Windows Script Host is unavailable, use **Start OVA Exporter.cmd** or:

```powershell
py -3 app.py
```

OVF Tool is located in this order: `OVFTOOL_PATH`, a private `ovftool/ovftool.exe` beside the app, the standard VMware installation under Program Files, then `PATH`. The public source archive contains no VMware executable or DLL.

When `OVFTOOL_PATH` is explicitly set, that exact path is used. A missing override
produces an error rather than selecting a different installation.

For a custom installation, set the executable path before launching:

```powershell
$env:OVFTOOL_PATH = 'D:\Tools\VMware OVF Tool\ovftool.exe'
py -3 app.py
```

## Export a VM

1. Click **New export** or press **Ctrl+N**.
2. Enter an ESXi or vCenter address, username and password. Press **Enter** in the password field to connect. The eye toggles password visibility.
3. Verify the certificate fingerprint before accepting it. The app remembers that exact certificate; a changed fingerprint requires review again.
4. Choose a powered-off VM, folder and `.ova` filename, then add the task. Existing destination files are preserved.
5. Select its dashboard row for progress details. Add another export to work with another server.

The connection and selection sections keep their `+`/`−` headers. **F5** refreshes inventory; **Escape** closes an idle setup window. Shift+wheel scrolls tables horizontally. Drag the dashboard divider to resize its detail pane.

Use the top-right theme button to switch light/dark appearance. Short windows
hide the large summary cards to keep more room for the task table; the counts
and throughput remain available in the status line. Narrow windows prioritize
the server, VM, progress, status and speed columns; wider windows also show dates
and destination. Scroll the selected task's detail pane to see its full graph.

Server aliases and a vCenter plus its ESXi host can refer to the same physical resources. The per-address queue cannot identify all such overlaps. Concurrent exports still share your PC's NIC, storage and any common network links.

## Progress and cancellation

Speed is derived from OVA file growth, not total adapter traffic. ETA is approximate and excludes subsequent verification and server cleanup. A verified OVA with a source-state warning is distinguished from a failed transfer.

**Cancelling a remote export can leave some ESXi versions stuck in an exporting state**, blocking power-on or later exports. See [Broadcom KB 334593](https://knowledge.broadcom.com/external/article/334593/unable-to-power-on-vm-with-error-the-att.html). A warning does not prevent that server defect. Letting transfers finish is preferable where possible.

Queued tasks and local verification can be cancelled independently. An active-export cancellation requires confirmation. If OVF Tool stalls, a separate force-stop confirmation ends only the process owned by that task; it cannot guarantee server cleanup. The app never restarts ESXi services or changes VM power state. Incomplete files are not valid completed exports and cannot be resumed.

## Privacy

The compatible data directory remains `%LOCALAPPDATA%\OVA Exporter`:

| File | Contents |
| --- | --- |
| `connections.json` | DPAPI-encrypted address/username hints, only when requested |
| `trusted_servers.json` | DPAPI-encrypted approved certificate fingerprints |
| `appearance.json` | Plain `light`/`dark` preference only |

There is no analytics or telemetry code. Diagnostics and task rows stay in memory by default. **Clear saved data** removes connection hints and certificate approvals. Passwords, cookies and session tickets are not written to these settings files. DPAPI protects stored data from casual file inspection and other Windows users; software running as the same Windows user can still decrypt it.

## Development

Read [CONTRIBUTING.md](CONTRIBUTING.md) and [the architecture notes](docs/ARCHITECTURE.md). The existing offline regression suite uses fake clients; do not point tests at a production server.

Run `py -3 tools/offline_tests.py` for guarded offline regressions. See the
[release review](docs/RELEASE_REVIEW.md) for findings, fixes and unverified lab checks.

An isolated visual preview is available without credentials or VMware binaries:

```powershell
py -3 tools/preview_ui.py
```

It injects in-memory settings, fake VM inventory and progress, and blocks socket connections and subprocess creation. It cannot export a VM or save connection settings.

See [publishing and free discovery](docs/PUBLISHING.md) for repository metadata, release preparation and realistic search expectations.

## License

Application code: [MIT](LICENSE). VMware OVF Tool and Python retain their own licenses; they are not included in this source distribution. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
