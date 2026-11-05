# Release review plan

Review scope: local source and release artifacts, fake VMware clients, temporary
test files, and isolated UI previews. No production host, credentials, VM power
operation, real export or service restart is authorized by this review.

1. Establish the baseline: read README/architecture/validation, inventory tests,
   run the offline suite behind network/process guards, and record failures.
2. Review independent areas in parallel: design/accessibility, QA, security and
   deployment. The lead owns production edits; QA owns regression tests.
3. Prioritize data loss, false integrity claims, certificate/session weaknesses,
   broken exports and crashes before visual polish or optional product work.
4. Reproduce confirmed issues with fake clients or in-memory/temp fixtures, fix
   the cause, and have reviewers verify the affected behavior.
5. Re-run focused checks, then the complete offline suite. Build a source ZIP,
   inspect its contents/checksum, extract it into a clean temporary folder and
   check imports/tests/preview there.
6. Record remaining live-lab, clean-machine and release-signing limitations.
   Publish nothing and perform no production deployment in this review.

Main user journeys:

| Journey | Key checks |
| --- | --- |
| Start/install | Python/Tk availability, OVF Tool discovery, clear missing-dependency errors |
| Connect | Address validation, Enter/focus, masked password, certificate review/change detection |
| Remember/clear | Opt-in hints only, DPAPI storage, no saved password or plaintext fallback |
| Choose VM/output | Search, power-state filter/recheck, safe filename, disk space, no overwrite |
| Export/dashboard | Per-endpoint queue, independent sessions, progress/rate/ETA, selected details |
| Verify/save | Streamed manifest coverage and hashes, malformed archives, atomic final publication |
| Cancel/exit | Explicit risk confirmation, owned-process scope, honest cleanup uncertainty |
| Release | Public archive allowlist, no vendor/user data, portable instructions and checksum |
