"""Offline regression cases. Fake tools and SOAP responses; no real VM operations.

These tests exercise fake tools only. Do not substitute a live VM or production
OVF Tool process; real-server cancellation requires separate lab authorization.
"""
import queue
import threading
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from dashboard import TaskView
from jobs import Cancelled, ExportJob, JobManager
from vsphere import VSphere


def xml_response(content):
    return ET.fromstring('<root xmlns="urn:vim25"><returnval>' + content + '</returnval></root>')


class FakeTool:
    """Stays alive after ABORT until the test explicitly completes its cleanup."""
    def __init__(self):
        self.lines = queue.Queue()
        self.returncode = None
        self.exited = threading.Event()
        self.abort_received = threading.Event()
        self.stdin = Mock()
        self.stdin.write.side_effect = self.write
        self.stdout = self
        self.closed = False
        self.terminate = Mock(side_effect=AssertionError('Must not terminate a live export'))
        self.kill = Mock(side_effect=AssertionError('Must not kill a live export'))

    def __iter__(self):
        while True:
            item = self.lines.get()
            if item is None:
                return
            if isinstance(item, Exception):
                raise item
            yield item

    def write(self, text):
        if text == 'ABORT\n':
            self.abort_received.set()

    def poll(self):
        return self.returncode

    def finish(self, code=1):
        if not self.exited.is_set():
            self.returncode = code
            self.lines.put(None)
            self.exited.set()

    def wait(self):
        if not self.exited.wait(3):
            raise AssertionError('Test did not finish its fake tool')
        return self.returncode

    def close(self):
        self.closed = True


class CancellationTests(unittest.TestCase):
    def setUp(self):
        # Even an accidental attempt to invoke a real tool or create a network
        # connection must fail immediately in this isolated regression suite.
        for target in ('subprocess.Popen', 'socket.socket'):
            guard = patch(target, side_effect=AssertionError('External access forbidden in offline tests'))
            guard.start()
            self.addCleanup(guard.stop)
        self.events = queue.Queue()
        self.manager = JobManager('unused', lambda *event: self.events.put(event))

    def client(self):
        return SimpleNamespace(authority='example.test', cookie='', logout=Mock(),
                               export_readiness=Mock(return_value=(True, 'No restrictions reported.')))

    def start_tool_job(self, tool):
        job = self.manager.add(self.client(), {'id':'vm-1', 'name':'Offline VM'}, Path('unused.ova'))
        started = threading.Event()
        def runner(job):
            job.process, job.export_started = tool, True
            started.set()
            result = self.manager.wait_for_tool(job)
            job.check()
            if result:
                raise RuntimeError('Fake tool failed')
            return 3
        self.manager.runner = runner
        worker = threading.Thread(target=self.manager.run, args=(job,), daemon=True)
        worker.start()
        self.assertTrue(started.wait(2))
        return job, worker

    def test_silent_tool_failure_waits_for_cleanup_and_keeps_session_and_slot(self):
        tool = FakeTool()
        with patch('jobs.CLEANUP_POLL_SECONDS', 0), patch('jobs.ABORT_NOTICE_SECONDS', 0):
            job, worker = self.start_tool_job(tool)
            try:
                tool.lines.put('AUTHENTICATION\n')
                self.assertTrue(tool.abort_received.wait(2))
                warning = None
                for _ in range(10):
                    _, (_, kind, value) = self.events.get(timeout=2)
                    if kind == 'stalled' and 'Cleanup remains unconfirmed' in value:
                        warning = value
                        break
                self.assertIsNotNone(warning, 'A silent tool must still produce the cleanup warning')
                self.assertIn(job, self.manager.unfinished())
                self.assertIn(job.id, self.manager.active)
                job.client.logout.assert_not_called()
                tool.terminate.assert_not_called()
                tool.kill.assert_not_called()
                tool.lines.put('PROGRESS\n')
                tool.lines.put('+ 40\n')
                tool.lines.put('RESULT\n')
                tool.lines.put('+ CANCELLED\n')
            finally:
                tool.finish()
                worker.join(3)
            self.assertFalse(worker.is_alive())
        self.assertEqual(job.state, 'failed')
        tool.stdin.write.assert_called_once_with('ABORT\n')
        job.client.logout.assert_called_once()
        self.assertEqual(job.client.export_readiness.call_count, 3)
        self.assertIn('+ CANCELLED', job.log_lines)
        self.assertTrue(tool.closed)

    def test_abort_closes_input_so_tool_waiting_for_eof_can_exit(self):
        tool = FakeTool()
        tool.stdin.close.side_effect = tool.finish
        with patch('jobs.CLEANUP_POLL_SECONDS', 0):
            job, worker = self.start_tool_job(tool)
            try:
                tool.lines.put('AUTHENTICATION\n')
                worker.join(3)
                self.assertFalse(worker.is_alive(), 'ABORT must be followed by EOF without waiting for tool exit')
                self.assertEqual(job.state, 'failed')
                tool.stdin.close.assert_called()
                tool.terminate.assert_not_called()
            finally:
                tool.finish()
                worker.join(3)

    def test_abort_acknowledgement_is_not_treated_as_tool_exit(self):
        tool = FakeTool()
        with patch('jobs.CLEANUP_POLL_SECONDS', 0):
            job, worker = self.start_tool_job(tool)
            try:
                tool.lines.put('AUTHENTICATION\n')
                self.assertTrue(tool.abort_received.wait(2))
                tool.lines.put('ERROR\n')
                tool.lines.put('+ <Type>ovftool.abort</Type>\n')
                tool.lines.put('+ <LocalizedMsg>Execution aborted</LocalizedMsg>\n')
                acknowledged = False
                for _ in range(12):
                    _, (_, kind, value) = self.events.get(timeout=2)
                    if kind == 'status' and 'Abort acknowledged' in value:
                        acknowledged = True
                        break
                self.assertTrue(acknowledged)
                self.assertTrue(job.abort_acknowledged)
                self.assertIn(job, self.manager.unfinished())
                job.client.logout.assert_not_called()
            finally:
                tool.finish()
                worker.join(3)
        self.assertFalse(worker.is_alive())

    def test_remote_cancellation_is_not_allowed_without_explicit_override(self):
        tool = FakeTool()
        with patch('jobs.CLEANUP_POLL_SECONDS', 0):
            job, worker = self.start_tool_job(tool)
            try:
                self.assertFalse(job.can_cancel)
                self.assertTrue(job.can_request_cancel)
                self.assertFalse(self.manager.cancel(job.id))
                self.assertFalse(self.manager.cancel(job.id))
                self.assertFalse(job.cancelled.is_set())
                tool.stdin.write.assert_not_called()
            finally:
                tool.finish(0)
                worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(job.state, 'done')

    def test_confirmed_remote_cancel_requests_abort_but_never_forces_termination(self):
        tool = FakeTool()
        with patch('jobs.CLEANUP_POLL_SECONDS', 0):
            job, worker = self.start_tool_job(tool)
            try:
                self.assertTrue(self.manager.cancel(job.id, allow_remote=True))
                self.assertTrue(tool.abort_received.wait(2))
                self.assertTrue(job.can_force_stop)
                tool.terminate.assert_not_called()
                self.assertFalse(job.force_requested.is_set())
            finally:
                tool.finish()
                worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(job.state, 'cancelled')

    def test_force_stop_requires_confirmation_and_only_stops_its_owned_tool(self):
        tool = FakeTool()
        tool.terminate.side_effect = lambda: tool.finish(1)
        job, worker = self.start_tool_job(tool)
        other = self.manager.add(self.client(), {'id':'vm-2','name':'Other VM'}, Path('other.ova'))
        try:
            self.assertFalse(self.manager.force_stop(job.id))
            tool.terminate.assert_not_called()
            self.assertFalse(job.force_requested.is_set())
            self.assertTrue(self.manager.force_stop(job.id, confirmed=True))
            worker.join(3)
        finally:
            tool.finish()
            worker.join(3)
        self.assertFalse(worker.is_alive())
        tool.terminate.assert_called_once_with()
        self.assertEqual(job.state, 'cleanup_required')
        job.client.export_readiness.assert_not_called()
        self.assertFalse(other.cancelled.is_set())

    def test_failed_force_stop_does_not_report_that_local_tools_have_exited(self):
        tool = FakeTool()
        tool.terminate.side_effect = OSError('Simulated termination failure')
        job, worker = self.start_tool_job(tool)
        try:
            self.manager.force_stop(job.id, confirmed=True)
            self.assertFalse(self.manager.local_tools_stopped())
            self.assertIn(job, self.manager.unfinished())
        finally:
            tool.finish()
            worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertTrue(self.manager.local_tools_stopped())

    def test_exit_override_freezes_new_submissions_and_cancels_queued_work(self):
        jobs = [self.manager.add(self.client(), {'id':str(i),'name':str(i)}, Path(f'queue-{i}.ova')) for i in range(2)]
        self.assertFalse(self.manager.stop_all(force=True))
        self.assertFalse(self.manager.stopping)
        self.manager.stop_all(force=True, confirmed=True)
        self.assertTrue(self.manager.stopping)
        self.assertTrue(all(job.cancelled.is_set() and job.force_requested.is_set() for job in jobs))
        with self.assertRaisesRegex(RuntimeError, 'before closing'):
            self.manager.add(self.client(), {'id':'new','name':'new'}, Path('new.ova'))
        run = Mock(side_effect=AssertionError('Queued work must never invoke the export runner after exit'))
        self.manager.runner = run
        for job in jobs:
            self.manager.run(job)
            self.assertEqual(job.state, 'cancelled')
        run.assert_not_called()

    def test_local_verification_can_stop_without_sending_abort_to_tool(self):
        tool = FakeTool()
        tool.finish(0)
        job = self.manager.add(self.client(), {'id':'vm-1','name':'Offline VM'}, Path('unused.ova'))
        job.process, job.state = tool, 'verifying'
        self.manager.active.add(job.id)
        self.assertTrue(job.can_cancel)
        self.assertTrue(self.manager.cancel(job.id))
        with self.assertRaises(Cancelled):
            job.check()
        tool.stdin.write.assert_not_called()

    def test_authentication_failure_also_waits_for_abort_cleanup(self):
        tool = FakeTool()
        with patch('jobs.CLEANUP_POLL_SECONDS', 0):
            job, worker = self.start_tool_job(tool)
            try:
                tool.lines.put('AUTHENTICATION\n')
                self.assertTrue(tool.abort_received.wait(2))
                job.client.logout.assert_not_called()
            finally:
                tool.finish()
                worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(job.state, 'failed')
        self.assertTrue(any('session was rejected' in line for line in job.log_lines))
        tool.terminate.assert_not_called()

    def test_output_read_failure_does_not_force_stop_the_tool(self):
        tool = FakeTool()
        with patch('jobs.CLEANUP_POLL_SECONDS', 0):
            job, worker = self.start_tool_job(tool)
            try:
                tool.lines.put(OSError('Fake broken output pipe'))
                self.assertTrue(tool.abort_received.wait(2))
                self.assertIn(job.id, self.manager.active)
            finally:
                tool.finish()
                worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(job.state, 'failed')
        tool.kill.assert_not_called()

    def test_unconfirmed_cleanup_is_not_reported_as_cancelled(self):
        job = ExportJob(self.client(), {'id':'vm-1', 'name':'Offline VM'}, Path('unused.ova'))
        self.manager.jobs[job.id] = job
        self.manager.waiting.append(job.id)
        def runner(job):
            job.export_started = True
            job.cancelled.set()
            job.check()
        self.manager.runner = runner
        job.client.export_readiness.return_value = (False, 'Power-on remains restricted.')
        with patch('jobs.CLEANUP_CHECK_SECONDS', 0):
            self.manager.run(job)
        self.assertEqual(job.state, 'cleanup_required')
        self.assertIn('vm-1', self.manager.pending_cleanup[job.endpoint])
        other_job = ExportJob(self.client(), {'id':'vm-2', 'name':'Other VM'}, Path('other.ova'))
        self.manager.check_previous_cleanup(other_job)
        other_job.client.export_readiness.assert_not_called()
        self.assertIn('vm-1', self.manager.pending_cleanup[job.endpoint])
        next_job = ExportJob(self.client(), {'id':'vm-1', 'name':'Offline VM'}, Path('retry.ova'))
        next_job.client.export_readiness.return_value = (False, 'Still restricted.')
        with self.assertRaisesRegex(RuntimeError, 'previous export'):
            self.manager.check_previous_cleanup(next_job)
        next_job.client.export_readiness.return_value = (True, 'No restrictions reported.')
        self.manager.check_previous_cleanup(next_job)
        self.assertNotIn('vm-1', self.manager.pending_cleanup[job.endpoint])

    def test_cleanup_network_failure_is_not_assumed_safe(self):
        job = ExportJob(self.client(), {'id':'vm-1', 'name':'Offline VM'}, Path('unused.ova'))
        job.client.export_readiness.side_effect = OSError('Fake disconnected server')
        with patch('jobs.CLEANUP_CHECK_SECONDS', 0):
            ready, detail = self.manager.confirm_cleanup(job)
        self.assertFalse(ready)
        self.assertIn('disconnected', detail)

    def test_verified_saved_package_keeps_success_when_vm_followup_is_needed(self):
        job = self.manager.add(self.client(), {'id':'vm-1','name':'Offline VM'}, Path('unused.ova'))
        def runner(job):
            job.export_started = True
            return 3
        self.manager.runner = runner
        job.client.export_readiness.return_value = (False, 'Power-on is disabled separately.')
        with patch('jobs.CLEANUP_CHECK_SECONDS', 0):
            self.manager.run(job)
        self.assertEqual(job.state, 'done_warning')
        self.assertTrue(any('3 file checksums verified' in line for line in job.log_lines))
        job.client.export_readiness.assert_called_once_with('vm-1', cleanup=True)
        view = TaskView(job)
        view.update('done_warning', 'File saved; check the VM state')
        self.assertEqual(view.percent, 100)
        self.assertEqual(view.status_text(), 'Saved; check VM')

    def test_preflight_rejects_existing_export_restriction_before_tool_starts(self):
        job = ExportJob(self.client(), {'id':'vm-1', 'name':'Offline VM'}, Path('unused.ova'))
        job.client.inventory = Mock(return_value=[{'id':'vm-1', 'power':'poweredOff'}])
        job.client.export_readiness.return_value = (False, 'Export is disabled.')
        with self.assertRaisesRegex(RuntimeError, 'not available for export'):
            self.manager.export(job)
        self.assertFalse(job.export_started)
        self.assertIsNone(job.process)

    def test_dashboard_does_not_overwrite_cancelling_with_progress(self):
        job = ExportJob(self.client(), {'id':'vm-1', 'name':'Offline VM'}, Path('unused.ova'))
        view = TaskView(job)
        view.update('running', None)
        view.update('cancelling', 'Waiting for cleanup')
        view.update('progress', 42)
        self.assertEqual(view.state, 'cancelling')
        self.assertEqual(view.detail, 'Waiting for cleanup')
        view.update('cleaning', 'Reading server state')
        view.update('cleanup_required', 'Server still restricts export')
        view.update('progress', 100)
        self.assertEqual(view.status_text(), 'Needs attention')
        self.assertEqual(view.percent, 42)


class ReadinessTests(unittest.TestCase):
    def setUp(self):
        self.api = VSphere('example.test', b'not-a-real-certificate')
        self.api.refs = {'propertyCollector': ('PropertyCollector', 'props')}

    def vm_response(self, disabled='', task=False):
        tasks = '<ManagedObjectReference type="Task">task-1</ManagedObjectReference>' if task else ''
        return xml_response('<objects><obj type="VirtualMachine">vm-1</obj>'
                            '<propSet><name>runtime.powerState</name><val>poweredOff</val></propSet>'
                            '<propSet><name>disabledMethod</name><val>' + disabled + '</val></propSet>'
                            '<propSet><name>recentTask</name><val>' + tasks + '</val></propSet></objects>')

    def test_power_on_restriction_is_separate_from_export_eligibility(self):
        with patch.object(self.api, 'call', return_value=self.vm_response('<string>PowerOnVM_Task</string>')) as call:
            self.assertTrue(self.api.export_readiness('vm-1')[0])
            ready, _ = self.api.export_readiness('vm-1', cleanup=True)
        self.assertFalse(ready)
        self.assertEqual([args.args[0] for args in call.call_args_list], ['RetrievePropertiesEx', 'RetrievePropertiesEx'])
        self.assertNotIn('<pathSet>recentTask</pathSet>', call.call_args_list[0].args[1])

    def test_disabled_export_is_still_rejected_before_start(self):
        with patch.object(self.api, 'call', return_value=self.vm_response('<string>ExportVm</string>')):
            ready, detail = self.api.export_readiness('vm-1')
        self.assertFalse(ready)
        self.assertIn('disables export', detail)

    def test_powered_on_vm_is_still_ineligible(self):
        result = self.vm_response('<string>PowerOnVM_Task</string>')
        result.find('.//{urn:vim25}propSet/{urn:vim25}val').text = 'poweredOn'
        with patch.object(self.api, 'call', return_value=result):
            ready, detail = self.api.export_readiness('vm-1')
        self.assertFalse(ready)
        self.assertIn('must be powered off', detail)

    def test_active_export_task_is_detected_even_when_method_list_is_empty(self):
        task = xml_response('<objects><obj type="Task">task-1</obj>'
                            '<propSet><name>info.state</name><val>running</val></propSet>'
                            '<propSet><name>info.descriptionId</name><val>VirtualMachine.exportVm</val></propSet></objects>')
        with patch.object(self.api, 'call', side_effect=[self.vm_response(task=True), task]):
            ready, detail = self.api.export_readiness('vm-1', cleanup=True)
        self.assertFalse(ready)
        self.assertIn('export task', detail)

    def test_no_restrictions_is_distinct_from_missing_data(self):
        with patch.object(self.api, 'call', return_value=self.vm_response()):
            self.assertTrue(self.api.export_readiness('vm-1')[0])
        with patch.object(self.api, 'call', return_value=xml_response('')):
            with self.assertRaisesRegex(RuntimeError, 'unavailable'):
                self.api.export_readiness('vm-1')

    def test_optional_empty_arrays_can_be_omitted_but_property_faults_cannot(self):
        empty = xml_response('<objects><obj type="VirtualMachine">vm-1</obj>'
                             '<propSet><name>runtime.powerState</name><val>poweredOff</val></propSet></objects>')
        with patch.object(self.api, 'call', return_value=empty):
            self.assertTrue(self.api.export_readiness('vm-1')[0])
        fault = xml_response('<objects><obj type="VirtualMachine">vm-1</obj>'
                             '<missingSet><path>disabledMethod</path></missingSet></objects>')
        with patch.object(self.api, 'call', return_value=fault):
            with self.assertRaisesRegex(RuntimeError, 'cleanup properties'):
                self.api.export_readiness('vm-1')

    def test_property_fault_identifies_path_and_reason(self):
        fault = xml_response('<objects xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
                             '<obj type="Task">task-1</obj><missingSet><path>info.state</path>'
                             '<fault><fault xsi:type="NoPermission"/>'
                             '<localizedMessage>Read access denied</localizedMessage></fault></missingSet></objects>')
        with patch.object(self.api, 'call', return_value=fault):
            with self.assertRaisesRegex(RuntimeError, r'Task task-1: info.state \(NoPermission\): Read access denied'):
                self.api.properties('Task', ['task-1'], ('info.state',))


if __name__ == '__main__':
    unittest.main(verbosity=2)
