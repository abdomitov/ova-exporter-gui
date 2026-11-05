"""Isolated UI demo. No network, subprocesses, credentials, or settings I/O.

Run from the project root: python tools/preview_ui.py
All hosts below use documentation-only IP ranges. Never import real user data.
"""
import math
import socket
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def blocked(*args, **kwargs):
    raise RuntimeError('The UI preview blocks network, subprocess, and persistent settings access.')


socket.socket.connect = blocked
socket.socket.connect_ex = blocked
socket.create_connection = blocked
subprocess.Popen = blocked

import app as application
from connection_settings import ConnectionSettings
from secure_storage import WindowsDataProtection

ConnectionSettings.__init__ = blocked
WindowsDataProtection.protect = blocked
WindowsDataProtection.unprotect = blocked
import wizard
wizard.probe = blocked
wizard.VSphere = blocked


class MemorySettings:
    directory = Path('PREVIEW-NO-SETTINGS')

    def migrate_legacy(self):
        return []

    def profiles(self):
        return []

    def trusted_pin(self, address):
        return None

    def clear_all(self):
        return None


class DemoClient:
    product = 'VMware ESXi · illustrative inventory'
    cookie = ''

    def __init__(self, address):
        self.authority = address

    def logout(self):
        pass


def machine(index, name, power='poweredOff'):
    return dict(id=f'demo-{index}', name=name, power=power, cpu='4', ram='8192',
                capacity=80 * 1024**3, path='[Demo] example.vmx')


class PreviewApp(application.App):
    def __init__(self, root):
        super().__init__(root, settings=MemorySettings(), remember_theme=False)
        root.title('OVA Exporter GUI — FAKE DATA PREVIEW')
        self.manager.start = blocked
        self.manager.export = blocked
        self.jobs = []
        for index, (name, host, phase, percent) in enumerate([
            ('Atlas Maps', '192.0.2.10', 'running', 46),
            ('Build Worker', '198.51.100.20', 'running', 23),
            ('Analytics Archive', '203.0.113.30', 'done', 100),
            ('Lab Gateway', '192.0.2.10', 'queued', 0),
        ]):
            job = self.manager.add(DemoClient(host), machine(index, name), Path('D:/Exports') / (name.replace(' ', '-') + '.ova'))
            self.jobs.append(job)
            self.dashboard.add(job)
            if phase != 'queued':
                job.state = 'running'
                self.dashboard.handle(job.id, 'running', None)
                for point in range(1, percent+1):
                    speed = (36 + 10*math.sin(point/4) + 4*math.cos(point/2)) * 1_000_000
                    self.dashboard.handle(job.id, 'progress', point)
                    self.dashboard.handle(job.id, 'sample', dict(speed=speed, bytes=int(point*240_000_000), elapsed=point*7))
                if phase == 'done':
                    job.state = 'done'
                    self.dashboard.handle(job.id, 'done', '3 manifest checksums verified. Example package saved.')
            job.log_lines.append('Fake-data preview. No real export has been started.')
        self.dashboard.tree.selection_set(self.jobs[0].id)
        self.dashboard.selection_changed()
        self.caption.set('FAKE DATA PREVIEW · Network and OVF Tool execution are blocked.')
        root.after(500, self.self_check)

    def self_check(self):
        """Exercise presentation only, including the narrow layout and both themes."""
        self.root.update_idletasks()
        assert len(self.dashboard.cards) == 4
        assert self.dashboard.panel.canvas.find_withtag('progress_fill')
        assert self.dashboard.panel.canvas.find_withtag('speed_history')
        assert self.dashboard.metrics[0].get() == '3'
        assert self.dashboard.metrics[1].get() == '1'
        original = self.theme.mode
        for mode in ('light', 'dark'):
            self.theme.mode = mode
            self.theme.apply()
            assert self.dashboard.panel.colors == self.theme.colors
        self.root.geometry('640x420')
        self.root.update()
        self.resize_layout()
        self.root.update_idletasks()
        assert self.root.winfo_width() == 640
        assert self.root.winfo_height() == 420
        assert self.dashboard.tree.winfo_width() > 300
        assert not self.dashboard.metrics_row.winfo_manager()
        assert self.footer.winfo_ismapped()
        assert self.dashboard.summary_label.winfo_ismapped()
        assert self.dashboard.tree.winfo_height() >= 70
        assert tuple(self.dashboard.tree['displaycolumns']) == ('server','vm','progress','status','speed')
        self.root.geometry('1120x780')
        self.root.update()
        self.resize_layout()
        self.root.update_idletasks()
        assert self.dashboard.metrics_row.winfo_manager() == 'pack'
        self.new_download()
        form = self.wizard
        form.root.geometry('600x420')
        self.root.update_idletasks()
        assert form.step == 1
        assert form.password.get() == ''
        assert form.login_entries[2]['show'] == '\u2022'
        assert not form.remember_connection.get()
        assert form.login_entries[2].bind('<Return>')
        for mode in ('light', 'dark'):
            self.theme.mode = mode
            self.theme.apply()
            self.root.update_idletasks()
            assert form.password_icons
        form.connect()
        form.poll()
        assert form.step == 2
        assert len(form.tree.get_children()) == 4  # Running VM is filtered out.
        form.destroy_wizard()
        self.theme.mode = original
        self.theme.apply()
        print('PASS: fake dashboard + wizard; two themes; graph; statistics; narrow layouts; keyboard binding; powered-off filter', flush=True)
        if '--check' in sys.argv:
            self.finish_close()
        elif '--compact' in sys.argv:
            self.root.geometry('640x420')
        elif '--wizard-connect' in sys.argv or '--wizard-selection' in sys.argv:
            self.new_download()
            self.wizard.root.geometry('740x620')
            if '--wizard-selection' in sys.argv:
                self.wizard.connect()

    def new_download(self):
        super().new_download()
        wizard = self.wizard
        if not wizard:
            return
        wizard.root.title('New export — FAKE DATA PREVIEW')
        wizard.folder.set('D:/Exports')
        def connect_fake():
            wizard.emit('connected', (DemoClient('192.0.2.10'), [
                machine(20, 'Atlas Maps'), machine(21, 'Build Worker'),
                machine(22, 'Analytics Archive'), machine(23, 'Lab Gateway'),
                machine(24, 'Example Database', 'poweredOn'),
            ]))
        wizard.connect = connect_fake
        wizard.connect_btn.configure(command=connect_fake)
        wizard.export = self.preview_notice
        wizard.export_btn.configure(command=self.preview_notice)
        wizard.browse = self.preview_notice

    def preview_notice(self, *args):
        messagebox.showinfo('Fake-data preview', 'This preview cannot start exports or save data.', parent=self.root)

    def cancel_job(self, job_id):
        self.preview_notice()

    def close(self):
        self.finish_close()


def main():
    root = tk.Tk()
    failures = []
    if '--check' in sys.argv:
        def fail_check(kind, value, trace):
            import traceback
            traceback.print_exception(kind, value, trace)
            failures.append(value)
            root.destroy()
        root.report_callback_exception = fail_check
    PreviewApp(root)
    root.mainloop()
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
