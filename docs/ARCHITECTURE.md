# Architecture

Application modules below live in `src/`; regression tests live in `tests/`.
Run the app from the repository root with `py -3 launch.pyw`.
`src/project_paths.py` locates icons and resources in source/frozen builds.

| Module | Responsibility |
| --- | --- |
| `app.py` | Application lifecycle, task actions, exit confirmation, event polling |
| `wizard.py` | Connection, certificate review, inventory and destination UI |
| `dashboard.py` | Compact task table and selected task details |
| `task_view.py` | Presentation state and task status labels |
| `transfer_ui.py` | Progress, speed history and time formatting |
| `theme.py` | Shared light/dark tokens, ttk styles and appearance preference |
| `ui_assets.py` | Code-drawn checkbox and password eye assets |
| `accordion.py` | Collapsible sections and wheel routing |
| `jobs.py` | Bounded scheduler, process ownership, cancellation and cleanup checks |
| `exporter.py` | OVF Tool arguments, progress parsing, throughput and OVA checksums |
| `vsphere.py` | Pinned HTTPS SOAP sessions and read-only inventory/readiness queries |
| `connection_settings.py` | Allowlisted saved hints, certificate pins and migration |
| `secure_storage.py` | Windows current-user DPAPI boundary |
| `tool_paths.py` | Installed OVF Tool discovery |
| `output_paths.py` | Shared Windows filename validation for UI and export worker |
| `metadata.py` | Public name and version |
| `updates.py` | Public GitHub metadata, release validation, bounded HTTPS downloads and checksums |
| `update_ui.py` | Update preferences, prompts and task-aware installer handoff |

Tk widgets are updated on the main thread. Worker results cross a queue. Each
export owns its API session, output path and original subprocess handle. The
scheduler allows three jobs across distinct address strings, one per address;
different aliases can still resolve to the same physical host.

`TaskView` presents progress without controlling jobs. `ThemeManager` updates
shared ttk styles and registered canvas-based widgets. A theme change never
connects to a server or restarts a task. The app can accept injected settings
and disable appearance persistence for the isolated fake-data preview.

Existing settings keep the `OVA Exporter` directory and DPAPI purpose strings
for backward compatibility. Application branding must not silently change those
encryption inputs. The theme preference contains only an appearance mode.

Update workers use the same event queue, with no access to VMware sessions. Update
choices (`automatic`, `skipped`, `remind_after`) are ordinary non-secret JSON;
they contain no connection data. A manual check overrides skipped/reminder choices.
Preview releases are included because this project currently publishes previews.
Both the source fixture and frozen self-test disable update networking explicitly.
Downloading never executes an installer. The UI rechecks unfinished tasks after
the confirmation dialog, rehashes the file, launches setup without a shell, and
closes the idle app. No VMware task is cancelled as part of an update.

Cancellation behavior was deliberately preserved during the 2.0 UI refactor.
An abort acknowledgment does not prove server lease release. Cleanup checks are
read-only; no service restart, VM power operation or automatic timed process kill
is performed. The complete existing regression suite is retained for reviewers.
