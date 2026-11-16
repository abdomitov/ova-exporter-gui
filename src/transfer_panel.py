"""One canvas showing where an export is: stage track, statistics and speed history.

OVF Tool exports pass through a fixed sequence, so the progress bar is drawn as
that sequence: preflight, transfer, checksum verification and the read-only
server check. The transfer segment fills with the tool's reported percentage.
"""
import tkinter as tk
from tkinter import ttk

from theme import PALETTES, theme_for

STAGES = (('Preflight', 2.2), ('Transfer', 5.0), ('Verify', 1.6), ('Server check', 2.4))

TITLES = {
    'idle': 'Ready to export', 'preparing': 'Preparing export', 'queued': 'Waiting in the queue',
    'cancelling': 'Cancelling export', 'cleaning': 'Checking server cleanup',
    'cleanup_required': 'Server cleanup needs attention', 'stalled': 'Cancellation stalled',
    'force_stopping': 'Stopping the local export tool', 'exporting': 'Exporting virtual machine',
    'verifying': 'Verifying your OVA', 'done': 'Export complete',
    'done_warning': 'OVA saved and verified', 'error': 'Export stopped',
}
HINTS = {
    'idle': 'Progress and speed will appear here.', 'queued': 'Starts when this server is free.',
    'verifying': 'Checking every file against the manifest.', 'done': 'Your OVA is ready to use.',
    'done_warning': 'Check the VM state in the message above.',
    'cancelling': 'Waiting for OVF Tool to stop.', 'cleaning': 'Confirming the server released the export.',
    'cleanup_required': 'Review this VM in vCenter.', 'stalled': 'OVF Tool has not exited.',
    'force_stopping': 'Server cleanup will remain unconfirmed.',
}


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


def stage_states(phase, value):
    """Return one of todo/active/done/warning/problem for each stage."""
    if phase in ('idle', 'queued'):
        return ['todo'] * 4
    if phase == 'done':
        return ['done'] * 4
    if phase == 'done_warning':
        return ['done', 'done', 'done', 'warning']
    reached = 0 if value <= 0 else 1 if value < 100 else 2
    if phase == 'verifying':
        reached = 2
    if phase == 'cleaning':
        # The server check also runs after a stopped transfer; keep that visible.
        states = ['done'] * reached + ['warning' if reached < 2 else 'done'] + ['todo'] * 3
        states = states[:3] + ['active']
        return states
    if phase == 'cleanup_required':
        return (['done'] * reached + ['warning'] + ['todo'] * 3)[:3] + ['problem']
    mark = {'cancelling': 'warning', 'stalled': 'problem', 'force_stopping': 'problem',
            'error': 'problem'}.get(phase, 'active')
    return (['done'] * reached + [mark] + ['todo'] * 3)[:4]


class TransferPanel(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent, style='Surface.TFrame')
        self.phase = 'idle'
        self.value = 0
        self.elapsed = 0
        self.speed = 0
        self.written = 0
        self.history = []
        self.peak_speed = 0
        self.detail = ''
        self.colors = PALETTES['light']
        self.theme = theme_for(self)
        self.px = self.theme.px if self.theme else round
        self.font = self.theme.font if self.theme else (lambda role='body', size=10, weight='normal': ('TkDefaultFont', size, weight))
        self.canvas = tk.Canvas(self, height=self.px(370), highlightthickness=0, borderwidth=0)
        self.canvas.pack(fill='both', expand=True)
        self.canvas.bind('<Configure>', lambda event: self.draw())
        if self.theme:
            self.theme.register(self)
        self.draw()

    def apply_theme(self, colors):
        self.colors = colors
        self.draw()

    def draw(self):
        canvas, c, px, font = self.canvas, self.colors, self.px, self.font
        canvas.delete('all')
        width, height = max(canvas.winfo_width(), px(320)), max(canvas.winfo_height(), px(300))
        canvas.configure(background=c['surface'])
        pad = px(22)
        left, right = pad, width - pad
        states = stage_states(self.phase, self.value)
        problem = 'problem' in states
        warning = 'warning' in states
        ink = c['negative'] if problem else c['warning'] if warning else c['positive'] if self.phase == 'done' else c['text']

        # Percentage and what is happening now.
        number = canvas.create_text(left - px(2), pad - px(10), text=f'{self.value:.0f}%' if self.phase != 'idle' else '—',
                                    anchor='nw', fill=ink, font=font('numeric', 44, 'bold'))
        box = canvas.bbox(number)
        text_x = max(left + px(128), box[2] + px(20))
        canvas.create_text(text_x, pad - px(2), text=TITLES.get(self.phase, self.phase), anchor='nw',
                           width=max(px(120), right - text_x), fill=c['text'], font=font('display', 14, 'bold'))
        if self.phase == 'error':
            hint = 'The reason is shown above.'
        else:
            hint = HINTS.get(self.phase) or remaining_text(self.elapsed, self.value, self.speed)
        canvas.create_text(text_x, pad + px(26), text=hint, anchor='nw', width=max(px(120), right - text_x),
                           fill=c['muted'], font=font('body', 10))
        canvas.create_text(text_x, pad + px(46), text=self.detail, anchor='nw', width=max(px(120), right - text_x),
                           fill=c['muted'], font=font('body', 9), tags='transfer_detail')

        # Stage track: four rounded segments sized by how long each stage usually takes.
        top = pad + px(92)
        bar, gap = px(8), px(12)
        middle = top + bar / 2
        total = sum(weight for _, weight in STAGES)
        usable = right - left - gap * (len(STAGES) - 1)
        x = left
        assets = self.theme.assets if self.theme else None
        for (label, weight), state in zip(STAGES, states):
            end = x + usable * weight / total
            start, stop = x + bar / 2, end - bar / 2
            canvas.create_line(start, middle, stop, middle, fill=c['track'], width=bar, capstyle='round', tags='stage_track')
            fill = {'done': c['accent'], 'active': c['graph'], 'warning': c['warning'],
                    'problem': c['negative']}.get(state)
            if label == 'Transfer' and state != 'done' and 0 < self.value < 100:
                canvas.create_line(start, middle, start + (stop - start) * self.value / 100, middle, width=bar,
                                   fill=c['accent'] if state == 'active' else fill or c['accent'],
                                   capstyle='round', tags='progress_fill')
            elif fill:
                canvas.create_line(start, middle, stop, middle, fill=fill, width=bar, capstyle='round',
                                   tags='progress_fill' if label == 'Transfer' else 'stage_fill')
            current = state in ('active', 'warning', 'problem')
            label_x = x
            if assets:
                canvas.create_image(x, top + bar + px(17), anchor='w', image=assets.get(f'stage_{state}_card'), tags='stage_mark')
                label_x = x + px(22)
            canvas.create_text(label_x, top + bar + px(17), text=label, anchor='w',
                               fill={'problem': c['negative'], 'warning': c['warning']}.get(state, c['text'] if state != 'todo' else c['muted']),
                               font=font('body', 9, 'bold' if current else 'normal'), tags='stage_label')
            x = end + gap

        # Statistics, separated by hairlines.
        top += px(58)
        finished_transfer = self.phase in ('done', 'done_warning', 'verifying')
        rate = self.written / self.elapsed if finished_transfer and self.elapsed > 0 else self.speed
        metrics = [('Average speed' if finished_transfer else 'Speed', f'{rate / 1_000_000:.1f} MB/s'),
                   ('Written', size_text(self.written)), ('Elapsed', duration_text(self.elapsed)),
                   ('Peak', f'{self.peak_speed / 1_000_000:.1f} MB/s')]
        canvas.create_line(left, top - px(12), right, top - px(12), fill=c['grid'])
        for index, (label, value) in enumerate(metrics):
            x = left + index * (right - left) / len(metrics)
            if index:
                canvas.create_line(x - px(14), top, x - px(14), top + px(40), fill=c['grid'])
            canvas.create_text(x, top, text=label, anchor='nw', fill=c['muted'], font=font('body', 9))
            canvas.create_text(x, top + px(18), text=value, anchor='nw', fill=c['text'],
                               font=font('numeric', 14 if right - left >= px(400) else 12, 'bold'),
                               tags='speed_peak' if label == 'Peak' else 'stat')

        # Speed history, plotted against progress so its width matches the track.
        top, bottom = top + px(78), height - pad
        if bottom - top < px(40):
            return
        for fraction in (0, 0.5, 1):
            y = bottom - (bottom - top) * fraction
            canvas.create_line(left, y, right, y, fill=c['grid'], dash=() if not fraction else (3, 4), tags='speed_grid')
        if self.history:
            ceiling = max(1_000_000, self.peak_speed * 1.15)
            points = []
            for percent, speed in self.history:
                points.extend((left + (right - left) * percent / 100,
                               bottom - min(max(speed, 0) / ceiling, 1) * (bottom - top)))
            if len(points) >= 4:
                canvas.create_polygon([points[0], bottom] + points + [points[-2], bottom],
                                      fill=c['graph'], outline='', tags='speed_history')
                canvas.create_line(*points, fill=c['graph_line'], width=px(2), tags='speed_outline')
            canvas.create_text(right, top - px(4), text=f'{ceiling / 1_000_000:.0f} MB/s', anchor='se',
                               fill=c['muted'], font=font('body', 8))
            canvas.create_text(left, top - px(4), text='Speed across the transfer', anchor='sw',
                               fill=c['muted'], font=font('body', 8))
        else:
            canvas.create_text((left + right) / 2, (top + bottom) / 2, text='Transfer speed will be drawn here',
                               fill=c['muted'], font=font('body', 9), tags='speed_hint')
