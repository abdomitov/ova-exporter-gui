"""Application shell: navigation rail, the three views, task actions and lifecycle."""
import queue
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from branding import set_icon
from connection_settings import ConnectionSettings
from export_flow import ExportFlow
from jobs import JobManager
from metadata import APP_NAME, VERSION
from project_paths import ROOT
from queue_view import QueueView
from scrolling import install_mousewheel
from settings_view import SettingsView
from theme import ThemeManager
from tool_paths import find_ovftool, ToolLocation, tool_file_exists
from update_ui import UpdateUI

BASE = ROOT
STOP_WARNING = ('Interrupting an export may leave the VM locked on ESXi and unable to power on or export again. '
                'An administrator may need to restart hostd, which can affect host management and other tasks.\n\n'
                'Any partial OVA remains incomplete and cannot be resumed. The app will not restart ESXi services.')
VIEWS = (('queue', 'Exports'), ('new', 'New export'), ('settings', 'Settings'))


class App:
    def __init__(self, root, *, settings=None, remember_theme=True, tool_store=None, tool_locator=None,
                 update_checks=True):
        self.root = root
        self.events = queue.Queue()
        self.close_mode = None
        self.exit_dialog = None
        self.current = None
        self.settings = settings if settings is not None else ConnectionSettings()
        self.settings_error = ''
        try:
            self.settings.migrate_legacy()
        except (OSError, ValueError) as error:
            self.settings_error = str(error)
        root.title(f'{APP_NAME} {VERSION}')
        set_icon(root)
        root.geometry(f'{max(1080, min(1200, root.winfo_screenwidth() - 80))}x'
                      f'{max(660, min(780, root.winfo_screenheight() - 100))}')
        root.minsize(1080, 660)
        directory = getattr(self.settings, 'directory', None)
        preference = directory / 'appearance.json' if remember_theme and isinstance(directory, Path) else None
        self.tool_store = (ToolLocation(directory) if isinstance(directory, Path) else None) if tool_store is None else tool_store or None
        self.tool_locator = tool_locator or find_ovftool
        self.selected_tool = None
        self.tool_storage_error = ''
        if self.tool_store is not None:
            try:
                self.selected_tool = self.tool_store.read()
            except (OSError, ValueError, TypeError, UnicodeError):
                self.tool_storage_error = 'Saved tool location could not be read; select it again in Settings.'
        self.theme = ThemeManager(root, preference)
        px = self.theme.px
        self.caption = tk.StringVar(value=self.tool_storage_error)
        self.tool_status = tk.StringVar()
        self.tool_ready = False
        self.tool_path = self.tool_locator(BASE, self.selected_tool)
        self.manager = JobManager(self.tool_path or BASE / 'ovftool' / 'ovftool.exe', self.emit)

        root.columnconfigure(1, weight=1)
        root.rowconfigure(0, weight=1)

        # Navigation rail.
        rail = self.theme.panel(root, tone='rail', width=px(232))
        self.rail = rail
        rail.grid(row=0, column=0, sticky='ns')
        rail.pack_propagate(False)
        brand = ttk.Frame(rail, style='Rail.TFrame', padding=(px(20), px(24), px(18), px(22)))
        brand.pack(fill='x')
        logo = getattr(root, '_ova_logo', None)
        self.brand_icon = logo.subsample(max(1, logo.width() // px(34))) if logo else None
        if self.brand_icon:
            ttk.Label(brand, image=self.brand_icon, style='Rail.TLabel').pack(side='left', padx=(0, px(12)))
        names = ttk.Frame(brand, style='Rail.TFrame')
        names.pack(side='left')
        ttk.Label(names, text='OVA Exporter', style='Brand.Rail.TLabel').pack(anchor='w')
        ttk.Label(names, text='for VMware OVF Tool', style='Small.Rail.TLabel').pack(anchor='w')
        self.nav = {}
        self.nav_labels = dict(VIEWS)
        for name, label in VIEWS:
            button = ttk.Button(rail, text='  ' + label, style='Nav.TButton', compound='left',
                                command=lambda name=name: self.navigate(name))
            button.pack(fill='x', padx=px(12), pady=(0, px(4)))
            self.nav[name] = button
        foot = ttk.Frame(rail, style='Rail.TFrame', padding=(px(14), 0, px(14), px(16)))
        foot.pack(side='bottom', fill='x')
        card = ttk.Frame(foot, style='RailCard.TFrame', padding=(px(14), px(12)))
        card.pack(fill='x')
        self.tool_label = ttk.Label(card, style='RailCard.TLabel',
                                    compound='left', font=self.theme.font('body', 10, 'bold'))
        self.tool_label.pack(anchor='w')
        self.tool_hint = ttk.Label(card, style='Small.RailCard.TLabel', wraplength=px(170))
        self.tool_hint.pack(anchor='w', pady=(3, 0))
        row = ttk.Frame(foot, style='Rail.TFrame')
        row.pack(fill='x', pady=(px(12), 0))
        self.theme_button = ttk.Button(row, command=self.toggle_theme, style='Rail.TButton')
        self.theme_button.pack(side='left')
        ttk.Label(row, text=f'v{VERSION}', style='Small.Rail.TLabel').pack(side='right')

        # Main area: one view at a time above a single status line.
        gutter = self.theme.card_margin[0]
        main = ttk.Frame(root, padding=(px(30) - gutter, px(26), px(30) - gutter, px(14)))
        self.main = main
        main.grid(row=0, column=1, sticky='nsew')
        main.columnconfigure(0, weight=1)
        main.rowconfigure(0, weight=1)
        self.queue = QueueView(main, self.new_download, self.cancel_job, open_settings=lambda: self.show('settings'),
                               on_summary=self.queue_changed, notify=self.caption.set, theme=self.theme)
        self.flow = ExportFlow(main, self)
        self.updater = UpdateUI(self, directory if isinstance(directory, Path) else None, enabled=update_checks)
        self.settings_view = SettingsView(main, self)
        self.views = {'queue': self.queue, 'new': self.flow, 'settings': self.settings_view}
        footer = ttk.Frame(main)
        self.footer = footer
        footer.grid(row=1, column=0, sticky='ew', pady=(px(6), 0), padx=gutter)
        footer.columnconfigure(0, weight=1)
        self.caption_label = ttk.Label(footer, textvariable=self.caption, style='Small.TLabel', wraplength=px(560))
        self.caption_label.grid(row=0, column=0, sticky='w')
        ttk.Label(footer, text='Passwords are never saved', style='Small.TLabel').grid(row=0, column=1, sticky='e', padx=(12, 0))
        main.bind('<Configure>', lambda event: self.caption_label.configure(wraplength=max(px(220), event.width - px(260))), add='+')

        self.theme.register(self)
        self.refresh_tool()
        self.show('queue')
        self.refresh_wheel = install_mousewheel(root)
        root.protocol('WM_DELETE_WINDOW', self.close)
        for key in ('<Control-n>', '<Control-N>'):
            root.bind(key, lambda event: self.new_download())
        for index, (name, _) in enumerate(VIEWS, 1):
            root.bind(f'<Control-Key-{index}>', lambda event, name=name: self.navigate(name))
        for key in ('<Control-f>', '<Control-F>'):
            root.bind(key, self.flow.focus_search)
        root.bind('<F5>', lambda event: self.flow.refresh() if self.current == 'new' and self.flow.step == 2 else None)
        self.timer = root.after(100, self.poll)

    # -- appearance and navigation ----------------------------------------
    def apply_theme(self, colors):
        self.theme_button.configure(text='Light theme' if self.theme.mode == 'dark' else 'Dark theme')
        self.paint_navigation()

    def paint_navigation(self):
        icons = {'queue': 'exports', 'new': 'new', 'settings': 'settings'}
        for key, button in self.nav.items():
            active = key == self.current
            normal, lit = (self.theme.assets.get('nav_' + icons[key] + suffix) for suffix in ('', '_hover'))
            button.configure(style='NavActive.TButton' if active else 'Nav.TButton',
                             image=(lit,) if active else (normal, 'active', lit))
        self.tool_label.configure(image=self.theme.assets.get('dot_positive' if self.tool_ready else 'dot_negative'))

    def toggle_theme(self):
        self.theme.toggle()

    def navigate(self, name):
        if name == 'new':
            self.new_download()
        else:
            self.show(name)

    def show(self, name):
        if name == self.current:
            return
        self.current = name
        for key, view in self.views.items():
            if key == name:
                view.grid(row=0, column=0, sticky='nsew')
            else:
                view.grid_remove()
        self.paint_navigation()
        self.queue.set_active(name == 'queue')
        if name == 'settings':
            self.refresh_tool()

    def queue_changed(self, counts):
        waiting = counts['active'] + counts['queued']
        self.nav['queue'].configure(text=f'  Exports   {waiting}' if waiting else '  Exports')

    def session_changed(self):
        self.settings_view.refresh_session()

    def emit(self, kind, payload):
        self.events.put((kind, payload))

    # -- OVF Tool location --------------------------------------------------
    def refresh_tool(self):
        busy = bool(self.manager.unfinished())
        path = self.manager.tool if busy else self.tool_locator(BASE, self.selected_tool)
        ready = tool_file_exists(path)
        self.tool_ready = ready
        self.tool_path = Path(path) if path else None
        if not busy:
            self.manager.tool = self.tool_path or BASE / 'ovftool' / 'ovftool.exe'
        self.tool_status.set('OVF Tool ready' if ready else 'OVF Tool missing')
        self.tool_label.configure(text='  ' + self.tool_status.get(),
                                  style='Success.RailCard.TLabel' if ready else 'Error.RailCard.TLabel')
        self.tool_hint.configure(text='Exports are available.' if ready else 'Set its location in Settings to enable exports.')
        self.paint_navigation()
        self.queue.set_tool_ready(ready)
        self.settings_view.refresh_tool(ready, self.tool_path, busy)
        return ready

    def choose_tool(self):
        if self.manager.unfinished():
            messagebox.showinfo('Exports active', 'Wait for all tasks to finish before changing OVF Tool.', parent=self.root)
            return
        chosen = filedialog.askopenfilename(parent=self.root, title='Select ovftool.exe in its installation folder',
                    filetypes=[('VMware OVF Tool', 'ovftool.exe')],
                    initialdir=str(self.tool_path.parent) if self.tool_path and self.tool_path.parent.is_dir() else None)
        if not chosen:
            return
        path = Path(chosen)
        if path.name.casefold() != 'ovftool.exe' or not path.is_file():
            messagebox.showerror('Invalid tool', 'Select the official ovftool.exe and leave its supporting DLLs/folders in place.', parent=self.root)
            return
        self.selected_tool = path
        self.save_tool_location(path)
        self.refresh_tool()

    def save_tool_location(self, path):
        if self.tool_store is not None:
            try:
                self.tool_store.save(path)
            except (OSError, ValueError) as error:
                messagebox.showwarning('Location not saved', 'The tool is available for this session, but its location could not be saved: ' + str(error), parent=self.root)

    def auto_tool(self):
        if self.manager.unfinished():
            return
        self.selected_tool = None
        self.save_tool_location(None)
        self.refresh_tool()

    # -- tasks --------------------------------------------------------------
    def new_download(self):
        if self.close_mode:
            self.root.bell()
            return
        if not self.refresh_tool():
            self.show('settings')
            messagebox.showerror('VMware OVF Tool is required', 'Install VMware OVF Tool, then click Auto-detect in Settings. For a custom folder, click Locate ovftool.exe and select it. Keep its supporting files together.', parent=self.root)
            return
        self.show('new')
        self.flow.show_step(self.flow.step)

    def add_job(self, job):
        self.queue.add(job, select=True)
        self.refresh_wheel()
        self.manager.start(job)
        self.refresh_tool()
        self.show('queue')

    def cancel_job(self, job_id):
        job = self.manager.jobs[job_id]
        if job.can_force_stop:
            if messagebox.askyesno('Force stop this local export tool?',
                    job.vm['name'] + ' · ' + job.client.authority + '\n\n' + STOP_WARNING +
                    '\n\nThis ends only this task\'s local OVF Tool process. Server cleanup cannot be confirmed.\n\nForce stop anyway?',
                    parent=self.root, default=messagebox.NO):
                self.manager.force_stop(job_id, confirmed=True)
            return
        if not job.can_request_cancel:
            return
        remote = job.state == 'running'
        description = (STOP_WARNING + '\n\nRequest cancellation anyway? OVF Tool may take time to stop or become stuck.' if remote else
                       'Remove this queued export before it starts?' if job.state == 'queued' else
                       'Stop the local checksum scan? The server transfer has already ended. '
                       'The package will remain marked .incomplete and unverified.')
        if messagebox.askyesno('Cancel active export?' if remote else 'Cancel task?',
                               job.vm['name'] + '\n\n' + description, parent=self.root, default=messagebox.NO):
            if not self.manager.cancel(job_id, allow_remote=remote):
                messagebox.showinfo('Task state changed', 'This task has started transferring or has finished. '
                                    'No cancellation request was sent.', parent=self.root)

    def poll(self):
        # Keep input/paint callbacks responsive even if workers emit a burst.
        # Samples change presentation only; locating the tool belongs to task
        # transitions and explicit user actions, not every progress update.
        self.root.after_cancel(self.timer)
        deadline = time.perf_counter() + 0.008
        refresh_tool = False
        try:
            for _ in range(128):
                kind, payload = self.events.get_nowait()
                if kind == 'job':
                    self.queue.handle(*payload, defer=True)
                    refresh_tool |= payload[1] not in ('sample', 'progress', 'status')
                elif kind == 'update':
                    self.updater.handle(*payload)
                if time.perf_counter() >= deadline:
                    break
        except queue.Empty:
            pass
        self.queue.flush_updates()
        self.flow.poll()
        if refresh_tool:
            self.refresh_tool()
        if self.close_mode and self.exit_dialog is None and (self.manager.local_tools_stopped() if self.close_mode == 'force' else not self.manager.unfinished()):
            self.finish_close()
            return
        waiting = not self.events.empty() or not self.flow.events.empty()
        delay = 10 if waiting else 100 if self.manager.unfinished() or self.updater.downloading or self.flow.busy else 400
        self.timer = self.root.after(delay, self.poll)

    # -- closing --------------------------------------------------------------
    def close(self):
        if self.updater.downloading:
            messagebox.showinfo('Update downloading', 'Wait for the app update download to finish before closing.', parent=self.root)
            return
        if self.flow.busy:
            messagebox.showinfo('Operation in progress', 'Wait for the connection or task registration to finish.', parent=self.root)
            return
        if self.manager.unfinished():
            self.show_exit_choices()
            return
        self.finish_close()

    def show_exit_choices(self):
        if self.exit_dialog and self.exit_dialog.winfo_exists():
            self.exit_dialog.lift()
            return
        px = self.theme.px
        dialog = tk.Toplevel(self.root)
        self.exit_dialog = dialog
        dialog.title('Export tasks are still active')
        dialog.transient(self.root)
        dialog.resizable(True, False)
        dialog.minsize(px(600), 1)
        frame = ttk.Frame(dialog, padding=px(28))
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='Choose how to close the app', style='Title.TLabel').pack(anchor='w')
        jobs = self.manager.unfinished()
        tasks = '\n'.join(job.vm['name'] + ', from ' + job.client.authority for job in jobs[:5])
        if len(jobs) > 5:
            tasks += '\n…and ' + str(len(jobs) - 5) + ' more tasks'
        ttk.Label(frame, text=tasks, wraplength=px(550)).pack(anchor='w', pady=(px(10), px(12)))
        ttk.Label(frame, text=STOP_WARNING, wraplength=px(516), style='Page.Notice.TLabel').pack(anchor='w', fill='x')
        ttk.Label(frame, text='Cancel and wait lets OVF Tool attempt cleanup. It can stall. Force stop and exit '
                  'ends only this app\'s local tools; server cleanup remains unconfirmed.',
                  wraplength=px(550), style='Muted.TLabel').pack(anchor='w', pady=(px(12), px(18)))

        def dismiss():
            self.exit_dialog = None
            dialog.destroy()

        def keep_open():
            self.close_mode = None
            self.manager.resume_submissions()
            self.caption.set('App kept open. Any cancellation already requested will continue.')
            dismiss()

        def stop(force):
            self.close_mode = 'force' if force else 'wait'
            self.caption.set('Stopping local export tools before exit. Server cleanup is unconfirmed.' if force else
                             'Cancellation requested. The app will close when tasks and cleanup checks finish; close the window again for other options.')
            self.flow.disconnect()
            self.manager.stop_all(force=force, confirmed=True)
            dismiss()
        buttons = ttk.Frame(frame)
        buttons.pack(fill='x')
        keep = ttk.Button(buttons, text='Keep app open', style='Accent.TButton', command=keep_open)
        keep.pack(side='left')
        ttk.Button(buttons, text='Cancel and wait', command=lambda: stop(False)).pack(side='left', padx=8)
        ttk.Button(buttons, text='Force stop and exit', style='Danger.TButton', command=lambda: stop(True)).pack(side='right')
        dialog.protocol('WM_DELETE_WINDOW', keep_open)
        dialog.bind('<Escape>', lambda event: keep_open())
        dialog.grab_set()
        keep.focus_set()

        def center():
            if dialog.winfo_exists():
                dialog.update_idletasks()
                x = self.root.winfo_rootx() + (self.root.winfo_width() - dialog.winfo_reqwidth()) // 2
                y = self.root.winfo_rooty() + (self.root.winfo_height() - dialog.winfo_reqheight()) // 3
                dialog.geometry(f'+{max(0, x)}+{max(0, y)}')
        dialog.after_idle(center)

    def finish_close(self):
        if self.exit_dialog and self.exit_dialog.winfo_exists():
            self.exit_dialog.destroy()
            self.exit_dialog = None
        self.flow.shutdown()
        self.root.after_cancel(self.timer)
        self.root.destroy()


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == '__main__':
    main()
