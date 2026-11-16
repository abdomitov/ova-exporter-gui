# Architecture

Application modules below live in `src/`; regression tests live in `tests/`.
Run the app from the repository root with `py -3 launch.pyw`.
`src/project_paths.py` locates icons and resources in source/frozen builds.

| Module | Responsibility |
| --- | --- |
| `app.py` | Window shell: navigation rail, view switching, task actions, exit confirmation, event polling |
| `queue_view.py` | Exports view: canvas task list, selected task header, transfer/log tabs |
| `transfer_panel.py` | Stage track, statistics, speed history and time formatting on one canvas |
| `export_flow.py` | New export view: connection, certificate review, inventory and destination steps |
| `settings_view.py` | OVF Tool location, appearance, update controls and saved-data clearing |
| `task_view.py` | Presentation state and task status labels |
| `theme.py` | Light/dark tokens, typefaces, DPI scaling, ttk styles and appearance preference |
| `ui_assets.py` | Code-drawn checkbox asset |
| `scrolling.py` | Scrollable bodies and wheel routing |
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

The three views share one window; only the visible one draws. The Exports view
redraws a task row and the transfer canvas at most once per poll, however many
worker events arrived. The New export view owns only the browsing session and
keeps it until Disconnect or exit; each queued task gets its own forked session.

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

Cancellation behavior was deliberately preserved during the 2.0 UI refactor
and again in the workbench UI rewrite; `jobs.py`, `exporter.py` and `vsphere.py`
were not changed by it.
An abort acknowledgment does not prove server lease release. Cleanup checks are
read-only; no service restart, VM power operation or automatic timed process kill
is performed. The complete existing regression suite is retained for reviewers.
