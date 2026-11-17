"""Light/dark tokens, typefaces, drawn surfaces and ttk styling for the workbench UI.

Export logic does not depend on this module. Only the appearance preference is
stored here; connection hints and certificate pins use the separate DPAPI store.

Rounded cards, buttons and fields are ttk image elements built from the RGBA
artwork in `ui_assets`. A style prefix says which surface a widget sits on, so
the pixels behind its rounded corners match: none for the page, `Surface.` for
a card, `Rail.` for the navigation rail (e.g. ``Surface.Accent.TButton``,
``Muted.Surface.TLabel``).
"""
import json
import math
import tkinter as tk
import weakref
from tkinter import font as tkfont
from tkinter import ttk

from platform_support import is_mac
from ui_assets import Assets, check_png, empty_png, icon_png, rounded_png, stage_png

PALETTES = {
    'light': {
        'bg': '#f1f3f8', 'surface': '#ffffff', 'field': '#ffffff', 'sunken': '#f5f7fb',
        'text': '#141b2b', 'muted': '#5d6880', 'border': '#dde2ec',
        'accent': '#3257f5', 'accent_hover': '#2444d6', 'accent_text': '#ffffff',
        'selection': '#e7edff', 'positive': '#12855a', 'negative': '#c22f4b',
        'warning': '#95600a', 'disabled': '#a2abbd',
        'track': '#e6eaf2', 'graph': '#d5dfff', 'graph_line': '#3257f5', 'grid': '#e8ecf4',
        'positive_fill': '#def5ea', 'negative_fill': '#fde4e9', 'warning_fill': '#fdf1d3',
        'rail': '#141b2e', 'rail_text': '#f0f3fa', 'rail_muted': '#97a2ba',
        'rail_active': '#263150', 'rail_border': '#2b3654',
        'rail_positive': '#6fe0b0', 'rail_negative': '#ff9eae',
        'shadow': '#1d2a55', 'shadow_strength': 0.10,
    },
    'dark': {
        'bg': '#0f131c', 'surface': '#181e2a', 'field': '#1f2634', 'sunken': '#141a25',
        'text': '#e9edf6', 'muted': '#97a2b8', 'border': '#2a3345',
        'accent': '#7193ff', 'accent_hover': '#8ea9ff', 'accent_text': '#0b1226',
        'selection': '#24315a', 'positive': '#5fd6a3', 'negative': '#ff8fa3',
        'warning': '#f2bd66', 'disabled': '#586377',
        'track': '#262e3e', 'graph': '#26387a', 'graph_line': '#8ea9ff', 'grid': '#222a39',
        'positive_fill': '#173a30', 'negative_fill': '#46222e', 'warning_fill': '#40361d',
        'rail': '#0a0d14', 'rail_text': '#f0f3fa', 'rail_muted': '#8e99b0',
        'rail_active': '#1b2337', 'rail_border': '#222a3c',
        'rail_positive': '#5fd6a3', 'rail_negative': '#ff8fa3',
        'shadow': '#000000', 'shadow_strength': 0.32,
    },
}

# First installed family wins; later names cover older Windows and other systems.
# Bahnschrift, a DIN face shipped with Windows 10 and later, sets the numerals.
FONT_CHOICES = {
    'display': ('Segoe UI Variable Display', 'Segoe UI', 'SF Pro Display', 'Helvetica Neue', 'Inter Display', 'Inter', 'DejaVu Sans'),
    'numeric': ('Bahnschrift', 'DIN Alternate', 'Segoe UI Variable Display', 'Segoe UI', 'SF Pro Display',
                'Helvetica Neue', 'Inter Display', 'Inter', 'DejaVu Sans'),
    'body': ('Segoe UI Variable Text', 'Segoe UI', 'SF Pro Text', 'Helvetica Neue', 'Inter', 'DejaVu Sans'),
    'mono': ('Cascadia Mono', 'Consolas', 'SF Mono', 'Menlo', 'DejaVu Sans Mono', 'Courier New'),
}


class ThemeManager:
    def __init__(self, root, preference_path=None, mode=None):
        self.root = root
        self.path = preference_path
        self.mode = mode or self.read_preference()
        self.widgets = weakref.WeakSet()
        self.style = ttk.Style(root)
        self.style.theme_use('clam')
        self.assets = Assets(root)
        self.elements = set()
        try:
            installed = {name.casefold(): name for name in tkfont.families(root)}
        except tk.TclError:
            installed = {}
        self.families = {role: next((installed[name.casefold()] for name in names if name.casefold() in installed),
                                    'TkDefaultFont' if role != 'mono' else 'TkFixedFont')
                         for role, names in FONT_CHOICES.items()}
        # Canvas and artwork geometry is in pixels while fonts are in points; scale both alike.
        try:
            self.scale = max(1.0, float(root.tk.call('tk', 'scaling')) * 72 / 96)
        except (tk.TclError, ValueError):
            self.scale = 1.0
        px = self.px
        self.card_margin = (px(8), px(5), px(8), px(13))
        self.card_padding = tuple(value + px(5) for value in self.card_margin)
        root._ova_theme = self
        self.apply()

    def px(self, value):
        return round(value * self.scale)

    def font(self, role='body', size=10, weight='normal'):
        # Tk on macOS treats a point as one screen point (72 per inch), while the layout
        # was drawn for 96 per inch; scale so text keeps its size relative to the artwork.
        return (self.families[role], round(size * 4 / 3) if is_mac() else size, weight)

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

    def panel(self, parent, tone='surface', **options):
        """A rounded, softly shadowed card; its children use the `Surface.` styles."""
        if tone == 'rail':
            return ttk.Frame(parent, style='Rail.TFrame', **options)
        return ttk.Frame(parent, style='Card.TFrame', padding=self.card_padding, **options)

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

    # -- drawn elements ----------------------------------------------------
    def nine(self, name, radius, margin=(0, 0, 0, 0), stretch=24, **options):
        """Create or recolor a stretchable rounded image; return it with its slice border."""
        width = options.get('border_width', 1)
        edge = math.ceil(radius + max(margin) + width + 1)
        # ttk tiles the middle slice when it stretches an element, so a wide
        # middle means a large card is painted in a few copies, not thousands.
        size = 2 * edge + self.px(stretch)
        return self.assets.set(name, rounded_png(size, size, radius, margin=margin, **options)), edge

    def element(self, name, images, **options):
        """Register a ttk image element once; later calls only recolor its images."""
        if name in self.elements:
            return
        self.elements.add(name)
        default, edge = images['normal']
        states = [(state, images[state][0]) for state in ('disabled', 'pressed', 'active', 'focus') if state in images]
        self.style.element_create(name, 'image', default, *states, border=edge, padding=0, sticky='nswe',
                                  width=1, height=1, **options)

    def button_art(self, key, radius, backdrop, normal, hover=None, focus=None, disabled=None):
        def image(suffix, options):
            return self.nine(key + suffix, radius, backdrop=backdrop, **options)
        images = {'normal': image('', normal)}
        if hover:
            images['active'] = images['pressed'] = image('_hover', hover)
        if disabled:
            images['disabled'] = image('_disabled', disabled)
        images['focus'] = image('_focus', focus or normal)
        self.element('Ova.' + key, images)
        return 'Ova.' + key

    def build_art(self):
        """Draw every element for the current palette; returns button kind -> element name."""
        c, px = self.colors, self.px
        r = px(8)
        ring = dict(border=c['accent'], border_width=px(2))
        art = {}
        # Buttons and fields are drawn once per surface they can sit on.
        for prefix, key, behind in (('', 'page', c['bg']), ('Surface.', 'card', c['surface'])):
            def make(kind, name, *states, **more):
                art[prefix + kind] = self.button_art(f'{name}_{key}', r, behind, *states, **more)
            make('Accent.', 'accent', dict(fill=c['accent']), dict(fill=c['accent_hover']),
                 dict(fill=c['accent'], border=c['text'], border_width=px(2)), dict(fill=c['track']))
            make('', 'plain', dict(fill=c['surface'], border=c['border']), dict(fill=c['sunken'], border=c['disabled']),
                 dict(fill=c['surface'], **ring), dict(fill=c['sunken'], border=c['border']))
            make('Danger.', 'danger', dict(fill=c['surface'], border=c['border']),
                 dict(fill=c['negative_fill'], border=c['negative']),
                 dict(fill=c['surface'], border=c['negative'], border_width=px(2)))
            make('Quiet.', 'quiet', dict(), dict(fill=c['track']), dict(**ring))
            make('Step.', 'flat', dict())
            art[prefix + 'Tab.'] = art[prefix + 'Quiet.']
            art[prefix + 'StepDone.'] = art[prefix + 'StepActive.'] = art[prefix + 'Step.']
            make('TabActive.', 'tab_active', dict(fill=c['selection']), None, dict(fill=c['selection'], **ring))
            make('Row.', 'row', dict(), dict(fill=c['selection']), dict(**ring))
            self.element('Ova.field_' + key, {
                'normal': self.nine('field_' + key, r, fill=c['field'], border=c['border'], backdrop=behind),
                'disabled': self.nine('field_disabled_' + key, r, fill=c['sunken'], border=c['border'], backdrop=behind),
                'focus': self.nine('field_focus_' + key, r, fill=c['field'], backdrop=behind, **ring)})
            for name in ('warning', 'negative', 'positive'):
                self.element(f'Ova.banner_{name}_{key}', {'normal': self.nine(
                    f'banner_{name}_{key}', px(10), fill=c[name + '_fill'], backdrop=behind)})
            check = px(18)
            images = [self.assets.set(f'check_{key}_{int(on)}{int(off)}', check_png(check, on, c, behind, off))
                      for on, off in ((False, False), (True, False), (False, True), (True, True))]
            if 'Ova.check_' + key not in self.elements:
                self.elements.add('Ova.check_' + key)
                self.style.element_create('Ova.check_' + key, 'image', images[0], ('disabled', 'selected', images[3]),
                                          ('disabled', images[2]), ('selected', images[1]),
                                          width=check + px(9), sticky='w')
            for state in ('done', 'active', 'todo', 'warning', 'problem'):
                self.assets.set(f'stage_{state}_{key}', stage_png(state, px(16), c, behind))
        rail_ring = dict(border=c['rail_muted'], border_width=px(2))
        art['Nav.'] = self.button_art('nav', r, c['rail'], dict(), dict(fill=c['rail_active']), rail_ring)
        art['NavActive.'] = self.button_art('nav_active', r, c['rail'], dict(fill=c['rail_active']), None,
                                            dict(fill=c['rail_active'], **rail_ring))
        art['Rail.'] = self.button_art('rail_button', r, c['rail'], dict(border=c['rail_border']),
                                       dict(fill=c['rail_active'], border=c['rail_border']), rail_ring)
        self.element('Ova.card', {'normal': self.nine(
            'card', px(14), self.card_margin, stretch=160, fill=c['surface'], border=c['border'], backdrop=c['bg'],
            shadow=(c['shadow'], c['shadow_strength'], px(13), px(4)))})
        self.element('Ova.rail_card', {'normal': self.nine('rail_card', px(10), fill=c['rail_active'], backdrop=c['rail'])})
        # Free-standing artwork used by canvases and labels.
        size = px(20)
        for name in ('exports', 'new', 'settings'):
            self.assets.set('nav_' + name, icon_png(name, size, c['rail_muted'], c['rail']))
            self.assets.set('nav_' + name + '_hover', icon_png(name, size, c['rail_text'], c['rail_active']))
        self.assets.set('empty', empty_png(px(84), c))
        for tone in ('positive', 'negative'):
            self.assets.set('dot_' + tone, rounded_png(px(9), px(9), px(5), fill=c['rail_' + tone], backdrop=c['rail_active']))
        return art

    def apply(self):
        c, s, f, px = self.colors, self.style, self.font, self.px
        art = self.build_art()
        s.configure('.', font=f('body', 10), background=c['bg'], foreground=c['text'],
                    bordercolor=c['border'], lightcolor=c['border'], darkcolor=c['border'],
                    troughcolor=c['bg'], focuscolor=c['accent'])
        tones = {'': c['bg'], 'Surface.': c['surface'], 'Sunken.': c['sunken'], 'Rail.': c['rail'],
                 'RailCard.': c['rail_active']}
        for prefix, background in tones.items():
            rail = prefix.startswith('Rail')
            text, muted = (c['rail_text'], c['rail_muted']) if rail else (c['text'], c['muted'])
            s.configure(prefix + 'TFrame', background=background)
            s.configure(prefix + 'TLabel', background=background, foreground=text)
            s.configure('Muted.' + prefix + 'TLabel', foreground=muted)
            s.configure('Small.' + prefix + 'TLabel', foreground=muted, font=f('body', 9))
            s.configure('Heading.' + prefix + 'TLabel', font=f('display', 12, 'bold'))
            s.configure('Title.' + prefix + 'TLabel', font=f('display', 21, 'bold'))
            s.configure('Mono.' + prefix + 'TLabel', font=f('mono', 9), foreground=muted)
            s.configure('Warning.' + prefix + 'TLabel', foreground=c['warning'])
            s.configure('Error.' + prefix + 'TLabel', foreground=c['rail_negative' if rail else 'negative'])
            s.configure('Success.' + prefix + 'TLabel', foreground=c['rail_positive' if rail else 'positive'])
            if prefix in ('', 'Surface.'):
                s.layout(prefix + 'Ova.TCheckbutton', [('Checkbutton.padding', {'sticky': 'nswe', 'children': [
                    ('Ova.check_' + ('card' if prefix else 'page'), {'side': 'left', 'sticky': ''}),
                    ('Checkbutton.focus', {'side': 'left', 'sticky': 'w', 'children': [
                        ('Checkbutton.label', {'sticky': 'nswe'})]})]})])
            s.configure(prefix + 'Ova.TCheckbutton', background=background, foreground=text)
            s.map(prefix + 'Ova.TCheckbutton', background=[('active', background)],
                  foreground=[('disabled', c['disabled'])])
        s.configure('Ova.TCheckbutton', padding=(0, 3))
        s.configure('Brand.Rail.TLabel', font=f('display', 14, 'bold'))
        s.layout('Card.TFrame', [('Ova.card', {'sticky': 'nswe'})])
        s.configure('Card.TFrame', background=c['bg'])
        s.layout('RailCard.TFrame', [('Ova.rail_card', {'sticky': 'nswe'})])
        s.configure('RailCard.TFrame', background=c['rail'])
        for style, tone in (('Notice', 'warning'), ('Problem', 'negative'), ('Good', 'positive')):
            for prefix, key, behind in (('', 'card', c['surface']), ('Page.', 'page', c['bg'])):
                s.layout(prefix + style + '.TLabel', [(f'Ova.banner_{tone}_{key}', {'sticky': 'nswe', 'children': [
                    ('Label.padding', {'sticky': 'nswe', 'children': [('Label.label', {'sticky': 'nswe'})]})]})])
                s.configure(prefix + style + '.TLabel', background=behind, foreground=c[tone], padding=(px(14), px(10)))

        def button(kind, foreground, *, padding=(15, 8), font=None, anchor='center', background=None, disabled=None):
            for prefix, behind in (('', background or c['bg']), ('Surface.', c['surface'])):
                if prefix + kind not in art:
                    continue
                name = prefix + kind + 'TButton'
                s.layout(name, [(art[prefix + kind], {'sticky': 'nswe', 'children': [
                    ('Button.padding', {'sticky': 'nswe', 'children': [('Button.label', {'sticky': 'nswe'})]})]})])
                s.configure(name, padding=padding, background=behind, foreground=foreground,
                            anchor=anchor, font=font or f('body', 10), width=0, borderwidth=0, relief='flat')
                s.map(name, foreground=[('disabled', disabled or c['disabled'])], background=[])

        bold = f('body', 10, 'bold')
        button('', c['text'])
        button('Accent.', c['accent_text'], font=bold)
        button('Danger.', c['negative'])
        button('Quiet.', c['text'])
        button('Tab.', c['muted'], padding=(14, 7))
        button('TabActive.', c['accent'], padding=(14, 7), font=bold)
        button('Row.', c['text'], padding=(12, 9), anchor='w')
        button('Step.', c['muted'], padding=(8, 7), anchor='w')
        button('StepDone.', c['text'], padding=(8, 7), anchor='w')
        button('StepActive.', c['accent'], padding=(8, 7), anchor='w', font=bold, disabled=c['accent'])
        button('Nav.', c['rail_muted'], padding=(12, 9), anchor='w', background=c['rail'])
        s.map('Nav.TButton', foreground=[('active', c['rail_text'])])
        button('NavActive.', c['rail_text'], padding=(12, 9), anchor='w', font=bold, background=c['rail'])
        button('Rail.', c['rail_muted'], padding=(12, 6), font=f('body', 9), background=c['rail'])
        s.map('Rail.TButton', foreground=[('active', c['rail_text'])])

        s.configure('TSeparator', background=c['border'])
        for name, key in (('TEntry', 'card'), ('Page.TEntry', 'page')):
            s.layout(name, [('Ova.field_' + key, {'sticky': 'nswe', 'children': [
                ('Entry.padding', {'sticky': 'nswe', 'children': [('Entry.textarea', {'sticky': 'nswe'})]})]})])
        s.configure('TEntry', background=c['surface'], fieldbackground=c['field'], foreground=c['text'],
                    padding=(px(11), px(8)), selectbackground=c['selection'], selectforeground=c['text'],
                    insertcolor=c['text'], borderwidth=0)
        s.map('TEntry', foreground=[('disabled', c['disabled'])], fieldbackground=[('disabled', c['sunken'])])
        s.configure('Page.TEntry', background=c['bg'])
        s.configure('Treeview', rowheight=px(36), background=c['surface'], fieldbackground=c['surface'],
                    foreground=c['text'], borderwidth=0, font=f('body', 10))
        s.map('Treeview', background=[('selected', c['selection'])], foreground=[('selected', c['text'])])
        s.configure('Treeview.Heading', background=c['surface'], foreground=c['muted'],
                    font=f('body', 9), padding=(10, 8), relief='flat', borderwidth=0)
        s.map('Treeview.Heading', background=[('active', c['sunken'])], foreground=[('active', c['text'])])
        s.layout('Treeview', [('Treeview.treearea', {'sticky': 'nswe'})])
        for prefix, trough in (('', c['bg']), ('Surface.', c['surface'])):
            s.configure(prefix + 'Vertical.TScrollbar', background=c['track'], arrowcolor=c['muted'], borderwidth=0,
                        gripcount=0, arrowsize=px(11), troughcolor=trough, width=px(11),
                        bordercolor=trough, lightcolor=c['track'], darkcolor=c['track'])
            s.map(prefix + 'Vertical.TScrollbar', background=[('active', c['disabled'])])
            s.layout(prefix + 'Vertical.TScrollbar', [('Vertical.Scrollbar.trough', {'sticky': 'ns', 'children': [
                ('Vertical.Scrollbar.thumb', {'expand': '1', 'sticky': 'nswe'})]})])
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
            elif isinstance(widget, tk.Text):
                widget.configure(background=c['sunken'], foreground=c['text'],
                                 insertbackground=c['text'], selectbackground=c['selection'],
                                 selectforeground=c['text'], relief='flat', borderwidth=0,
                                 highlightthickness=0, padx=self.px(14), pady=self.px(12))
            for child in widget.winfo_children():
                visit(child)
        visit(self.root)


def theme_for(widget):
    return getattr(widget._root(), '_ova_theme', None)
