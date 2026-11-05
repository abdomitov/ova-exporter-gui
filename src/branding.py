"""Shared application icon for source and frozen builds."""
import tkinter as tk
from project_paths import ROOT


def set_icon(root):
    path=ROOT/'assets'/'logo.png'
    try:
        root._ova_logo=tk.PhotoImage(master=root,file=str(path))
        root.iconphoto(True,root._ova_logo)
    except (OSError,tk.TclError):
        pass  # A missing optional icon must not prevent startup.
