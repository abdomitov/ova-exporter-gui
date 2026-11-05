"""Windowed launcher with a visible startup error instead of a silent exit."""
try:
    import sys
    if '--self-test-report' in sys.argv:
        import json
        from pathlib import Path
        report=Path(sys.argv[sys.argv.index('--self-test-report')+1])
        sys.argv.append('--check')
        from tools.preview_ui import main
        status=main()
        report.write_text(json.dumps({'fake_ui_check':'passed' if status==0 else 'failed',
                                     'network':'blocked','subprocesses':'blocked','settings':'in-memory'}))
        raise SystemExit(status)
    else:
        from app import main
        main()
except Exception as error:
    import tkinter as tk
    from tkinter import messagebox
    root = tk.Tk()
    root.withdraw()
    help_text=('Reinstall the application or report this startup error to the maintainer.'
               if getattr(sys,'frozen',False) else 'Run Start OVA Exporter.cmd for console diagnostics.')
    messagebox.showerror('OVA Exporter GUI could not start',
                         str(error) + '\n\n'+help_text, parent=root)
    root.destroy()
