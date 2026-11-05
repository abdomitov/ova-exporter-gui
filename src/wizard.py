"""Connection and VM selection wizard; no export process ownership."""
import queue
import re
import shutil
import threading
import tkinter as tk
from collections import deque
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from accordion import Accordion, install_mousewheel
from metadata import APP_NAME, VERSION
from ui_assets import password_eye_images
from vsphere import VSphere, endpoint, fingerprint, probe
from output_paths import validate_output_name


class ExportWizard:
    def __init__(self, root, owner):
        self.owner = owner
        self.manager = owner.manager
        self.closed = False
        self.root = root
        self.events = queue.Queue()
        self.client = None
        self.machines = []
        self.busy = False
        self.secret = ''
        self.login_identity = None
        root.title(f'New export — {APP_NAME} {VERSION}')
        root.geometry('740x620')
        root.minsize(600, 420)
        root.resizable(True, True)
        self.theme = owner.theme
        style = self.theme.style
        self.password_icons, eye_size = password_eye_images(root, self.theme.colors['muted'])
        style.configure('Password.TEntry', padding=(8, 7, eye_size + 14, 7))
        outer = ttk.Frame(root, padding=12)
        outer.pack(fill='both', expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(2, weight=1)
        ttk.Label(outer, text='New export', font=('Segoe UI', 18, 'bold')).grid(row=0, column=0, sticky='w')
        self.step_caption = tk.StringVar()
        ttk.Label(outer, textvariable=self.step_caption, style='Muted.TLabel').grid(row=1, column=0, sticky='w', pady=(2, 7))

        self.accordion = Accordion(outer, {1:'1  Connect to server', 2:'2  Choose VM and destination'}, self.toggle_step)
        self.accordion.grid(row=2, column=0, sticky='nsew')
        login = self.accordion.bodies[1].inner
        self.address = tk.StringVar()
        self.username = tk.StringVar()
        self.password = tk.StringVar()
        self.password_visible = tk.BooleanVar(value=False)
        self.remember_connection = tk.BooleanVar(value=False)
        self.storage_notice = tk.StringVar(value=owner.settings_error or
            'Saved addresses and usernames are encrypted for your Windows account. Passwords are never saved.')
        self.saved_profiles = []
        self.saved_addresses = []
        self.last_address_identity = ''
        self.suggested_username = None
        self.login_entries = []
        for col, (label, var) in enumerate((('vCenter or ESXi address', self.address),
                                           ('Username', self.username), ('Password', self.password))):
            ttk.Label(login, text=label).grid(row=col, column=0, sticky='w', padx=(0, 10), pady=4)
            if col == 2:
                password_row = ttk.Frame(login)
                password_row.grid(row=col, column=1, sticky='ew', padx=(0, 8), pady=4)
                password_row.columnconfigure(0, weight=1)
                widget = ttk.Entry(password_row, textvariable=var, width=18, show='\u2022', style='Password.TEntry')
                widget.grid(row=0, column=0, sticky='ew')
                self.show_password_btn = ttk.Button(password_row, text='Show', image=self.password_icons[0],
                                                    compound='none', style='PasswordEye.TButton', command=self.toggle_password)
                self.show_password_btn.place(relx=1, x=-3, rely=0.5, anchor='e', width=eye_size+8, relheight=1, height=-6)
                for key in ('<Return>', '<KP_Enter>'):
                    self.show_password_btn.bind(key, self.password_visibility_enter)
            else:
                widget = ttk.Combobox(login, textvariable=var, width=24, state='normal')
                widget.grid(row=col, column=1, columnspan=2, sticky='ew', padx=(0, 8), pady=4)
        
            self.login_entries.append(widget)
            widget.bind('<Control-a>', self.select_all)
            widget.bind('<Control-A>', self.select_all)
        self.address_combo, self.username_combo = self.login_entries[:2]
        self.address_combo.configure(postcommand=lambda: self.address_combo.configure(values=self.saved_addresses))
        self.address_combo.bind('<<ComboboxSelected>>', self.select_saved_address)
        self.address_combo.bind('<KeyRelease>', self.suggest_addresses)
        self.address_combo.bind('<FocusOut>', lambda event: self.apply_saved_address())
        self.username_combo.bind('<<ComboboxSelected>>', self.select_saved_username)
        for key in ('<Return>', '<KP_Enter>'):
            self.login_entries[0].bind(key, self.address_enter)
            self.login_entries[1].bind(key, lambda event: self.focus_login(2))
            self.login_entries[2].bind(key, self.password_enter)
        login.columnconfigure(1, weight=1)
        self.connect_btn = ttk.Button(login, text='Connect', style='Accent.TButton', command=self.connect)
        self.connect_btn.grid(row=2, column=2, sticky='ew')
        self.connect_btn.bind('<Return>', self.password_enter)
        self.connection = tk.StringVar(value='Not connected. Use the host account for ESXi, or your vCenter account for vCenter.')
        self.remember_check = ttk.Checkbutton(login, text='Remember address and username only',
                                             variable=self.remember_connection, style='Ova.TCheckbutton')
        self.remember_check.grid(row=3, column=0, columnspan=2, sticky='w', pady=(4, 0))
        self.clear_saved_btn = ttk.Button(login, text='Clear saved data', command=self.clear_saved_data)
        self.clear_saved_btn.grid(row=3, column=2, sticky='ew', pady=(4, 0))
        ttk.Label(login, textvariable=self.connection, style='Muted.TLabel', wraplength=450).grid(row=4, column=0, columnspan=3, sticky='ew', pady=(6, 0))
        ttk.Label(login, textvariable=self.storage_notice, style='Muted.TLabel', wraplength=480).grid(row=5, column=0, columnspan=3, sticky='ew', pady=(5, 0))
        self.load_saved_profiles()

        inventory = self.accordion.bodies[2].inner
        inventory.columnconfigure(0, weight=1)
        inventory.rowconfigure(2, weight=1)
        context = ttk.Frame(inventory)
        context.grid(row=0, column=0, sticky='ew', pady=(0, 5))
        context.columnconfigure(0, weight=1)
        ttk.Label(context, textvariable=self.connection, style='Muted.TLabel', wraplength=360).grid(row=0, column=0, sticky='w')
        self.change_server_btn = ttk.Button(context, text='Change server', command=self.connect)
        self.change_server_btn.grid(row=0, column=1, sticky='e')
        toolbar = ttk.Frame(inventory)
        toolbar.grid(row=1, column=0, sticky='ew', pady=(0, 5))
        toolbar.columnconfigure(1, weight=1)
        ttk.Label(toolbar, text='Search').grid(row=0, column=0, sticky='w', padx=(0, 8))
        self.search = tk.StringVar()
        self.search.trace_add('write', lambda *args: self.show_vms())
        ttk.Entry(toolbar, textvariable=self.search, width=18).grid(row=0, column=1, sticky='ew', padx=(0, 8))
        self.power_off_only = tk.BooleanVar(value=True)
        ttk.Checkbutton(toolbar, text='Powered off only', variable=self.power_off_only,
                        command=self.show_vms, style='Ova.TCheckbutton').grid(row=1, column=0, columnspan=2, sticky='w', pady=(5, 0))
        self.count = tk.StringVar(value='0 virtual machines')
        ttk.Label(toolbar, textvariable=self.count).grid(row=1, column=2, sticky='e', pady=(5, 0))
        self.refresh_btn = ttk.Button(toolbar, text='Refresh', command=self.refresh, state='disabled')
        self.refresh_btn.grid(row=0, column=2, sticky='e')
        table = ttk.Frame(inventory)
        table.grid(row=2, column=0, sticky='nsew')
        self.tree = ttk.Treeview(table, columns=('name', 'power', 'cpu', 'ram', 'disk'), show='headings', selectmode='browse', height=2)
        for key, title, width in (('name', 'Virtual machine', 200), ('power', 'Power state', 90),
                                  ('cpu', 'CPUs', 60), ('ram', 'Memory', 65), ('disk', 'Disk capacity', 100)):
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, minwidth=40, stretch=key == 'name')
        table.columnconfigure(0, weight=1)
        table.rowconfigure(0, weight=1)
        self.tree.grid(row=0, column=0, sticky='nsew')
        scroll = ttk.Scrollbar(table, orient='vertical', command=self.tree.yview)
        scroll.grid(row=0, column=1, sticky='ns')
        horizontal = ttk.Scrollbar(table, orient='horizontal', command=self.tree.xview)
        horizontal.grid(row=1, column=0, sticky='ew')
        self.tree.configure(yscrollcommand=scroll.set, xscrollcommand=horizontal.set)
        self.tree.bind('<<TreeviewSelect>>', lambda event: self.selection_changed())
        self.detail = tk.StringVar(value='Choose a powered-off VM to export. Running VMs are never shut down automatically.')
        ttk.Label(inventory, textvariable=self.detail, style='Muted.TLabel', wraplength=480).grid(row=3, column=0, sticky='w', pady=(4, 4))

        destination = ttk.Frame(inventory, padding=(0, 5))
        destination.grid(row=4, column=0, sticky='ew')
        destination.columnconfigure(1, weight=1)
        self.folder = tk.StringVar(value=str(Path('D:/VMs') if Path('D:/VMs').is_dir() else Path.home() / 'Documents'))
        self.filename = tk.StringVar(value='virtual-machine.ova')
        self.selected_vm_id = None
        ttk.Label(destination, text='Folder').grid(row=0, column=0, sticky='w')
        self.folder_entry = ttk.Entry(destination, textvariable=self.folder, width=22)
        self.folder_entry.grid(row=0, column=1, sticky='ew', pady=3, padx=8)
        ttk.Button(destination, text='Browse…', command=self.browse).grid(row=0, column=2, sticky='ew', pady=3)
        ttk.Label(destination, text='Filename').grid(row=1, column=0, sticky='w')
        self.filename_entry = ttk.Entry(destination, textvariable=self.filename, width=22)
        self.filename_entry.grid(row=1, column=1, sticky='ew', pady=3, padx=8)
        self.folder_entry.bind('<Return>', lambda event: self.filename_entry.focus_set())
        self.filename_entry.bind('<Return>', self.export_enter)
        self.export_btn = ttk.Button(destination, text='Add export task →', style='Accent.TButton', command=self.export, state='disabled')
        self.export_btn.grid(row=1, column=2, sticky='ew', pady=3)

        self.status = tk.StringVar(value='Ready')
        self.status.trace_add('write', self.status_changed)
        ttk.Label(inventory, textvariable=self.status, style='Muted.TLabel', wraplength=480).grid(row=5, column=0, sticky='w', pady=(8, 0))
        self.pages = {1: login, 2: inventory}
        self.step = 1
        self.show_step(1)
        self.activity = deque(maxlen=200)
        ttk.Label(outer, text=f'v{VERSION} · Encrypted saved entries · Passwords never saved',
                  font=('Segoe UI', 9), style='Muted.TLabel').grid(row=3, column=0, sticky='w', pady=(6, 0))
        root.protocol('WM_DELETE_WINDOW', self.close)
        self.refresh_wheel = install_mousewheel(root)
        root.bind('<F5>', lambda event: self.refresh() if self.step == 2 else None)
        root.bind('<Escape>', lambda event: self.close())
        root.after_idle(self.login_entries[0].focus_set)
        self.theme.register(self)
        self.timer = root.after(100, self.poll)

    def apply_theme(self, colors):
        self.password_icons, _ = password_eye_images(self.root, colors['muted'])
        self.show_password_btn.configure(image=self.password_icons[int(self.password_visible.get())])

    def hide_password(self):
        self.password_visible.set(False)
        self.login_entries[2].configure(show='\u2022')
        self.show_password_btn.configure(text='Show', image=self.password_icons[0])

    def toggle_password(self):
        if self.busy or self.client:
            return
        visible = not self.password_visible.get()
        self.password_visible.set(visible)
        self.login_entries[2].configure(show='' if visible else '\u2022')
        self.show_password_btn.configure(text='Hide' if visible else 'Show', image=self.password_icons[int(visible)])
        self.login_entries[2].focus_set()

    def password_visibility_enter(self, event=None):
        self.toggle_password()
        return 'break'

    def load_saved_profiles(self):
        try:
            self.saved_profiles = self.owner.settings.profiles()
        except (OSError, ValueError) as error:
            self.saved_profiles = []
            self.storage_notice.set('Saved entries could not be read: ' + str(error))
        self.saved_addresses = list(dict.fromkeys(row['address'] for row in self.saved_profiles))
        self.address_combo.configure(values=self.saved_addresses)
        self.username_combo.configure(values=self.saved_usernames(self.address.get()))

    def saved_usernames(self, address):
        try:
            canonical = endpoint(address)[2].casefold()
        except ValueError:
            return []
        return sorted({row['username'] for row in self.saved_profiles if row['address']==canonical}, key=str.casefold)

    def suggest_addresses(self, event=None):
        if self.busy or self.client:
            return
        key = getattr(event, 'keysym', '')
        if key in ('Return','KP_Enter','Tab','Escape','Up','Down','Left','Right','Home','End','Shift_L','Shift_R'):
            return
        typed = self.address.get()
        matches = [value for value in self.saved_addresses if value.casefold().startswith(typed.strip().casefold())]
        self.address_combo.configure(values=matches)
        # Offer an inline completion while preserving the typed prefix and
        # caret. Navigation, deletion and modifier shortcuts do not autocomplete.
        if (not typed or typed != typed.strip() or not matches or key in ('BackSpace','Delete') or
                not getattr(event, 'char', '').isprintable() or getattr(event, 'state', 0) & 0x000c):
            return
        if self.address_combo.index('insert') == len(typed) and matches[0] != typed:
            self.address.set(matches[0])
            self.address_combo.selection_range(len(typed), 'end')
            self.address_combo.icursor(len(typed))

    def apply_saved_address(self, force=False):
        if self.busy or self.client:
            return
        try:
            canonical = endpoint(self.address.get())[2].casefold()
        except ValueError:
            canonical = self.address.get().strip().casefold()
        usernames = self.saved_usernames(self.address.get())
        self.username_combo.configure(values=usernames)
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

    def select_saved_username(self, event=None):
        if not self.busy and not self.client:
            self.suggested_username = self.username.get()
            self.password.set('')
            self.hide_password()
            self.login_entries[2].focus_set()

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
        self.username_combo.configure(values=())
        self.last_address_identity = ''
        self.suggested_username = None
        self.login_identity = None
        self.remember_connection.set(False)
        self.storage_notice.set('Some saved data could not be cleared: '+str(error) if error else
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
            self.storage_notice.set('Connected, but the address/username could not be saved: '+str(error))

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
        if not self.busy and self.client and self.step == 2:
            self.export()
        return 'break'

    def toggle_step(self, step):
        if self.accordion.open_step == step:
            self.accordion.select(None)
        else:
            self.step = step
            self.accordion.select(step)

    def show_step(self, step):
        # Automatic transitions open the next body; every header stays visible.
        if self.busy:
            return
        if step == 2 and not self.client:
            return
        self.step = step
        self.accordion.select(step)
        self.step_caption.set({1:'Connect, choose a VM, then export. Use + / − to open or close a section.',
                               2:'Connected. Choose a virtual machine and save location.',
                               3:'Downloads run in the main task window.'}[step])

    def status_changed(self, *args):
        if self.step == 1 and not self.client:
            self.connection.set(self.status.get())

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
        for widget in self.login_entries:
            widget.configure(state='disabled' if busy or self.client else 'normal')
        for widget in (self.show_password_btn, self.remember_check, self.clear_saved_btn):
            widget.configure(state='disabled' if blocked else 'normal')
        self.connect_btn.configure(state='disabled' if busy else 'normal')
        for button in (self.change_server_btn,):
            button.configure(state='disabled' if busy else 'normal')
        self.refresh_btn.configure(state='normal' if self.client and not busy else 'disabled')
        self.selection_changed()

    def connect(self):
        if self.busy:
            return
        if self.client:
            client, self.client = self.client, None
            threading.Thread(target=client.logout, daemon=True).start()
            self.machines = []
            self.selected_vm_id = None
            self.show_vms()
            self.connect_btn.configure(text='Connect')
            self.connection.set('Disconnected')
            self.address.set('')
            self.username.set('')
            self.password.set('')
            self.hide_password()
            self.login_identity = None
            self.remember_connection.set(False)
            self.last_address_identity = ''
            self.suggested_username = None
            self.address_combo.configure(values=self.saved_addresses)
            self.username_combo.configure(values=())
            self.set_busy(False)
            self.show_step(1)
            return
        try:
            endpoint(self.address.get())
            if not self.username.get().strip() or not self.password.get():
                raise ValueError('Enter your username and password.')
        except ValueError as error:
            messagebox.showerror('Connection', str(error))
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

    def authenticate(self, address, cert):
        sha256 = fingerprint(cert)
        try:
            trusted = self.owner.settings.trusted_pin(address)
        except (OSError, ValueError) as error:
            trusted = None
            self.storage_notice.set('Saved certificate trust could not be read: '+str(error))
        if trusted != sha256:
            changed = ('The certificate has changed since your previous approval.\n'
                       f'Previously trusted SHA-256:\n{trusted}\n\n') if trusted else ''
            accepted = messagebox.askyesno('Certificate changed — review required' if trusted else 'Trust this VMware server?',
                f'Server: {address}\n\n'+changed+f'Current SHA-256 certificate fingerprint:\n{sha256}\n\n'
                'Compare this fingerprint with your server certificate before continuing.\n'
                'Trust and remember this certificate on this PC?', parent=self.root)
            if not accepted:
                self.password.set('')
                self.hide_password()
                self.set_busy(False)
                self.status.set('Connection cancelled')
                return
            try:
                self.owner.settings.trust_certificate(address, sha256)
            except (OSError, ValueError) as error:
                self.storage_notice.set('Certificate approved for this connection, but trust could not be saved: '+str(error))
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

    def show_vms(self):
        previous = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        query = self.search.get().casefold()
        for vm in self.machines:
            if query not in vm['name'].casefold():
                continue
            if self.power_off_only.get() and vm.get('power') != 'poweredOff':
                continue
            power = {'poweredOff': 'Powered off', 'poweredOn': 'Running', 'suspended': 'Suspended'}.get(vm['power'], vm['power'])
            ram = f"{int(vm['ram']) / 1024:g} GB" if vm['ram'] else '—'
            disk = f"{vm['capacity'] / 1024**3:g} GB" if vm['capacity'] else '—'
            self.tree.insert('', 'end', iid=vm['id'], values=(vm['name'], power, vm['cpu'], ram, disk))
        if previous and self.tree.exists(previous[0]):
            self.tree.selection_set(previous)
        self.count.set(f'{len(self.tree.get_children())} of {len(self.machines)} VMs')
        self.selection_changed()

    def selection_changed(self):
        selected = self.tree.selection()
        vm = next((vm for vm in self.machines if selected and vm['id'] == selected[0]), None)
        if vm:
            if vm.get('power') == 'poweredOff':
                self.detail.set(vm['path'] or vm['name'])
            else:
                self.detail.set('Export unavailable: this VM is running, suspended, or its power state is unknown. The app will not shut it down.')
            if self.selected_vm_id != vm['id']:
                self.filename.set((re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', vm['name']).strip('. ') or 'virtual-machine') + '.ova')
                self.selected_vm_id = vm['id']
        else:
            self.detail.set('Choose a powered-off VM to export. Running VMs are never shut down automatically.')
        self.export_btn.configure(state='normal' if vm and vm.get('power') == 'poweredOff' and self.client and not self.busy else 'disabled')

    def browse(self):
        folder = filedialog.askdirectory(initialdir=self.folder.get(), title='Choose where to save the OVA')
        if folder:
            self.folder.set(folder)

    def export(self):
        selected = self.tree.selection()
        vm = next((v for v in self.machines if selected and v['id'] == selected[0]), None)
        if not vm or self.busy:
            return
        if vm['power'] != 'poweredOff':
            messagebox.showinfo('VM must be powered off', 'Shut down this VM normally in VMware, then click Refresh before exporting.')
            return
        folder = Path(self.folder.get())
        if not folder.is_dir():
            messagebox.showerror('Save folder', 'Choose an existing folder.')
            return
        name = self.filename.get().strip()
        try:
            validate_output_name(name)
        except ValueError as error:
            messagebox.showerror('Filename', str(error), parent=self.root)
            return
        target = folder / name
        if target.exists():
            messagebox.showinfo('Choose a new filename', 'Choose a filename that does not already exist. Existing OVA packages are preserved.')
            return
        if target.suffix.lower() != '.ova':
            messagebox.showerror('Filename', 'The filename must end with .ova.')
            return
        if shutil.disk_usage(target.parent).free < 512 * 1024**2:
            messagebox.showerror('Disk space', 'Less than 512 MB is available. Choose another drive.')
            return
        if self.manager.conflicts(self.client.authority, vm['id'], target):
            messagebox.showinfo('Task already exists', 'This VM or output filename already has an unfinished task.')
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

    def poll(self):
        self.root.after_cancel(self.timer)
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == 'certificate':
                    self.authenticate(*payload)
                elif kind == 'connected':
                    self.client, self.machines = payload
                    self.password.set('')
                    self.hide_password()
                    self.remember_connected_profile()
                    self.connect_btn.configure(text='Disconnect')
                    self.connection.set(self.client.authority + ' · ' + self.client.product)
                    self.show_vms()
                    self.set_busy(False)
                    self.show_step(2)
                    self.status.set('Connected. Select a powered-off VM.')
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
                    self.owner.add_job(job)
                    self.set_busy(False)
                    self.destroy_wizard()
                    return
                elif kind == 'error':
                    self.password.set('')
                    self.hide_password()
                    self.login_identity = None
                    self.set_busy(False)
                    self.status.set('Operation failed: ' + payload)
                    self.append_log(payload)
        except queue.Empty:
            pass
        if not self.closed:
            self.refresh_wheel()
            self.timer = self.root.after(100, self.poll)

    def close(self):
        if self.busy:
            messagebox.showinfo('Operation in progress', 'Wait for the connection or task registration to finish.', parent=self.root)
            return
        self.destroy_wizard()

    def destroy_wizard(self):
        if self.closed:
            return
        self.closed = True
        self.password.set('')
        self.hide_password()
        self.login_identity = None
        self.username.set('')
        self.address.set('')
        self.root.after_cancel(self.timer)
        if self.client:
            threading.Thread(target=self.client.logout, daemon=True).start()
        self.owner.wizard = None
        self.root.destroy()

