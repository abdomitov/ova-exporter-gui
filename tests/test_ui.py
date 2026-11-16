import tkinter as tk
from tkinter import ttk
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app import App
from diagnostics import machine_error_messages
from test_app import close_root
from vsphere import fingerprint


class UITests(unittest.TestCase):
    def setUp(self):
        # Never migrate or inspect the actual user's settings during UI tests.
        settings = Mock()
        settings.profiles.return_value = []
        settings.trusted_pin.return_value = None
        settings.migrate_legacy.return_value = []
        guard = patch("app.ConnectionSettings", return_value=settings)
        guard.start()
        self.addCleanup(guard.stop)
        tool_guard = patch("app.find_ovftool", return_value=Path(__file__))
        tool_guard.start()
        self.addCleanup(tool_guard.stop)

    def vm(self, index=1):
        return {
            "id": str(index),
            "name": f"VM {index}",
            "power": "poweredOff",
            "cpu": "4",
            "ram": "8192",
            "capacity": 1024**3,
            "path": "[DS] test.vmx",
        }

    def test_missing_tool_blocks_new_export_without_creating_wizard(self):
        root = tk.Tk()
        root.withdraw()
        self.addCleanup(lambda: close_root(root))
        app = App(root, tool_store=False, tool_locator=lambda *args: None)
        self.assertIn("missing", app.tool_status.get())
        self.assertEqual(app.tool_label["style"], "Error.Rail.TLabel")
        self.assertEqual(str(app.queue.new_button["state"]), "disabled")
        self.assertIn("not set up", app.queue.empty_title["text"])
        self.assertEqual(app.queue.empty_action["text"], "Open settings")
        with patch("app.messagebox.showerror") as warning:
            app.new_download()
            warning.assert_called_once()
        # The export steps stay closed; Settings opens where the tool is fixed.
        self.assertEqual(app.current, "settings")
        self.assertFalse(app.flow.active)
        app.show("queue")
        app.queue.empty_action.invoke()
        self.assertEqual(app.current, "settings")

    def test_custom_tool_can_be_selected_remembered_and_redetected(self):
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ovftool.exe"
            path.write_bytes(b"not executable; fixture only")
            root = tk.Tk()
            root.withdraw()
            self.addCleanup(lambda: close_root(root))
            store = Mock()
            store.read.return_value = None
            app = App(
                root,
                tool_store=store,
                tool_locator=lambda base, selected: Path(selected) if selected else None,
            )
            with patch("app.filedialog.askopenfilename", return_value=str(path)):
                app.choose_tool()
            self.assertEqual(app.manager.tool, path)
            store.save.assert_called_once_with(path)
            self.assertEqual(app.tool_label["style"], "Success.Rail.TLabel")
            self.assertEqual(app.settings_view.tool_location.get(), str(path))
            app.auto_tool()
            store.save.assert_called_with(None)
            self.assertFalse(app.refresh_tool())

    def test_tool_cannot_change_during_active_or_queued_exports(self):
        root = tk.Tk()
        root.withdraw()
        self.addCleanup(lambda: close_root(root))
        app = App(root, tool_store=False)
        app.manager.add(self.client(), self.vm(), Path("tool-selection-test.ova"))
        original = app.manager.tool
        with (
            patch("app.messagebox.showinfo") as warning,
            patch("app.filedialog.askopenfilename") as browse,
        ):
            app.choose_tool()
            warning.assert_called_once()
            browse.assert_not_called()
        self.assertEqual(app.manager.tool, original)
        app.show("settings")
        self.assertEqual(str(app.settings_view.tool_browse["state"]), "disabled")
        self.assertEqual(str(app.settings_view.tool_auto["state"]), "disabled")

    def client(self):
        return SimpleNamespace(
            authority="preview.local", product="VMware", logout=Mock(), cookie="secret-cookie"
        )

    def test_keyboard_focus_reveals_offscreen_fields_in_scroll_body(self):
        from scrolling import ScrollBody, install_mousewheel

        root = tk.Tk()
        self.addCleanup(lambda: close_root(root) if root.winfo_exists() else None)
        root.geometry("640x200")
        body = ScrollBody(root)
        body.pack(fill="both", expand=True)
        for index in range(30):
            ttk.Label(body.inner, text=f"Fake field {index}").pack(pady=4)
        field = ttk.Entry(body.inner)
        field.pack(fill="x")
        install_mousewheel(root)
        root.update()
        root.focus_force()
        root.update()
        self.assertGreater(
            field.winfo_rooty(), body.canvas.winfo_rooty() + body.canvas.winfo_height()
        )
        field.focus_force()
        root.update()
        self.assertEqual(root.focus_get(), field)
        self.assertGreater(body.canvas.yview()[0], 0)
        self.assertGreaterEqual(field.winfo_rooty(), body.canvas.winfo_rooty())
        self.assertLessEqual(
            field.winfo_rooty() + field.winfo_height(),
            body.canvas.winfo_rooty() + body.canvas.winfo_height(),
        )

    def test_task_list_rows_and_selected_task_detail(self):
        root = tk.Tk()
        root.withdraw()
        app = App(root)
        self.assertTrue(app.queue.empty.winfo_manager())
        first = app.manager.add(self.client(), self.vm(1), Path("one.ova"))
        second = app.manager.add(self.client(), self.vm(2), Path("two.ova"))
        for job in (first, second):
            app.queue.add(job)
        self.assertFalse(app.queue.empty.winfo_manager())
        self.assertEqual(app.queue.list.order, [first.id, second.id])
        # The first task is shown at once; later tasks do not steal the selection.
        self.assertEqual(app.queue.selected, first.id)
        self.assertEqual(app.queue.detail_title.get(), "VM 1")
        app.queue.handle(first.id, "running", None)
        app.queue.handle(first.id, "progress", 42)
        app.queue.handle(second.id, "running", None)
        app.queue.handle(second.id, "progress", 15)
        self.assertEqual(app.queue.panel.value, 42)
        self.assertEqual(app.queue.cards[second.id].percent, 15)
        self.assertTrue(app.queue.list.canvas.find_withtag("row-" + second.id))
        app.queue.handle(first.id, "failed", "Actual readable failure reason")
        self.assertEqual(app.queue.message["text"], "Actual readable failure reason")
        self.assertEqual(app.queue.message["style"], "Problem.TLabel")
        app.queue.list.move(1)
        self.assertEqual(app.queue.selected, second.id)
        self.assertEqual(app.queue.panel.value, 15)
        self.assertEqual(app.queue.message["text"], "")
        self.assertIn("(1)", app.nav["queue"]["text"])
        close_root(root)

    def test_tool_log_tab_shows_in_memory_lines_for_the_selected_task(self):
        root = tk.Tk()
        root.withdraw()
        app = App(root)
        job = app.manager.add(self.client(), self.vm(), Path("log-tab.ova"))
        app.queue.add(job)
        app.manager.record(job, "first fixture line")
        app.queue.show_tab("log")
        self.assertTrue(app.queue.log_body.winfo_manager())
        self.assertFalse(app.queue.transfer_body.winfo_manager())
        self.assertIn("first fixture line", app.queue.log_text.get("1.0", "end"))
        self.assertEqual(str(app.queue.log_text["state"]), "disabled")
        app.manager.record(job, "second fixture line")
        app.queue.handle(job.id, "status", "fixture status")
        self.assertIn("second fixture line", app.queue.log_text.get("1.0", "end"))
        app.queue.show_tab("transfer")
        self.assertTrue(app.queue.transfer_body.winfo_manager())
        close_root(root)

    def test_new_export_registers_task_shows_queue_and_keeps_session_for_next_vm(self):
        root = tk.Tk()
        root.withdraw()
        app = App(root)
        app.new_download()
        flow = app.flow
        self.assertEqual(app.current, "new")
        self.assertEqual(flow.step, 1)
        self.assertEqual((flow.address.get(), flow.username.get(), flow.password.get()), ("", "", ""))
        flow.show_step(2)
        self.assertEqual(flow.step, 1)  # No session yet.
        client = self.client()
        vm = self.vm()
        flow.emit("connected", (client, [vm, self.vm(2)]))
        flow.poll()
        self.assertEqual(flow.step, 2)
        self.assertIn("preview.local", flow.step_buttons[1]["text"])
        flow.show_step(3)
        self.assertEqual(flow.step, 2)  # Nothing selected yet.
        flow.tree.selection_set(vm["id"])
        flow.selection_changed()
        self.assertEqual(str(flow.continue_btn["state"]), "normal")
        flow.continue_btn.invoke()
        self.assertEqual(flow.step, 3)
        self.assertEqual(flow.vm_name.get(), "VM 1")
        self.assertIn("4 CPUs", flow.vm_specs.get())
        flow.folder.set(str(Path(__file__).resolve().parent))
        flow.filename.set("flow-test-never-created.ova")
        with patch("export_flow.threading.Thread"):
            flow.export()
        self.assertTrue(flow.busy)
        with patch.object(app.manager, "start") as start:
            flow.emit("prepared", (self.client(), vm, Path("flow-test-never-created.ova")))
            app.poll()
            start.assert_called_once()
        self.assertFalse(flow.busy)
        self.assertEqual(app.current, "queue")
        self.assertEqual(len(app.queue.cards), 1)
        self.assertEqual(app.queue.selected, start.call_args.args[0].id)
        # Still signed in, back on the VM list with nothing selected.
        self.assertIs(flow.client, client)
        self.assertEqual(flow.step, 2)
        self.assertFalse(flow.tree.selection())
        self.assertEqual(str(flow.export_btn["state"]), "disabled")
        self.assertIn("added to the queue", flow.status_display.get())
        flow.disconnect()
        client.logout.assert_called_once()
        self.assertIsNone(flow.client)
        self.assertEqual(flow.step, 1)
        self.assertEqual((flow.address.get(), flow.username.get(), flow.password.get()), ("", "", ""))
        self.assertFalse(flow.tree.get_children())
        close_root(root)

    def test_closing_the_app_ends_the_browsing_session_and_clears_fields(self):
        root = tk.Tk()
        root.withdraw()
        app = App(root)
        flow = app.flow
        client = self.client()
        flow.emit("connected", (client, [self.vm()]))
        flow.poll()
        flow.password.set("transient-only")
        with patch("export_flow.threading.Thread") as worker:
            flow.shutdown()
            self.assertIs(worker.call_args.kwargs["target"], client.logout)
        self.assertIsNone(flow.client)
        self.assertEqual(flow.password.get(), "")
        close_root(root)

    def test_mousewheel_scrolls_task_list_and_transfer_detail_body(self):
        root = tk.Tk()
        app = App(root)
        root.geometry("960x600")
        self.addCleanup(lambda: close_root(root) if root.winfo_exists() else None)
        jobs = []
        for i in range(40):
            job = app.manager.add(self.client(), self.vm(i), Path(f"wheel-{i}.ova"))
            app.queue.add(job)
            jobs.append(job)
        root.update()
        rows = app.queue.list
        rows.canvas.yview_moveto(0)
        self.assertTrue(rows.scroll.winfo_manager())
        with patch.object(root, "winfo_containing", return_value=rows.canvas):
            rows.canvas.event_generate("<MouseWheel>", delta=-120, x=10, y=10)
            root.update()
        self.assertGreater(rows.canvas.yview()[0], 0)
        app.queue.handle(jobs[0].id, "failed", "Illustrative server error. " * 120)
        root.update()
        settled = tk.BooleanVar(root, value=False)
        root.after(120, lambda: settled.set(True))
        root.wait_variable(settled)
        body = app.queue.detail_scroll
        self.assertGreater(body.canvas.winfo_height(), 1)
        body.canvas.yview_moveto(0)
        root.update()
        self.assertLess(body.canvas.yview()[1], 1)
        graph = app.queue.panel.canvas
        with patch.object(root, "winfo_containing", return_value=graph):
            graph.event_generate("<MouseWheel>", delta=-120, x=10, y=10)
            root.update()
        self.assertGreater(body.canvas.yview()[0], 0)

    def test_machine_error_reads_message_instead_of_xml_closing_tags(self):
        lines = [
            "ERROR",
            "+ <Errors>",
            "+ <Error>",
            "+ <LocalizedMsg>",
            "+ The virtual machine has an unsupported device &amp; cannot be exported.",
            "+ </LocalizedMsg>",
            "+ </Error>",
            "+ </Errors>",
            "RESULT",
            "+ ERROR",
        ]
        self.assertEqual(
            machine_error_messages(lines),
            ["The virtual machine has an unsupported device & cannot be exported."],
        )

    def test_task_diagnostic_output_redacts_session_secrets(self):
        root = tk.Tk()
        root.withdraw()
        app = App(root)
        job = app.manager.add(self.client(), self.vm(), Path("redaction.ova"))
        job.secret = "one-use-ticket"
        line = app.manager.record(job, "one-use-ticket secret-cookie vi://root:password@host/vm")
        for secret in ("one-use-ticket", "secret-cookie", "password"):
            self.assertNotIn(secret, line)
        close_root(root)

    def test_password_enter_connects_and_busy_guard_blocks_repeat(self):
        root = tk.Tk()
        app = App(root)
        app.new_download()
        wizard = app.flow
        wizard.address.set("192.0.2.10")
        wizard.username.set("example-user")
        wizard.password.set("test-only")
        root.update()
        entry = wizard.password_entry
        entry.focus_force()
        root.update()
        with patch.object(wizard, "connect") as connect:
            entry.event_generate("<Return>")
            root.update()
            connect.assert_called_once()
            self.assertTrue(entry.bind("<KP_Enter>"))
            wizard.password_enter()
            self.assertEqual(connect.call_count, 2)
            wizard.busy = True
            entry.event_generate("<Return>")
            root.update()
            self.assertEqual(connect.call_count, 2)
        wizard.busy = False
        close_root(root)

    def test_same_server_notice_can_cancel_before_creating_session(self):
        root = tk.Tk()
        root.withdraw()
        app = App(root)
        app.manager.add(self.client(), self.vm(1), Path("existing-task.ova"))
        app.new_download()
        wizard = app.flow
        wizard.emit("connected", (self.client(), [self.vm(2)]))
        wizard.poll()
        wizard.tree.selection_set("2")
        wizard.selection_changed()
        wizard.show_step(3)
        wizard.folder.set(str(Path(__file__).resolve().parent))
        wizard.filename.set("queue-notice-test-not-created.ova")
        with (
            patch("app.messagebox.askyesno", return_value=False) as notice,
            patch("export_flow.threading.Thread") as worker,
        ):
            wizard.export()
            notice.assert_called_once()
            self.assertIn("CPU", notice.call_args.args[1])
            self.assertIn("queue", notice.call_args.args[1])
            worker.assert_not_called()
            self.assertFalse(wizard.busy)
        with (
            patch("app.messagebox.askyesno", return_value=True),
            patch("export_flow.threading.Thread") as worker,
        ):
            wizard.export()
            worker.return_value.start.assert_called_once()
        wizard.busy = False
        close_root(root)

    def test_app_does_not_save_diagnostic_data_to_disk(self):
        root = tk.Tk()
        root.withdraw()
        app = App(root)
        self.assertIsNone(app.manager.log_dir)
        job = app.manager.add(self.client(), self.vm(), Path("privacy-test.ova"))
        app.manager.record(job, "Source: preview.local")
        with patch("pathlib.Path.write_text") as write:
            app.manager.save_log(job)
            write.assert_not_called()
        self.assertIsNone(job.log_file)
        close_root(root)

    def test_active_transfer_offers_warned_cancel_and_verification_its_own_action(self):
        root = tk.Tk()
        root.withdraw()
        app = App(root)
        job = app.manager.add(self.client(), self.vm(), Path("policy-ui-test.ova"))
        app.queue.add(job)
        self.assertEqual(app.queue.cancel_button["text"], "Remove from queue")
        job.state = "running"
        app.queue.handle(job.id, "running", None)
        self.assertEqual(app.queue.cancel_button.winfo_manager(), "grid")
        self.assertEqual(app.queue.cancel_button["text"], "Cancel export…")
        job.state = "verifying"
        app.queue.handle(job.id, "verifying", None)
        self.assertEqual(app.queue.cancel_button.winfo_manager(), "grid")
        self.assertEqual(app.queue.cancel_button["text"], "Stop verification")
        job.state = "done"
        app.queue.handle(job.id, "done", "Checksums verified")
        self.assertFalse(app.queue.cancel_button.winfo_manager())
        self.assertEqual(app.queue.message["style"], "Good.TLabel")
        close_root(root)

    def test_declining_active_cancel_sends_no_stop_request(self):
        root = tk.Tk()
        root.withdraw()
        app = App(root)
        job = app.manager.add(self.client(), self.vm(), Path("warned-cancel-test.ova"))
        job.state = "running"
        job.process = Mock()
        job.process.poll.return_value = None
        with (
            patch("app.messagebox.askyesno", return_value=False) as prompt,
            patch.object(app.manager, "cancel") as cancel,
        ):
            app.cancel_job(job.id)
            self.assertIn("may leave the VM locked", prompt.call_args.args[1])
            cancel.assert_not_called()
        with (
            patch("app.messagebox.askyesno", return_value=True),
            patch.object(app.manager, "cancel", return_value=True) as cancel,
        ):
            app.cancel_job(job.id)
            cancel.assert_called_once_with(job.id, allow_remote=True)
        close_root(root)

    def test_exit_dialog_does_not_cancel_until_a_choice_is_made(self):
        root = tk.Tk()
        root.withdraw()
        app = App(root)
        job = app.manager.add(self.client(), self.vm(), Path("exit-dialog-test.ova"))
        with patch.object(tk.Toplevel, "grab_set"), patch.object(app.manager, "stop_all") as stop:
            app.close()
            self.assertIsNotNone(app.exit_dialog)
            stop.assert_not_called()

            def buttons(widget):
                for child in widget.winfo_children():
                    if isinstance(child, ttk.Button):
                        yield child
                    yield from buttons(child)

            keep = next(
                button for button in buttons(app.exit_dialog) if button["text"] == "Keep app open"
            )
            keep.invoke()
            self.assertIsNone(app.exit_dialog)
            self.assertIsNone(app.close_mode)
            self.assertFalse(job.cancelled.is_set())
            stop.assert_not_called()
        close_root(root)

    def test_force_exit_waits_until_its_local_tool_has_actually_exited(self):
        root = tk.Tk()
        root.withdraw()
        app = App(root)
        job = app.manager.add(self.client(), self.vm(), Path("force-exit-test.ova"))
        job.state = "running"
        job.process = Mock()
        job.process.poll.return_value = None
        with patch.object(tk.Toplevel, "grab_set"):
            app.close()

            def buttons(widget):
                for child in widget.winfo_children():
                    if isinstance(child, ttk.Button):
                        yield child
                    yield from buttons(child)

            force = next(
                button
                for button in buttons(app.exit_dialog)
                if button["text"] == "Force stop and exit"
            )
            job.process.terminate.assert_not_called()
            force.invoke()
        self.assertEqual(app.close_mode, "force")
        job.process.terminate.assert_called_once_with()
        with patch.object(app, "finish_close") as finish:
            app.poll()
            finish.assert_not_called()
            job.process.poll.return_value = 1
            app.poll()
            finish.assert_called_once_with()
        close_root(root)

    def test_password_visibility_is_opt_in_and_resets_when_connecting(self):
        settings = Mock()
        settings.profiles.return_value = []
        with patch("app.ConnectionSettings", return_value=settings):
            root = tk.Tk()
            root.withdraw()
            app = App(root)
            app.new_download()
        wizard = app.flow
        wizard.password.set("not-a-real-password")
        self.assertEqual(wizard.password_entry["show"], "\u2022")
        self.assertFalse(wizard.remember_connection.get())
        wizard.toggle_password()
        self.assertEqual(wizard.password_entry["show"], "")
        self.assertEqual(wizard.show_password_btn["text"], "Hide")
        wizard.set_busy(True)
        self.assertEqual(wizard.connect_btn["text"], "Connecting…")
        self.assertEqual(wizard.password_entry["show"], "\u2022")
        self.assertFalse(wizard.password_visible.get())
        self.assertEqual(str(wizard.connect_btn["state"]), "disabled")
        self.assertEqual(wizard.remember_check["style"], "Surface.Ova.TCheckbutton")
        settings.remember_profile.assert_not_called()
        wizard.set_busy(False)
        close_root(root)

    def test_selecting_saved_server_fills_only_address_and_username(self):
        settings = Mock()
        settings.profiles.return_value = [{"address": "example.test", "username": "root"}]
        with patch("app.ConnectionSettings", return_value=settings):
            root = tk.Tk()
            root.withdraw()
            app = App(root)
            app.new_download()
        wizard = app.flow
        self.assertEqual(wizard.address.get(), "")
        self.assertEqual(wizard.username.get(), "")
        wizard.password.set("transient-only")
        wizard.toggle_password()
        self.assertEqual(wizard.saved_buttons[0]["text"], "example.test\nroot")
        wizard.saved_buttons[0].invoke()
        self.assertEqual(
            (wizard.address.get(), wizard.username.get(), wizard.password.get()),
            ("example.test", "root", ""),
        )
        self.assertFalse(wizard.password_visible.get())
        wizard.login_identity = ("example.test", "root", False)
        wizard.remember_connected_profile()
        settings.remember_profile.assert_not_called()
        wizard.login_identity = ("example.test", "root", True)
        wizard.remember_connected_profile()
        settings.remember_profile.assert_called_once_with("example.test", "root")
        close_root(root)

    def test_address_typeahead_keeps_typed_prefix_selected_completion_and_no_password(self):
        settings = Mock()
        settings.profiles.return_value = [
            {"address": "192.0.2.10", "username": "admin"},
            {"address": "192.0.2.20", "username": "root"},
        ]
        with patch("app.ConnectionSettings", return_value=settings):
            root = tk.Tk()
            root.withdraw()
            app = App(root)
            app.new_download()
        wizard = app.flow
        prefix = "192.0.2."
        wizard.address.set(prefix)
        wizard.address_entry.icursor("end")
        wizard.suggest_addresses(SimpleNamespace(keysym="period", char=".", state=0))
        self.assertEqual(wizard.address.get(), "192.0.2.10")
        self.assertEqual(wizard.address_entry.index("insert"), len(prefix))
        self.assertTrue(wizard.address_entry.selection_present())
        wizard.password.set("transient-only")
        wizard.select_saved_address()
        self.assertEqual(wizard.username.get(), "admin")
        self.assertEqual(wizard.password.get(), "")
        self.assertEqual(str(wizard.address_entry["state"]), "normal")
        self.assertEqual(len(wizard.saved_buttons), 2)
        close_root(root)

    def test_clear_saved_data_requires_confirmation_and_clears_all_hint_fields(self):
        settings = Mock()
        settings.profiles.return_value = [{"address": "example.test", "username": "root"}]
        with patch("app.ConnectionSettings", return_value=settings):
            root = tk.Tk()
            root.withdraw()
            app = App(root)
            app.new_download()
        wizard = app.flow
        job = app.manager.add(
            self.client(), self.vm(), Path("clear-settings-does-not-touch-this.ova")
        )
        wizard.address.set("example.test")
        wizard.username.set("root")
        wizard.password.set("transient-only")
        with patch("app.messagebox.askyesno", return_value=False):
            wizard.clear_saved_data()
        settings.clear_all.assert_not_called()
        self.assertEqual(wizard.address.get(), "example.test")
        settings.profiles.return_value = []
        with patch("app.messagebox.askyesno", return_value=True):
            wizard.clear_saved_data()
        settings.clear_all.assert_called_once_with()
        self.assertEqual(
            (wizard.address.get(), wizard.username.get(), wizard.password.get()), ("", "", "")
        )
        self.assertEqual(wizard.saved_addresses, [])
        self.assertEqual(wizard.saved_buttons, [])
        self.assertFalse(wizard.remember_connection.get())
        self.assertFalse(wizard.password_visible.get())
        self.assertIsNone(wizard.login_identity)
        self.assertFalse(job.cancelled.is_set())
        self.assertEqual(job.state, "queued")
        close_root(root)

    def test_matching_saved_certificate_skips_dialog_but_password_is_still_required(self):
        cert = b"offline-test-certificate"
        settings = Mock()
        settings.profiles.return_value = []
        settings.trusted_pin.return_value = fingerprint(cert)
        with patch("app.ConnectionSettings", return_value=settings):
            root = tk.Tk()
            root.withdraw()
            app = App(root)
            app.new_download()
        wizard = app.flow
        wizard.username.set("example-user")
        wizard.password.set("transient-only")
        with patch("export_flow.threading.Thread"), patch("app.messagebox.askyesno") as prompt:
            wizard.authenticate("example.test", cert)
            prompt.assert_not_called()
        self.assertEqual(wizard.password.get(), "")
        settings.trust_certificate.assert_not_called()
        settings.remember_profile.assert_not_called()
        close_root(root)

    def test_first_certificate_approval_is_saved_without_account_or_password(self):
        cert = b"offline-test-certificate"
        settings = Mock()
        settings.profiles.return_value = []
        settings.trusted_pin.return_value = None
        with patch("app.ConnectionSettings", return_value=settings):
            root = tk.Tk()
            root.withdraw()
            app = App(root)
            app.new_download()
        wizard = app.flow
        wizard.username.set("example-user")
        wizard.password.set("transient-only")
        with patch("export_flow.threading.Thread"), patch("app.messagebox.askyesno", return_value=True):
            wizard.authenticate("example.test", cert)
        settings.trust_certificate.assert_called_once_with("example.test", fingerprint(cert))
        settings.remember_profile.assert_not_called()
        self.assertEqual(wizard.password.get(), "")
        close_root(root)

    def test_changed_certificate_requires_new_approval_and_decline_preserves_old_pin(self):
        cert = b"changed-offline-certificate"
        settings = Mock()
        settings.profiles.return_value = []
        settings.trusted_pin.return_value = ":".join(["AA"] * 32)
        with patch("app.ConnectionSettings", return_value=settings):
            root = tk.Tk()
            root.withdraw()
            app = App(root)
            app.new_download()
        wizard = app.flow
        wizard.username.set("example-user")
        wizard.password.set("transient-only")
        with (
            patch("export_flow.threading.Thread") as worker,
            patch("app.messagebox.askyesno", return_value=False) as prompt,
        ):
            wizard.authenticate("example.test", cert)
            self.assertIn("changed", prompt.call_args.args[0].lower())
            worker.assert_not_called()
        settings.trust_certificate.assert_not_called()
        self.assertEqual(wizard.password.get(), "")
        close_root(root)


if __name__ == "__main__":
    unittest.main(verbosity=2)
