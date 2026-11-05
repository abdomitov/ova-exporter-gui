# Contributing

Start with a small issue or pull request explaining the user-visible behavior.
Keep export/session ownership in `jobs.py` and VMware API work in `vsphere.py`.
Put presentation changes in the UI modules and use the shared palette instead of
adding hardcoded colors. There are no mandatory third-party Python dependencies.

Use documentation addresses such as `192.0.2.10` and invented VM names in examples.
Do not attach credentials, cookies, session tickets, real inventories, private IP
lists, proprietary binaries, or unredacted logs/screenshots to an issue.

The preview can be run with `py -3 tools/preview_ui.py`; its network/subprocess
guards must remain in place. The offline regression suite is run by maintainers
with `py -3 tools/offline_tests.py`. This blocks real network, subprocess and
default-profile access. UI tests require a graphical
desktop. Settings tests inject a test protector and temporary directories.
Do not replace the test protector with a real profile or point tests at servers.

For export-related changes, document what was checked with fake clients and what
still requires an explicitly authorized disposable lab. Cancellation can expose
an ESXi management-state defect; never validate it on a production VM.

Before requesting review, run syntax checks, inspect both themes, and check a
640x420 main window plus a 600x420 setup window. Confirm keyboard navigation and
mouse-wheel scrolling. Changes to certificate pinning, stored settings, process
termination and cancellation need careful review and meaningful offline tests.
