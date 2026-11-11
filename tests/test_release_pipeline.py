"""Release gates are checked with synthetic files and no publishing credentials."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
import zipfile
from unittest.mock import Mock, patch

from tools.ci_installer_check import ensure_runner
from tools import ci_installer_check
from tools.release_artifacts import (create_draft, expected_files, publish_reviewed,
                                     validate_publish_choice, verify_files, verify_source)
from metadata import VERSION
from tools.runtime_licenses import license_urls, runtime_versions


class ReleasePipelineTests(unittest.TestCase):
    def test_runtime_version_probe_uses_tk_initialization_and_always_closes_it(self):
        root=Mock()
        root.tk.eval.side_effect=lambda command: {'info patchlevel': '8.6.17',
                                                'package provide Tk': '8.6.16'}[command]
        with patch('tools.runtime_licenses.tkinter.Tk', return_value=root):
            self.assertEqual(runtime_versions(), ('8.6.17', '8.6.16'))
        root.withdraw.assert_called_once()
        root.destroy.assert_called_once()

    def test_runtime_license_urls_follow_exact_versions_without_local_tk_paths(self):
        urls = license_urls('8.6.17', '8.6.16', '3.5.4')
        self.assertEqual(urls['TK.txt'], 'https://raw.githubusercontent.com/tcltk/tk/core-8-6-16/license.terms')
        self.assertIn('tcl/core-8-6-17/', urls['TCL.txt'])
        self.assertIn('openssl-3.5.4/', urls['OPENSSL.txt'])
        with self.assertRaises(ValueError):
            license_urls('8.6.17/../main', '8.6.16', '3.5.4')

    def fixture_files(self, directory):
        for name in expected_files(VERSION)[::2]:
            path = Path(directory) / name
            path.write_bytes(b'fabricated release file, never execute')
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            path.with_name(name + '.sha256').write_text(digest + '  ' + name + '\n')

    def test_manifest_files_reject_tampering_and_missing_assets(self):
        with tempfile.TemporaryDirectory() as directory:
            self.fixture_files(directory)
            self.assertEqual(len(verify_files(directory, VERSION)), 4)
            target = Path(directory) / expected_files(VERSION)[0]
            target.write_bytes(b'changed payload')
            with self.assertRaisesRegex(ValueError, 'mismatch'):
                verify_files(directory, VERSION)
            target.unlink()
            with self.assertRaisesRegex(ValueError, 'Missing'):
                verify_files(directory, VERSION)

    def test_installer_tests_refuse_local_and_self_hosted_runners(self):
        for values in ({'GITHUB_ACTIONS': 'false'},
                       {'GITHUB_ACTIONS': 'true', 'RUNNER_ENVIRONMENT': 'self-hosted', 'RUNNER_OS': 'Windows'},
                       {'GITHUB_ACTIONS': 'true', 'RUNNER_ENVIRONMENT': 'github-hosted', 'RUNNER_OS': 'Linux'}):
            with patch.dict(os.environ, values, clear=True):
                with self.assertRaises(RuntimeError):
                    ensure_runner()

    def test_installer_lifecycle_guard_runs_before_any_file_download_or_process(self):
        with patch.object(ci_installer_check,'ensure_runner',side_effect=RuntimeError('fixture refusal')), \
                patch.object(ci_installer_check.subprocess,'run') as execute, \
                patch.object(ci_installer_check.urllib.request,'urlopen') as download, \
                patch.object(Path,'mkdir') as create:
            with self.assertRaisesRegex(RuntimeError,'fixture refusal'):
                ci_installer_check.run()
        execute.assert_not_called()
        download.assert_not_called()
        create.assert_not_called()

    def test_no_release_mutations_from_local_or_pull_request_context(self):
        with patch.dict(os.environ, {'GITHUB_ACTIONS': 'false'}, clear=True), \
             patch('tools.release_artifacts.subprocess.run') as mutate:
            with self.assertRaises(RuntimeError):
                create_draft('unused')
            with self.assertRaises(RuntimeError):
                publish_reviewed()
            mutate.assert_not_called()
        with patch.dict(os.environ, {'GITHUB_ACTIONS': 'true', 'GITHUB_EVENT_NAME': 'pull_request',
                                     'GITHUB_REF': 'refs/pull/1/merge'}, clear=True):
            with self.assertRaises(RuntimeError):
                create_draft('unused')

    def test_publish_requires_exact_version_commit_and_explicit_approval(self):
        validate_publish_choice('v' + VERSION, 'a' * 40, 'true')
        for tag, commit, confirmed in [('v' + VERSION, 'a' * 40, 'false'),
                                      ('v0.0.1', 'a' * 40, 'true'),
                                      ('v' + VERSION, 'main', 'true'),
                                      ('v' + VERSION + '; command', 'a' * 40, 'true')]:
            with self.assertRaises(ValueError):
                validate_publish_choice(tag, commit, confirmed)

    def test_source_package_rejects_unexpected_paths_before_processing_payloads(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / 'untrusted.zip'
            with zipfile.ZipFile(archive, 'w') as zipped:
                zipped.writestr('../unexpected.py', 'raise RuntimeError("never execute")')
            with self.assertRaisesRegex(ValueError, 'allowlist'):
                verify_source(archive, VERSION)

    def publish_environment(self):
        return dict(GITHUB_ACTIONS='true', GITHUB_EVENT_NAME='workflow_dispatch',
                    GITHUB_REF='refs/heads/main', GITHUB_SHA='a' * 40,
                    GITHUB_REPOSITORY='example/project', OVA_RELEASE_TAG='v' + VERSION,
                    OVA_RELEASE_COMMIT='a' * 40, OVA_CONFIRM_PUBLISH='true')

    def test_publish_refuses_a_moved_main_before_any_mutation(self):
        with patch.dict(os.environ, self.publish_environment(), clear=True), \
             patch('tools.release_artifacts.subprocess.check_output',
                   return_value=json.dumps({'object': {'sha': 'b' * 40}})), \
             patch('tools.release_artifacts.subprocess.run') as mutate:
            with self.assertRaisesRegex(ValueError, 'Main moved'):
                publish_reviewed()
            mutate.assert_not_called()

    def test_publish_never_modifies_an_already_published_release(self):
        responses = [json.dumps({'object': {'sha': 'a' * 40}}),
                     json.dumps({'draft': False, 'target_commitish': 'a' * 40})]
        with patch.dict(os.environ, self.publish_environment(), clear=True), \
             patch('tools.release_artifacts.subprocess.check_output', side_effect=responses), \
             patch('tools.release_artifacts.subprocess.run') as mutate:
            with self.assertRaisesRegex(ValueError, 'new draft'):
                publish_reviewed()
            mutate.assert_not_called()


if __name__ == '__main__':
    unittest.main()
