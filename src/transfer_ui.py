"""One large progress surface containing transfer state and statistics."""
import tkinter as tk
from tkinter import ttk
from theme import PALETTES, theme_for


def size_text(value):
    return f'{value / 1_000_000_000:.2f} GB' if value >= 1_000_000_000 else f'{value / 1_000_000:.1f} MB'


def duration_text(seconds):
    seconds = max(0, int(seconds))
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    return f'{hours}:{minutes:02d}:{seconds:02d}' if hours else f'{minutes}:{seconds:02d}'


def remaining_text(elapsed, percent, speed):
    if percent >= 100:
        return 'Finishing transfer…'
    if speed <= 0 and percent > 0:
        return 'Waiting for data…'
    if percent <= 0 or elapsed < 5:
        return 'Calculating time remaining…'
    seconds = elapsed * (100 - percent) / percent
    return 'About ' + duration_text(max(1, seconds)) + ' remaining'


class TransferPanel(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self.phase = 'idle'
        self.value = 0
        self.elapsed = 0
        self.speed = 0
        self.written = 0
        self.history = []
        self.peak_speed = 0
        self.detail = 'Choose a virtual machine and press Export to OVA.'
        self.colors = PALETTES['dark']
        self.canvas = tk.Canvas(self, height=250, highlightthickness=1)
        self.canvas.pack(fill='both', expand=True)
        self.canvas.bind('<Configure>', lambda event: self.draw())
        theme = theme_for(self)
        if theme:
            theme.register(self)
        self.draw()

    def apply_theme(self, colors):
        self.colors = colors
        self.draw()

    def reset(self):
        self.phase = 'preparing'
        self.value = self.elapsed = self.speed = self.written = 0
        self.history.clear()
        self.peak_speed = 0
        self.detail = 'Preparing export…'
        self.draw()

    def set_status(self, text):
        self.detail = text
        self.draw()

    def set_progress(self, value):
        if self.phase not in ('preparing', 'exporting'):
            return
        self.phase = 'exporting'
        self.value = max(self.value, min(100, max(0, float(value))))
        self.draw()

    def sample(self, sample):
        if self.phase not in ('preparing', 'exporting'):
            return
        self.speed = sample['speed']
        self.elapsed = sample['elapsed']
        self.written = sample['bytes']
        self.peak_speed = max(self.peak_speed, self.speed)
        point = (self.value, max(0, self.speed))
        if self.history and self.history[-1][0] == self.value:
            self.history[-1] = point
        else:
            self.history.append(point)
        if self.written > 0:
            self.phase = 'exporting'
        self.draw()

    def finish(self, phase):
        self.phase = phase
        if phase in ('verifying', 'done'):
            self.value = 100
        self.draw()

    def draw(self):
        canvas, c = self.canvas, self.colors
        canvas.delete('all')
        width, height = max(canvas.winfo_width(), 300), max(canvas.winfo_height(), 250)
        problem = self.phase in ('error', 'cleanup_required', 'stalled', 'force_stopping')
        fill = c['error_fill'] if problem else c['warning_fill'] if self.phase == 'done_warning' else c['progress']
        ink = c['negative'] if problem else c['warning'] if self.phase == 'done_warning' else c['positive']
        canvas.configure(highlightbackground=c['border'])
        canvas.create_rectangle(0, 0, width, height, fill=c['surface'], outline='')
        if self.value:
            canvas.create_rectangle(0, 0, width * self.value / 100, height, fill=fill, outline='', tags='progress_fill')
        title = {
            'idle':'Ready to export', 'preparing':'Preparing export', 'queued':'Queued for export',
            'cancelling':'Cancelling export', 'cleaning':'Checking server cleanup',
            'cleanup_required':'Server cleanup needs attention', 'stalled':'Cancellation stalled',
            'force_stopping':'Stopping the local export tool', 'exporting':'Exporting virtual machine',
            'verifying':'Verifying your OVA', 'done':'Export complete',
            'done_warning':'OVA saved and verified', 'error':'Export stopped',
        }.get(self.phase, self.phase)
        canvas.create_text(20, 17, text=title, width=width-185, anchor='nw',
                           fill=c['text'], font=('Segoe UI', 14, 'bold'))
        if self.phase != 'idle':
            canvas.create_text(width-20, 53, text=f'{self.value:g}%', anchor='ne',
                               fill=ink, font=('Segoe UI', 26, 'bold'))
        eta = {
            'idle':'Progress and speed will appear here.', 'queued':'Waiting for an export slot',
            'verifying':'Checking every file against the manifest', 'done':'Your OVA is ready to use.',
            'done_warning':'Check the VM state in the details below.',
            'error':'Export cancelled.' if 'cancel' in self.detail.lower() else 'See the task message below.',
            'cancelling':'Waiting for OVF Tool to stop.', 'cleaning':'Confirming the server released the export.',
            'cleanup_required':'Review this VM in vCenter.', 'stalled':'OVF Tool has not exited.',
            'force_stopping':'Server cleanup will remain unconfirmed.',
        }.get(self.phase, remaining_text(self.elapsed, self.value, self.speed))
        canvas.create_text(20, 48, text=eta, width=width-180, anchor='nw',
                           fill=c['text'], font=('Segoe UI', 10))
        finished_transfer = self.phase in ('done','done_warning','verifying')
        rate = self.written/self.elapsed if finished_transfer and self.elapsed > 0 else self.speed
        metrics = [('AVERAGE SPEED' if finished_transfer else 'TRANSFER SPEED', f'{rate/1_000_000:.1f} MB/s'),
                   ('WRITTEN', size_text(self.written)), ('ELAPSED', duration_text(self.elapsed))]
        for index, (label, value) in enumerate(metrics):
            x = 20 + index * (width-40)/3
            canvas.create_text(x, 91, text=label, anchor='nw', fill=c['text'], font=('Segoe UI', 8, 'bold'))
            canvas.create_text(x, 109, text=value, anchor='nw', fill=c['text'], font=('Segoe UI', 13, 'bold'))
        canvas.create_text(20, 140, text=self.detail, width=width-170, anchor='nw',
                           fill=c['text'], font=('Segoe UI', 9), tags='transfer_detail')
        canvas.create_text(width-20, 143, text=f'Peak {self.peak_speed/1_000_000:.1f} MB/s', anchor='ne',
                           fill=c['text'], font=('Segoe UI', 9), tags='speed_peak')
        left, right, top, bottom = 20, width-20, 174, height-16
        for fraction in (0, 0.5, 1):
            y = bottom - (bottom-top)*fraction
            canvas.create_line(left,y,right,y,fill=c['grid'],tags='speed_grid')
        for percent in range(0, 101, 10):
            x = left+(right-left)*percent/100
            canvas.create_line(x,top,x,bottom,fill=c['grid'],tags='speed_grid')
        if self.history:
            ceiling = max(1_000_000,self.peak_speed*1.15)
            points = []
            for percent, speed in self.history:
                points.extend((left+(right-left)*percent/100,bottom-min(max(speed,0)/ceiling,1)*(bottom-top)))
            if len(points) >= 4:
                canvas.create_polygon([points[0],bottom]+points+[points[-2],bottom],
                                      fill=c['graph'],outline='',tags='speed_history')
                canvas.create_line(*points,fill=c['graph_line'],width=2,tags='speed_outline')
        else:
            canvas.create_text(left+10,(top+bottom)/2,text='Transfer speed history',anchor='w',
                               fill=c['muted'],font=('Segoe UI',9),tags='speed_hint')
