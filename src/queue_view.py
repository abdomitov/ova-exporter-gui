"""Export queue: a list of tasks beside the selected task's transfer and log."""
import subprocess
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

from platform_support import open_folder, tool_name
from jobs import TERMINAL
from scrolling import ScrollBody
from task_view import TaskView
from theme import PALETTES, theme_for
from transfer_panel import TransferPanel
from ui_assets import rounded_png

ACTIVE_STATES = ('running', 'verifying', 'cancelling', 'cleaning', 'stalled', 'force_stopping')
LOG_TAIL = 500


def state_tone(state):
    if state in ('failed', 'cleanup_required', 'stalled', 'force_stopping'):
        return 'negative'
    if state in ('done_warning', 'cancelling'):
        return 'warning'
    if state == 'done':
        return 'positive'
    if state in ('running', 'verifying', 'cleaning'):
        return 'accent'
    return 'muted'


class TaskList(ttk.Frame):
    """Canvas-drawn task rows; each row carries its own slim progress bar."""

    def __init__(self, parent, views, on_select):
        super().__init__(parent, style='Surface.TFrame')
        self.views = views
        self.on_select = on_select
        self.order = []
        self.selected = None
        self.colors = PALETTES['light']
        self.theme = theme_for(self)
        self.px = self.theme.px if self.theme else round
        font = self.theme.font if self.theme else (lambda role='body', size=10, weight='normal': ('TkDefaultFont', size, weight))
        self.fonts = {'name': tkfont.Font(self, font=font('body', 10, 'bold')),
                      'small': tkfont.Font(self, font=font('body', 9)),
                      'number': tkfont.Font(self, font=font('numeric', 12, 'bold'))}
        self.row_height = self.px(78)
        self.selection_image = None
        self.selection_size = None
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(self, highlightthickness=0, borderwidth=0, takefocus=1, width=1, height=1)
        self.canvas.grid(row=0, column=0, sticky='nsew')
        self.scroll = ttk.Scrollbar(self, orient='vertical', command=self.canvas.yview, style='Surface.Vertical.TScrollbar')
        for name in ('<FocusIn>', '<FocusOut>'):
            self.canvas.bind(name, lambda event: self.redraw_row(self.selected), add='+')
        self.canvas.configure(yscrollcommand=self.scroll.set)
        self.canvas.bind('<Configure>', lambda event: self.redraw())
        self.canvas.bind('<Button-1>', self.click)
        for key, step in (('<Up>', -1), ('<Down>', 1)):
            self.canvas.bind(key, lambda event, step=step: self.move(step))
        self.canvas.bind('<Home>', lambda event: self.move(-len(self.order)))
        self.canvas.bind('<End>', lambda event: self.move(len(self.order)))
        if self.theme:
            self.theme.register(self)

    def apply_theme(self, colors):
        self.colors = colors
        self.canvas.configure(background=colors['surface'])
        self.selection_size = None
        self.redraw()

    def wheel_units(self, units):
        view = self.canvas.yview()
        if (units < 0 and view[0] > 0) or (units > 0 and view[1] < 1):
            self.canvas.yview_scroll(units, 'units')
            return True
        return False

    def add(self, job_id):
        self.order.append(job_id)
        self.redraw()
        self.see(job_id)

    def clear(self):
        self.order.clear()
        self.selected = None
        self.redraw()

    def click(self, event):
        self.canvas.focus_set()
        index = int(self.canvas.canvasy(event.y) // self.row_height)
        if 0 <= index < len(self.order):
            self.select(self.order[index])

    def move(self, step):
        if not self.order:
            return 'break'
        current = self.order.index(self.selected) if self.selected in self.order else -1 if step > 0 else len(self.order)
        self.select(self.order[max(0, min(len(self.order) - 1, current + step))])
        return 'break'

    def select(self, job_id, notify=True):
        previous, self.selected = self.selected, job_id
        for key in (previous, job_id):
            if key in self.views:
                self.redraw_row(key)
        if job_id is not None:
            self.see(job_id)
        if notify:
            self.on_select(job_id)

    def see(self, job_id):
        total = len(self.order) * self.row_height
        height = self.canvas.winfo_height()
        if job_id not in self.order or total <= height or height <= 1:
            return
        top = self.order.index(job_id) * self.row_height
        first = self.canvas.canvasy(0)
        if top < first:
            self.canvas.yview_moveto(top / total)
        elif top + self.row_height > first + height:
            self.canvas.yview_moveto((top + self.row_height - height) / total)

    def redraw(self):
        self.canvas.delete('all')
        width = max(self.canvas.winfo_width(), self.px(200))
        total = len(self.order) * self.row_height
        self.canvas.configure(scrollregion=(0, 0, width, max(total, 1)), yscrollincrement=self.px(24))
        if total > self.canvas.winfo_height() > 1:
            self.scroll.grid(row=0, column=1, sticky='ns')
        else:
            self.scroll.grid_remove()
            self.canvas.yview_moveto(0)
        for job_id in self.order:
            self.redraw_row(job_id)

    def fit(self, text, font, room):
        if font.measure(text) <= room:
            return text
        while len(text) > 1 and font.measure(text + '…') > room:
            text = text[:-1]
        return text + '…'

    def selection_background(self, width, height):
        """A rounded highlight sized to the row; rebuilt only when the list is resized."""
        focused = self.canvas.focus_displayof() is self.canvas if self.canvas.winfo_exists() else False
        key = (width, height, self.colors['selection'], focused)
        if key != self.selection_size:
            self.selection_size = key
            data = rounded_png(width, height, self.px(10), fill=self.colors['selection'], backdrop=self.colors['surface'],
                               border=self.colors['accent'] if focused else None, border_width=self.px(2))
            self.selection_image = (self.theme.assets.set('row_selected', data) if self.theme
                                    else tk.PhotoImage(master=self, data=__import__('base64').b64encode(data)))
        return self.selection_image

    def redraw_row(self, job_id):
        if job_id not in self.order:
            return
        canvas, c, px = self.canvas, self.colors, self.px
        view = self.views[job_id]
        tag = 'row-' + job_id
        canvas.delete(tag)
        width = max(canvas.winfo_width(), px(200))
        top = self.order.index(job_id) * self.row_height
        inset = px(4)
        left, right = px(18), width - px(18)
        if job_id == self.selected:
            canvas.create_image(inset, top + inset, anchor='nw', tags=tag,
                                image=self.selection_background(width - 2 * inset, self.row_height - 2 * inset))
        tone = c[state_tone(view.state)]
        percent = f'{view.percent:.0f}%'
        number_room = self.fonts['number'].measure(percent) + px(12)
        canvas.create_text(right, top + px(15), text=percent, anchor='ne', fill=c['text'],
                           font=self.fonts['number'], tags=tag)
        canvas.create_text(left, top + px(16), anchor='nw', fill=c['text'], font=self.fonts['name'], tags=tag,
                           text=self.fit(view.job.vm['name'], self.fonts['name'], right - left - number_room))
        status = view.status_text()
        if view.state == 'running' and view.percent:
            status += f', {view.speed / 1_000_000:.1f} MB/s'
        status_room = self.fonts['small'].measure(status) + px(12)
        canvas.create_text(right, top + px(38), text=status, anchor='ne', fill=tone, font=self.fonts['small'], tags=tag)
        canvas.create_text(left, top + px(38), anchor='nw', fill=c['muted'], font=self.fonts['small'], tags=tag,
                           text=self.fit(view.job.client.authority, self.fonts['small'], right - left - status_room))
        bar, thick = top + px(60), px(4)
        canvas.create_line(left, bar, right, bar, fill=c['track'], width=thick, capstyle='round', tags=tag)
        if view.percent:
            end = left + (right - left) * view.percent / 100
            canvas.create_line(left, bar, max(left + 1, end), bar, width=thick, capstyle='round', tags=tag,
                               fill=tone if state_tone(view.state) != 'muted' else c['disabled'])


class QueueView(ttk.Frame):
    def __init__(self, parent, new_download, cancel, *, open_settings=lambda: None,
                 on_summary=lambda counts: None, notify=lambda text: None, theme=None):
        super().__init__(parent)
        self.cancel = cancel
        self.on_summary = on_summary
        self.notify = notify
        self.theme = theme or theme_for(self)
        px = self.theme.px if self.theme else round
        self.cards = {}
        self.dirty = {}
        self.selected = None
        self.active = True
        self.tab = 'transfer'
        self.tool_ready = None
        self.log_state = None
        self.summary = tk.StringVar(value='Nothing queued yet')
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        header = ttk.Frame(self)
        header.grid(row=0, column=0, sticky='ew', pady=(0, px(10)), padx=self.theme.card_margin[0] if self.theme else 0)
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text='Exports', style='Title.TLabel').grid(row=0, column=0, sticky='w')
        self.summary_label = ttk.Label(header, textvariable=self.summary, style='Muted.TLabel')
        self.summary_label.grid(row=1, column=0, sticky='w', pady=(2, 0))
        self.new_button = ttk.Button(header, text='New export', style='Accent.TButton', command=new_download)
        self.new_button.grid(row=0, column=1, rowspan=2, sticky='e')

        body = ttk.Frame(self)
        self.body = body
        body.grid(row=1, column=0, sticky='nsew')
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        make_panel = self.theme.panel if self.theme else (lambda parent, **kw: tk.Frame(parent))
        list_panel = make_panel(body)
        list_panel.grid(row=0, column=0, sticky='nsew', padx=(0, px(2)))
        list_panel.configure(width=px(300))
        list_panel.grid_propagate(False)
        list_panel.pack_propagate(False)
        self.list = TaskList(list_panel, self.cards, self.selection_changed)
        self.list.pack(fill='both', expand=True)

        detail = make_panel(body)
        self.detail = detail
        detail.grid(row=0, column=1, sticky='nsew')
        detail.columnconfigure(0, weight=1)
        detail.rowconfigure(2, weight=1)
        head = ttk.Frame(detail, style='Surface.TFrame', padding=(px(22), px(16), px(22), px(10)))
        self.head = head
        head.grid(row=0, column=0, sticky='ew')
        head.columnconfigure(1, weight=1)
        self.detail_title = tk.StringVar()
        self.detail_source = tk.StringVar()
        self.detail_target = tk.StringVar()
        self.title_label = ttk.Label(head, textvariable=self.detail_title, style='Title.Surface.TLabel', wraplength=px(420))
        self.title_label.grid(row=0, column=0, columnspan=2, sticky='w')
        self.cancel_button = ttk.Button(head, text='Cancel', style='Surface.Danger.TButton', command=self.cancel_current)
        ttk.Label(head, text='From', style='Muted.Surface.TLabel').grid(row=1, column=0, sticky='nw', pady=(8, 0), padx=(0, 12))
        ttk.Label(head, textvariable=self.detail_source, style='Surface.TLabel').grid(row=1, column=1, sticky='w', pady=(8, 0))
        ttk.Label(head, text='Saved to', style='Muted.Surface.TLabel').grid(row=2, column=0, sticky='nw', pady=(2, 0), padx=(0, 12))
        self.target_label = ttk.Label(head, textvariable=self.detail_target, style='Surface.TLabel', wraplength=px(420))
        self.target_label.grid(row=2, column=1, sticky='w', pady=(2, 0))

        bar = ttk.Frame(detail, style='Surface.TFrame', padding=(px(22), 0, px(22), px(6)))
        bar.grid(row=1, column=0, sticky='ew')
        self.tab_buttons = {}
        for name, label in (('transfer', 'Transfer'), ('log', 'Tool log')):
            button = ttk.Button(bar, text=label, command=lambda name=name: self.show_tab(name))
            button.pack(side='left', padx=(0, 4))
            self.tab_buttons[name] = button
        self.copy_button = ttk.Button(bar, text='Copy path', style='Surface.TButton', command=self.copy_path)
        self.copy_button.pack(side='right')
        self.folder_button = ttk.Button(bar, text='Open folder', style='Surface.TButton', command=self.open_folder)
        self.folder_button.pack(side='right', padx=(0, 8))

        self.transfer_body = ScrollBody(detail, tone='Surface.', padding=0)
        self.detail_scroll = self.transfer_body
        self.transfer_body.grid(row=2, column=0, sticky='nsew')
        inner = self.transfer_body.inner
        inner.columnconfigure(0, weight=1)
        inner.rowconfigure(1, weight=1)
        self.panel = TransferPanel(inner)
        self.panel.grid(row=1, column=0, sticky='nsew')
        self.message = ttk.Label(inner, style='Notice.TLabel', wraplength=px(480))
        self.message_pad = (px(22), 0, px(22), px(18))
        self.transfer_body.canvas.bind('<Configure>', self.wrap_details, add='+')

        self.log_body = ttk.Frame(detail, style='Surface.TFrame', padding=(px(22), 0, px(22), px(18)))
        self.log_body.columnconfigure(0, weight=1)
        self.log_body.rowconfigure(1, weight=1)
        ttk.Label(self.log_body, text='Kept in memory for this session and never written to disk.',
                  style='Small.Surface.TLabel').grid(row=0, column=0, columnspan=2, sticky='w', pady=(0, 8))
        self.log_text = tk.Text(self.log_body, wrap='word', height=4, width=20, state='disabled',
                                font=self.theme.font('mono', 9) if self.theme else None)
        self.log_text.grid(row=1, column=0, sticky='nsew')
        log_scroll = ttk.Scrollbar(self.log_body, command=self.log_text.yview, style='Surface.Vertical.TScrollbar')
        log_scroll.grid(row=1, column=1, sticky='ns')
        self.log_text.configure(yscrollcommand=log_scroll.set)

        # Shown instead of the two panels until the first task exists.
        self.empty = make_panel(body)
        box = ttk.Frame(self.empty, style='Surface.TFrame')
        box.place(relx=0.5, rely=0.45, anchor='center')
        self.empty_art = ttk.Label(box, style='Surface.TLabel')
        self.empty_art.pack(pady=(0, px(14)))
        self.empty_title = ttk.Label(box, text='No exports yet', style='Title.Surface.TLabel')
        self.empty_title.pack()
        self.empty_hint = ttk.Label(box, style='Muted.Surface.TLabel', wraplength=px(420), justify='center')
        self.empty_hint.pack(pady=(8, 20))
        self.empty_action = ttk.Button(box, text='New export', style='Surface.Accent.TButton', command=new_download)
        self.empty_action.pack()
        self.empty_new, self.empty_settings = new_download, open_settings
        self.set_tool_ready(True)
        self.show_empty()
        self.show_tab('transfer')
        if self.theme:
            self.theme.register(self)

    def apply_theme(self, colors):
        self.empty_art.configure(image=self.theme.assets.get('empty'))

    # -- empty state -----------------------------------------------------
    def set_tool_ready(self, ready):
        if ready == self.tool_ready:
            return
        self.tool_ready = ready
        self.empty_title.configure(text='No exports yet' if ready else 'VMware OVF Tool is not set up')
        self.empty_hint.configure(text='Sign in to an ESXi host or vCenter, pick a powered-off VM and choose where to save its OVA.'
                                  if ready else f'Exports run through VMware OVF Tool. Install it, or point this app at {tool_name()}, in Settings.')
        self.empty_action.configure(text='New export' if ready else 'Open settings',
                                    command=self.empty_new if ready else self.empty_settings)
        self.new_button.configure(state='normal' if ready else 'disabled')

    def show_empty(self):
        if not self.cards:
            self.empty.grid(row=0, column=0, columnspan=2, sticky='nsew')
            self.empty.lift()

    # -- tasks -----------------------------------------------------------
    def add(self, job, select=False):
        self.empty.grid_remove()
        self.cards[job.id] = TaskView(job)
        self.list.add(job.id)
        if select or self.selected is None:
            self.list.select(job.id)
        self.update_summary()

    def clear(self):
        self.cards.clear()
        self.dirty.clear()
        self.selected = None
        self.list.clear()
        self.update_summary()
        self.show_empty()

    def handle(self, job_id, kind, value, *, defer=False):
        view = self.cards.get(job_id)
        if view is None:
            return
        view.update(kind, value)
        self.dirty[job_id] = None
        if not defer:
            self.flush_updates()

    def flush_updates(self):
        if not self.dirty:
            return
        for job_id in self.dirty:
            self.list.redraw_row(job_id)
        if self.selected in self.dirty:
            self.render_detail()
        self.update_summary()
        self.dirty.clear()

    def select(self, job_id):
        self.list.select(job_id)

    def selection_changed(self, job_id):
        self.selected = job_id
        self.log_state = None
        self.render_detail()

    def set_active(self, active):
        """Only the visible view spends time drawing the transfer canvas."""
        self.active = active
        if active:
            self.render_detail()

    def show_tab(self, name):
        self.tab = name
        for key, button in self.tab_buttons.items():
            button.configure(style='Surface.TabActive.TButton' if key == name else 'Surface.Tab.TButton')
        if name == 'log':
            self.transfer_body.grid_remove()
            self.log_body.grid(row=2, column=0, sticky='nsew')
            self.log_state = None
        else:
            self.log_body.grid_remove()
            self.transfer_body.grid(row=2, column=0, sticky='nsew')
        self.render_detail()

    def wrap_details(self, event):
        px = self.theme.px if self.theme else round
        self.message.configure(wraplength=max(px(220), event.width - px(72)))
        for label in (self.title_label, self.target_label):
            label.configure(wraplength=max(px(200), event.width - px(150)))
        self.transfer_body.schedule()

    def render_detail(self):
        view = self.cards.get(self.selected)
        if view is None:
            return
        job = view.job
        self.detail_title.set(job.vm['name'])
        self.detail_source.set(job.client.authority)
        self.detail_target.set(str(job.target))
        panel = self.panel
        panel.phase = {'running': 'exporting' if view.percent else 'preparing',
                       'failed': 'error', 'cancelled': 'error'}.get(view.state, view.state)
        panel.value, panel.speed, panel.written, panel.elapsed = view.percent, view.speed, view.written, view.elapsed
        panel.peak_speed, panel.history = view.peak, list(view.history)
        # Full errors belong in the wrapping message above the panel, so a long
        # tool diagnostic cannot cover the stage track or the speed history.
        panel.detail = {
            'done': 'Checksums verified.',
            'done_warning': 'The package is complete; the source VM needs a look.',
            'cleanup_required': 'Server cleanup could not be confirmed.',
            'stalled': 'Server cleanup could not be confirmed.',
            'failed': '',
            'cancelled': 'Cancelled. Partial packages remain marked incomplete.',
        }.get(view.state, view.detail)
        if self.active and self.tab == 'transfer':
            panel.draw()
        active = view.state not in TERMINAL
        can_force = job.can_force_stop
        can_cancel = job.can_request_cancel or can_force
        self.cancel_button.configure(text='Force stop…' if can_force else 'Stop verification' if view.state == 'verifying'
                                     else 'Cancel export…' if view.state == 'running' else 'Remove from queue')
        if can_cancel:
            self.cancel_button.grid(row=0, column=2, sticky='ne', padx=(12, 0))
        else:
            self.cancel_button.grid_remove()
        message = view.detail if not active or view.state == 'stalled' else ''
        style = {'done': 'Good.TLabel', 'done_warning': 'Notice.TLabel', 'cancelled': 'Notice.TLabel'}.get(view.state, 'Problem.TLabel')
        if self.message['text'] != message or str(self.message['style']) != style:
            self.message.configure(text=message, style=style)
            if message:
                self.message.grid(row=0, column=0, sticky='ew', padx=self.message_pad[0], pady=(self.theme.px(6) if self.theme else 6, 0))
            else:
                self.message.grid_remove()
            # Changing a child's requested height does not always notify the
            # scroll canvas, so recompute its region explicitly.
            self.transfer_body.schedule()
        if self.tab == 'log':
            self.render_log(job)

    def render_log(self, job):
        lines = job.log_lines
        state = (job.id, len(lines), lines[-1] if lines else '')
        if state == self.log_state:
            return
        self.log_state = state
        text = self.log_text
        at_end = text.yview()[1] >= 0.999
        tail = list(lines)[-LOG_TAIL:]
        text.configure(state='normal')
        text.delete('1.0', 'end')
        text.insert('1.0', '\n'.join(tail) or 'No tool output yet. It appears here once the export starts.')
        text.configure(state='disabled')
        if at_end:
            text.yview_moveto(1)

    # -- actions ---------------------------------------------------------
    def cancel_current(self):
        if self.selected:
            self.cancel(self.selected)

    def copy_path(self):
        view = self.cards.get(self.selected)
        if view:
            self.clipboard_clear()
            self.clipboard_append(str(view.job.target))
            self.notify('Path copied to the clipboard.')

    def open_folder(self):
        view = self.cards.get(self.selected)
        if not view:
            return
        folder = view.job.target.parent
        try:
            open_folder(folder)
        except (OSError, subprocess.SubprocessError) as error:
            self.notify('The folder could not be opened: ' + str(error))

    # -- summary ---------------------------------------------------------
    def counts(self):
        views = list(self.cards.values())
        return dict(
            active=sum(v.state in ACTIVE_STATES for v in views),
            queued=sum(v.state == 'queued' for v in views),
            done=sum(v.state in ('done', 'done_warning') for v in views),
            failed=sum(v.state == 'failed' for v in views),
            attention=sum(v.state in ('cleanup_required', 'stalled', 'done_warning') for v in views),
            rate=sum(v.speed for v in views if v.state == 'running') / 1_000_000)

    def update_summary(self):
        counts = self.counts()
        parts = [f'{counts[key]} {label}' for key, label in (('active', 'exporting'), ('queued', 'queued'),
                 ('done', 'completed'), ('failed', 'failed'), ('attention', 'need attention')) if counts[key]]
        text = ', '.join(parts) if parts else 'Nothing queued yet'
        if counts['active']:
            text += f", {counts['rate']:.1f} MB/s combined"
        self.summary.set(text)
        self.on_summary(counts)
