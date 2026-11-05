"""Application lifecycle and task actions for OVA Exporter GUI."""
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from accordion import install_mousewheel
from connection_settings import ConnectionSettings
from dashboard import Dashboard
from metadata import APP_NAME, VERSION
from theme import ThemeManager
from tool_paths import find_ovftool
from jobs import JobManager
from wizard import ExportWizard
from branding import set_icon
from project_paths import ROOT

BASE = ROOT
STOP_WARNING = ('Interrupting an export may leave the VM locked on ESXi and unable to power on or export again. '
                'An administrator may need to restart hostd, which can affect host management and other tasks.\n\n'
                'Any partial OVA remains incomplete and cannot be resumed. The app will not restart ESXi services.')


class App:
    def __init__(self, root, *, settings=None, remember_theme=True):
        self.root=root
        self.events=queue.Queue()
        self.wizard=None
        self.close_mode=None
        self.exit_dialog=None
        self.settings=settings if settings is not None else ConnectionSettings()
        self.settings_error=''
        try:
            self.settings.migrate_legacy()
        except (OSError,ValueError) as error:
            self.settings_error=str(error)
        root.title(f'{APP_NAME} {VERSION}')
        set_icon(root)
        root.geometry('1120x780')
        root.minsize(640,420)
        directory=getattr(self.settings, 'directory', None)
        preference=directory/'appearance.json' if remember_theme and isinstance(directory, Path) else None
        self.theme=ThemeManager(root, preference)
        outer=ttk.Frame(root,padding=(20,16))
        self.outer=outer
        outer.pack(fill='both',expand=True)
        header=ttk.Frame(outer)
        self.header=header
        header.pack(fill='x',pady=(0,14))
        logo=getattr(root,'_ova_logo',None)
        self.brand_icon=logo.subsample(3,3) if logo else None
        brand=ttk.Label(header,image=self.brand_icon,text='' if logo else 'OVA',style='Brand.TLabel',padding=(4,4))
        brand.pack(side='left',padx=(0,12))
        titles=ttk.Frame(header)
        titles.pack(side='left',fill='x',expand=True)
        ttk.Label(titles,text=APP_NAME,style='Title.TLabel').pack(anchor='w')
        ttk.Label(titles,text='VMware OVF Tool, made visual',style='Muted.TLabel').pack(anchor='w',pady=(2,0))
        self.theme_button=ttk.Button(header,command=self.toggle_theme,style='Quiet.TButton')
        self.theme_button.pack(side='right',padx=(10,0))
        self.caption=tk.StringVar(value='Your exports, in one place. Select a task to see its transfer details.')
        self.tool_path=find_ovftool(BASE)
        self.manager=JobManager(self.tool_path or BASE/'ovftool'/'ovftool.exe',self.emit)
        self.dashboard=Dashboard(outer,self.new_download,self.cancel_job,self.open_log,theme=self.theme)
        self.dashboard.pack(fill='both',expand=True)
        footer=ttk.Frame(outer)
        self.footer=footer
        footer.pack(fill='x',side='bottom',pady=(12,0),before=self.dashboard)
        self.caption_label=ttk.Label(footer,textvariable=self.caption,style='Footnote.TLabel',wraplength=560)
        self.caption_label.pack(side='left',anchor='w')
        ttk.Label(footer,text=f'v{VERSION} · Passwords never saved',style='Footnote.TLabel').pack(side='right',padx=(10,0))
        self.theme.register(self)
        root.bind('<Configure>', self.resize_layout, add='+')
        self.refresh_wheel=install_mousewheel(root)
        root.protocol('WM_DELETE_WINDOW',self.close)
        root.bind('<Control-n>',lambda event:self.new_download())
        root.bind('<Control-N>',lambda event:self.new_download())
        self.timer=root.after(100,self.poll)

    def apply_theme(self, colors):
        self.theme_button.configure(text='Light theme' if self.theme.mode == 'dark' else 'Dark theme')
        self.resize_layout()

    def resize_layout(self, event=None):
        if event is not None and event.widget is not self.root:
            return
        width=max(640,self.root.winfo_width())
        compact=self.root.winfo_height()<600
        self.outer.configure(padding=(12,10) if compact else (20,16))
        self.header.pack_configure(pady=(0,8) if compact else (0,14))
        self.caption_label.configure(wraplength=max(250,min(600,width-270)))
        self.theme.style.configure('Title.TLabel',font=('Segoe UI',17 if width<800 else 20,'bold'))
        self.theme.style.configure('Metric.TLabel',font=('Segoe UI',16 if width<800 else 19,'bold'))
        self.dashboard.fit_compact(self.root.winfo_height())
        self.dashboard.fit_columns(width)
        self.dashboard.summary_label.configure(wraplength=max(260,width-50))
        self.dashboard.after_idle(self.dashboard.fit_detail)

    def toggle_theme(self):
        self.theme.toggle()

    def emit(self,kind,payload):
        self.events.put((kind,payload))

    def new_download(self):
        if self.close_mode:
            self.root.bell()
            return
        if self.wizard and not self.wizard.closed:
            self.wizard.root.deiconify()
            self.wizard.root.lift()
            return
        window=tk.Toplevel(self.root)
        window.transient(self.root)
        self.wizard=ExportWizard(window,self)
        self.wizard.root.lift()

    def add_job(self,job):
        self.dashboard.add(job)
        self.refresh_wheel()
        self.manager.start(job)

    def cancel_job(self,job_id):
        job=self.manager.jobs[job_id]
        if job.can_force_stop:
            if messagebox.askyesno('Force stop this local export tool?',
                    job.vm['name']+' · '+job.client.authority+'\n\n'+STOP_WARNING+
                    '\n\nThis ends only this task\'s local OVF Tool process. Server cleanup cannot be confirmed.\n\nForce stop anyway?',
                    parent=self.root,default=messagebox.NO):
                self.manager.force_stop(job_id,confirmed=True)
            return
        if not job.can_request_cancel:
            return
        remote=job.state=='running'
        description=(STOP_WARNING+'\n\nRequest cancellation anyway? OVF Tool may take time to stop or become stuck.' if remote else
                     'Remove this queued export before it starts?' if job.state=='queued' else
                     'Stop the local checksum scan? The server transfer has already ended. '
                     'The package will remain marked .incomplete and unverified.')
        if messagebox.askyesno('Cancel active export?' if remote else 'Cancel task?',
                              job.vm['name']+'\n\n'+description,parent=self.root,default=messagebox.NO):
            if not self.manager.cancel(job_id,allow_remote=remote):
                messagebox.showinfo('Task state changed', 'This task has started transferring or has finished. '
                                    'No cancellation request was sent.',parent=self.root)

    def open_log(self,job):
        window=tk.Toplevel(self.root)
        window.title('Task log — '+job.vm['name'])
        window.geometry('850x440')
        window.minsize(500,260)
        frame=ttk.Frame(window,padding=10)
        frame.pack(fill='both',expand=True)
        ttk.Label(frame,text='In-memory task diagnostics — not saved to disk',wraplength=700).pack(anchor='w',pady=(0,6))
        text=tk.Text(frame,wrap='word',font=('Consolas',10))
        scroll=ttk.Scrollbar(frame,command=text.yview)
        scroll.pack(side='right',fill='y')
        text.pack(fill='both',expand=True)
        text.configure(yscrollcommand=scroll.set)
        text.insert('1.0','\n'.join(list(job.log_lines)) or 'No tool output yet. Run the export to collect its diagnostic messages.')
        text.configure(state='disabled')
        self.theme.refresh_windows()
        install_mousewheel(window)

    def poll(self):
        try:
            while True:
                kind,payload=self.events.get_nowait()
                if kind=='job':
                    self.dashboard.handle(*payload)
        except queue.Empty:
            pass
        if self.close_mode and self.exit_dialog is None and (self.manager.local_tools_stopped() if self.close_mode=='force' else not self.manager.unfinished()):
            self.finish_close()
            return
        self.root.after_cancel(self.timer)
        self.timer=self.root.after(100,self.poll)

    def close(self):
        if self.wizard and self.wizard.busy:
            messagebox.showinfo('Operation in progress','Wait for the export setup to finish.',parent=self.root)
            return
        if self.manager.unfinished():
            self.show_exit_choices()
            return
        self.finish_close()

    def show_exit_choices(self):
        if self.exit_dialog and self.exit_dialog.winfo_exists():
            self.exit_dialog.lift()
            return
        dialog=tk.Toplevel(self.root)
        self.exit_dialog=dialog
        dialog.title('Export tasks are still active')
        dialog.transient(self.root)
        dialog.resizable(True,False)
        dialog.minsize(580,1)
        frame=ttk.Frame(dialog,padding=16)
        frame.pack(fill='both',expand=True)
        ttk.Label(frame,text='Choose how to close the app',font=('Segoe UI',12,'bold')).pack(anchor='w')
        jobs=self.manager.unfinished()
        tasks='\n'.join(job.vm['name']+' · '+job.client.authority for job in jobs[:5])
        if len(jobs)>5:
            tasks+='\n…and '+str(len(jobs)-5)+' more tasks'
        ttk.Label(frame,text=tasks,wraplength=540).pack(anchor='w',pady=(8,8))
        ttk.Label(frame,text=STOP_WARNING,wraplength=540,style='Warning.TLabel').pack(anchor='w')
        ttk.Label(frame,text='Cancel and wait lets OVF Tool attempt cleanup. It can stall. Force stop and exit '
                  'ends only this app\'s local tools; server cleanup remains unconfirmed.',wraplength=540).pack(anchor='w',pady=(8,12))
        def dismiss():
            self.exit_dialog=None
            dialog.destroy()
        def keep_open():
            self.close_mode=None
            self.manager.resume_submissions()
            self.caption.set('App kept open. Any cancellation already requested will continue.')
            dismiss()
        def stop(force):
            self.close_mode='force' if force else 'wait'
            self.caption.set('Stopping local export tools before exit. Server cleanup is unconfirmed.' if force else
                             'Cancellation requested. The app will close when tasks and cleanup checks finish; use Exit again for other options.')
            if self.wizard:
                self.wizard.destroy_wizard()
            self.manager.stop_all(force=force,confirmed=True)
            dismiss()
        buttons=ttk.Frame(frame)
        buttons.pack(fill='x')
        keep=ttk.Button(buttons,text='Keep app open',command=keep_open)
        keep.pack(side='left')
        ttk.Button(buttons,text='Cancel and wait',command=lambda:stop(False)).pack(side='left',padx=8)
        ttk.Button(buttons,text='Force stop and exit',command=lambda:stop(True)).pack(side='right')
        dialog.protocol('WM_DELETE_WINDOW',keep_open)
        dialog.bind('<Escape>',lambda event:keep_open())
        dialog.grab_set()
        keep.focus_set()

    def finish_close(self):
        if self.exit_dialog and self.exit_dialog.winfo_exists():
            self.exit_dialog.destroy()
            self.exit_dialog=None
        if self.wizard:
            self.wizard.destroy_wizard()
        self.root.after_cancel(self.timer)
        self.root.destroy()


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == '__main__':
    main()
