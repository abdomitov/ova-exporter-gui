"""Presentation state for export tasks; contains no Tk widgets."""
import time
from dataclasses import dataclass, field
from jobs import TERMINAL


@dataclass
class TaskView:
    job: object
    state: str = 'queued'
    percent: float = 0
    speed: float = 0
    written: int = 0
    elapsed: float = 0
    peak: float = 0
    history: list = field(default_factory=list)
    detail: str = 'Waiting for an export slot.'
    started: str = ''
    ended: str = ''

    def update(self, kind, value):
        if self.state in TERMINAL:
            return
        if kind == 'running':
            self.state = 'running'
            self.started = time.strftime('%H:%M:%S')
            self.detail = 'Preparing export…'
        elif kind == 'progress':
            self.percent = max(self.percent, float(value))
            if self.state == 'running':
                self.detail = 'Exporting virtual disk…'
        elif kind == 'sample' and self.state == 'running':
            self.speed, self.written, self.elapsed = value['speed'], value['bytes'], value['elapsed']
            self.peak = max(self.peak,self.speed)
            point = (self.percent,max(0,self.speed))
            if self.history and self.history[-1][0] == self.percent:
                self.history[-1] = point
            else:
                self.history.append(point)
        elif kind == 'verifying':
            self.state = 'verifying'
            self.percent = 100
            self.detail = 'Transfer finished. Verifying checksums…'
        elif kind == 'status':
            self.detail = value
        elif kind in ('cancelling','cleaning','stalled','force_stopping'):
            self.state = kind
            self.speed = 0
            self.detail = value
        elif kind in TERMINAL:
            self.state = kind
            self.ended = time.strftime('%H:%M:%S')
            self.percent = 100 if kind in ('done','done_warning') else self.percent
            self.detail = value

    def status_text(self):
        return {'queued':'Queued','running':'Exporting' if self.percent else 'Preparing',
                'verifying':'Verifying','cancelling':'Cancelling','cleaning':'Checking cleanup',
                'stalled':'Cancellation stalled',
                'force_stopping':'Stopping local tool',
                'cleanup_required':'Needs attention','done':'Completed','done_warning':'Saved; check VM',
                'failed':'Failed','cancelled':'Cancelled'}[self.state]

