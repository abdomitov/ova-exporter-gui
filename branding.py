"""Shared application icon for source and frozen builds."""
from pathlib import Path
import tkinter as tk


def set_icon(root):
    path=Path(__file__).resolve().parent/'assets'/'logo.png'
    try:
        root._ova_logo=tk.PhotoImage(master=root,file=str(path))
        root.iconphoto(True,root._ova_logo)
    except (OSError,tk.TclError):
        pass  # A missing optional icon must not prevent startup.
