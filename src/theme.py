"""Light/dark tokens, typefaces and ttk styling for the workbench UI.

Export logic does not depend on this module. Only the appearance preference is
stored here; connection hints and certificate pins use the separate DPAPI store.

Surfaces are named by where a widget sits: the page (`bg`), a bordered panel
(`surface`) or the navigation rail (`rail`). A ttk style prefix selects the
matching background, e.g. ``Muted.Surface.TLabel``.
"""
import json
import tkinter as tk
import weakref
from tkinter import font as tkfont
from tkinter import ttk

from ui_assets import configure_checkboxes

PALETTES = {
    'light': {
        'bg': '#eceff3', 'surface': '#ffffff', 'field': '#ffffff', 'sunken': '#f4f6f9',
        'text': '#17202b', 'muted': '#5b6878', 'border': '#d3dae2',
        'accent': '#2456e6', 'accent_hover': '#1c46c2', 'accent_text': '#ffffff',
        'selection': '#dfe8ff', 'positive': '#197a50', 'negative': '#b92d47',
        'warning': '#8f5a00', 'disabled': '#9aa5b3',
        'track': '#e2e7ee', 'graph': '#c9d8ff', 'graph_line': '#2456e6', 'grid': '#e6eaf0',
        'positive_fill': '#dcf3e7', 'negative_fill': '#fbe1e6', 'warning_fill': '#fdf0cf',
        'rail': '#1c2633', 'rail_text': '#e7ecf2', 'rail_muted': '#93a1b3',
        'rail_active': '#2d3b4e', 'rail_border': '#2d3b4e',
        'rail_positive': '#74d8ab', 'rail_negative': '#ff9aa9',
    },
    'dark': {
        'bg': '#141a21', 'surface': '#1c242e', 'field': '#232d39', 'sunken': '#18202a',
        'text': '#e8edf3', 'muted': '#98a5b5', 'border': '#313c4a',
        'accent': '#6f95ff', 'accent_hover': '#8aa9ff', 'accent_text': '#0d1524',
        'selection': '#273a66', 'positive': '#62d3a0', 'negative': '#ff8fa0',
        'warning': '#f0bb62', 'disabled': '#5f6d7e',
        'track': '#2a3441', 'graph': '#2b417a', 'graph_line': '#8aa9ff', 'grid': '#27313d',
        'positive_fill': '#1d3d33', 'negative_fill': '#4a2530', 'warning_fill': '#463a20',
        'rail': '#0e1319', 'rail_text': '#e7ecf2', 'rail_muted': '#8c9aac',
        'rail_active': '#1f2a37', 'rail_border': '#222c38',
        'rail_positive': '#62d3a0', 'rail_negative': '#ff8fa0',
    },
}

# First installed family wins. Bahnschrift (a DIN face shipped with Windows 10+)
# gives headings and numerals an engineering-signage character; the rest are
# fallbacks for older Windows and for running the preview on other systems.
FONT_CHOICES = {
    'display': ('Bahnschrift', 'Segoe UI Variable Display', 'Segoe UI', 'Inter Display', 'Inter', 'DejaVu Sans'),
    'body': ('Segoe UI', 'Inter', 'DejaVu Sans'),
    'mono': ('Cascadia Mono', 'Consolas', 'DejaVu Sans Mono', 'Courier New'),
}


class ThemeManager:
    def __init__(self, root, preference_path=None, mode=None):
        self.root = root
        self.path = preference_path
        self.mode = mode or self.read_preference()
        self.widgets = weakref.WeakSet()
        self.panels = weakref.WeakKeyDictionary()
        self.style = ttk.Style(root)
        self.style.theme_use('clam')
        try:
            installed = {name.casefold(): name for name in tkfont.families(root)}
        except tk.TclError:
            installed = {}
        self.families = {role: next((installed[name.casefold()] for name in names if name.casefold() in installed),
                                    'TkDefaultFont' if role != 'mono' else 'TkFixedFont')
                         for role, names in FONT_CHOICES.items()}
        # Canvas geometry is in pixels while fonts are in points; scale both alike.
        try:
            self.scale = max(1.0, float(root.tk.call('tk', 'scaling')) * 72 / 96)
        except (tk.TclError, ValueError):
            self.scale = 1.0
        root._ova_theme = self
        self.apply()

    def px(self, value):
        return round(value * self.scale)

    def font(self, role='body', size=10, weight='normal'):
        return (self.families[role], size, weight)

    def read_preference(self):
        if self.path is not None:
            try:
                value = json.loads(self.path.read_text(encoding='utf-8')).get('theme')
                if value in PALETTES:
                    return value
            except (OSError, ValueError, AttributeError):
                pass
        return 'light'

    @property
    def colors(self):
        return PALETTES[self.mode]

    def register(self, widget):
        self.widgets.add(widget)
        widget.apply_theme(self.colors)
        self.refresh_windows()

    def panel(self, parent, tone='surface', border=True, **options):
        """A flat tk.Frame whose colors follow the theme; ttk cannot draw a hairline frame."""
        frame = tk.Frame(parent, highlightthickness=1 if border else 0, borderwidth=0, **options)
        self.panels[frame] = tone
        self.paint_panel(frame, tone)
        return frame

    def paint_panel(self, frame, tone):
        c = self.colors
        line = c['rail_border'] if tone == 'rail' else c['border']
        frame.configure(background=c[tone], highlightbackground=line, highlightcolor=line)

    def toggle(self):
        self.set_mode('light' if self.mode == 'dark' else 'dark')

    def set_mode(self, mode):
        if mode not in PALETTES or mode == self.mode:
            return
        self.mode = mode
        self.apply()
        if self.path is not None:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self.path.write_text(json.dumps({'theme': self.mode}) + '\n', encoding='utf-8')
            except OSError:
                pass  # A read-only profile must not prevent changing appearance.

    def apply(self):
        c, s, f = self.colors, self.style, self.font
        s.configure('.', font=f('body', 10), background=c['bg'], foreground=c['text'],
                    bordercolor=c['border'], lightcolor=c['border'], darkcolor=c['border'],
                    troughcolor=c['bg'], focuscolor=c['accent'])
        tones = {'': c['bg'], 'Surface.': c['surface'], 'Sunken.': c['sunken'], 'Rail.': c['rail']}
        for prefix, background in tones.items():
            rail = prefix == 'Rail.'
            text, muted = (c['rail_text'], c['rail_muted']) if rail else (c['text'], c['muted'])
            s.configure(prefix + 'TFrame', background=background)
            s.configure(prefix + 'TLabel', background=background, foreground=text)
            s.configure('Muted.' + prefix + 'TLabel', foreground=muted)
            s.configure('Small.' + prefix + 'TLabel', foreground=muted, font=f('body', 9))
            s.configure('Heading.' + prefix + 'TLabel', font=f('body', 11, 'bold'))
            s.configure('Title.' + prefix + 'TLabel', font=f('display', 20, 'bold'))
            s.configure('Number.' + prefix + 'TLabel', font=f('display', 15, 'bold'))
            s.configure('Mono.' + prefix + 'TLabel', font=f('mono', 9))
            s.configure('Warning.' + prefix + 'TLabel', foreground=c['warning'])
            s.configure('Error.' + prefix + 'TLabel', foreground=c['rail_negative' if rail else 'negative'])
            s.configure('Success.' + prefix + 'TLabel', foreground=c['rail_positive' if rail else 'positive'])
            s.configure(prefix + 'Ova.TCheckbutton', background=background, foreground=text)
            s.map(prefix + 'Ova.TCheckbutton', background=[('active', background)],
                  foreground=[('disabled', c['disabled'])])
        s.configure('Brand.Rail.TLabel', font=f('display', 15, 'bold'))
        s.configure('Notice.TLabel', background=c['warning_fill'], foreground=c['warning'], padding=(12, 8))
        s.configure('Problem.TLabel', background=c['negative_fill'], foreground=c['negative'], padding=(12, 8))
        s.configure('Good.TLabel', background=c['positive_fill'], foreground=c['positive'], padding=(12, 8))

        def button(name, background, foreground, border, hover, *, padding=(14, 7), font=None, anchor='center'):
            # clam only paints its outline for a non-flat relief; matching the
            # bevel colors to the fill leaves a single hairline.
            s.configure(name, padding=padding, background=background, foreground=foreground,
                        bordercolor=border, lightcolor=background, darkcolor=background,
                        borderwidth=1, relief='flat' if border == background else 'raised',
                        anchor=anchor, font=font or f('body', 10), width=0)
            s.map(name, relief=[('pressed', 'flat' if border == background else 'raised')],
                  background=[('disabled', background), ('pressed', hover), ('active', hover)],
                  lightcolor=[('pressed', hover), ('active', hover)],
                  darkcolor=[('pressed', hover), ('active', hover)],
                  foreground=[('disabled', c['disabled'])],
                  bordercolor=[('focus', c['accent'])])

        button('TButton', c['surface'], c['text'], c['border'], c['sunken'])
        button('Accent.TButton', c['accent'], c['accent_text'], c['accent'], c['accent_hover'],
               font=f('body', 10, 'bold'))
        s.map('Accent.TButton', background=[('disabled', c['track']), ('pressed', c['accent_hover']),
                                            ('active', c['accent_hover'])],
              lightcolor=[('disabled', c['track'])], darkcolor=[('disabled', c['track'])],
              bordercolor=[('disabled', c['track']), ('focus', c['text'])],
              foreground=[('disabled', c['disabled'])])
        button('Quiet.TButton', c['bg'], c['text'], c['bg'], c['track'])
        button('Quiet.Surface.TButton', c['surface'], c['text'], c['surface'], c['sunken'])
        button('Danger.TButton', c['surface'], c['negative'], c['border'], c['negative_fill'])
        button('Tab.TButton', c['surface'], c['muted'], c['surface'], c['sunken'], padding=(12, 6))
        button('TabActive.TButton', c['selection'], c['text'], c['selection'], c['selection'],
               padding=(12, 6), font=f('body', 10, 'bold'))
        button('Step.TButton', c['bg'], c['muted'], c['bg'], c['bg'], padding=(0, 6), anchor='w')
        s.map('Step.TButton', foreground=[('disabled', c['disabled'])])
        button('StepDone.TButton', c['bg'], c['text'], c['bg'], c['track'], padding=(0, 6), anchor='w')
        button('StepActive.TButton', c['bg'], c['accent'], c['bg'], c['bg'], padding=(0, 6),
               font=f('body', 10, 'bold'), anchor='w')
        button('Row.TButton', c['surface'], c['text'], c['surface'], c['selection'],
               padding=(12, 8), anchor='w')
        button('Nav.TButton', c['rail'], c['rail_muted'], c['rail'], c['rail_active'],
               padding=(18, 10), anchor='w', font=f('body', 10))
        s.map('Nav.TButton', foreground=[('active', c['rail_text'])], bordercolor=[('focus', c['rail_muted'])])
        button('NavActive.TButton', c['rail_active'], c['rail_text'], c['rail_active'], c['rail_active'],
               padding=(18, 10), anchor='w', font=f('body', 10, 'bold'))
        s.map('NavActive.TButton', bordercolor=[('focus', c['rail_muted'])])
        button('Rail.TButton', c['rail'], c['rail_muted'], c['rail_border'], c['rail_active'], padding=(10, 5),
               font=f('body', 9))
        s.map('Rail.TButton', foreground=[('active', c['rail_text'])], bordercolor=[('focus', c['rail_muted'])])

        s.configure('TSeparator', background=c['border'])
        s.configure('TEntry', fieldbackground=c['field'], foreground=c['text'], padding=(9, 7),
                    selectbackground=c['selection'], selectforeground=c['text'], insertcolor=c['text'],
                    bordercolor=c['border'], lightcolor=c['field'], darkcolor=c['field'])
        s.map('TEntry', fieldbackground=[('disabled', c['sunken']), ('readonly', c['sunken'])],
              foreground=[('disabled', c['disabled'])],
              bordercolor=[('focus', c['accent'])],
              lightcolor=[('focus', c['accent']), ('disabled', c['sunken'])],
              darkcolor=[('focus', c['accent']), ('disabled', c['sunken'])])
        s.configure('Treeview', rowheight=self.px(34), background=c['surface'], fieldbackground=c['surface'],
                    foreground=c['text'], borderwidth=0, font=f('body', 10))
        s.map('Treeview', background=[('selected', c['selection'])], foreground=[('selected', c['text'])])
        s.configure('Treeview.Heading', background=c['surface'], foreground=c['muted'],
                    font=f('body', 9), padding=(10, 8), relief='flat', borderwidth=0)
        s.map('Treeview.Heading', background=[('active', c['sunken'])], foreground=[('active', c['text'])])
        s.layout('Treeview', [('Treeview.treearea', {'sticky': 'nswe'})])
        s.configure('TScrollbar', background=c['border'], arrowcolor=c['muted'], borderwidth=0,
                    gripcount=0, arrowsize=self.px(12), troughcolor=c['bg'],
                    bordercolor=c['bg'], lightcolor=c['border'], darkcolor=c['border'])
        s.map('TScrollbar', background=[('active', c['muted'])])
        configure_checkboxes(self.root, s, c)
        self.refresh_windows()
        for frame, tone in list(self.panels.items()):
            try:
                self.paint_panel(frame, tone)
            except tk.TclError:
                pass
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
            elif isinstance(widget, tk.Text):
                widget.configure(background=c['sunken'], foreground=c['text'],
                                 insertbackground=c['text'], selectbackground=c['selection'],
                                 selectforeground=c['text'], relief='flat', borderwidth=0,
                                 highlightthickness=0, padx=self.px(12), pady=self.px(10))
            for child in widget.winfo_children():
                visit(child)
        visit(self.root)


def theme_for(widget):
    return getattr(widget._root(), '_ova_theme', None)
