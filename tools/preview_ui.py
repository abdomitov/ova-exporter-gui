"""Isolated UI demo. No network, subprocesses, credentials, or settings I/O.

Run from the project root: python tools/preview_ui.py
All hosts below use documentation-only IP ranges. Never import real user data.

Views:   --connect  --inventory  --no-results  --destination  --settings
States:  --empty  --missing-tool  --error-state  --log  --exit-dialog
         --update-available  --update-ready  --animate
Look:    --dark  --light  --size 960x600
"""
import math
import socket
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))


def blocked(*args, **kwargs):
    raise RuntimeError('The UI preview blocks network, subprocess, and persistent settings access.')


socket.socket.connect = blocked
socket.socket.connect_ex = blocked
socket.create_connection = blocked
subprocess.Popen = blocked

import app as application  # noqa: E402 - offline guards must be installed before app imports
from connection_settings import ConnectionSettings  # noqa: E402
from secure_storage import WindowsDataProtection  # noqa: E402

ConnectionSettings.__init__ = blocked
WindowsDataProtection.protect = blocked
WindowsDataProtection.unprotect = blocked
import export_flow  # noqa: E402 - apply the guards before loading application modules
export_flow.probe = blocked
export_flow.VSphere = blocked


class MemorySettings:
    directory = Path('PREVIEW-NO-SETTINGS')

    def migrate_legacy(self):
        return []

    def profiles(self):
        return [dict(address='192.0.2.10', username='root'),
                dict(address='vcenter.example.test', username='administrator@vsphere.local')]

    def trusted_pin(self, address):
        return None

    def clear_all(self):
        return None


class DemoClient:
    product = 'VMware ESXi (illustrative inventory)'
    cookie = ''

    def __init__(self, address):
        self.authority = address

    def logout(self):
        pass


def machine(index, name, power='poweredOff', cpu='4', ram='8192', disk=80):
    return dict(id=f'demo-{index}', name=name, power=power, cpu=cpu, ram=ram,
                capacity=disk * 1024**3, path=f'[Demo] {name}/{name}.vmx')


INVENTORY = [
    machine(20, 'Atlas Maps'), machine(21, 'Build Worker', cpu='8', ram='16384', disk=120),
    machine(22, 'Analytics Archive', cpu='2', ram='4096', disk=400), machine(23, 'Lab Gateway', cpu='2', ram='2048', disk=20),
    machine(24, 'Example Database', 'poweredOn', cpu='8', ram='32768', disk=250),
]


class PreviewApp(application.App):
    def __init__(self, root):
        super().__init__(root, settings=MemorySettings(), remember_theme=False,
                         tool_store=False, tool_locator=lambda base, selected=None: Path(sys.executable),
                         update_checks=False)
        root.title('OVA Exporter GUI — FAKE DATA PREVIEW')
        self.manager.start = blocked
        self.manager.export = blocked
        self.settings_view.tool_download.configure(command=self.preview_notice)
        self.settings_view.tool_browse.configure(command=self.preview_notice)
        self.queue.folder_button.configure(command=self.preview_notice)
        flow = self.flow
        flow.folder.set('D:/Exports')
        flow.connect = self.connect_fake
        flow.connect_btn.configure(command=self.connect_fake)
        flow.export = self.preview_notice
        flow.export_btn.configure(command=self.preview_notice)
        flow.browse = self.preview_notice
        flow.browse_btn.configure(command=self.preview_notice)
        flow.update_space = lambda: flow.space.set('412.6 GB free in this folder\'s drive.')
        self.jobs = []
        for index, (name, host, phase, percent) in enumerate([
            ('Atlas Maps', '192.0.2.10', 'running', 46),
            ('Build Worker', '198.51.100.20', 'running', 23),
            ('Analytics Archive', '203.0.113.30', 'done', 100),
            ('Lab Gateway', '192.0.2.10', 'queued', 0),
        ]):
            job = self.manager.add(DemoClient(host), machine(index, name), Path('D:/Exports') / (name.replace(' ', '-') + '.ova'))
            self.jobs.append(job)
            self.queue.add(job)
            if phase != 'queued':
                job.state = 'running'
                self.queue.handle(job.id, 'running', None)
                for point in range(1, percent+1):
                    speed = (36 + 10*math.sin(point/4) + 4*math.cos(point/2)) * 1_000_000
                    self.queue.handle(job.id, 'progress', point)
                    self.queue.handle(job.id, 'sample', dict(speed=speed, bytes=int(point*240_000_000), elapsed=point*7))
                if phase == 'done':
                    job.state = 'done'
                    self.queue.handle(job.id, 'done', '3 file checksums verified. Example package saved.')
            job.log_lines.extend(['Fake-data preview. No real export has been started.',
                                  f'VM: {name}', f'Source: {host}', 'Export preflight: illustrative only'])
        self.queue.select(self.jobs[0].id)
        self.caption.set('FAKE DATA PREVIEW. Network access and OVF Tool execution are blocked.')
        if '--skip-check' in sys.argv:
            root.geometry(self.size())
            root.after(200, self.apply_flags)
        else:
            root.after(500, self.self_check)

    def connect_fake(self):
        self.flow.emit('connected', (DemoClient('192.0.2.10'), [dict(vm) for vm in INVENTORY]))

    def self_check(self):
        """Exercise presentation only: every view, both themes and the smallest window."""
        root, queue, flow = self.root, self.queue, self.flow
        root.update_idletasks()
        assert len(queue.cards) == 4
        assert queue.panel.canvas.find_withtag('progress_fill')
        assert queue.panel.canvas.find_withtag('speed_history')
        counts = queue.counts()
        assert (counts['active'], counts['queued'], counts['done']) == (2, 1, 1)
        assert '3' in self.nav['queue']['text']
        original = self.theme.mode
        for mode in ('dark', 'light'):
            self.theme.set_mode(mode)
            assert queue.panel.colors == self.theme.colors
        root.geometry('960x600')
        root.update()
        assert queue.list.canvas.winfo_width() > 200
        assert queue.panel.canvas.winfo_width() > 300
        assert self.footer.winfo_ismapped()
        queue.show_tab('log')
        root.update_idletasks()
        assert 'Fake-data preview' in queue.log_text.get('1.0', 'end')
        queue.show_tab('transfer')
        self.show('settings')
        root.update_idletasks()
        assert self.settings_view.winfo_ismapped() and not queue.winfo_ismapped()
        assert str(self.settings_view.tool_browse['state']) == 'disabled'  # Unfinished fake tasks lock it.
        self.new_download()
        root.update_idletasks()
        assert self.current == 'new' and flow.step == 1
        assert flow.password.get() == ''
        assert flow.password_entry['show'] == '\u2022'
        assert not flow.remember_connection.get()
        assert flow.password_entry.bind('<Return>')
        assert len(flow.saved_buttons) == 2
        flow.connect()
        self.poll()
        assert flow.step == 2
        assert len(flow.tree.get_children()) == 4  # Running VM is filtered out.
        assert str(flow.continue_btn['state']) == 'disabled'
        flow.tree.selection_set('demo-20')
        flow.selection_changed()
        flow.show_step(3)
        assert flow.step == 3 and flow.filename.get() == 'Atlas Maps.ova'
        flow.disconnect()
        assert flow.step == 1 and not flow.active
        self.show('queue')
        root.geometry(self.size())
        self.theme.set_mode(original)
        print('PASS: fake queue, transfer panel and log; settings; new-export steps; two themes; minimum window', flush=True)
        self.apply_flags()

    @staticmethod
    def size():
        return sys.argv[sys.argv.index('--size') + 1] if '--size' in sys.argv else '1180x760'

    def apply_flags(self):
        flags, flow = set(sys.argv), self.flow
        if '--dark' in flags or '--light' in flags:
            self.theme.set_mode('dark' if '--dark' in flags else 'light')
        if '--check' in flags:
            self.finish_close()
            return
        if '--missing-tool' in flags or '--empty' in flags:
            self.queue.clear()
            self.manager.jobs.clear()
            self.manager.waiting.clear()
            if '--missing-tool' in flags:
                self.tool_locator = lambda *args: None
            self.refresh_tool()
        elif '--error-state' in flags:
            job = self.jobs[0]
            job.state = 'failed'
            self.queue.handle(job.id, 'failed',
                'Illustrative failure: OVF Tool exited with code 1. The server did not release the export lease. '
                'Review the VM state with your administrator before retrying. Partial files remain marked .incomplete.')
        elif '--log' in flags:
            self.queue.show_tab('log')
        elif '--settings' in flags:
            self.show('settings')
        elif flags & {'--connect', '--inventory', '--no-results', '--destination'}:
            self.new_download()
            if '--connect' not in flags:
                flow.connect()
                self.poll()
                if '--no-results' in flags:
                    flow.search.set('Example not found')
                else:
                    flow.tree.selection_set('demo-20')
                    flow.selection_changed()
                    if '--destination' in flags:
                        flow.show_step(3)
        elif '--exit-dialog' in flags:
            self.show_exit_choices()
        elif '--update-available' in flags or '--update-ready' in flags:
            from updates import Release, REPOSITORY
            self.updater.release = Release('9.0.0', f'https://github.com/{REPOSITORY}/releases/tag/v9.0.0',
                                           '', '', 'fake-installer.exe', 10, '', True, 'Fake release')
            self.updater.download = lambda *args: self.preview_notice()
            self.updater.install = self.preview_notice
            if '--update-ready' in flags:
                self.updater.ready = (Path('FAKE-NOT-AN-INSTALLER'), '0'*64)
                self.updater.show_ready()
            else:
                self.updater.show_offer()
            self.updater.dialog.title('Update prompt — FAKE DATA PREVIEW')
            self.updater.dialog.protocol('WM_DELETE_WINDOW', self.finish_close)
            self.updater.dialog.bind('<Escape>', lambda event: self.finish_close())
        if '--animate' in flags:
            self.animate()

    def animate(self):
        """Exercise real UI event handling with bounded synthetic progress."""
        for job in self.jobs:
            view = self.queue.cards[job.id]
            if view.state != 'running':
                continue
            percent = min(100, view.percent+0.15)
            speed = (32+12*math.sin(percent/2))*1_000_000
            self.emit('job', (job.id, 'progress', percent))
            self.emit('job', (job.id, 'sample', dict(speed=speed, bytes=int(percent*240_000_000),
                                                    elapsed=view.elapsed+0.125)))
            if percent >= 100:
                job.state = 'done'
                self.emit('job', (job.id, 'done', 'Illustrative package completed. No file was created.'))
        self.root.after(125, self.animate)

    def preview_notice(self, *args, **kwargs):
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
