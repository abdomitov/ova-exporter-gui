"""Repeatable fake-data UI workload; blocks network, tools and user settings.

Run: python tools/benchmark_ui.py --output artifacts/ui-benchmark.json
This measures UI event handling, not VMware or network throughput.
"""
import argparse
import json
import sys
import time
import tkinter as tk
from pathlib import Path
from unittest.mock import patch

from preview_ui import MemorySettings, DemoClient, machine, application


def benchmark():
    root = tk.Tk()
    root.withdraw()
    app = application.App(root, settings=MemorySettings(), remember_theme=False,
                          tool_store=False, tool_locator=lambda *args: Path(sys.executable),
                          update_checks=False)
    jobs = []
    for index in range(32):
        job = app.manager.add(DemoClient(f'192.0.2.{index+1}'), machine(index, f'Example {index}'),
                              Path(f'example-{index}.ova'))
        app.dashboard.add(job)
        job.state = 'running'
        app.dashboard.handle(job.id, 'running', None)
        jobs.append(job)
    app.dashboard.tree.selection_set(jobs[0].id)
    app.dashboard.selection_changed()
    root.update_idletasks()

    def workload(hidden=False):
        if hidden:
            app.dashboard.hide_details()
        for index in range(2000):
            job = jobs[index % len(jobs)]
            app.emit('job', (job.id, 'progress', (index // len(jobs)) % 100))
            app.emit('job', (job.id, 'sample', dict(speed=20_000_000, bytes=index*1_000_000,
                                                  elapsed=index+1)))
        started = time.perf_counter()
        heartbeat = []
        root.after(10, lambda: heartbeat.append(time.perf_counter()-started))
        cpu = time.process_time()
        with patch.object(app.dashboard.panel, 'draw', wraps=app.dashboard.panel.draw) as draws, \
                patch.object(app, 'refresh_tool', wraps=app.refresh_tool) as tool_checks:
            app.poll()
            while not app.events.empty() or not heartbeat:
                root.update()
            root.update_idletasks()
            return dict(events=4000, cpu_seconds=round(time.process_time()-cpu, 4),
                        wall_seconds=round(time.perf_counter()-started, 4),
                        heartbeat_delay_ms=round(heartbeat[0]*1000, 2),
                        chart_draws=draws.call_count, tool_refreshes=tool_checks.call_count)

    try:
        result = {'visible_details': workload(), 'hidden_details': workload(hidden=True)}
        polls = []
        original_poll = app.poll
        def count_poll():
            polls.append(1)
            original_poll()
        app.poll = count_poll
        # Empty dashboard represents an idle app (no active worker or update).
        app.manager.jobs.clear()
        done = tk.BooleanVar(root, False)
        cpu = time.process_time()
        root.after(2000, lambda: done.set(True))
        root.wait_variable(done)
        result['idle_2_seconds'] = dict(polls=len(polls), cpu_seconds=round(time.process_time()-cpu, 4))
        result['python'] = sys.version.split()[0]
        return result
    finally:
        for token in root.tk.call('after', 'info'):
            root.tk.call('after', 'cancel', token)
        root.destroy()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = benchmark()
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(result, indent=2))
