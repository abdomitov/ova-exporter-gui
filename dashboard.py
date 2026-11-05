"""Compact task table with one selected-task detail pane."""
import tkinter as tk
from tkinter import ttk
from accordion import ScrollBody
from transfer_ui import TransferPanel
from jobs import TERMINAL
from task_view import TaskView




class Dashboard(ttk.Frame):
    def __init__(self, parent, new_download, cancel, open_log=lambda job: None, theme=None):
        super().__init__(parent)
        self.cancel = cancel
        self.open_log = open_log
        self.cards = {}
        self.selected = None
        self.narrow_columns = None
        self.summary = tk.StringVar(value='No export tasks yet')
        self.metrics = [tk.StringVar(value=value) for value in ('0', '0', '0.0 MB/s')]
        metrics_row = ttk.Frame(self)
        self.metrics_row = metrics_row
        metrics_row.pack(fill='x', pady=(0,16))
        for index, title in enumerate(('IN PROGRESS', 'COMPLETED', 'TRANSFER SPEED')):
            metrics_row.columnconfigure(index, weight=1, uniform='metric')
            card = ttk.Frame(metrics_row, style='Card.TFrame', padding=(16,10))
            card.grid(row=0,column=index,sticky='ew',padx=(0,10) if index < 2 else 0)
            ttk.Label(card,text=title,style='Card.TLabel').pack(anchor='w')
            ttk.Label(card,textvariable=self.metrics[index],style='Metric.TLabel').pack(anchor='w',pady=(2,0))
        toolbar = ttk.Frame(self)
        self.toolbar = toolbar
        toolbar.pack(fill='x',pady=(0,10))
        ttk.Button(toolbar,text='+ New export',style='Accent.TButton',command=new_download).pack(side='left')
        self.cancel_selected = ttk.Button(toolbar,text='Cancel queued task',command=self.cancel_current,state='disabled')
        self.cancel_selected.pack(side='left',padx=6)
        self.log_button = ttk.Button(toolbar,text='Task log',command=self.log_current,state='disabled')
        self.log_button.pack(side='left')
        self.panes = ttk.Panedwindow(self,orient='vertical')
        self.fit_token = None
        self.panes.bind('<Configure>', self.schedule_detail_fit)
        self.panes.pack(fill='both',expand=True)
        table = ttk.Frame(self.panes)
        table.columnconfigure(0,weight=1)
        table.rowconfigure(0,weight=1)
        columns=('server','vm','progress','status','speed','start','end','destination')
        self.tree = ttk.Treeview(table,columns=columns,show='headings',selectmode='browse',height=8)
        for key,title,width in [('server','Server',135),('vm','Virtual machine',160),('progress','Progress',75),
                                ('status','Status',115),('speed','MB/s',65),('start','Started',80),('end','Finished',80),
                                ('destination','Destination',260)]:
            self.tree.heading(key,text=title)
            self.tree.column(key,width=width,minwidth=120 if key=='vm' else 55,stretch=key in ('vm','destination'))
        self.tree.grid(row=0,column=0,sticky='nsew')
        scroll=ttk.Scrollbar(table,orient='vertical',command=self.tree.yview)
        scroll.grid(row=0,column=1,sticky='ns')
        horizontal=ttk.Scrollbar(table,orient='horizontal',command=self.tree.xview)
        horizontal.grid(row=1,column=0,sticky='ew')
        self.tree.configure(yscrollcommand=scroll.set,xscrollcommand=horizontal.set)
        self.empty = ttk.Label(self.tree,text='Your next export starts here.\nChoose New export to connect to an ESXi host or vCenter.',
                               style='Empty.TLabel',anchor='center',justify='center')
        self.empty.place(relx=0.5,rely=0.5,anchor='center')
        self.tree.bind('<<TreeviewSelect>>',self.selection_changed)
        self.panes.add(table,weight=3)
        self.detail_scroll = ScrollBody(self.panes)
        inner=self.detail_scroll.inner
        inner.columnconfigure(0,weight=1)
        self.detail_title=tk.StringVar()
        ttk.Label(inner,textvariable=self.detail_title,font=('Segoe UI',10,'bold'),wraplength=550).grid(row=0,column=0,sticky='w')
        self.panel=TransferPanel(inner)
        self.panel.grid(row=1,column=0,sticky='ew',pady=(6,0))
        self.cancel_detail=ttk.Button(self.panel.canvas,text='Cancel',command=self.cancel_current)
        self.message=ttk.Label(inner,wraplength=650,style='Muted.TLabel')
        self.message.grid(row=2,column=0,sticky='ew',pady=(6,0))
        self.detail_scroll.canvas.bind('<Configure>',lambda event:self.message.configure(wraplength=max(250,event.width-30)),add='+')
        actions=ttk.Frame(inner)
        actions.grid(row=3,column=0,sticky='ew',pady=(6,0))
        ttk.Button(actions,text='Hide details',command=self.hide_details).pack(side='left')
        ttk.Button(actions,text='Open task log',command=self.log_current).pack(side='right')
        self.summary_label=ttk.Label(self,textvariable=self.summary,style='Footnote.TLabel',wraplength=950)
        self.summary_label.pack(anchor='w',side='bottom',pady=(6,0),before=self.panes)

        if theme:
            theme.register(self)

    def apply_theme(self, colors):
        for state in ('failed','cleanup_required','stalled'):
            self.tree.tag_configure(state,foreground=colors['negative'])
        self.tree.tag_configure('done',foreground=colors['positive'])
        self.tree.tag_configure('done_warning',foreground=colors['warning'])
        self.tree.tag_configure('even',background=colors['stripe'])
        self.tree.tag_configure('odd',background=colors['surface'])

    def fit_compact(self, height):
        """Give the task table priority when the window is short."""
        if height < 600:
            self.metrics_row.pack_forget()
        elif not self.metrics_row.winfo_manager():
            self.metrics_row.pack(fill='x',pady=(0,16),before=self.toolbar)

    def fit_columns(self, width):
        narrow = width < 900
        if narrow != self.narrow_columns:
            self.narrow_columns = narrow
            self.tree.configure(displaycolumns=('server','vm','progress','status','speed') if narrow else '#all')

    def add(self,job):
        self.empty.place_forget()
        view=TaskView(job)
        self.cards[job.id]=view
        self.tree.insert('', 'end', iid=job.id,values=self.values(view),tags=('even' if len(self.cards)%2==0 else 'odd',))
        self.tree.see(job.id)
        self.update_summary()

    def values(self,view):
        return (view.job.client.authority,view.job.vm['name'],f'{view.percent:g}%',view.status_text(),
                f'{view.speed/1_000_000:.1f}' if view.state=='running' else '—',
                view.started or '—',view.ended or '—',str(view.job.target))

    def handle(self,job_id,kind,value):
        view=self.cards.get(job_id)
        if view is None:
            return
        view.update(kind,value)
        self.tree.item(job_id,values=self.values(view),tags=(view.state, 'even' if list(self.cards).index(job_id)%2 else 'odd'))
        if self.selected==job_id:
            self.render_detail()
        self.update_summary()

    def selection_changed(self,event=None):
        selection=self.tree.selection()
        if not selection:
            return
        self.selected=selection[0]
        if str(self.detail_scroll) not in tuple(map(str,self.panes.panes())):
            self.panes.add(self.detail_scroll,weight=2)
            self.after_idle(self.fit_detail)
            self.winfo_toplevel().after(100,self.fit_detail)
        self.render_detail()

    def fit_detail(self):
        if str(self.detail_scroll) in tuple(map(str,self.panes.panes())):
            height=self.panes.winfo_height()
            if height>140:
                self.panes.sashpos(0,min(height-60,max(104,int(height*0.40))))

    def schedule_detail_fit(self, event=None):
        # ttk finishes distributing pane weights after the root Configure event.
        # Apply our split after that layout settles, preserving complete rows.
        if self.fit_token is not None:
            self.after_cancel(self.fit_token)
        self.fit_token = self.after(80,self.finish_detail_fit)

    def finish_detail_fit(self):
        self.fit_token = None
        self.fit_detail()

    def destroy(self):
        if self.fit_token is not None:
            self.after_cancel(self.fit_token)
            self.fit_token = None
        super().destroy()

    def hide_details(self):
        if str(self.detail_scroll) in tuple(map(str,self.panes.panes())):
            self.panes.forget(self.detail_scroll)

    def render_detail(self):
        if not self.selected:
            return
        view=self.cards[self.selected]
        self.detail_title.set(f"{view.job.vm['name']} · {view.job.client.authority} · {view.job.target}")
        panel=self.panel
        panel.phase={'running':'exporting' if view.percent else 'preparing','failed':'error','cancelled':'error'}.get(view.state,view.state)
        panel.value,panel.speed,panel.written,panel.elapsed=view.percent,view.speed,view.written,view.elapsed
        panel.peak_speed,panel.history=view.peak,list(view.history)
        panel.detail=('Your OVA is ready. See the message below about the VM state.' if view.state=='done_warning' else
                      'See the message below. Server cleanup could not be confirmed.'
                      if view.state in ('cleanup_required','stalled') else view.detail)
        panel.draw()
        active=view.state not in TERMINAL
        can_force=view.job.can_force_stop
        can_cancel=view.job.can_request_cancel or can_force
        cancel_label=('Force stop…' if can_force else 'Stop verification' if view.state=='verifying' else
                      'Cancel export…' if view.state=='running' else 'Cancel queued task')
        self.cancel_selected.configure(text=cancel_label,state='normal' if can_cancel else 'disabled')
        if can_cancel:
            self.cancel_selected.pack(side='left',padx=6,before=self.log_button)
        else:
            self.cancel_selected.pack_forget()
        self.log_button.configure(state='normal')
        if can_cancel:
            self.cancel_detail.configure(text=cancel_label)
            self.cancel_detail.place(relx=1,x=-12,y=10,anchor='ne')
        else:
            self.cancel_detail.place_forget()
        self.message.configure(text=view.detail if not active or view.state=='stalled' else '')

    def cancel_current(self):
        if self.selected:
            self.cancel(self.selected)

    def log_current(self):
        if self.selected:
            self.open_log(self.cards[self.selected].job)

    def update_summary(self):
        views=list(self.cards.values())
        active=sum(v.state in ('running','verifying','cancelling','cleaning','stalled','force_stopping') for v in views)
        queued=sum(v.state=='queued' for v in views)
        done=sum(v.state in ('done','done_warning') for v in views)
        failed=sum(v.state=='failed' for v in views)
        attention=sum(v.state in ('cleanup_required','stalled','done_warning') for v in views)
        rate=sum(v.speed for v in views if v.state=='running')/1_000_000
        for variable, value in zip(self.metrics,(str(active+queued),str(done),f'{rate:.1f} MB/s')):
            variable.set(value)
        self.summary.set(f'{active} active · {queued} queued · {done} completed · {failed} failed · {attention} need attention · {rate:.1f} MB/s total')
