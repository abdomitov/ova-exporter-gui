"""Independent export jobs and a bounded, per-endpoint scheduler."""
import os
import queue
import shutil
import subprocess
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

from exporter import export_command, ProgressParser, TransferTracker, verify_ova
from vsphere import fingerprint
from diagnostics import machine_error_messages
from output_paths import EXPORT_ID_LENGTH, validate_output_name

TERMINAL = {'done', 'done_warning', 'failed', 'cancelled', 'cleanup_required'}
ABORT_NOTICE_SECONDS = 60
CLEANUP_CHECK_SECONDS = 60
CLEANUP_POLL_SECONDS = 2


class Cancelled(Exception):
    pass


@dataclass
class ExportJob:
    client: object
    vm: dict
    target: Path
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:EXPORT_ID_LENGTH])
    state: str = 'queued'
    cancelled: threading.Event = field(default_factory=threading.Event)
    process: object = None
    secret: str = ''
    log_lines: object = field(default_factory=lambda: deque(maxlen=5000))
    log_file: object = None
    export_started: bool = False
    abort_sent: bool = False
    abort_acknowledged: bool = False
    force_requested: threading.Event = field(default_factory=threading.Event)

    @property
    def endpoint(self):
        return self.client.authority.casefold()

    @property
    def can_cancel(self):
        # Queue/local cancellation requires no server-transfer risk override.
        return (self.state in ('queued', 'verifying') and not self.cancelled.is_set() and
                (self.process is None or self.process.poll() is not None))

    @property
    def can_request_cancel(self):
        return self.state in ('queued', 'running', 'verifying') and not self.cancelled.is_set()

    @property
    def can_force_stop(self):
        return (self.state not in TERMINAL and self.process is not None and self.process.poll() is None and
                (self.cancelled.is_set() or self.state in ('cleaning', 'stalled', 'force_stopping')))

    def check(self):
        if self.cancelled.is_set():
            raise Cancelled('Export cancelled. Any partial package remains marked .incomplete.')


class JobManager:
    def __init__(self, tool, emit, limit=3, runner=None, log_dir=None):
        self.tool = Path(tool)
        self.emit = emit
        self.limit = limit
        self.runner = runner or self.export
        self.log_dir = Path(log_dir) if log_dir else None
        self.jobs = {}
        self.waiting = []
        self.active = set()
        self.stopping = False
        # Remember uncertain cleanup for this app session. A later job must
        # recheck the affected VM, using its own fresh session, before exporting.
        self.pending_cleanup = {}
        self.condition = threading.Condition(threading.RLock())

    def conflicts(self, endpoint, vm_id, target):
        name = os.path.normcase(str(Path(target).resolve()))
        with self.condition:
            return any(job.state not in TERMINAL and
                       (os.path.normcase(str(job.target.resolve())) == name or
                        (job.endpoint == endpoint.casefold() and job.vm['id'] == vm_id))
                       for job in self.jobs.values())

    def add(self, client, vm, target):
        with self.condition:
            if self.stopping:
                raise RuntimeError('The app is stopping export tasks before closing.')
            if self.conflicts(client.authority, vm['id'], target):
                raise ValueError('This VM or output filename already has an unfinished task.')
            job = ExportJob(client, vm.copy(), Path(target))
            self.jobs[job.id] = job
            self.waiting.append(job.id)
            return job

    def start(self, job):
        threading.Thread(target=self.run, args=(job,), daemon=True).start()

    def send(self, job, kind, value=None):
        if isinstance(value, str) and job.secret:
            value = value.replace(job.secret, '[session ticket]')
        self.emit('job', (job.id, kind, value))

    def record(self, job, text):
        text = str(text)
        for secret in (job.secret, getattr(job.client, 'cookie', '')):
            if secret:
                text = text.replace(secret, '[redacted]')
        import re
        text = re.sub(r'vi://[^\s@]+@', 'vi://[credentials]@', text)
        job.log_lines.append(text)
        return text

    def save_log(self, job):
        if not self.log_dir:
            return
        try:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            path = self.log_dir / f'task-{job.id}.log'
            path.write_text('\n'.join(job.log_lines), encoding='utf-8')
            job.log_file = path
        except OSError as error:
            job.log_lines.append('Could not save diagnostic log: ' + str(error))

    def run(self, job):
        outcome, message = 'failed', 'Export did not finish.'
        self.record(job, f"VM: {job.vm['name']}\nSource: {job.client.authority}\nDestination: {job.target}")
        try:
            # Waiting sessions are refreshed without keeping any password.
            while True:
                job.check()
                with self.condition:
                    busy_hosts = {self.jobs[key].endpoint for key in self.active}
                    first = next((key for key in self.waiting if self.jobs[key].endpoint == job.endpoint), None)
                    if len(self.active) < self.limit and job.endpoint not in busy_hosts and first == job.id:
                        self.waiting.remove(job.id)
                        self.active.add(job.id)
                        job.state = 'running'
                        break
                    notified = self.condition.wait(timeout=60)
                if not notified:
                    job.client.call('CurrentTime', '<_this type="ServiceInstance">ServiceInstance</_this>')
            job.check()
            self.send(job, 'running')
            count = self.runner(job)
            outcome, message = 'done', f'{count} file checksums verified. Saved to {job.target}'
        except Cancelled as error:
            outcome, message = 'cancelled', str(error)
        except Exception as error:
            outcome, message = 'failed', str(error)
        finally:
            # Graceful cancellation waits for lease cleanup. Force termination
            # is a separate, explicitly confirmed override handled by force_stop.
            if job.process and job.process.poll() is None:
                self.request_abort(job)
                try:
                    self.wait_for_tool(job)
                except Exception as error:
                    outcome, message = 'failed', str(error)
            if job.export_started:
                if job.force_requested.is_set():
                    ready, detail = False, 'The local tool was force-stopped at your request; server cleanup is unconfirmed.'
                else:
                    ready, detail = self.confirm_cleanup(job)
                if not ready:
                    with self.condition:
                        self.pending_cleanup.setdefault(job.endpoint, {})[job.vm['id']] = detail
                    # Package integrity and VM management state are separate.
                    # A verified, saved OVA remains a successful download even
                    # when the source VM still needs administrator follow-up.
                    outcome = 'done_warning' if outcome == 'done' else 'cleanup_required'
                    message += (' VM state/cleanup could not be confirmed: ' + detail +
                                ' Check this VM in vCenter before powering it on.'
                                ' An administrator may need to resolve the ESXi export-state issue (Broadcom KB 334593).')
                else:
                    message += ' Server check: ' + detail
            if job.force_requested.is_set():
                # A confirmed local stop must not wait on another possibly
                # stalled management request before reporting its outcome.
                threading.Thread(target=self.logout_session, args=(job.client,), daemon=True).start()
            else:
                self.logout_session(job.client)
            message = self.record(job, message)
            self.save_log(job)
            job.secret = ''
            with self.condition:
                if job.id in self.waiting:
                    self.waiting.remove(job.id)
                self.active.discard(job.id)
                job.state = outcome
                self.condition.notify_all()
            self.send(job, outcome, message)

    @staticmethod
    def logout_session(client):
        try:
            client.logout()
        except Exception:
            pass

    def cancel(self, job_id, *, allow_remote=False):
        job = self.jobs[job_id]
        with self.condition:
            remote_override = allow_remote and job.state == 'running' and not job.cancelled.is_set()
            if not job.can_cancel and not remote_override:
                return False
            job.cancelled.set()
            if job.id in self.active:
                job.state = 'cancelling'
                message = ('Waiting for OVF Tool to abort and release its server lease. Cancellation can stall…'
                           if remote_override else 'Stopping local checksum verification; the server transfer has already ended…')
                self.send(job, 'cancelling', message)
            self.condition.notify_all()
            return True

    def force_stop(self, job_id, *, confirmed=False):
        """Only terminate this job's own Popen handle after a separate warning."""
        if not confirmed:
            return False
        job = self.jobs[job_id]
        with self.condition:
            if job.state in TERMINAL:
                return False
            job.cancelled.set()
            job.force_requested.set()
            process = job.process
            if process is not None and process.poll() is None:
                job.state = 'force_stopping'
                self.send(job, 'force_stopping', 'Stopping the local OVF Tool at your request. Server cleanup is unconfirmed.')
                self.record(job, 'User confirmed force-stop of this task\'s local OVF Tool. VM power-on may require administrator recovery.')
                try:
                    process.terminate()
                except OSError as error:
                    self.record(job, 'Local tool could not be stopped: '+str(error))
                    self.send(job, 'stalled', 'Could not stop the local tool: '+str(error))
            self.condition.notify_all()
            return True

    def stop_all(self, *, force=False, confirmed=False):
        if not confirmed:
            return False
        # Freeze new submissions and cancel queued tasks before any can start.
        with self.condition:
            self.stopping = True
            for job in self.jobs.values():
                if job.state not in TERMINAL:
                    if force:
                        self.force_stop(job.id, confirmed=True)
                    else:
                        self.cancel(job.id, allow_remote=True)
            self.condition.notify_all()
        return True

    def local_tools_stopped(self):
        with self.condition:
            return all(job.process is None or job.process.poll() is not None for job in self.jobs.values())

    def resume_submissions(self):
        with self.condition:
            self.stopping = False
            self.condition.notify_all()

    def request_abort(self, job):
        """Send the supported machine-mode abort once, from the worker thread."""
        if job.force_requested.is_set() or job.abort_sent or not job.process or job.process.poll() is not None:
            return
        job.abort_sent = True
        job.state = 'cancelling' if job.cancelled.is_set() else 'cleaning'
        self.send(job, job.state, 'Waiting for OVF Tool to finish server cleanup. Keep this app open…')
        try:
            job.process.stdin.write('ABORT\n')
            job.process.stdin.flush()
            self.record(job, 'Abort requested; waiting for OVF Tool to exit without forcing termination.')
        except (OSError, ValueError) as error:
            self.record(job, 'Could not deliver abort: ' + str(error))
            self.send(job, 'status', 'OVF Tool did not accept the stop request. Waiting for it to exit; server cleanup is unconfirmed.')
        finally:
            # No further commands will be sent after ABORT. End the input stream
            # so a machine-mode input reader need not wait on our open pipe.
            # EOF is not a process kill and does not assert that its lease ended.
            try:
                job.process.stdin.close()
                self.record(job, 'OVF Tool input pipe closed after the abort request (EOF).')
            except (OSError, ValueError) as error:
                self.record(job, 'Could not close OVF Tool input: ' + str(error))

    def report_stalled_cancellation(self, job):
        """Inspect the server even if the aborted tool never closes its output."""
        if job.force_requested.is_set():
            return
        pid = getattr(job.process, 'pid', 'unknown')
        acknowledgement = 'acknowledged the abort' if job.abort_acknowledged else 'not confirmed the abort'
        self.record(job, f'Cancellation stalled: OVF Tool PID {pid} has {acknowledgement} and has not exited.')
        self.send(job, 'stalled', 'OVF Tool has not exited. Checking the server without changing VM state…')
        try:
            ready, detail = job.client.export_readiness(job.vm['id'], cleanup=True)
            state = ('The server currently reports no export restriction; the local tool is still running.'
                     if ready else 'The server still reports a restriction or active export: ' + detail)
        except Exception as error:
            state = 'Server state could not be checked: ' + str(error)
        self.record(job, state)
        if job.process.poll() is None:
            job.state = 'stalled'
            self.send(job, 'stalled', state + ' Cleanup remains unconfirmed. Review this VM in vCenter; '
                      'do not treat the abort message as successful cleanup. No tool or host service was force-restarted.')

    def wait_for_tool(self, job):
        """Drain output even while cancelling, including when the tool is silent."""
        output = queue.Queue()
        def read_output():
            try:
                for line in job.process.stdout:
                    output.put(line)
            except Exception as error:
                output.put(error)
            finally:
                output.put(None)
        reader = threading.Thread(target=read_output, daemon=True)
        reader.start()
        parser = ProgressParser()
        eof, failure, abort_time, warned = False, None, None, False
        try:
            while not eof or job.process.poll() is None:
                if job.force_requested.is_set() and job.process.poll() is not None:
                    break
                if job.cancelled.is_set() or failure:
                    self.request_abort(job)
                if job.abort_sent and abort_time is None:
                    abort_time = time.monotonic()
                if abort_time is not None and not warned and time.monotonic() - abort_time >= ABORT_NOTICE_SECONDS:
                    warned = True
                    if job.process.poll() is None:
                        self.report_stalled_cancellation(job)
                try:
                    item = output.get(timeout=0.2)
                except queue.Empty:
                    continue
                if item is None:
                    eof = True
                    continue
                if isinstance(item, Exception):
                    failure = failure or RuntimeError('Could not read OVF Tool output: ' + str(item))
                    continue
                line = item.strip()
                value = parser.feed(line)
                if value is not None:
                    self.send(job, 'progress', value)
                elif line:
                    self.record(job, line)
                if '<type>ovftool.abort</type>' in line.casefold() and not job.abort_acknowledged:
                    job.abort_acknowledged = True
                    self.record(job, 'OVF Tool acknowledged the abort. This does not confirm release of the server lease.')
                    if not warned:
                        self.send(job, 'status', 'Abort acknowledged by OVF Tool. Waiting for it to exit and release its server lease…')
                if line.startswith('AUTHENTICATION'):
                    failure = failure or RuntimeError('The export session was rejected. Reconnect and add this task again.')
            result = job.process.wait()
            if failure:
                raise failure
            return result
        finally:
            # Reached only after the tool exits in the normal/error/abort paths.
            if job.process.poll() is not None:
                reader.join(timeout=2)
                for stream in (job.process.stdin, job.process.stdout):
                    try:
                        stream.close()
                    except (OSError, ValueError):
                        pass

    def confirm_cleanup(self, job):
        job.state = 'cleaning'
        self.send(job, 'cleaning', 'OVF Tool exited. Checking the server for export restrictions…')
        deadline, clear_reads = time.monotonic() + CLEANUP_CHECK_SECONDS, 0
        detail = 'The server has not confirmed its export state.'
        while True:
            if job.force_requested.is_set():
                return False, 'The local task was force-stopped at your request; server cleanup is unconfirmed.'
            try:
                ready, detail = job.client.export_readiness(job.vm['id'], cleanup=True)
                clear_reads = clear_reads + 1 if ready else 0
                # Two observations help avoid immediately trusting cached state.
                if clear_reads >= 2:
                    return True, detail
            except Exception as error:
                clear_reads = 0
                detail = str(error)
            if time.monotonic() >= deadline:
                return False, detail
            time.sleep(CLEANUP_POLL_SECONDS)

    def check_previous_cleanup(self, job):
        vm_id = job.vm['id']
        with self.condition:
            pending = vm_id in self.pending_cleanup.get(job.endpoint, {})
        if not pending:
            return
        ready, detail = job.client.export_readiness(vm_id)
        if not ready:
            raise RuntimeError('The previous export of this VM still needs cleanup. ' + detail +
                               ' No new export was started. Resolve this VM in vCenter before retrying it; '
                               'other VMs are checked independently.')
        with self.condition:
            self.pending_cleanup.get(job.endpoint, {}).pop(vm_id, None)

    def unfinished(self):
        with self.condition:
            return [job for job in self.jobs.values() if job.state not in TERMINAL]

    def export(self, job):
        temporary = job.target.with_name(job.target.stem + f'.incomplete-{job.id}.ova')
        monitor_stop = threading.Event()
        monitor = None
        try:
            job.check()
            validate_output_name(job.target.name)
            current = next((v for v in job.client.inventory() if v['id'] == job.vm['id']), None)
            if current is None or current['power'] != 'poweredOff':
                raise RuntimeError('VM is no longer powered off. Shut it down normally and add a new task.')
            self.check_previous_cleanup(job)
            ready, detail = job.client.export_readiness(job.vm['id'])
            if not ready:
                raise RuntimeError('The VM is not available for export. ' + detail)
            self.record(job, 'Export preflight: ' + detail)
            if job.target.exists():
                raise RuntimeError('The destination already exists. Choose a new filename.')
            if shutil.disk_usage(job.target.parent).free < 512 * 1024**2:
                raise RuntimeError('Less than 512 MB remains on the destination drive.')
            if not self.tool.is_file():
                raise RuntimeError('OVF Tool was not found. Install VMware OVF Tool from Broadcom, or set OVFTOOL_PATH to ovftool.exe and restart this app.')
            job.secret = job.client.clone_ticket()
            if not job.secret:
                raise RuntimeError('The server did not issue an export ticket.')
            command = export_command(self.tool, job.client.authority, job.vm['id'], job.secret,
                                     fingerprint(job.client.certificate, 'sha1'), temporary)
            with self.condition:
                job.check()
                job.process = subprocess.Popen(command, cwd=self.tool.parent, stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT, stdin=subprocess.PIPE, text=True, encoding='utf-8',
                    errors='replace', creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), bufsize=1)
                job.export_started = True
                self.record(job, f'OVF Tool PID: {job.process.pid}')
            monitor = threading.Thread(target=self.monitor, args=(job, temporary, monitor_stop), daemon=True)
            monitor.start()
            result = self.wait_for_tool(job)
            monitor_stop.set()
            monitor.join(timeout=2)
            job.check()
            if result:
                messages = machine_error_messages(job.log_lines)
                detail = '; '.join(messages) or 'The tool did not provide a readable error. Open Task log for the full output.'
                raise RuntimeError(f'OVF Tool exited with code {result}. {detail} Partial files remain marked .incomplete.')
            with self.condition:
                job.check()
                job.state = 'verifying'
                self.send(job, 'verifying')
            count = verify_ova(temporary, lambda text: self.send(job, 'status', text), job.check)
            with self.condition:
                job.check()
                temporary.rename(job.target)
            return count
        finally:
            monitor_stop.set()
            if monitor:
                monitor.join(timeout=2)

    def monitor(self, job, path, stop):
        tracker = TransferTracker(time.monotonic())
        while not stop.is_set():
            try:
                size = path.stat().st_size
            except OSError:
                size = 0
            self.send(job, 'sample', tracker.sample(time.monotonic(), size))
            if stop.wait(0.5):
                break
