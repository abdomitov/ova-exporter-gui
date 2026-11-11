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
        self.dirty = {}
        self.row_tags = {}
        self.selected = None
        self.narrow_columns = None
        self.compact = False
        self.tool_ready = None
        self.summary = tk.StringVar(value='No export tasks yet')
        self.metrics = [tk.StringVar(value=value) for value in ('0', '0', '0.0 MB/s')]
        metrics_row = ttk.Frame(self,style='Card.TFrame',padding=(6,8))
        self.metrics_row = metrics_row
        metrics_row.pack(fill='x', pady=(0,12))
        for index, title in enumerate(('Active + queued', 'Completed', 'Combined write speed')):
            metrics_row.columnconfigure(index,weight=2 if index==2 else 1)
            card = ttk.Frame(metrics_row,style='Card.TFrame',padding=(12,0))
            card.grid(row=0,column=index,sticky='ew')
            if index<2:
                ttk.Separator(card,orient='vertical').pack(side='right',fill='y',padx=(8,0))
            ttk.Label(card,textvariable=self.metrics[index],style='Metric.TLabel').pack(side='left')
            ttk.Label(card,text=title,style='Card.TLabel',wraplength=85).pack(side='left',padx=(10,0))
        toolbar = ttk.Frame(self)
        self.toolbar = toolbar
        toolbar.pack(fill='x',pady=(0,10))
        ttk.Button(toolbar,text='+ New export',style='Accent.TButton',command=new_download).pack(side='left')
        self.cancel_selected = ttk.Button(toolbar,text='Cancel queued task',command=self.cancel_current,state='disabled')
        self.log_button = ttk.Button(toolbar,text='Task log',command=self.log_current,state='disabled')
        self.log_button.pack(side='left')
        self.details_button=ttk.Button(toolbar,text='Show details',command=self.toggle_details,state='disabled')
        self.details_button.pack(side='left',padx=(6,0))
        self.panes = ttk.Panedwindow(self,orient='vertical')
        self.fit_token = None
        self.split_ratio = None
        self.dragging_split = False
        self.pane_size = None
        self.panes.bind('<Configure>', self.schedule_detail_fit)
        self.panes.bind('<ButtonPress-1>', self.start_split_drag, add='+')
        self.panes.bind('<ButtonRelease-1>', self.finish_split_drag, add='+')
        self.panes.pack(fill='both',expand=True)
        table = ttk.Frame(self.panes)
        self.table = table
        table.columnconfigure(0,weight=1)
        table.rowconfigure(0,weight=1)
        columns=('server','vm','progress','status','speed','start','end','destination')
        self.tree = ttk.Treeview(table,columns=columns,show='',selectmode='browse',height=8)
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
        self.empty = ttk.Frame(self.tree,style='Card.TFrame',padding=(24,16))
        self.empty_title=ttk.Label(self.empty,text='Ready for your first export',style='EmptyTitle.TLabel')
        self.empty_title.pack()
        self.empty_hint=ttk.Label(self.empty,text='Connect to an ESXi host or vCenter, choose a powered-off VM, and save one OVA package.',
                                  style='TableHint.TLabel',wraplength=350,justify='center')
        self.empty_hint.pack(pady=(4,8))
        self.empty_action=ttk.Button(self.empty,text='New export',style='Accent.TButton',command=new_download)
        self.empty_action.pack()
        self.empty.place(relx=0.5,rely=0.5,anchor='center')
        self.tree.bind('<<TreeviewSelect>>',self.selection_changed)
        self.tree.bind('<Return>',lambda event:self.toggle_details())
        self.tree.bind('<Escape>',lambda event:self.hide_details())
        self.panes.add(table,weight=3)
        self.detail_scroll = ScrollBody(self.panes)
        inner=self.detail_scroll.inner
        inner.columnconfigure(0,weight=1)
        self.detail_title=tk.StringVar()
        self.detail_label=ttk.Label(inner,textvariable=self.detail_title,font=('Segoe UI',10,'bold'),wraplength=550)
        self.detail_label.grid(row=0,column=0,sticky='w',pady=(5,0))
        self.panel=TransferPanel(inner)
        self.panel.grid(row=1,column=0,columnspan=2,sticky='ew',pady=(8,0))
        self.cancel_detail=ttk.Button(inner,text='Cancel',command=self.cancel_current)
        self.message=ttk.Label(inner,wraplength=650,style='Muted.TLabel')
        self.message.grid(row=2,column=0,columnspan=2,sticky='ew',pady=(8,0))
        self.message.grid_remove()
        self.detail_scroll.canvas.bind('<Configure>',self.wrap_details,add='+')
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

    def set_tool_ready(self, ready):
        if ready==self.tool_ready:
            return
        self.tool_ready=ready
        self.empty_title.configure(text='Ready for your first export' if ready else 'Set up VMware OVF Tool')
        self.empty_hint.configure(text='Connect to an ESXi host or vCenter, choose a powered-off VM, and save one OVA package.'
                                  if ready else 'Install OVF Tool using Download above, or choose Locate OVF Tool if it is already installed.')
        self.empty_action.configure(state='normal' if ready else 'disabled')

    def fit_compact(self, height):
        """Give the task table priority when the window is short."""
        self.compact = height < 600
        if self.compact:
            self.metrics_row.pack_forget()
        elif not self.metrics_row.winfo_manager():
            self.metrics_row.pack(fill='x',pady=(0,12),before=self.toolbar)
        self.fit_panes()

    def fit_panes(self):
        """Short windows show the list or the detail, rather than two slivers."""
        panes=tuple(map(str,self.panes.panes()))
        detail_visible=str(self.detail_scroll) in panes
        table_visible=str(self.table) in panes
        if self.compact and detail_visible and table_visible:
            self.panes.forget(self.table)
        elif not table_visible and (not self.compact or not detail_visible):
            self.panes.insert(0 if panes else 'end',self.table,weight=3)

    def fit_columns(self, width):
        narrow = width < 900
        if narrow != self.narrow_columns:
            self.narrow_columns = narrow
            self.tree.configure(displaycolumns=('server','vm','progress','status','speed') if narrow else '#all')

    def add(self,job):
        self.empty.place_forget()
        self.tree.configure(show='headings')
        view=TaskView(job)
        self.cards[job.id]=view
        self.row_tags[job.id]='even' if len(self.cards)%2==0 else 'odd'
        self.tree.insert('', 'end', iid=job.id,values=self.values(view),tags=(self.row_tags[job.id],))
        self.tree.see(job.id)
        self.update_summary()

    def show_empty(self):
        if not self.cards:
            self.tree.configure(show='')
            self.empty.place(relx=0.5,rely=0.5,anchor='center')

    def values(self,view):
        return (view.job.client.authority,view.job.vm['name'],f'{view.percent:g}%',view.status_text(),
                f'{view.speed/1_000_000:.1f}' if view.state=='running' else '—',
                view.started or '—',view.ended or '—',str(view.job.target))

    def handle(self,job_id,kind,value,*,defer=False):
        view=self.cards.get(job_id)
        if view is None:
            return
        view.update(kind,value)
        self.dirty[job_id]=None
        if not defer:
            self.flush_updates()

    def flush_updates(self):
        if not self.dirty:
            return
        for job_id in self.dirty:
            view=self.cards[job_id]
            self.tree.item(job_id,values=self.values(view),tags=(view.state,self.row_tags[job_id]))
        if self.selected in self.dirty:
            self.render_detail()
        self.update_summary()
        self.dirty.clear()

    def selection_changed(self,event=None):
        selection=self.tree.selection()
        if not selection:
            return
        self.selected=selection[0]
        if str(self.detail_scroll) not in tuple(map(str,self.panes.panes())):
            self.panes.add(self.detail_scroll,weight=2)
            self.after_idle(self.fit_detail)
            self.winfo_toplevel().after(100,self.fit_detail)
        self.fit_panes()
        self.render_detail()

    def fit_detail(self):
        if len(self.panes.panes())>1 and str(self.detail_scroll) in tuple(map(str,self.panes.panes())):
            height=self.panes.winfo_height()
            if height>140:
                table_height=int(height*self.split_ratio) if self.split_ratio is not None else min(int(height*0.40),height-316)
                self.panes.sashpos(0,min(height-60,max(104,table_height)))

    def start_split_drag(self,event):
        self.dragging_split=self.panes.identify(event.x,event.y) != ''

    def finish_split_drag(self,event):
        if self.dragging_split and len(self.panes.panes())>1:
            self.split_ratio=self.panes.sashpos(0)/max(1,self.panes.winfo_height())
        self.dragging_split=False

    def wrap_details(self,event):
        width=max(250,event.width-30)
        self.message.configure(wraplength=width)
        self.detail_label.configure(wraplength=max(200,width-150))
        self.detail_scroll.schedule()

    def schedule_detail_fit(self, event=None):
        if event is not None:
            size=(event.width,event.height)
            if size==self.pane_size:
                return
            self.pane_size=size
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
        self.fit_panes()
        self.details_button.configure(text='Show details')

    def toggle_details(self):
        if str(self.detail_scroll) in tuple(map(str,self.panes.panes())):
            self.hide_details()
        else:
            self.selection_changed()

    def render_detail(self):
        if not self.selected:
            return
        visible=str(self.detail_scroll) in tuple(map(str,self.panes.panes()))
        self.details_button.configure(state='normal',text='Hide details' if visible else 'Show details')
        view=self.cards[self.selected]
        title=f"{view.job.vm['name']} · {view.job.client.authority} · {view.job.target}"
        if self.detail_title.get()!=title:
            self.detail_title.set(title)
            self.detail_scroll.schedule()
        panel=self.panel
        panel.phase={'running':'exporting' if view.percent else 'preparing','failed':'error','cancelled':'error'}.get(view.state,view.state)
        panel.value,panel.speed,panel.written,panel.elapsed=view.percent,view.speed,view.written,view.elapsed
        panel.peak_speed,panel.history=view.peak,list(view.history)
        # Full errors belong in the wrapping message below, so a long tool
        # diagnostic cannot cover the speed graph or its labels.
        panel.detail={
            'done':'Completed and checksums verified.',
            'done_warning':'Your OVA is ready. Review the VM state below.',
            'cleanup_required':'Server cleanup could not be confirmed. See below.',
            'stalled':'Server cleanup could not be confirmed. See below.',
            'failed':'Read the task message below for the cause.',
            'cancelled':'Export cancelled. Partial packages remain incomplete.',
        }.get(view.state,view.detail)
        if visible:
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
            self.cancel_detail.grid(row=0,column=1,sticky='ne',padx=(8,0))
        else:
            self.cancel_detail.grid_remove()
        message=view.detail if not active or view.state=='stalled' else ''
        if self.message['text']!=message:
            self.message.configure(text=message)
            if message:
                self.message.grid()
            else:
                self.message.grid_remove()
            # The canvas fixes the inner frame's actual height. Changing a
            # child's requested height does not necessarily send Configure to
            # that frame, so explicitly recompute the scroll region.
            self.detail_scroll.schedule()

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
