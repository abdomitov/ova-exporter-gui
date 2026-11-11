import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from jobs import JobManager
from vsphere import VSphere
from test_app import response
import test_app
from exporter import verify_ova


class JobTests(unittest.TestCase):
    def client(self, host):
        return SimpleNamespace(authority=host, logout=Mock(), call=Mock())

    def wait_state(self, job, state):
        deadline = time.monotonic() + 3
        while job.state != state and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual(job.state, state)

    def test_three_hosts_run_in_parallel_and_queued_cancel_is_isolated(self):
        started = {str(i): threading.Event() for i in range(4)}
        release = threading.Event()

        def runner(job):
            started[job.vm["id"]].set()
            while not release.wait(0.01):
                job.check()
            return 3

        manager = JobManager("unused.exe", lambda *args: None, runner=runner)
        jobs = [
            manager.add(
                self.client(f"host-{i}"), {"id": str(i), "name": str(i)}, Path(f"task-{i}.ova")
            )
            for i in range(4)
        ]
        try:
            for job in jobs[:3]:
                manager.start(job)
                self.assertTrue(started[job.vm["id"]].wait(2))
            manager.start(jobs[3])
            self.assertFalse(started["3"].wait(0.05))
            self.assertTrue(manager.cancel(jobs[3].id))
            self.wait_state(jobs[3], "cancelled")
            self.assertFalse(started["3"].is_set())
            self.assertEqual(jobs[0].state, "running")
            self.assertEqual(jobs[1].state, "running")
            self.assertEqual(jobs[2].state, "running")
        finally:
            release.set()
            for job in jobs[:3]:
                self.wait_state(job, "done")
        for job in jobs:
            job.client.logout.assert_called_once()

    def test_same_endpoint_queues_while_other_endpoint_runs(self):
        starts = {str(i): threading.Event() for i in range(3)}
        releases = {str(i): threading.Event() for i in range(3)}

        def runner(job):
            starts[job.vm["id"]].set()
            releases[job.vm["id"]].wait(3)
            return 3

        manager = JobManager("unused", lambda *args: None, runner=runner)
        jobs = [
            manager.add(
                self.client("host-a" if i < 2 else "host-b"),
                {"id": str(i), "name": str(i)},
                Path(f"same-{i}.ova"),
            )
            for i in range(3)
        ]
        try:
            manager.start(jobs[0])
            self.assertTrue(starts["0"].wait(2))
            manager.start(jobs[1])
            manager.start(jobs[2])
            self.assertTrue(starts["2"].wait(2))
            self.assertFalse(starts["1"].wait(0.05))
            releases["0"].set()
            self.assertTrue(starts["1"].wait(2))
        finally:
            for event in releases.values():
                event.set()
            for job in jobs:
                self.wait_state(job, "done")

    def test_cancel_queued_never_starts_its_export(self):
        started, release = threading.Event(), threading.Event()
        run = Mock()

        def runner(job):
            run(job.vm["id"])
            started.set()
            release.wait(3)
            return 3

        manager = JobManager("unused", lambda *args: None, limit=1, runner=runner)
        first = manager.add(
            self.client("a"), {"id": "first", "name": "first"}, Path("queue-first.ova")
        )
        second = manager.add(
            self.client("b"), {"id": "second", "name": "second"}, Path("queue-second.ova")
        )
        try:
            manager.start(first)
            self.assertTrue(started.wait(2))
            manager.start(second)
            manager.cancel(second.id)
            self.wait_state(second, "cancelled")
            run.assert_called_once_with("first")
        finally:
            release.set()
            self.wait_state(first, "done")

    def test_filename_and_vm_conflicts_across_tasks(self):
        manager = JobManager("unused", lambda *args: None)
        manager.add(self.client("a"), {"id": "vm-1", "name": "A"}, Path("reserved.ova"))
        with self.assertRaises(ValueError):
            manager.add(self.client("b"), {"id": "vm-2", "name": "B"}, Path("reserved.ova"))
        with self.assertRaises(ValueError):
            manager.add(self.client("A"), {"id": "vm-1", "name": "A"}, Path("another.ova"))

    def test_failed_job_releases_slot_even_if_logout_fails(self):
        def runner(job):
            if job.vm["id"] == "bad":
                raise RuntimeError("Simulated transfer failure")
            return 3

        manager = JobManager("unused", lambda *args: None, limit=1, runner=runner)
        client = self.client("host")
        client.logout.side_effect = RuntimeError("Simulated logout failure")
        bad = manager.add(client, {"id": "bad", "name": "bad"}, Path("failed.ova"))
        good = manager.add(self.client("host"), {"id": "good", "name": "good"}, Path("good.ova"))
        manager.start(bad)
        manager.start(good)
        self.wait_state(bad, "failed")
        self.wait_state(good, "done")
        self.assertEqual(manager.active, set())

    def test_fork_consumes_ticket_without_copying_browser_cookie(self):
        parent = VSphere("host", b"cert")
        parent.refs = {"sessionManager": ("SessionManager", "sessions")}
        parent.cookie = "browser-session"

        def call(child, method, body):
            self.assertEqual(method, "CloneSession")
            self.assertEqual(child.cookie, "")
            child.cookie = "task-session"
            return response("<returnval/>")

        with (
            patch.object(parent, "clone_ticket", return_value="one-use"),
            patch.object(VSphere, "call", autospec=True, side_effect=call),
        ):
            child = parent.fork()
        self.assertEqual(parent.cookie, "browser-session")
        self.assertEqual(child.cookie, "task-session")
        self.assertIsNot(parent.refs, child.refs)

    def test_verification_can_be_cancelled(self):
        package = test_app.Tests().make_ova()

        def stop():
            raise RuntimeError("cancelled during checksum scan")

        with self.assertRaisesRegex(RuntimeError, "cancelled during"):
            verify_ova(package, cancel_check=stop)


if __name__ == "__main__":
    unittest.main(verbosity=2)
