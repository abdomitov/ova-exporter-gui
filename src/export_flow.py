"""New export, inline in the main window: connect, choose a VM, choose where to save.

This view owns the browsing session only. Each queued export receives its own
forked session, and the job manager owns every OVF Tool process.
"""
import queue
import re
import shutil
import threading
import tkinter as tk
from collections import deque
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from output_paths import validate_output_name
from platform_support import shortcut_modifiers
from vsphere import VSphere, endpoint, fingerprint, probe

ROUTINE_STATUS = ('Ready', 'Connected. Select a powered-off VM.', 'Virtual machine list updated', 'Disconnected')
STEP_TITLES = {1: 'Connect', 2: 'Choose a VM', 3: 'Save as'}
POWER_TEXT = {'poweredOff': 'Powered off', 'poweredOn': 'Running', 'suspended': 'Suspended'}
SAVED_ROWS = 8


def gigabytes(value):
    return f'{value / 1024**3:.1f} GB'


class ExportFlow(ttk.Frame):
    def __init__(self, parent, owner):
        super().__init__(parent)
        self.owner = owner
        self.manager = owner.manager
        self.root = owner.root
        self.theme = owner.theme
        px = self.theme.px
        self.events = queue.Queue()
        self.client = None
        self.machines = []
        self.busy = False
        self.filter_timer = None
        self.secret = ''
        self.login_identity = None
        self.selected_vm_id = None
        self.sort_key, self.sort_reverse = 'name', False
        self.activity = deque(maxlen=200)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        gutter = self.theme.card_margin[0]
        ttk.Label(self, text='New export', style='Title.TLabel').grid(row=0, column=0, sticky='w', padx=gutter)
        stepper = ttk.Frame(self)
        stepper.grid(row=1, column=0, sticky='ew', pady=(px(8), px(10)), padx=0)
        self.step_buttons = {}
        for number in (1, 2, 3):
            if number > 1:
                ttk.Label(stepper, text='›', style='Muted.TLabel').pack(side='left', padx=px(2))
            button = ttk.Button(stepper, command=lambda n=number: self.show_step(n), style='Step.TButton',
                                takefocus=0, compound='left')
            button.pack(side='left')
            self.step_buttons[number] = button

        pages = ttk.Frame(self)
        pages.grid(row=2, column=0, sticky='nsew')
        pages.columnconfigure(0, weight=1)
        pages.rowconfigure(0, weight=1)
        self.pages = {number: ttk.Frame(pages) for number in (1, 2, 3)}
        for page in self.pages.values():
            page.grid(row=0, column=0, sticky='nsew')

        self.status = tk.StringVar(value='Ready')
        self.status_display = tk.StringVar()
        self.status.trace_add('write', self.status_changed)
        self.status_label = ttk.Label(self, textvariable=self.status_display, style='Muted.TLabel', wraplength=px(640))
        self.status_label.grid(row=3, column=0, sticky='w', pady=(px(2), 0), padx=gutter)
        self.bind('<Configure>', lambda event: self.status_label.configure(wraplength=max(px(240), event.width - px(20))), add='+')

        self.build_connect(self.pages[1])
        self.build_inventory(self.pages[2])
        self.build_destination(self.pages[3])
        self.step = 1
        self.show_step(1)
        self.theme.register(self)

    # -- step 1: connect -------------------------------------------------
    def build_connect(self, page):
        px = self.theme.px
        page.columnconfigure(0, weight=1)
        page.rowconfigure(0, weight=1)
        self.address = tk.StringVar()
        self.username = tk.StringVar()
        self.password = tk.StringVar()
        self.password_visible = tk.BooleanVar(value=False)
        self.remember_connection = tk.BooleanVar(value=False)
        self.storage_notice = tk.StringVar(value=self.owner.settings_error or
            'Saved addresses and usernames are encrypted for your Windows account. Passwords are never saved.')
        self.saved_profiles = []
        self.saved_addresses = []
        self.last_address_identity = ''
        self.suggested_username = None

        card = self.theme.panel(page)
        card.grid(row=0, column=0, sticky='nsew', padx=(0, px(4)))
        form = ttk.Frame(card, style='Surface.TFrame', padding=(px(22), px(16)))
        form.pack(fill='both', expand=True)
        form.columnconfigure(0, weight=1)
        ttk.Label(form, text='Sign in to an ESXi host or vCenter', style='Heading.Surface.TLabel').grid(row=0, column=0, columnspan=2, sticky='w')
        self.login_entries = []
        for index, (label, variable) in enumerate((('Server address', self.address), ('Username', self.username),
                                                   ('Password', self.password))):
            ttk.Label(form, text=label, style='Surface.TLabel').grid(row=2 + index * 2, column=0, columnspan=2, sticky='w', pady=(10, 4))
            entry = ttk.Entry(form, textvariable=variable, show='\u2022' if index == 2 else '', exportselection=False)
            entry.grid(row=3 + index * 2, column=0, columnspan=1 if index == 2 else 2, sticky='ew')
            for modifier in shortcut_modifiers():
                entry.bind(f'<{modifier}-a>', self.select_all)
                entry.bind(f'<{modifier}-A>', self.select_all)
            self.login_entries.append(entry)
        self.address_entry, self.username_entry, self.password_entry = self.login_entries
        self.show_password_btn = ttk.Button(form, text='Show', command=self.toggle_password, width=6, style='Surface.TButton')
        self.show_password_btn.grid(row=7, column=1, sticky='e', padx=(8, 0))
        for key in ('<Return>', '<KP_Enter>'):
            self.show_password_btn.bind(key, self.password_visibility_enter)
            self.address_entry.bind(key, self.address_enter)
            self.username_entry.bind(key, lambda event: self.focus_login(2))
            self.password_entry.bind(key, self.password_enter)
        self.address_entry.bind('<KeyRelease>', self.suggest_addresses)
        self.address_entry.bind('<FocusOut>', lambda event: self.apply_saved_address())
        self.remember_check = ttk.Checkbutton(form, text='Remember this address and username',
                                              variable=self.remember_connection, style='Surface.Ova.TCheckbutton')
        self.remember_check.grid(row=8, column=0, columnspan=2, sticky='w', pady=(12, 0))
        self.connect_btn = ttk.Button(form, text='Connect', style='Surface.Accent.TButton', command=self.connect)
        self.connect_btn.grid(row=9, column=0, columnspan=2, sticky='w', pady=(14, 0))
        self.connect_btn.bind('<Return>', self.password_enter)

        side = self.theme.panel(page, width=px(320))
        side.grid(row=0, column=1, sticky='nsew')
        side.pack_propagate(False)
        saved = ttk.Frame(side, style='Surface.TFrame', padding=(0, px(16), 0, px(12)))
        saved.pack(fill='both', expand=True)
        saved.columnconfigure(0, weight=1)
        saved.rowconfigure(1, weight=1)
        ttk.Label(saved, text='Saved servers', style='Heading.Surface.TLabel').grid(row=0, column=0, sticky='w', padx=px(20), pady=(0, 8))
        ttk.Label(saved, text='The VM list is read with your account. This app never changes a VM.',
                  style='Small.Surface.TLabel', wraplength=px(256)).grid(row=4, column=0, sticky='w', padx=px(20), pady=(px(12), 0))
        self.saved_rows = ttk.Frame(saved, style='Surface.TFrame')
        self.saved_rows.grid(row=1, column=0, sticky='new')
        self.saved_rows.columnconfigure(0, weight=1)
        self.storage_label = ttk.Label(saved, textvariable=self.storage_notice, style='Small.Surface.TLabel', wraplength=px(240))
        self.storage_label.grid(row=2, column=0, sticky='ew', padx=px(20), pady=(8, 8))
        self.clear_saved_btn = ttk.Button(saved, text='Clear saved data…', command=self.clear_saved_data, style='Surface.TButton')
        self.clear_saved_btn.grid(row=3, column=0, sticky='w', padx=px(20))
        saved.bind('<Configure>', lambda event: self.storage_label.configure(wraplength=max(px(160), event.width - px(44))), add='+')
        self.saved_buttons = []
        self.load_saved_profiles()

    # -- step 2: inventory -----------------------------------------------
    def build_inventory(self, page):
        px = self.theme.px
        page.columnconfigure(0, weight=1)
        page.rowconfigure(1, weight=1)
        toolbar = ttk.Frame(page)
        toolbar.grid(row=0, column=0, sticky='ew', pady=(0, px(6)), padx=self.theme.card_margin[0])
        toolbar.columnconfigure(1, weight=1)
        self.connection = tk.StringVar(value='Not connected')
        self.server_label = ttk.Label(toolbar, textvariable=self.connection, style='Heading.TLabel')
        self.server_label.grid(row=0, column=0, columnspan=2, sticky='w', pady=(0, px(8)))
        self.change_server_btn = ttk.Button(toolbar, text='Disconnect', command=self.disconnect)
        self.change_server_btn.grid(row=0, column=3, columnspan=2, sticky='e', pady=(0, px(8)))
        ttk.Label(toolbar, text='Search', style='Muted.TLabel').grid(row=1, column=0, sticky='w', padx=(0, 8))
        self.search = tk.StringVar()
        self.search.trace_add('write', self.schedule_filter)
        self.search_entry = ttk.Entry(toolbar, textvariable=self.search, width=20, style='Page.TEntry',
                                      exportselection=False)
        self.search_entry.grid(row=1, column=1, sticky='ew')
        self.power_off_only = tk.BooleanVar(value=True)
        ttk.Checkbutton(toolbar, text='Powered off only', variable=self.power_off_only,
                        command=self.show_vms, style='Ova.TCheckbutton').grid(row=1, column=2, sticky='w', padx=(14, 14))
        self.count = tk.StringVar(value='0 virtual machines')
        ttk.Label(toolbar, textvariable=self.count, style='Muted.TLabel').grid(row=1, column=3, sticky='e', padx=(0, 12))
        self.refresh_btn = ttk.Button(toolbar, text='Refresh', command=self.refresh, state='disabled')
        self.refresh_btn.grid(row=1, column=4, sticky='e')

        table = self.theme.panel(page)
        table.grid(row=1, column=0, sticky='nsew')
        table.columnconfigure(0, weight=1)
        table.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(table, columns=('name', 'power', 'cpu', 'ram', 'disk'), show='headings',
                                 selectmode='browse', height=3)
        self.column_titles = {'name': 'Virtual machine', 'power': 'Power', 'cpu': 'CPUs', 'ram': 'Memory', 'disk': 'Disk capacity'}
        for key, width in (('name', 260), ('power', 110), ('cpu', 70), ('ram', 90), ('disk', 120)):
            self.tree.heading(key, anchor='w', command=lambda key=key: self.sort_by(key))
            self.tree.column(key, width=px(width), minwidth=px(50), stretch=key == 'name', anchor='w')
        self.label_headings()
        self.tree.grid(row=0, column=0, sticky='nsew')
        scroll = ttk.Scrollbar(table, orient='vertical', command=self.tree.yview, style='Surface.Vertical.TScrollbar')
        scroll.grid(row=0, column=1, sticky='ns')
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.bind('<<TreeviewSelect>>', lambda event: self.selection_changed())
        self.tree.bind('<Double-Button-1>', lambda event: self.show_step(3))
        self.tree.bind('<Return>', lambda event: self.show_step(3))
        self.inventory_empty = ttk.Label(self.tree, text='No matching virtual machines', style='Muted.Surface.TLabel',
                                         wraplength=px(400), justify='center', anchor='center')
        self.tree.bind('<Configure>', lambda event: self.inventory_empty.configure(
            wraplength=max(px(200), min(px(440), event.width - px(24)))), add='+')

        actions = ttk.Frame(page)
        actions.grid(row=2, column=0, sticky='ew', pady=(px(4), 0), padx=self.theme.card_margin[0])
        actions.columnconfigure(0, weight=1)
        self.detail = tk.StringVar(value='Choose a powered-off VM. Running VMs cannot be exported.')
        self.detail_label = ttk.Label(actions, textvariable=self.detail, style='Muted.TLabel', wraplength=px(520))
        self.detail_label.grid(row=0, column=0, sticky='w')
        self.continue_btn = ttk.Button(actions, text='Continue', style='Accent.TButton',
                                       command=lambda: self.show_step(3), state='disabled')
        self.continue_btn.grid(row=0, column=1, sticky='e', padx=(12, 0))
        actions.bind('<Configure>', lambda event: self.detail_label.configure(wraplength=max(px(200), event.width - px(140))), add='+')

    # -- step 3: destination ---------------------------------------------
    def build_destination(self, page):
        px = self.theme.px
        page.columnconfigure(0, weight=1)
        page.rowconfigure(2, weight=1)
        summary = self.theme.panel(page)
        summary.grid(row=0, column=0, sticky='ew')
        box = ttk.Frame(summary, style='Surface.TFrame', padding=(px(22), px(16)))
        box.pack(fill='x')
        self.vm_name = tk.StringVar()
        self.vm_specs = tk.StringVar()
        self.vm_path = tk.StringVar()
        ttk.Label(box, textvariable=self.vm_name, style='Title.Surface.TLabel').pack(anchor='w')
        ttk.Label(box, textvariable=self.vm_specs, style='Surface.TLabel').pack(anchor='w', pady=(4, 0))
        ttk.Label(box, textvariable=self.vm_path, style='Muted.Surface.TLabel').pack(anchor='w', pady=(2, 0))

        card = self.theme.panel(page)
        card.grid(row=1, column=0, sticky='ew')
        destination = ttk.Frame(card, style='Surface.TFrame', padding=(px(22), px(18)))
        destination.pack(fill='x')
        destination.columnconfigure(0, weight=1)
        self.folder = tk.StringVar(value=str(Path('D:/VMs') if Path('D:/VMs').is_dir() else Path.home() / 'Documents'))
        self.filename = tk.StringVar(value='virtual-machine.ova')
        ttk.Label(destination, text='Save folder', style='Surface.TLabel').grid(row=0, column=0, sticky='w', pady=(0, 5))
        self.folder_entry = ttk.Entry(destination, textvariable=self.folder)
        self.folder_entry.grid(row=1, column=0, sticky='ew')
        self.browse_btn = ttk.Button(destination, text='Browse…', command=self.browse, style='Surface.TButton')
        self.browse_btn.grid(row=1, column=1, sticky='e', padx=(8, 0))
        self.space = tk.StringVar()
        self.space_label = ttk.Label(destination, textvariable=self.space, style='Small.Surface.TLabel', wraplength=px(560))
        self.space_label.grid(row=2, column=0, columnspan=2, sticky='w', pady=(6, 0))
        ttk.Label(destination, text='OVA filename', style='Surface.TLabel').grid(row=3, column=0, sticky='w', pady=(14, 5))
        self.filename_entry = ttk.Entry(destination, textvariable=self.filename)
        self.filename_entry.grid(row=4, column=0, columnspan=2, sticky='ew')
        ttk.Label(destination, text='The file is written as .incomplete until every checksum in its manifest has been verified.',
                  style='Small.Surface.TLabel', wraplength=px(560)).grid(row=5, column=0, columnspan=2, sticky='w', pady=(6, 0))
        self.folder_entry.bind('<Return>', lambda event: (self.update_space(), self.filename_entry.focus_set()))
        self.folder_entry.bind('<FocusOut>', lambda event: self.update_space())
        self.filename_entry.bind('<Return>', self.export_enter)

        actions = ttk.Frame(page)
        actions.grid(row=3, column=0, sticky='ew', pady=(px(4), 0), padx=self.theme.card_margin[0])
        self.back_btn = ttk.Button(actions, text='Back', command=lambda: self.show_step(2))
        self.back_btn.pack(side='left')
        self.export_btn = ttk.Button(actions, text='Add to queue', style='Accent.TButton', command=self.export, state='disabled')
        self.export_btn.pack(side='right')

    def apply_theme(self, colors):
        self.tree.tag_configure('unavailable', foreground=colors['disabled'])

    # -- navigation ------------------------------------------------------
    @property
    def active(self):
        """True while a browsing session or a background step exists."""
        return self.busy or self.client is not None

    def chosen_vm(self):
        return next((vm for vm in self.machines if vm['id'] == self.selected_vm_id), None)

    def exportable(self):
        vm = self.chosen_vm()
        return bool(vm and vm.get('power') == 'poweredOff' and self.client and not self.busy
                    and self.filter_timer is None and self.tree.selection() == (vm['id'],))

    def show_step(self, step):
        if self.busy:
            return
        if step == 1 and self.client:
            return  # Use Disconnect; the sign-in form is cleared while connected.
        if step >= 2 and not self.client:
            return
        if step == 3:
            if not self.exportable():
                return
            vm = self.chosen_vm()
            self.vm_name.set(vm['name'])
            ram = f"{int(vm['ram']) / 1024:g} GB memory" if vm.get('ram') else 'memory unknown'
            disk = f"{vm['capacity'] / 1024**3:g} GB of virtual disks" if vm.get('capacity') else 'disk size unknown'
            self.vm_specs.set(f"{vm.get('cpu') or '—'} CPUs, {ram}, {disk}")
            self.vm_path.set(vm.get('path') or '')
            self.update_space()
        self.raise_page(step)
        self.refresh_steps()
        target = {1: self.address_entry, 2: self.search_entry, 3: self.filename_entry}[step]
        if self.winfo_ismapped():
            target.focus_set()

    def raise_page(self, step):
        # Hidden pages are unmapped so Tab cannot reach their controls.
        self.step = step
        for number, page in self.pages.items():
            if number == step:
                page.grid()
            else:
                page.grid_remove()

    def refresh_steps(self):
        for number, button in self.step_buttons.items():
            title = '  ' + STEP_TITLES[number]
            if number == 1 and self.client:
                title = f'  Connected to {self.client.authority}'
            reachable = (number == 1 and not self.client) or (number == 2 and bool(self.client)) or \
                        (number == 3 and self.exportable())
            style = 'StepActive.TButton' if number == self.step else 'StepDone.TButton' if number < self.step else 'Step.TButton'
            mark = 'active' if number == self.step else 'done' if number < self.step else 'todo'
            button.configure(text=title, style=style, image=self.theme.assets.get(f'stage_{mark}_page'),
                             state='normal' if number == self.step or (reachable and not self.busy) else 'disabled')

    def focus_search(self, event=None):
        if self.client and not self.busy:
            self.owner.show('new')
            self.show_step(2)
            self.search_entry.focus_set()
            self.search_entry.selection_range(0, 'end')
        return 'break'

    def status_changed(self, *args):
        text = self.status.get()
        self.status_label.configure(style='Error.TLabel' if text.startswith('Operation failed:') else 'Muted.TLabel')
        self.status_display.set('' if text in ROUTINE_STATUS else text)

    # -- password field --------------------------------------------------
    def hide_password(self):
        self.password_visible.set(False)
        self.password_entry.configure(show='\u2022')
        self.show_password_btn.configure(text='Show')

    def toggle_password(self):
        if self.busy or self.client:
            return
        visible = not self.password_visible.get()
        self.password_visible.set(visible)
        self.password_entry.configure(show='' if visible else '\u2022')
        self.show_password_btn.configure(text='Hide' if visible else 'Show')
        self.password_entry.focus_set()

    def password_visibility_enter(self, event=None):
        self.toggle_password()
        return 'break'

    # -- saved addresses and usernames -----------------------------------
    def load_saved_profiles(self):
        try:
            self.saved_profiles = self.owner.settings.profiles()
        except (OSError, ValueError) as error:
            self.saved_profiles = []
            self.storage_notice.set('Saved entries could not be read: ' + str(error))
        self.saved_addresses = list(dict.fromkeys(row['address'] for row in self.saved_profiles))
        for widget in self.saved_rows.winfo_children():
            widget.destroy()
        self.saved_buttons = []
        for index, row in enumerate(self.saved_profiles[:SAVED_ROWS]):
            button = ttk.Button(self.saved_rows, text=row['address'] + '\n' + row['username'], style='Surface.Row.TButton',
                                command=lambda row=row: self.use_profile(row['address'], row['username']))
            button.grid(row=index, column=0, sticky='ew', padx=self.theme.px(8))
            self.saved_buttons.append(button)
        if not self.saved_profiles:
            note = 'None yet. Tick “Remember this address and username” when you connect.'
        elif len(self.saved_profiles) > SAVED_ROWS:
            note = f'{len(self.saved_profiles) - SAVED_ROWS} more are suggested as you type an address.'
        else:
            note = ''
        if note:
            ttk.Label(self.saved_rows, text=note, style='Muted.Surface.TLabel', wraplength=self.theme.px(220)
                      ).grid(row=SAVED_ROWS, column=0, sticky='w', padx=self.theme.px(20), pady=(2, 0))
        self.lock_saved_rows()

    def lock_saved_rows(self):
        state = 'disabled' if self.busy or self.client else 'normal'
        for button in self.saved_buttons:
            button.configure(state=state)

    def use_profile(self, address, username):
        if self.busy or self.client:
            return
        self.address.set(address)
        self.apply_saved_address(force=True)
        self.username.set(username)
        self.suggested_username = username
        self.password_entry.focus_set()

    def saved_usernames(self, address):
        try:
            canonical = endpoint(address)[2].casefold()
        except ValueError:
            return []
        return sorted({row['username'] for row in self.saved_profiles if row['address'] == canonical}, key=str.casefold)

    def suggest_addresses(self, event=None):
        if self.busy or self.client:
            return
        key = getattr(event, 'keysym', '')
        if key in ('Return', 'KP_Enter', 'Tab', 'Escape', 'Up', 'Down', 'Left', 'Right', 'Home', 'End', 'Shift_L', 'Shift_R'):
            return
        typed = self.address.get()
        matches = [value for value in self.saved_addresses if value.casefold().startswith(typed.strip().casefold())]
        # Offer an inline completion while preserving the typed prefix and
        # caret. Navigation, deletion and modifier shortcuts do not autocomplete.
        if (not typed or typed != typed.strip() or not matches or key in ('BackSpace', 'Delete') or
                not getattr(event, 'char', '').isprintable() or getattr(event, 'state', 0) & 0x000c):
            return
        if self.address_entry.index('insert') == len(typed) and matches[0] != typed:
            self.address.set(matches[0])
            self.address_entry.selection_range(len(typed), 'end')
            self.address_entry.icursor(len(typed))

    def apply_saved_address(self, force=False):
        if self.busy or self.client:
            return
        try:
            canonical = endpoint(self.address.get())[2].casefold()
        except ValueError:
            canonical = self.address.get().strip().casefold()
        usernames = self.saved_usernames(self.address.get())
        if not force and canonical == self.last_address_identity:
            return
        self.last_address_identity = canonical
        self.password.set('')
        self.hide_password()
        current = self.username.get()
        if len(usernames) == 1:
            self.username.set(usernames[0])
            self.suggested_username = usernames[0]
        elif current not in usernames and (usernames or current == self.suggested_username):
            self.username.set('')
            self.suggested_username = None
        else:
            self.suggested_username = current if current in usernames else None
        if force:
            self.remember_connection.set(False)

    def select_saved_address(self, event=None):
        self.apply_saved_address(force=True)
        if not self.busy and not self.client:
            self.login_entries[2 if self.username.get() else 1].focus_set()

    def address_enter(self, event=None):
        self.apply_saved_address()
        return self.focus_login(1)

    def clear_saved_data(self):
        if self.busy or self.client:
            return
        if not messagebox.askyesno('Clear all saved connection data?',
                'Remove every remembered server address, username and trusted certificate on this PC?\n\n'
                'Current exports and OVA files are unaffected. Future connections will ask for certificate approval again.',
                parent=self.root, default=messagebox.NO):
            return
        error = None
        try:
            self.owner.settings.clear_all()
        except OSError as problem:
            error = problem
        self.load_saved_profiles()
        self.address.set('')
        self.username.set('')
        self.password.set('')
        self.hide_password()
        self.last_address_identity = ''
        self.suggested_username = None
        self.login_identity = None
        self.remember_connection.set(False)
        self.storage_notice.set('Some saved data could not be cleared: ' + str(error) if error else
                                'All saved addresses, usernames and certificate trust have been cleared.')

    def remember_connected_profile(self):
        identity, self.login_identity = self.login_identity, None
        if not identity or not identity[2]:
            return
        address, username, _ = identity
        try:
            self.owner.settings.remember_profile(address, username)
            self.load_saved_profiles()
            self.storage_notice.set('Address and username saved with Windows encryption. No password was saved.')
        except (OSError, ValueError) as error:
            self.storage_notice.set('Connected, but the address/username could not be saved: ' + str(error))

    @staticmethod
    def select_all(event):
        event.widget.selection_range(0, 'end')
        event.widget.icursor('end')
        return 'break'

    def focus_login(self, index):
        if not self.busy:
            self.login_entries[index].focus_set()
        return 'break'

    def password_enter(self, event=None):
        if not self.busy and not self.client and self.step == 1:
            self.connect()
        return 'break'

    def export_enter(self, event=None):
        if not self.busy and self.client and self.step == 3:
            self.export()
        return 'break'

    # -- session ---------------------------------------------------------
    def emit(self, kind, payload):
        if isinstance(payload, str) and self.secret:
            payload = payload.replace(self.secret, '[session ticket]')
        self.events.put((kind, payload))

    def append_log(self, value):
        value = str(value)
        if self.secret:
            value = value.replace(self.secret, '[session ticket]')
        value = re.sub(r'vi://[^\s@]+@', 'vi://[credentials]@', value)
        self.activity.append(value.rstrip())

    def set_busy(self, busy):
        self.busy = busy
        blocked = busy or self.client is not None
        if blocked:
            self.hide_password()
        for widget in self.login_entries + [self.show_password_btn, self.remember_check, self.clear_saved_btn]:
            widget.configure(state='disabled' if blocked else 'normal')
        self.lock_saved_rows()
        self.connect_btn.configure(state='disabled' if blocked else 'normal',
                                   text='Connecting…' if busy and not self.client else 'Connect')
        for widget in (self.change_server_btn, self.back_btn, self.browse_btn):
            widget.configure(state='disabled' if busy else 'normal')
        self.refresh_btn.configure(state='normal' if self.client and not busy else 'disabled')
        self.selection_changed()

    def connect(self):
        if self.busy or self.client:
            return
        try:
            endpoint(self.address.get())
            if not self.username.get().strip() or not self.password.get():
                raise ValueError('Enter your username and password.')
        except ValueError as error:
            messagebox.showerror('Connection', str(error), parent=self.root)
            return
        self.set_busy(True)
        self.status.set('Checking server certificate…')
        address = self.address.get()

        def worker():
            try:
                self.emit('certificate', (address, probe(address)))
            except Exception as error:
                self.emit('error', str(error))
        threading.Thread(target=worker, daemon=True).start()

    def disconnect(self):
        if self.busy or not self.client:
            return
        client, self.client = self.client, None
        threading.Thread(target=client.logout, daemon=True).start()
        self.machines = []
        self.selected_vm_id = None
        self.show_vms()
        self.connection.set('Not connected')
        self.address.set('')
        self.username.set('')
        self.password.set('')
        self.hide_password()
        self.login_identity = None
        self.remember_connection.set(False)
        self.last_address_identity = ''
        self.suggested_username = None
        self.search.set('')
        self.set_busy(False)
        self.show_step(1)
        self.status.set('Disconnected')
        self.owner.session_changed()

    def authenticate(self, address, cert):
        sha256 = fingerprint(cert)
        try:
            trusted = self.owner.settings.trusted_pin(address)
        except (OSError, ValueError) as error:
            trusted = None
            self.storage_notice.set('Saved certificate trust could not be read: ' + str(error))
        if trusted != sha256:
            changed = ('The certificate has changed since your previous approval.\n'
                       f'Previously trusted SHA-256:\n{trusted}\n\n') if trusted else ''
            accepted = messagebox.askyesno('Certificate changed — review required' if trusted else 'Trust this VMware server?',
                f'Server: {address}\n\n' + changed + f'Current SHA-256 certificate fingerprint:\n{sha256}\n\n'
                'Compare this fingerprint with your server certificate before continuing.\n'
                'Trust and remember this certificate on this PC?', parent=self.root, default=messagebox.NO)
            if not accepted:
                self.password.set('')
                self.hide_password()
                self.set_busy(False)
                self.status.set('Connection cancelled')
                return
            try:
                self.owner.settings.trust_certificate(address, sha256)
            except (OSError, ValueError) as error:
                self.storage_notice.set('Certificate approved for this connection, but trust could not be saved: ' + str(error))
        username, password = self.username.get().strip(), self.password.get()
        self.login_identity = (address, username, self.remember_connection.get())
        self.password.set('')
        self.hide_password()
        self.status.set('Signing in and reading virtual machines…')

        def worker():
            client = VSphere(address, cert)
            try:
                client.login(username, password)
                self.emit('connected', (client, client.inventory()))
            except Exception as error:
                client.logout()
                self.emit('error', str(error))
        threading.Thread(target=worker, daemon=True).start()

    def refresh(self):
        if self.busy or not self.client:
            return
        self.set_busy(True)
        self.status.set('Refreshing virtual machines…')

        def worker():
            try:
                self.emit('inventory', self.client.inventory())
            except Exception as error:
                self.emit('error', str(error))
        threading.Thread(target=worker, daemon=True).start()

    # -- inventory table -------------------------------------------------
    def label_headings(self):
        for key, title in self.column_titles.items():
            arrow = (' ▾' if self.sort_reverse else ' ▴') if key == self.sort_key else ''
            self.tree.heading(key, text=title + arrow)

    def sort_by(self, key):
        self.sort_reverse = not self.sort_reverse if key == self.sort_key else False
        self.sort_key = key
        self.label_headings()
        self.show_vms()

    def sort_value(self, vm):
        if self.sort_key == 'name':
            return vm['name'].casefold()
        if self.sort_key == 'power':
            return str(vm.get('power'))
        raw = vm.get({'cpu': 'cpu', 'ram': 'ram', 'disk': 'capacity'}[self.sort_key]) or 0
        try:
            return float(raw)
        except (TypeError, ValueError):
            return 0.0

    def show_vms(self):
        if self.filter_timer is not None:
            self.root.after_cancel(self.filter_timer)
            self.filter_timer = None
        previous = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        query = self.search.get().casefold()
        for vm in sorted(self.machines, key=self.sort_value, reverse=self.sort_reverse):
            if query not in vm['name'].casefold():
                continue
            if self.power_off_only.get() and vm.get('power') != 'poweredOff':
                continue
            ram = f"{int(vm['ram']) / 1024:g} GB" if vm['ram'] else '—'
            disk = f"{vm['capacity'] / 1024**3:g} GB" if vm['capacity'] else '—'
            self.tree.insert('', 'end', iid=vm['id'],
                             values=(vm['name'], POWER_TEXT.get(vm['power'], vm['power']), vm['cpu'], ram, disk),
                             tags=() if vm.get('power') == 'poweredOff' else ('unavailable',))
        if previous and self.tree.exists(previous[0]):
            self.tree.selection_set(previous)
        count = len(self.tree.get_children())
        self.count.set(f'{count} of {len(self.machines)} VMs')
        if count:
            self.inventory_empty.place_forget()
        else:
            self.inventory_empty.configure(text='No matching VMs. Try another name or turn off Powered off only.'
                                           if self.machines else 'No virtual machines were returned by this server.')
            self.inventory_empty.place(relx=0.5, rely=0.55, anchor='center')
        self.selection_changed()

    def schedule_filter(self, *args):
        if self.filter_timer is not None:
            self.root.after_cancel(self.filter_timer)
        # Do not allow an old selection to be exported while its filter changes.
        self.export_btn.configure(state='disabled')
        self.continue_btn.configure(state='disabled')
        self.filter_timer = self.root.after(120, self.show_vms)

    def selection_changed(self):
        selected = self.tree.selection()
        vm = next((vm for vm in self.machines if selected and vm['id'] == selected[0]), None)
        if vm:
            if vm.get('power') == 'poweredOff':
                self.detail.set(vm['path'] or vm['name'])
            else:
                self.detail.set('This VM is running, suspended, or its power state is unknown. '
                                'Shut it down in VMware first; this app never powers a VM off.')
            if self.selected_vm_id != vm['id']:
                self.filename.set((re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', vm['name']).strip('. ') or 'virtual-machine') + '.ova')
                self.selected_vm_id = vm['id']
        else:
            self.selected_vm_id = None
            self.detail.set('Choose a powered-off VM. Running VMs cannot be exported.')
        state = 'normal' if self.exportable() else 'disabled'
        self.export_btn.configure(state=state)
        self.continue_btn.configure(state=state)
        if self.step == 3 and state == 'disabled' and not self.busy and self.client:
            self.raise_page(2)
        self.refresh_steps()

    # -- destination -----------------------------------------------------
    def browse(self):
        folder = filedialog.askdirectory(parent=self.root, initialdir=self.folder.get(), title='Choose where to save the OVA')
        if folder:
            self.folder.set(folder)
            self.update_space()

    def update_space(self):
        """Describe free space where the OVA will be written; never blocks an export."""
        folder_text = self.folder.get().strip()
        try:
            folder = Path(folder_text)
            if not folder_text or not folder.is_dir():
                raise OSError('missing')
            free = shutil.disk_usage(folder).free
        except (OSError, ValueError):
            self.space.set('This folder does not exist yet. Choose an existing folder.')
            self.space_label.configure(style='Warning.Surface.TLabel')
            return
        vm = self.chosen_vm()
        capacity = vm.get('capacity') if vm else 0
        if capacity and free < capacity:
            self.space.set(f'{gigabytes(free)} free here, less than this VM\'s {gigabytes(capacity)} of virtual disks. '
                           'A thin or mostly empty disk can still fit, because OVF Tool compresses it.')
            self.space_label.configure(style='Warning.Surface.TLabel')
        else:
            self.space.set(f'{gigabytes(free)} free in this folder\'s drive.')
            self.space_label.configure(style='Small.Surface.TLabel')

    def export(self):
        vm = self.chosen_vm()
        if not vm or self.busy or self.filter_timer is not None or self.tree.selection() != (vm['id'],):
            return
        if vm['power'] != 'poweredOff':
            messagebox.showinfo('VM must be powered off', 'Shut down this VM normally in VMware, then click Refresh before exporting.', parent=self.root)
            return
        folder_text = self.folder.get().strip()
        if not folder_text:
            messagebox.showerror('Save folder', 'Choose an existing folder.', parent=self.root)
            return
        folder = Path(folder_text)
        try:
            if not folder.is_dir():
                raise ValueError('Choose an existing folder.')
        except (OSError, ValueError) as error:
            messagebox.showerror('Save folder', str(error), parent=self.root)
            return
        name = self.filename.get().strip()
        try:
            validate_output_name(name)
        except ValueError as error:
            messagebox.showerror('Filename', str(error), parent=self.root)
            return
        target = folder / name
        try:
            exists = target.exists()
            available = shutil.disk_usage(target.parent).free
        except OSError as error:
            messagebox.showerror('Save folder unavailable', 'The destination could not be checked: ' + str(error), parent=self.root)
            return
        if exists:
            messagebox.showinfo('Choose a new filename', 'Choose a filename that does not already exist. Existing OVA packages are preserved.', parent=self.root)
            return
        if target.suffix.lower() != '.ova':
            messagebox.showerror('Filename', 'The filename must end with .ova.', parent=self.root)
            return
        if available < 512 * 1024**2:
            messagebox.showerror('Disk space', 'Less than 512 MB is available. Choose another drive.', parent=self.root)
            return
        if self.manager.conflicts(self.client.authority, vm['id'], target):
            messagebox.showinfo('Task already exists', 'This VM or output filename already has an unfinished task.', parent=self.root)
            return
        same_server = [job for job in self.manager.unfinished()
                       if job.endpoint == self.client.authority.casefold()]
        if same_server and not messagebox.askyesno(
                'Another export from this server',
                'Another VM from this server address is already exporting or queued.\n\n'
                'Concurrent exports share server CPU, storage and network bandwidth, which can slow transfers.\n\n'
                'This app runs one export at a time per server address. Your new task will wait in the queue.\n\n'
                'Add this VM to the queue?', parent=self.root, default=messagebox.NO):
            return
        self.set_busy(True)
        self.status.set('Creating an independent export session…')
        browser = self.client

        def prepare():
            child = None
            try:
                child = browser.fork()
                self.emit('prepared', (child, vm.copy(), target))
            except Exception as error:
                if child:
                    child.logout()
                self.emit('error', str(error))
        threading.Thread(target=prepare, daemon=True).start()

    # -- worker results --------------------------------------------------
    def poll(self):
        try:
            for _ in range(16):
                kind, payload = self.events.get_nowait()
                if kind == 'certificate':
                    self.authenticate(*payload)
                elif kind == 'connected':
                    self.client, self.machines = payload
                    self.password.set('')
                    self.hide_password()
                    self.remember_connected_profile()
                    product = getattr(self.client, 'product', '')
                    self.connection.set(self.client.authority + (', ' + product if product else ''))
                    self.address.set('')
                    self.username.set('')
                    self.show_vms()
                    self.set_busy(False)
                    self.show_step(2)
                    self.status.set('Connected. Select a powered-off VM.')
                    self.owner.session_changed()
                elif kind == 'inventory':
                    self.machines = payload
                    self.show_vms()
                    self.set_busy(False)
                    self.status.set('Virtual machine list updated')
                elif kind == 'prepared':
                    child, vm, target = payload
                    try:
                        job = self.manager.add(child, vm, target)
                    except Exception as error:
                        threading.Thread(target=child.logout, daemon=True).start()
                        self.set_busy(False)
                        self.status.set(str(error))
                        continue
                    self.set_busy(False)
                    # Stay signed in so another VM from this server can be queued.
                    self.tree.selection_set(())
                    self.selection_changed()
                    self.show_step(2)
                    self.status.set(f"{vm['name']} was added to the queue. Choose another VM, or disconnect when finished.")
                    self.owner.add_job(job)
                elif kind == 'error':
                    self.password.set('')
                    self.hide_password()
                    self.login_identity = None
                    self.set_busy(False)
                    self.status.set('Operation failed: ' + payload)
                    self.append_log(payload)
        except queue.Empty:
            pass

    def shutdown(self):
        """Forget typed credentials and end the browsing session; exports keep their own."""
        self.password.set('')
        self.hide_password()
        self.login_identity = None
        self.username.set('')
        self.address.set('')
        if self.filter_timer is not None:
            self.root.after_cancel(self.filter_timer)
            self.filter_timer = None
        client, self.client = self.client, None
        if client:
            threading.Thread(target=client.logout, daemon=True).start()
