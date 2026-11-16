"""Settings: OVF Tool location, appearance, app updates and saved connection data."""
import tkinter as tk
import webbrowser
from tkinter import ttk

from metadata import APP_NAME, VERSION
from scrolling import ScrollBody
from updates import REPOSITORY

TOOL_DOWNLOAD = 'https://developer.broadcom.com/tools/open-virtualization-format-ovf-tool/latest/'
PROJECT_URL = f'https://github.com/{REPOSITORY}'


class SettingsView(ttk.Frame):
    def __init__(self, parent, owner):
        super().__init__(parent)
        self.owner = owner
        theme = owner.theme
        px = theme.px
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        ttk.Label(self, text='Settings', style='Title.TLabel').grid(row=0, column=0, sticky='w', pady=(0, px(16)))
        body = ScrollBody(self, padding=0)
        body.grid(row=1, column=0, sticky='nsew')
        self.body = body
        inner = body.inner
        inner.columnconfigure(0, weight=1)
        self.wrapping = []

        def section(title):
            card = theme.panel(inner)
            card.grid(column=0, sticky='ew', pady=(0, px(14)), padx=(0, px(4)))
            frame = ttk.Frame(card, style='Surface.TFrame', padding=(px(24), px(18)))
            frame.pack(fill='x')
            ttk.Label(frame, text=title, style='Heading.Surface.TLabel').pack(anchor='w')
            return frame

        def note(frame, style='Muted.Surface.TLabel', **options):
            label = ttk.Label(frame, style=style, wraplength=px(560), **options)
            label.pack(anchor='w', pady=(4, 0))
            self.wrapping.append(label)
            return label

        # VMware OVF Tool
        tool = section('VMware OVF Tool')
        self.tool_label = note(tool, textvariable=owner.tool_status)
        self.tool_location = tk.StringVar()
        note(tool, style='Mono.Surface.TLabel', textvariable=self.tool_location)
        row = ttk.Frame(tool, style='Surface.TFrame')
        row.pack(anchor='w', pady=(px(12), 0))
        self.tool_browse = ttk.Button(row, text='Locate ovftool.exe…', command=owner.choose_tool)
        self.tool_browse.pack(side='left')
        self.tool_auto = ttk.Button(row, text='Auto-detect', command=owner.auto_tool)
        self.tool_auto.pack(side='left', padx=8)
        self.tool_download = ttk.Button(row, text='Download from Broadcom', command=lambda: webbrowser.open(TOOL_DOWNLOAD))
        self.tool_download.pack(side='left')
        self.tool_busy = note(tool, style='Small.Surface.TLabel',
                              text='This app runs your own installed copy; it does not include or update OVF Tool.')

        # Appearance
        look = section('Appearance')
        row = ttk.Frame(look, style='Surface.TFrame')
        row.pack(anchor='w', pady=(px(10), 0))
        self.mode_buttons = {}
        for mode, label in (('light', 'Light'), ('dark', 'Dark')):
            button = ttk.Button(row, text=label, command=lambda mode=mode: theme.set_mode(mode))
            button.pack(side='left', padx=(0, 4))
            self.mode_buttons[mode] = button

        # Updates
        updates = section('App updates')
        self.update_status = tk.StringVar()
        note(updates, textvariable=self.update_status)
        row = ttk.Frame(updates, style='Surface.TFrame')
        row.pack(anchor='w', pady=(px(12), 0))
        updater = owner.updater
        self.check_button = ttk.Button(row, text='Check for updates', command=lambda: updater.check(manual=True))
        self.check_button.pack(side='left')
        self.install_button = ttk.Button(row, text='Install downloaded update…', command=updater.install)
        self.install_button.pack(side='left', padx=8)
        self.automatic_check = ttk.Checkbutton(updates, text='Check automatically at startup', variable=updater.automatic,
                                               command=updater.toggle_automatic, style='Surface.Ova.TCheckbutton')
        self.automatic_check.pack(anchor='w', pady=(px(12), 0))
        updater.on_change = self.refresh_updates

        # Saved data
        saved = section('Saved connection data')
        note(saved, text='Remembered addresses, usernames and approved certificates are encrypted for your Windows '
                         'account on this PC. Passwords and session tickets are never saved.')
        self.clear_button = ttk.Button(saved, text='Clear saved data…', command=owner.flow.clear_saved_data)
        self.clear_button.pack(anchor='w', pady=(px(12), 0))

        about = section('About')
        note(about, text=f'{APP_NAME} {VERSION}. An independent graphical front end for VMware OVF Tool; '
                         'not affiliated with Broadcom or VMware.')
        ttk.Button(about, text='Project page on GitHub', command=lambda: webbrowser.open(PROJECT_URL)
                   ).pack(anchor='w', pady=(px(12), 0))

        body.canvas.bind('<Configure>', self.wrap, add='+')
        theme.register(self)
        self.refresh_updates()

    def wrap(self, event):
        width = max(self.owner.theme.px(240), event.width - self.owner.theme.px(70))
        for label in self.wrapping:
            label.configure(wraplength=width)
        self.body.schedule()

    def apply_theme(self, colors):
        for mode, button in self.mode_buttons.items():
            button.configure(style='TabActive.TButton' if mode == self.owner.theme.mode else 'Tab.TButton')

    def refresh_tool(self, ready, path, busy):
        self.tool_label.configure(style='Success.Surface.TLabel' if ready else 'Error.Surface.TLabel')
        self.tool_location.set(str(path) if ready and path else 'No ovftool.exe found in the usual locations.')
        state = 'disabled' if busy else 'normal'
        for button in (self.tool_browse, self.tool_auto):
            button.configure(state=state)
        self.tool_busy.configure(text='The tool location is locked until every queued and active export has finished.' if busy else
                                 'This app runs your own installed copy; it does not include or update OVF Tool.')
        self.refresh_session()

    def refresh_session(self):
        flow = self.owner.flow
        self.clear_button.configure(state='disabled' if flow.active else 'normal')

    def refresh_updates(self):
        updater = self.owner.updater
        if not updater.enabled:
            text = f'Version {VERSION}. Update checks are turned off in this copy.'
        elif updater.downloading:
            text = f'Version {VERSION}. Downloading the new installer; exports continue normally.'
        elif updater.ready:
            text = f'Version {updater.release.version} is downloaded and verified. Install it when no export is running.'
        elif updater.checking:
            text = f'Version {VERSION}. Checking GitHub for a newer release…'
        else:
            text = f'Version {VERSION} is installed. Updates come from this project\'s GitHub releases.'
        self.update_status.set(text)
        usable = updater.enabled and not updater.checking
        self.check_button.configure(state='normal' if usable else 'disabled')
        self.automatic_check.configure(state='normal' if updater.enabled else 'disabled')
        self.install_button.configure(state='normal' if updater.ready else 'disabled')
