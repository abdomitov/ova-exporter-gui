# UI and responsiveness review — 2.3.3 candidate

## Direction

Refine the existing native Tk interface and teal identity. The app should feel
like a calm infrastructure utility: a compact task list first, with readable
transfer details when requested. This follows the user's request to improve the
existing app; it is not a new product or a web-based redesign.

Two layouts were considered. A permanently expanded transfer card for every task
was rejected because it consumes space and redraws offscreen charts. The selected
layout retains the table and one selected task. At short window heights, the list
and details share the same space, with Show details / Hide details switching
between them. Larger windows retain an adjustable split view.

The visual refinement replaces the three separate metric cards with one compact
summary strip, gives the header coherent Updates/theme menus, and removes the
permanent native white menu strip from dark mode. OVF Tool setup actions collapse
into a settings menu when ready; missing-tool actions stay explicit. The transfer
card has one clear progress rail, a prominent percentage, aligned statistics and
an unobstructed speed history. Cancel remains next to the selected task, above
the card. Denser 32 px task rows preserve room for the work itself.

The second design pass covers setup and first launch. The chosen full-height
connection layout uses labels above full-width inputs in a single surface with
24 px inset and 16 px field spacing. The old label/input matrix was retained
only as a deliberate compact arrangement below 600 px window height. This keeps
all three credential fields visible at 600 × 420 without changing their values
or keyboard order. Segoe UI remains the only family: 13 pt section headings,
10 pt form text and 9 pt privacy notes. Active sections, grouped output controls,
explicit busy/error feedback, a first-export action and an inventory empty state
make the setup flow consistent with the dashboard. Ctrl+F focuses VM search.
Routine repeated status text is hidden; failures and work in progress remain
visible. Dialogs and the folder picker belong to the setup window.

Keep Segoe UI, the existing type hierarchy, light/dark tokens and simple controls.
Motion is limited to data-driven progress and speed-chart updates. No animation
loop, web renderer, new runtime dependency or decorative effect was added to the
production app. The animated preview is an explicitly isolated developer tool.

## Confirmed issues and fixes

| Severity | Problem | Fix |
| --- | --- | --- |
| Medium | Unbounded event draining can block input during a worker burst. | Process at most 128 events or about 8 ms per poll, then yield; keep all state transitions in order. |
| Medium | Every sample redraws the selected chart, scans task summaries and refreshes OVF Tool status. | Batch row/chart/summary updates; refresh the tool on task transitions and explicit actions. |
| Medium | Hidden task details keep redrawing. | Update presentation state while skipping hidden chart draws; reopening shows the latest values. |
| Medium | The automatic divider position overrides the user's split. | Remember the chosen ratio and apply it when resizing. |
| Medium | The minimum-height window reduces list and details to unusable slivers. | Show one at a time below 600 px height; restore both on larger windows. |
| Medium | A long error can grow past a stale scroll region and remain unreachable until resizing. | Explicitly recalculate the scroll area when error text, titles, wrapping, VM details or status text changes; verify wheel scrolling after dynamic content changes. |
| Low | Details are awkward to reopen for an already selected task. | Add one persistent Show details / Hide details action and Enter/Escape handling in the table. |
| Low | Duplicate actions take room below the chart; long errors can cover it. | Keep actions in the toolbar; show concise chart hints and full wrapping diagnostics below. |
| Low | Filtering rebuilds inventory on every keystroke. | Debounce typing by 120 ms and disable export while the old selection is being filtered. |
| Low | Idle wizard polling repeatedly traverses every widget to bind the wheel. | Bind once; poll idle windows less often. |
| Low | Fractional progress can retain arbitrarily many chart points. | Retain one sample per integer percentage bucket, at most 101 points; preserve peak separately. |
| Low | Initial windows may exceed a smaller screen and VM selection is cramped. | Clamp initial sizes to the screen; give the VM chooser a taller default where space permits. |

The compact-layout regression caught an empty-pane insertion error during
development. It was corrected and the list/detail/resize regression now covers
that path, including failing on unexpected Tk callback exceptions.

## Verification

- 133 guarded offline tests passed on local Python 3.14.5. Tests deny network,
  real subprocess execution and access to actual saved connection settings.
- The source fake-UI self-check passed for both themes, compact layouts,
  connection/selection transitions, graph rendering and keyboard bindings.
- The frozen Windows application passed its fake-data self-test, reporting
  network and subprocesses blocked and settings in memory.
- The Windows x64 app and Inno installer compiled successfully. This review
  did not install or upgrade the user's working copy.
- Visually inspected the 1120 × 780 dashboard in both themes, animated fake
  transfer updates, the divider drag and hide-details behavior, the 640 × 420
  list/detail switch and mouse-wheel graph scrolling, and the 740 × 700 dark
  connection/VM chooser. Also inspected the earlier 740 × 620 light chooser.
- The powered-off filter exposes four of five fake VMs; disabling it exposes the
  running VM, whose selection leaves export disabled and explains why.
- Manually confirmed mouse-wheel access to the full dynamically inserted error
  after fixing its scroll region, without resizing the window first.
- The second pass visually checks the 740 × 700 connection and chooser in both
  themes, the no-results state, the first-export action, and the adaptive
  600 × 420 connection form. Screenshots are under `artifacts/ui-review/pass2/`.
  Regression checks cover compact-to-full reflow, error feedback, Ctrl+F,
  empty-inventory safety, dialog ownership and first-task transitions.

Saved local visual evidence is in `artifacts/ui-review/`: dashboard-dark.png,
dashboard-light.png, task-list.png, dashboard-compact.png,
dashboard-compact-graph.png, task-list-compact.png, wizard-dark.png,
wizard-light.png, vm-selection-dark.png, error-scroll-light.png, redesign-dark.png,
redesign-light.png and redesign-compact.png. These are invented data; they are
not evidence of a live VMware export. Earlier comparison captures are labeled
`initial`. Artifacts are deliberately excluded from source releases.

## Performance evidence

Reproduce with `python tools/benchmark_ui.py --output artifacts/ui-benchmark.json`.
The benchmark uses 32 fake tasks and 4,000 queued presentation events with the
Tk root withdrawn. It measures event-handling work, not rendered frame rate,
network speed or VMware performance. Times vary with system load.

| Measurement | Before | After |
| --- | ---: | ---: |
| Visible-detail CPU time | 0.8906 s | 0.3438 s |
| Scheduled 10 ms callback observed after | 820.60 ms | 10.08 ms |
| Chart draws for that burst | 127 | 33 |
| OVF Tool status refreshes for that burst | 4,000 | 0 |
| Hidden-detail chart draws | 126 | 0 |
| Polls during two idle seconds | 17 | 4 |

Baseline and final measurements are saved locally as `artifacts/ui-before.json`
and `artifacts/ui-after.json`. CPU work fell about 61% in this particular visible
workload. This is not a promise of zero lag or a claim about total process RAM.
The bounded-history regression checks 10,001 fractional progress samples.

## Limits and release checks

No live credentials, VMware endpoint, export, cancellation, power operation or
host service restart was tested. Existing cancellation/cleanup safeguards were
preserved; the known ESXi export-state issue remains a server-side limitation.

The interface was visually checked at the listed sizes, not on every display,
scaling setting or operating system. A full screen-reader audit is outstanding:
Tk widgets expose limited information through the available Windows automation
tree, so keyboard checks are not proof of complete screen-reader accessibility.
Windows 10, high-DPI configurations, large real inventories and macOS/Linux
remain separate validation or implementation work. No new runtime dependencies
were introduced. The installer remains unsigned; this work does not change
SmartScreen behavior. No public release is implied by a local candidate build.

## Run the reviewed source

On Windows with Python 3.10+ and Tk, run `Start OVA Exporter.vbs` or
`python launch.pyw` from the project folder. For a safe demonstration, run
`python tools/preview_ui.py --animate`; use `--compact`, `--light`,
`--wizard-selection`, `--wizard-compact`, `--wizard-no-results`, `--empty`,
`--error-state` or `--missing-tool` for specific views.
The normal app still requires a separately licensed VMware OVF Tool installation.
