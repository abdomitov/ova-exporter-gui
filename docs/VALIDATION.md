# Validation for the 2.0 redesign

This redesign is a presentation refactor, not a new live-server certification.

- Python source was compiled for syntax errors.
- An isolated Tk preview used invented VM names and documentation-only IPs.
- The preview injected an in-memory settings store and disabled appearance persistence.
- Socket connections, OVF Tool subprocess creation and real settings protection
  calls were blocked in the preview.
- Presentation checks covered four fake tasks (queued, exporting and completed), metrics, progress fill, speed
  history, both palettes, the 640x420 main-window layout and 600x420 wizard.
- The fake wizard checked masked-by-default passwords, an Enter-key binding,
  unchecked connection remembering and exclusion of a running VM by the filter.
- The connection wizard and shared theme use the same presentation modules as
  the app; no real login, export, cancellation, power operation or host-service
  restart was performed for this redesign.
- Source comparison confirmed the export, session, encryption and scrolling
  modules were unchanged. Job scheduling/cancellation/cleanup code was unchanged;
  only the missing-OVF-Tool message changed in the job module.

Manual visual inspection completed on 2026-11-05 after Windows was unlocked.
The dashboard was inspected in both themes, the 640x420 layout was checked, and
mouse-wheel scrolling over the compact progress pane revealed its speed graph.
The fake connection form and VM selection screen were inspected, including
shared theme switching. Documentation screenshots contain only invented data.
Selecting a completed fake task displayed its verified completion message,
100% progress and speed history. Completed/verification cards label their
calculated mean transfer rate as average speed rather than current throughput.

Visual review found that a short window could crowd out task rows and the footer.
Version 2.0.1 reserves space for the footer/status line, reapplies the pane split
after ttk resizing settles, and prioritizes core task columns in narrow windows.
The wizard has a little more default height and enough width for its CPU heading.

The existing offline regression tests are retained for maintainers. They are not
a claim of full-suite execution or live VMware compatibility validation during
this UI-only work. Test new export behavior only in an explicitly authorized
disposable lab. Server-side export-state bugs are not fixed by a new theme.
