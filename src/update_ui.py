"""Tk update workflow. Workers communicate through the app's event queue."""
from pathlib import Path
import os
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk
import webbrowser

from metadata import VERSION
from updates import UpdateClient, UpdatePreferences, verify_installer


def installed_app_directory():
    """A source checkout/portable build must retain the normal first-install UI."""
    directory = Path(sys.executable).resolve().parent
    return directory if (getattr(sys, 'frozen', False)
                         and (directory / 'unins000.exe').is_file()) else None


def installer_command(path):
    directory = installed_app_directory()
    if directory is None:
        return [str(path), '/SP-']
    # Keep error dialogs and a progress window. Do not close other instances,
    # suppress security prompts, or permit an unattended machine restart.
    return [str(path), '/SP-', '/SILENT', '/NORESTART', '/OVAUPDATE=1',
            f'/OVAPID={os.getpid()}', f'/DIR={directory}']


class UpdateUI:
    def __init__(self, app, directory=None, *, enabled=True, client=None):
        self.app, self.root = app, app.root
        self.client = client or UpdateClient()
        if not enabled:
            directory = None  # Fake previews/tests must not even read real preferences.
        self.preferences = UpdatePreferences(directory)
        self.directory = Path(directory) / 'updates' if directory is not None else None
        self.enabled = enabled and self.directory is not None
        self.checking = self.downloading = self.launching = False
        self.release = self.ready = self.dialog = None
        self.install_after_download = False
        self.automatic = tk.BooleanVar(value=self.preferences.automatic)
        self.menu = tk.Menu(self.root, tearoff=False)
        self.menu.add_command(label='Check for updates…', command=lambda: self.check(manual=True),
                              state='normal' if self.enabled else 'disabled')
        self.menu.add_checkbutton(label='Check automatically at startup', variable=self.automatic,
                                  command=self.toggle_automatic,
                                  state='normal' if self.enabled else 'disabled')
        self.menu.add_separator()
        self.menu.add_command(label='Install downloaded update…', command=self.install, state='disabled')
        self.button = ttk.Menubutton(app.header_actions,text='Updates',menu=self.menu,style='Quiet.TMenubutton')
        self.button.pack(side='left')
        self.app.theme.refresh_windows()
        if self.enabled and self.preferences.due():
            self.root.after(2500, self.check)

    def save_preferences(self):
        try:
            self.preferences.save()
        except OSError:
            self.app.caption.set('Update choices apply this session; they could not be saved.')

    def toggle_automatic(self):
        self.preferences.automatic = self.automatic.get()
        self.save_preferences()

    def check(self, manual=False):
        if not self.enabled or self.app.close_mode:
            return
        if self.downloading:
            if manual:
                messagebox.showinfo('Update downloading', 'The installer is downloading. You can continue exporting.', parent=self.root)
            return
        if self.ready:
            if manual:
                self.show_ready()
            return
        if self.checking or (not manual and not self.preferences.due()):
            return
        self.checking = True
        self.menu.entryconfigure(0, state='disabled')
        if manual:
            self.app.caption.set('Checking GitHub for a newer OVA Exporter GUI release…')
        def worker():
            try:
                release = self.client.check(VERSION, '' if manual else self.preferences.skipped)
                self.app.emit('update', ('checked', (manual, release, None)))
            except Exception:
                self.app.emit('update', ('checked', (manual, None, 'GitHub could not be reached or returned invalid release data. Check your connection and try again later.')))
        threading.Thread(target=worker, daemon=True, name='update-check').start()

    def handle(self, kind, payload):
        if kind == 'checked':
            self.checking = False
            self.menu.entryconfigure(0, state='normal')
            manual, release, error = payload
            if error:
                if manual:
                    self.app.caption.set('Update check failed. Exports remain available.')
                    messagebox.showwarning('Could not check for updates', error, parent=self.root)
                return  # Offline startup must not interrupt the export workflow.
            if release is None:
                if manual:
                    self.app.caption.set('No newer Windows installer is available.')
                    messagebox.showinfo('No update available', 'You are using version ' + VERSION + '. No newer Windows installer is published.', parent=self.root)
                return
            self.release = release
            self.show_offer()
        elif kind == 'progress':
            done, total = payload
            self.app.caption.set(f'Downloading app update · {done / total:.0%} · Export tasks continue normally.')
        elif kind == 'downloaded':
            self.downloading = False
            path, digest, error = payload
            if error:
                self.app.caption.set('Update download failed. Your installed version is unchanged.')
                messagebox.showerror('Update not downloaded', error, parent=self.root)
                return
            self.ready = path, digest
            self.menu.entryconfigure(3, state='normal')
            if self.install_after_download and not self.blocked():
                self.install(confirmed=True)
            else:
                self.show_ready()

    def window(self, title):
        if self.dialog and self.dialog.winfo_exists():
            self.dialog.destroy()
        window = tk.Toplevel(self.root)
        self.dialog = window
        window.title(title)
        window.transient(self.root)
        window.minsize(460, 1)
        window.resizable(True, False)
        frame = ttk.Frame(window, padding=20)
        frame.pack(fill='both', expand=True)
        # Non-modal: an update notification never steals a credential dialog's grab.
        window.bind('<Escape>', lambda event: window.destroy())
        self.app.theme.refresh_windows()
        def center():
            if not window.winfo_exists():
                return
            window.update_idletasks()
            x = self.root.winfo_rootx() + (self.root.winfo_width() - window.winfo_reqwidth()) // 2
            y = self.root.winfo_rooty() + (self.root.winfo_height() - window.winfo_reqheight()) // 2
            window.geometry(f'+{max(0, x)}+{max(0, y)}')
        window.after_idle(center)
        return window, frame

    def show_offer(self):
        release = self.release
        window, frame = self.window('OVA Exporter GUI update available')
        ttk.Label(frame, text=f'Version {release.version} is available', style='Heading.TLabel').pack(anchor='w')
        ttk.Label(frame, text=f'Installed: {VERSION}' + (' · New release: Windows preview' if release.preview else ''),
                  style='Muted.TLabel').pack(anchor='w', pady=(6, 10))
        ttk.Label(frame, text=('Update downloads and verifies the installer, applies the upgrade '
                  'with a progress window, and reopens the app. Your existing folder and '
                  'shortcut choices are retained. ' if installed_app_directory() else
                  'Download the app installer from this project’s GitHub release. ') +
                  'Its SHA-256 checksum is checked before installation. The installer is unsigned. '
                  'VMware OVF Tool is installed and updated separately.', wraplength=490).pack(anchor='w')
        ttk.Label(frame, text='Installation is available after all queued and active export tasks finish.',
                  wraplength=490, style='Warning.TLabel').pack(anchor='w', pady=(10, 12))
        ttk.Button(frame, text='View release notes', command=lambda: webbrowser.open(release.url),
                   style='Quiet.TButton').pack(anchor='w', pady=(0, 14))
        buttons = ttk.Frame(frame)
        buttons.pack(fill='x')
        update = ttk.Button(buttons, text='Update', style='Accent.TButton', command=lambda: self.download(window))
        update.pack(side='left')
        def choose(skip=False):
            if skip:
                self.preferences.skipped = release.version
            else:
                self.preferences.remind_after = time.time() + 86400
            self.save_preferences()
            window.destroy()
        ttk.Button(buttons, text='Remind me later', command=choose).pack(side='left', padx=8)
        ttk.Button(buttons, text='Skip this version', command=lambda: choose(True)).pack(side='left')
        window.protocol('WM_DELETE_WINDOW', choose)
        window.bind('<Escape>', lambda event: choose())
        self.app.theme.refresh_windows()

    def download(self, window=None):
        if self.downloading or self.checking or self.app.close_mode or self.ready:
            return
        if window is not None:
            window.destroy()
        self.downloading = True
        self.install_after_download = installed_app_directory() is not None
        release = self.release
        self.app.caption.set('Downloading the app update. Export tasks continue normally…')
        def worker():
            try:
                path, digest = self.client.download(release, self.directory,
                                  lambda done, total: self.app.emit('update', ('progress', (done, total))))
                self.app.emit('update', ('downloaded', (path, digest, None)))
            except Exception:
                self.app.emit('update', ('downloaded', (None, None,
                              'The installer could not be downloaded and verified. Nothing was installed. '
                              'Check network access and free disk space, then use Updates → Check for updates to retry.')))
        threading.Thread(target=worker, daemon=True, name='update-download').start()

    def blocked(self):
        return bool(self.app.manager.unfinished() or self.app.close_mode
                    or (self.app.wizard and not self.app.wizard.closed))

    def show_ready(self):
        busy = self.blocked()
        self.app.caption.set('App update downloaded and verified. Use Updates → Install downloaded update when exports finish.')
        window, frame = self.window('App update ready')
        ttk.Label(frame, text=f'Version {self.release.version} is ready', style='Heading.TLabel').pack(anchor='w')
        ttk.Label(frame, text=('Finish all export tasks and close the New export window before installing. '
                  'Then choose Updates → Install downloaded update.' if busy else
                  ('Install now updates the app with a progress window and reopens it. '
                   if installed_app_directory() else
                   'Install now closes this app and opens the Windows setup wizard. ') +
                  'Your exports and saved preferences are preserved.'), wraplength=490).pack(anchor='w', pady=12)
        ttk.Label(frame, text='The installer is unsigned; Windows may show a SmartScreen warning.',
                  style='Warning.TLabel', wraplength=490).pack(anchor='w', pady=(0, 12))
        buttons = ttk.Frame(frame)
        buttons.pack(fill='x')
        ttk.Button(buttons, text='Install now', command=lambda: self.install(confirmed=True),
                   state='disabled' if busy else 'normal', style='Accent.TButton').pack(side='left')
        ttk.Button(buttons, text='Later', command=window.destroy).pack(side='left', padx=8)
        self.app.theme.refresh_windows()

    def install(self, *, confirmed=False):
        if not self.ready or self.launching:
            return
        if self.blocked():
            messagebox.showinfo('Finish exports first', 'Finish all queued and active export tasks and close the New export window before installing. No task was stopped.', parent=self.root)
            return
        if not confirmed and not messagebox.askyesno('Install app update?',
                'Close OVA Exporter GUI and install the downloaded update? '
                'This updates the GUI only. VMware OVF Tool remains separate.', parent=self.root, default=messagebox.NO):
            return
        # Recheck after the confirmation (nested Tk loop) before starting setup.
        if self.blocked():
            return
        path, digest = self.ready
        try:
            verify_installer(path, self.release, digest)
            subprocess.Popen(installer_command(path), shell=False)
        except (OSError, ValueError):
            messagebox.showerror('Update could not start', 'The installer could not be verified or opened. Download it again from the project’s GitHub Releases page.', parent=self.root)
            return
        self.launching = True
        self.app.finish_close()
