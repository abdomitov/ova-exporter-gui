"""Release gates are checked with synthetic files and no publishing credentials."""
import hashlib
import os
from pathlib import Path
import tempfile
import unittest
import zipfile
from unittest.mock import patch

from tools.ci_installer_check import ensure_runner
from tools.release_artifacts import (create_draft, expected_files, publish_reviewed,
                                     validate_publish_choice, verify_files, verify_source)
from metadata import VERSION


class ReleasePipelineTests(unittest.TestCase):
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


if __name__ == '__main__':
    unittest.main()
