"""Application-wide light/dark tokens and Tk/ttk styling.

Export logic does not depend on this module. Only the appearance preference is
stored here; connection hints and certificate pins use the separate DPAPI store.
"""
import json
import tkinter as tk
import weakref
from tkinter import ttk

from ui_assets import configure_checkboxes

PALETTES = {
    'dark': {
        'bg': '#111820', 'surface': '#19232e', 'field': '#202d3b',
        'text': '#e9f0f7', 'muted': '#9cacc0', 'border': '#344454',
        'accent': '#087f8c', 'accent_hover': '#066b76', 'selection': '#23596b',
        'positive': '#77d9b0', 'negative': '#ff9da5', 'warning': '#efc578',
        'progress': '#1c4944', 'graph': '#359b80', 'graph_line': '#8ee6c7',
        'grid': '#304751', 'error_fill': '#542d38', 'warning_fill': '#51442b',
        'stripe': '#1d2834', 'disabled': '#627386',
    },
    'light': {
        'bg': '#f3f6fa', 'surface': '#ffffff', 'field': '#ffffff',
        'text': '#1c3044', 'muted': '#5e7085', 'border': '#cfdae5',
        'accent': '#087f8c', 'accent_hover': '#066b76', 'selection': '#d4edf0',
        'positive': '#177959', 'negative': '#b43c4d', 'warning': '#885d0e',
        'progress': '#d6f1e5', 'graph': '#63bca0', 'graph_line': '#187c60',
        'grid': '#dae5e9', 'error_fill': '#f8dce1', 'warning_fill': '#fff0cb',
        'stripe': '#f7f9fc', 'disabled': '#94a3b5',
    },
}


class ThemeManager:
    def __init__(self, root, preference_path=None, mode=None):
        self.root = root
        self.path = preference_path
        self.mode = mode or self.read_preference()
        self.widgets = weakref.WeakSet()
        self.style = ttk.Style(root)
        self.style.theme_use('clam')
        root._ova_theme = self
        self.apply()

    def read_preference(self):
        if self.path is not None:
            try:
                value = json.loads(self.path.read_text(encoding='utf-8')).get('theme')
                if value in PALETTES:
                    return value
            except (OSError, ValueError, AttributeError):
                pass
        return 'dark'

    @property
    def colors(self):
        return PALETTES[self.mode]

    def register(self, widget):
        self.widgets.add(widget)
        widget.apply_theme(self.colors)
        self.refresh_windows()

    def toggle(self):
        self.mode = 'light' if self.mode == 'dark' else 'dark'
        self.apply()
        if self.path is not None:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self.path.write_text(json.dumps({'theme': self.mode}) + '\n', encoding='utf-8')
            except OSError:
                pass  # A read-only profile must not prevent changing appearance.

    def apply(self):
        c, s = self.colors, self.style
        s.configure('.', font=('Segoe UI', 10), background=c['bg'], foreground=c['text'],
                    bordercolor=c['border'], lightcolor=c['border'], darkcolor=c['border'],
                    troughcolor=c['bg'], focuscolor=c['accent'])
        s.configure('TFrame', background=c['bg'])
        s.configure('TLabel', background=c['bg'], foreground=c['text'])
        s.configure('Title.TLabel', font=('Segoe UI', 20, 'bold'))
        s.configure('Heading.TLabel', font=('Segoe UI', 13, 'bold'))
        s.configure('Muted.TLabel', foreground=c['muted'])
        s.configure('Footnote.TLabel', foreground=c['muted'], font=('Segoe UI', 9))
        s.configure('Warning.TLabel', foreground=c['warning'])
        s.configure('Error.TLabel', foreground=c['negative'])
        s.configure('Success.TLabel', foreground=c['positive'])
        s.configure('Brand.TLabel', background=c['accent'], foreground='#ffffff', font=('Segoe UI', 11, 'bold'))
        s.configure('Card.TFrame', background=c['surface'])
        s.configure('Card.TLabel', background=c['surface'], foreground=c['muted'], font=('Segoe UI', 9))
        s.configure('Metric.TLabel', background=c['surface'], foreground=c['text'], font=('Segoe UI', 19, 'bold'))
        s.configure('Empty.TLabel', background=c['surface'], foreground=c['muted'], font=('Segoe UI', 11), padding=20)
        s.configure('TButton', padding=(12, 7), background=c['surface'], foreground=c['text'],
                    borderwidth=1, relief='flat')
        s.map('TButton', background=[('disabled', c['bg']), ('pressed', c['selection']), ('active', c['field'])],
              foreground=[('disabled', c['disabled'])], bordercolor=[('focus', c['accent'])])
        s.configure('Accent.TButton', background=c['accent'], foreground='#ffffff', bordercolor=c['accent'])
        s.map('Accent.TButton', background=[('disabled', c['border']), ('active', c['accent_hover'])],
              foreground=[('disabled', c['disabled']), ('!disabled', '#ffffff')])
        s.configure('Quiet.TButton', background=c['bg'])
        s.configure('Section.TButton', anchor='w', font=('Segoe UI', 10, 'bold'), padding=(12, 9))
        for kind in ('TEntry', 'TCombobox'):
            s.configure(kind, fieldbackground=c['field'], foreground=c['text'], padding=(8, 7),
                        selectbackground=c['selection'], selectforeground=c['text'], arrowsize=14,
                        bordercolor='#6c8095' if self.mode=='dark' else '#8092a7')
            s.map(kind, fieldbackground=[('disabled', c['bg']), ('readonly', c['field'])],
                  foreground=[('disabled', c['disabled'])], bordercolor=[('focus', c['accent'])])
        s.configure('PasswordEye.TButton', background=c['field'], borderwidth=0, padding=0)
        s.layout('PasswordEye.TButton', [('Button.padding', {'sticky': 'nswe', 'children': [
            ('Button.focus', {'sticky': 'nswe', 'children': [('Button.label', {'sticky': 'nswe'})]})]})])
        s.map('PasswordEye.TButton', background=[('disabled', c['bg']), ('focus', c['selection']), ('active', c['selection'])])
        s.configure('Treeview', rowheight=34, background=c['surface'], fieldbackground=c['surface'],
                    foreground=c['text'], borderwidth=0)
        s.map('Treeview', background=[('selected', c['selection'])], foreground=[('selected', c['text'])])
        s.configure('Treeview.Heading', background=c['field'], foreground=c['muted'],
                    font=('Segoe UI', 9, 'bold'), padding=(10, 9), relief='flat', borderwidth=0)
        s.map('Treeview.Heading', background=[('active', c['selection'])])
        s.configure('TScrollbar', background=c['border'], arrowcolor=c['muted'], borderwidth=0,
                    gripcount=0, arrowsize=12, troughcolor=c['bg'])
        s.map('TScrollbar', background=[('active', c['muted'])])
        s.configure('TPanedwindow', background=c['bg'], sashwidth=8)
        s.configure('Ova.TCheckbutton', background=c['bg'], foreground=c['text'])
        s.map('Ova.TCheckbutton', background=[('active', c['bg'])], foreground=[('disabled', c['disabled'])])
        configure_checkboxes(self.root, s, c)
        self.root.option_add('*TCombobox*Listbox.background', c['field'])
        self.root.option_add('*TCombobox*Listbox.foreground', c['text'])
        self.root.option_add('*TCombobox*Listbox.selectBackground', c['selection'])
        self.root.option_add('*TCombobox*Listbox.selectForeground', c['text'])
        self.refresh_windows()
        for widget in list(self.widgets):
            try:
                widget.apply_theme(c)
            except tk.TclError:
                self.widgets.discard(widget)

    def refresh_windows(self):
        c = self.colors
        def visit(widget):
            if isinstance(widget, (tk.Tk, tk.Toplevel)):
                widget.configure(background=c['bg'])
            elif isinstance(widget, tk.Canvas):
                widget.configure(background=c['bg'], highlightbackground=c['border'])
            elif isinstance(widget, tk.Text):
                widget.configure(background=c['surface'], foreground=c['text'],
                                 insertbackground=c['text'], selectbackground=c['selection'],
                                 relief='flat', padx=12, pady=12)
            for child in widget.winfo_children():
                visit(child)
        visit(self.root)


def theme_for(widget):
    return getattr(widget._root(), '_ova_theme', None)
