"""Update checks use fabricated GitHub responses/files; never real downloads/setup."""
import hashlib
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import tkinter as tk
import unittest
from unittest.mock import Mock, patch

from metadata import VERSION
from updates import (GitHubRedirect, REPOSITORY, RELEASES_URL, UpdateClient,
                     UpdatePreferences, safe_url, select_release, verify_installer, version_tuple)


INSTALLER = b'fake installer fixture; never execute'
DIGEST = hashlib.sha256(INSTALLER).hexdigest()


def release_row(version='9.0.0', **overrides):
    name = f'OVA-Exporter-GUI-{version}-Windows-x64-Setup.exe'
    prefix = f'https://github.com/{REPOSITORY}/releases/download/v{version}/'
    row = dict(tag_name='v' + version, draft=False, prerelease=True,
               html_url=f'https://github.com/{REPOSITORY}/releases/tag/v{version}',
               body='Fabricated release notes', assets=[
                   dict(name=name, state='uploaded', size=len(INSTALLER),
                        browser_download_url=prefix + name, digest='sha256:' + DIGEST),
                   dict(name=name + '.sha256', state='uploaded', size=160,
                        browser_download_url=prefix + name + '.sha256')])
    row.update(overrides)
    return row


class Response(io.BytesIO):
    def __init__(self, body, url):
        super().__init__(body)
        self.url = url

    def geturl(self):
        return self.url


class UpdatesTests(unittest.TestCase):
    def test_selects_highest_numeric_version_including_published_preview(self):
        release = select_release([release_row('2.9.0'), release_row('2.10.0'),
                                  release_row('2.11.0', draft=True)], '2.2.0')
        self.assertEqual(release.version, '2.10.0')
        self.assertTrue(release.preview)
        self.assertIsNone(select_release([release_row('2.2.0'), release_row('2.1.0')], '2.2.0'))

    def test_skipping_latest_does_not_offer_an_older_release(self):
        rows = [release_row('2.10.0'), release_row('2.9.0')]
        self.assertIsNone(select_release(rows, '2.2.0', '2.10.0'))
        self.assertEqual(select_release(rows, '2.2.0').version, '2.10.0')
        self.assertEqual(select_release([release_row('2.11.0')], '2.2.0', '2.10.0').version, '2.11.0')

    def test_malformed_source_only_and_untrusted_releases_are_ignored(self):
        rows = [release_row('2.3.0-rc1'), release_row(assets=[]), None,
                release_row(html_url='https://evil.test/fake')]
        bad = release_row()
        bad['assets'][0]['browser_download_url'] = 'https://github.com/other/repo/payload.exe'
        rows.append(bad)
        for size in (0, -1, True, 400 * 1024**2, '12'):
            bad = release_row()
            bad['assets'][0]['size'] = size
            rows.append(bad)
        self.assertIsNone(select_release(rows, VERSION))
        with self.assertRaises(ValueError):
            select_release({'error': 'rate limit'}, VERSION)
        for tag in ('1.0', '1.0.0.exe', '../1.0.0', None):
            with self.assertRaises(ValueError):
                version_tuple(tag)

    def test_https_host_and_redirect_allowlist(self):
        for url in ('http://github.com/x', 'https://github.com.evil.test/x',
                    'https://user:password@github.com/x', 'file:///payload.exe',
                    'https://github.com:8443/x', 'https://evil.test/x'):
            with self.assertRaises(ValueError):
                safe_url(url)
        safe_url('https://release-assets.githubusercontent.com/release/path?signature=example')
        request = Mock()
        with self.assertRaises(ValueError):
            GitHubRedirect().redirect_request(request, None, 302, '', {}, 'http://github.com/file')

    def test_metadata_request_uses_public_api_without_credentials(self):
        opener = Mock()
        opener.open.return_value = Response(json.dumps([release_row()]).encode(), RELEASES_URL)
        client = UpdateClient(opener)
        self.assertEqual(client.check(VERSION).version, '9.0.0')
        request = opener.open.call_args.args[0]
        self.assertEqual(request.full_url, RELEASES_URL)
        self.assertFalse(any(key.lower() in ('authorization', 'cookie') for key in request.headers))
        self.assertEqual(opener.open.call_args.kwargs['timeout'], 15)

    def download_client(self, release, body=INSTALLER, digest=DIGEST):
        opener = Mock()
        opener.open.side_effect = [
            Response(f'{digest}  {release.filename}\n'.encode(), release.checksum_url),
            Response(body, release.installer_url)]
        return UpdateClient(opener)

    def test_download_verifies_size_checksum_and_rechecks_before_install(self):
        release = select_release([release_row()], VERSION)
        with tempfile.TemporaryDirectory() as directory:
            progress = Mock()
            path, digest = self.download_client(release).download(release, directory, progress)
            self.assertEqual(path.read_bytes(), INSTALLER)
            self.assertEqual(digest, DIGEST)
            progress.assert_called_with(len(INSTALLER), len(INSTALLER))
            verify_installer(path, release, digest)
            path.write_bytes(b'changed file')
            with self.assertRaises(ValueError):
                verify_installer(path, release, digest)

    def test_corrupt_truncated_and_oversized_downloads_are_removed(self):
        release = select_release([release_row()], VERSION)
        for body in (b'x' * len(INSTALLER), INSTALLER[:-1], INSTALLER + b'extra'):
            with tempfile.TemporaryDirectory() as directory:
                with self.assertRaises(ValueError):
                    self.download_client(release, body).download(release, directory)
                self.assertEqual(list(Path(directory).iterdir()), [])

    def test_disagreeing_checksum_is_rejected_before_downloading_executable(self):
        release = select_release([release_row()], VERSION)
        client = self.download_client(release, digest='0' * 64)
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, 'disagree'):
                client.download(release, directory)
        self.assertEqual(client.opener.open.call_count, 1)

    def test_failed_transfer_removes_partial_and_does_not_create_installer(self):
        release = select_release([release_row()], VERSION)
        client = self.download_client(release)
        client.opener.open.side_effect = [
            Response(f'{DIGEST}  {release.filename}'.encode(), release.checksum_url),
            TimeoutError('fixture connection failure')]
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(TimeoutError):
                client.download(release, directory)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_update_preferences_only_store_choices_and_survive_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            preferences = UpdatePreferences(directory)
            self.assertTrue(preferences.due())
            preferences.automatic = False
            preferences.skipped = '2.4.0'
            preferences.remind_after = 1500
            preferences.save()
            saved = UpdatePreferences(directory)
            self.assertFalse(saved.due())
            self.assertEqual(saved.skipped, '2.4.0')
            self.assertEqual(set(json.loads(saved.path.read_text())),
                             {'automatic', 'skipped', 'remind_after'})
            saved.path.write_text('corrupt JSON')
            self.assertTrue(UpdatePreferences(directory).due())

    def test_reminder_defers_automatic_checks(self):
        preferences = UpdatePreferences()
        with patch('updates.time.time', return_value=100):
            preferences.remind_after = 200
            self.assertFalse(preferences.due())
            preferences.remind_after = 99
            self.assertTrue(preferences.due())


class UpdateUITests(unittest.TestCase):
    def setUp(self):
        from app import App
        from test_app import close_root
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(lambda: close_root(self.root))
        settings = Mock()
        settings.migrate_legacy.return_value = []
        self.app = App(self.root, settings=settings, tool_store=False,
                       tool_locator=lambda *args: Path(__file__), update_checks=False)
        self.ui = self.app.updater
        self.ui.enabled = True
        self.ui.release = select_release([release_row()], VERSION)
        self.ui.ready = Path('fixture-never-run.exe'), DIGEST

    def buttons(self, widget):
        from tkinter import ttk
        for child in widget.winfo_children():
            if isinstance(child, ttk.Button):
                yield child
            yield from self.buttons(child)

    def test_install_blocked_for_running_queued_verifying_and_stalled_tasks(self):
        for state in ('running', 'queued', 'verifying', 'cancel_stalled'):
            self.app.manager.unfinished = Mock(return_value=[SimpleNamespace(state=state)])
            with patch('update_ui.subprocess.Popen') as launch, patch('update_ui.messagebox.showinfo'):
                self.ui.install()
                launch.assert_not_called()

    def test_install_requires_confirmation_and_rechecks_busy_state(self):
        self.app.manager.unfinished = Mock(side_effect=[[], [object()]])
        with patch('update_ui.messagebox.askyesno', return_value=True), patch('update_ui.subprocess.Popen') as launch:
            self.ui.install()
            launch.assert_not_called()

    def test_install_verifies_file_and_never_runs_rejected_file(self):
        with patch('update_ui.messagebox.askyesno', return_value=True), \
             patch('update_ui.verify_installer', side_effect=ValueError('changed')), \
             patch('update_ui.subprocess.Popen') as launch, patch('update_ui.messagebox.showerror'):
            self.ui.install()
            launch.assert_not_called()

    def test_confirmed_idle_update_opens_setup_and_closes_app_without_stopping_exports(self):
        with patch('update_ui.messagebox.askyesno', return_value=True), \
             patch('update_ui.verify_installer') as verify, \
             patch('update_ui.subprocess.Popen') as launch, \
             patch.object(self.app, 'finish_close') as finish, \
             patch.object(self.app.manager, 'stop_all') as stop:
            self.ui.install()
            verify.assert_called_once()
            launch.assert_called_once_with(['fixture-never-run.exe', '/SP-'], shell=False)
            finish.assert_called_once()
            stop.assert_not_called()

    def test_ready_prompt_disables_install_until_exports_finish(self):
        self.app.manager.unfinished = Mock(return_value=[object()])
        self.ui.show_ready()
        button = next(button for button in self.buttons(self.ui.dialog) if button['text'] == 'Install now')
        self.assertEqual(str(button['state']), 'disabled')
        self.ui.dialog.destroy()

    def test_skip_and_remind_choices_and_manual_check_override(self):
        self.ui.show_offer()
        next(button for button in self.buttons(self.ui.dialog) if button['text'] == 'Skip this version').invoke()
        self.assertEqual(self.ui.preferences.skipped, '9.0.0')
        self.ui.show_offer()
        next(button for button in self.buttons(self.ui.dialog) if button['text'] == 'Remind me later').invoke()
        self.assertFalse(self.ui.preferences.due())
        self.ui.ready = None
        self.ui.client = Mock()
        self.ui.client.check.return_value = None
        def inline_thread(**kwargs):
            return SimpleNamespace(start=kwargs['target'])
        with patch('update_ui.threading.Thread', side_effect=inline_thread), \
             patch('update_ui.messagebox.showinfo'):
            self.ui.check(manual=True)
            self.app.poll()
        self.ui.client.check.assert_called_once_with(VERSION, '')

    def test_offline_startup_does_not_interrupt_exports_or_show_popup(self):
        with patch('update_ui.messagebox.showwarning') as warning:
            self.ui.handle('checked', (False, None, 'offline fixture'))
            warning.assert_not_called()
        self.assertFalse(self.ui.checking)

    def test_installed_update_preserves_folder_and_never_restarts_windows_or_forces_apps(self):
        from update_ui import installer_command
        folder = Path('C:/Example Folder/OVA Exporter GUI')
        with patch('update_ui.installed_app_directory', return_value=folder), \
             patch('update_ui.os.getpid', return_value=1234):
            command = installer_command(Path('downloaded.exe'))
        self.assertEqual(command, ['downloaded.exe', '/SP-', '/SILENT', '/NORESTART',
                                  '/OVAUPDATE=1', '/OVAPID=1234', f'/DIR={folder}'])
        self.assertFalse(any('CLOSEAPPLICATIONS' in arg or 'FORCE' in arg for arg in command))

    def test_portable_or_source_install_keeps_normal_setup(self):
        from update_ui import installer_command, installed_app_directory
        with patch('update_ui.sys.frozen', False, create=True):
            self.assertIsNone(installed_app_directory())
            self.assertEqual(installer_command('downloaded.exe'), ['downloaded.exe', '/SP-'])
        with patch('update_ui.sys.frozen', True, create=True), \
             patch.object(Path, 'is_file', return_value=False):
            self.assertIsNone(installed_app_directory())

    def test_verified_download_auto_installs_only_after_explicit_update_choice(self):
        self.ui.install_after_download = True
        with patch.object(self.ui, 'install') as install, patch.object(self.ui, 'show_ready') as ready:
            self.ui.handle('downloaded', (Path('downloaded.exe'), DIGEST, None))
            install.assert_called_once_with(confirmed=True)
            ready.assert_not_called()

    def test_download_without_auto_install_consent_stays_ready(self):
        self.ui.install_after_download = False
        with patch.object(self.ui, 'install') as install, patch.object(self.ui, 'show_ready') as ready:
            self.ui.handle('downloaded', (Path('downloaded.exe'), DIGEST, None))
            install.assert_not_called()
            ready.assert_called_once()

    def test_new_export_started_during_download_defers_installation(self):
        self.ui.install_after_download = True
        self.app.manager.unfinished = Mock(return_value=[object()])
        with patch.object(self.ui, 'install') as install, patch.object(self.ui, 'show_ready') as ready:
            self.ui.handle('downloaded', (Path('downloaded.exe'), DIGEST, None))
            install.assert_not_called()
            ready.assert_called_once()

    def test_update_download_failure_never_closes_or_installs(self):
        self.ui.install_after_download = True
        with patch.object(self.ui, 'install') as install, \
             patch.object(self.app, 'finish_close') as close, \
             patch('update_ui.messagebox.showerror'):
            self.ui.handle('downloaded', (None, None, 'fixture download failed'))
            install.assert_not_called()
            close.assert_not_called()

    def test_explicit_ready_button_does_not_repeat_confirmation(self):
        self.ui.show_ready()
        with patch('update_ui.messagebox.askyesno') as ask, \
             patch('update_ui.verify_installer'), patch('update_ui.subprocess.Popen'), \
             patch.object(self.app, 'finish_close'):
            next(button for button in self.buttons(self.ui.dialog) if button['text'] == 'Install now').invoke()
            ask.assert_not_called()


if __name__ == '__main__':
    unittest.main()
