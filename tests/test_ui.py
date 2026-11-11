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
        self.assertEqual(app.tool_label["style"], "Error.TLabel")
        self.assertEqual(str(app.dashboard.empty_action["state"]), "disabled")
        self.assertIn("Set up", app.dashboard.empty_title["text"])
        with patch("app.messagebox.showerror") as warning:
            app.new_download()
            warning.assert_called_once()
        self.assertIsNone(app.wizard)

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
            self.assertEqual(app.tool_label["style"], "Success.TLabel")
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

    def client(self):
        return SimpleNamespace(
            authority="preview.local", product="VMware", logout=Mock(), cookie="secret-cookie"
        )

    def test_keyboard_focus_reveals_offscreen_fields_in_scroll_body(self):
        from accordion import ScrollBody, install_mousewheel

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

    def test_compact_rows_only_show_selected_task_details(self):
        root = tk.Tk()
        root.withdraw()
        app = App(root)
        first = app.manager.add(self.client(), self.vm(1), Path("one.ova"))
        second = app.manager.add(self.client(), self.vm(2), Path("two.ova"))
        for job in (first, second):
            app.dashboard.add(job)
        self.assertEqual(len(app.dashboard.tree.get_children()), 2)
        self.assertEqual(len(app.dashboard.panes.panes()), 1)
        app.dashboard.tree.selection_set(first.id)
        app.dashboard.selection_changed()
        self.assertEqual(len(app.dashboard.panes.panes()), 2)
        app.dashboard.handle(first.id, "running", None)
        app.dashboard.handle(first.id, "progress", 42)
        app.dashboard.handle(second.id, "running", None)
        app.dashboard.handle(second.id, "progress", 15)
        self.assertEqual(app.dashboard.panel.value, 42)
        self.assertEqual(app.dashboard.cards[second.id].percent, 15)
        app.dashboard.handle(first.id, "failed", "Actual readable failure reason")
        self.assertEqual(app.dashboard.message["text"], "Actual readable failure reason")
        app.dashboard.hide_details()
        self.assertEqual(len(app.dashboard.panes.panes()), 1)
        close_root(root)

    def test_new_export_wizard_registers_task_then_closes_and_is_fresh_next_time(self):
        root = tk.Tk()
        root.withdraw()
        app = App(root)
        app.new_download()
        wizard = app.wizard
        self.assertEqual(wizard.step, 1)
        self.assertEqual(wizard.address.get(), "")
        self.assertEqual(wizard.username.get(), "")
        self.assertEqual(wizard.password.get(), "")
        self.assertEqual(wizard.login_entries[0].winfo_class(), "TCombobox")
        client = self.client()
        vm = self.vm()
        wizard.emit("connected", (client, [vm]))
        wizard.poll()
        self.assertEqual(wizard.step, 2)
        wizard.tree.selection_set(vm["id"])
        wizard.selection_changed()
        wizard.folder.set(str(Path(__file__).resolve().parent))
        wizard.filename.set("wizard-test-never-created.ova")
        with patch("wizard.threading.Thread"):
            wizard.export()
        self.assertTrue(wizard.busy)
        with patch.object(app.manager, "start") as start:
            wizard.emit("prepared", (self.client(), vm, Path("wizard-test-never-created.ova")))
            wizard.poll()
            start.assert_called_once()
        self.assertIsNone(app.wizard)
        self.assertTrue(wizard.closed)
        self.assertEqual(len(app.dashboard.cards), 1)
        self.assertIsNone(app.dashboard.selected)
        app.new_download()
        self.assertIsNot(wizard, app.wizard)
        self.assertIsNone(app.wizard.client)
        self.assertEqual(app.wizard.address.get(), "")
        self.assertEqual(app.wizard.username.get(), "")
        self.assertEqual(app.wizard.password.get(), "")
        app.wizard.destroy_wizard()
        close_root(root)

    def test_mousewheel_scrolls_table_and_graph_detail_body(self):
        root = tk.Tk()
        app = App(root)
        root.geometry("640x420")
        self.addCleanup(lambda: close_root(root) if root.winfo_exists() else None)
        for i in range(40):
            job = app.manager.add(self.client(), self.vm(i), Path(f"wheel-{i}.ova"))
            app.dashboard.add(job)
        app.dashboard.tree.yview_moveto(0)
        root.update()
        tree = app.dashboard.tree
        with patch.object(root, "winfo_containing", return_value=tree):
            tree.event_generate("<MouseWheel>", delta=-120, x=10, y=10)
            root.update()
        self.assertGreater(tree.yview()[0], 0)
        first = tree.get_children()[0]
        tree.selection_set(first)
        app.dashboard.selection_changed()
        root.update()
        settled = tk.BooleanVar(root, value=False)
        root.after(120, lambda: settled.set(True))
        root.wait_variable(settled)
        body = app.dashboard.detail_scroll
        self.assertGreater(body.canvas.winfo_height(), 1)
        body.canvas.yview_moveto(0)
        root.update()
        self.assertLess(body.canvas.yview()[1], 1)
        graph = app.dashboard.panel.canvas
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
        wizard = app.wizard
        wizard.address.set("192.0.2.10")
        wizard.username.set("example-user")
        wizard.password.set("test-only")
        root.update()
        entry = wizard.login_entries[2]
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
        wizard.destroy_wizard()
        close_root(root)

    def test_same_server_notice_can_cancel_before_creating_session(self):
        root = tk.Tk()
        root.withdraw()
        app = App(root)
        app.manager.add(self.client(), self.vm(1), Path("existing-task.ova"))
        app.new_download()
        wizard = app.wizard
        wizard.emit("connected", (self.client(), [self.vm(2)]))
        wizard.poll()
        wizard.tree.selection_set("2")
        wizard.selection_changed()
        wizard.folder.set(str(Path(__file__).resolve().parent))
        wizard.filename.set("queue-notice-test-not-created.ova")
        with (
            patch("app.messagebox.askyesno", return_value=False) as notice,
            patch("wizard.threading.Thread") as worker,
        ):
            wizard.export()
            notice.assert_called_once()
            self.assertIn("CPU", notice.call_args.args[1])
            self.assertIn("queue", notice.call_args.args[1])
            worker.assert_not_called()
            self.assertFalse(wizard.busy)
        with (
            patch("app.messagebox.askyesno", return_value=True),
            patch("wizard.threading.Thread") as worker,
        ):
            wizard.export()
            worker.return_value.start.assert_called_once()
        wizard.busy = False
        wizard.destroy_wizard()
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
        app.dashboard.add(job)
        app.dashboard.tree.selection_set(job.id)
        app.dashboard.selection_changed()
        job.state = "running"
        app.dashboard.handle(job.id, "running", None)
        self.assertEqual(app.dashboard.cancel_selected.winfo_manager(), "pack")
        self.assertEqual(app.dashboard.cancel_detail.winfo_manager(), "grid")
        self.assertEqual(app.dashboard.cancel_selected["text"], "Cancel export…")
        job.state = "verifying"
        app.dashboard.handle(job.id, "verifying", None)
        self.assertEqual(app.dashboard.cancel_selected.winfo_manager(), "pack")
        self.assertEqual(app.dashboard.cancel_detail.winfo_manager(), "grid")
        self.assertEqual(app.dashboard.cancel_selected["text"], "Stop verification")
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
        wizard = app.wizard
        wizard.password.set("not-a-real-password")
        self.assertEqual(wizard.login_entries[2]["show"], "\u2022")
        self.assertFalse(wizard.remember_connection.get())
        wizard.toggle_password()
        self.assertEqual(wizard.login_entries[2]["show"], "")
        self.assertEqual(wizard.show_password_btn["text"], "Hide")
        wizard.set_busy(True)
        self.assertEqual(wizard.connect_btn["text"], "Connecting…")
        self.assertEqual(wizard.login_entries[2]["show"], "\u2022")
        self.assertFalse(wizard.password_visible.get())
        self.assertEqual(wizard.remember_check["style"], "Ova.TCheckbutton")
        settings.remember_profile.assert_not_called()
        wizard.set_busy(False)
        wizard.destroy_wizard()
        close_root(root)

    def test_selecting_saved_server_fills_only_address_and_username(self):
        settings = Mock()
        settings.profiles.return_value = [{"address": "example.test", "username": "root"}]
        with patch("app.ConnectionSettings", return_value=settings):
            root = tk.Tk()
            root.withdraw()
            app = App(root)
            app.new_download()
        wizard = app.wizard
        self.assertEqual(wizard.address.get(), "")
        self.assertEqual(wizard.username.get(), "")
        wizard.password.set("transient-only")
        wizard.toggle_password()
        wizard.address_combo.set("example.test")
        wizard.select_saved_address()
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
        wizard.destroy_wizard()
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
        wizard = app.wizard
        prefix = "192.0.2."
        wizard.address.set(prefix)
        wizard.address_combo.icursor("end")
        wizard.suggest_addresses(SimpleNamespace(keysym="period", char=".", state=0))
        self.assertEqual(wizard.address.get(), "192.0.2.10")
        self.assertEqual(wizard.address_combo.index("insert"), len(prefix))
        self.assertTrue(wizard.address_combo.selection_present())
        wizard.password.set("transient-only")
        wizard.select_saved_address()
        self.assertEqual(wizard.username.get(), "admin")
        self.assertEqual(wizard.password.get(), "")
        self.assertEqual(str(wizard.address_combo["state"]), "normal")
        wizard.destroy_wizard()
        close_root(root)

    def test_clear_saved_data_requires_confirmation_and_clears_all_hint_fields(self):
        settings = Mock()
        settings.profiles.return_value = [{"address": "example.test", "username": "root"}]
        with patch("app.ConnectionSettings", return_value=settings):
            root = tk.Tk()
            root.withdraw()
            app = App(root)
            app.new_download()
        wizard = app.wizard
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
        self.assertFalse(wizard.remember_connection.get())
        self.assertFalse(wizard.password_visible.get())
        self.assertIsNone(wizard.login_identity)
        self.assertFalse(job.cancelled.is_set())
        self.assertEqual(job.state, "queued")
        wizard.destroy_wizard()
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
        wizard = app.wizard
        wizard.username.set("example-user")
        wizard.password.set("transient-only")
        with patch("wizard.threading.Thread"), patch("app.messagebox.askyesno") as prompt:
            wizard.authenticate("example.test", cert)
            prompt.assert_not_called()
        self.assertEqual(wizard.password.get(), "")
        settings.trust_certificate.assert_not_called()
        settings.remember_profile.assert_not_called()
        wizard.destroy_wizard()
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
        wizard = app.wizard
        wizard.username.set("example-user")
        wizard.password.set("transient-only")
        with patch("wizard.threading.Thread"), patch("app.messagebox.askyesno", return_value=True):
            wizard.authenticate("example.test", cert)
        settings.trust_certificate.assert_called_once_with("example.test", fingerprint(cert))
        settings.remember_profile.assert_not_called()
        self.assertEqual(wizard.password.get(), "")
        wizard.destroy_wizard()
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
        wizard = app.wizard
        wizard.username.set("example-user")
        wizard.password.set("transient-only")
        with (
            patch("wizard.threading.Thread") as worker,
            patch("app.messagebox.askyesno", return_value=False) as prompt,
        ):
            wizard.authenticate("example.test", cert)
            self.assertIn("changed", prompt.call_args.args[0].lower())
            worker.assert_not_called()
        settings.trust_certificate.assert_not_called()
        self.assertEqual(wizard.password.get(), "")
        wizard.destroy_wizard()
        close_root(root)


if __name__ == "__main__":
    unittest.main(verbosity=2)
