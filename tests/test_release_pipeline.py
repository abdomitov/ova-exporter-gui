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
from tools import bump_version, release_artifacts
from tools.release_artifacts import (Superseded, decide_release, expected_files, parse_version,
                                     publish, verify_files, verify_source)
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

    def test_source_package_rejects_unexpected_paths_before_processing_payloads(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / 'untrusted.zip'
            with zipfile.ZipFile(archive, 'w') as zipped:
                zipped.writestr('../unexpected.py', 'raise RuntimeError("never execute")')
            with self.assertRaisesRegex(ValueError, 'allowlist'):
                verify_source(archive, VERSION)

    def test_version_decision_releases_only_a_new_higher_version(self):
        self.assertEqual(parse_version('v2.4.0'), (2, 4, 0))
        self.assertIsNone(parse_version('v2.4'))
        self.assertIsNone(parse_version('main'))
        release, _, previous = decide_release('2.5.0', ['v2.4.0', 'v2.3.5', 'nightly'])
        self.assertTrue(release)
        self.assertEqual(previous, 'v2.4.0')
        release, reason, _ = decide_release('2.4.0', ['v2.4.0', 'v2.3.5'])
        self.assertFalse(release)
        self.assertIn('already released', reason)
        self.assertTrue(decide_release('0.1.0', [])[0])
        with self.assertRaisesRegex(ValueError, 'lower'):
            decide_release('2.3.9', ['v2.4.0'])
        with self.assertRaises(ValueError):
            decide_release('2.x', [])

    def test_version_ten_sorts_after_nine(self):
        release, _, previous = decide_release('2.10.0', ['v2.9.0'])
        self.assertTrue(release)
        self.assertEqual(previous, 'v2.9.0')

    def publish_environment(self):
        return dict(GITHUB_ACTIONS='true', GITHUB_EVENT_NAME='push', GITHUB_REF='refs/heads/main',
                    GITHUB_SHA='a' * 40, GITHUB_REPOSITORY='example/project', GITHUB_RUN_ID='77')

    def manifest_directory(self, directory, **changes):
        self.fixture_files(directory)
        self.fixture_source = None
        manifest = dict(schema=1, version=VERSION, commit='a' * 40, repository='example/project', run_id='77',
                        files=verify_files(directory, VERSION),
                        checks=dict(frozen='passed', source='passed', installer={
                            name: 'passed' for name in ('fresh_install', 'fresh_launch_self_test', 'fresh_uninstall',
                                                        'parent_exit_wait', 'upgrade', 'reopen', 'uninstall')}))
        manifest.update(changes)
        (Path(directory) / 'build-manifest.json').write_text(json.dumps(manifest))

    def test_publish_is_limited_to_the_main_branch_pipeline(self):
        for values in ({'GITHUB_ACTIONS': 'false'},
                       dict(self.publish_environment(), GITHUB_EVENT_NAME='pull_request'),
                       dict(self.publish_environment(), GITHUB_REF='refs/heads/feature')):
            with patch.dict(os.environ, values, clear=True), \
                    patch('tools.release_artifacts.subprocess.run') as mutate:
                with self.assertRaises(RuntimeError):
                    publish('unused')
                mutate.assert_not_called()

    def test_publish_rejects_a_manifest_from_another_commit_or_run(self):
        for change in (dict(commit='b' * 40), dict(run_id='78'), dict(repository='other/project'),
                       dict(version='0.0.1')):
            with tempfile.TemporaryDirectory() as directory, \
                    patch.dict(os.environ, self.publish_environment(), clear=True), \
                    patch('tools.release_artifacts.subprocess.run') as mutate:
                self.manifest_directory(directory, **change)
                with self.subTest(change=change), self.assertRaisesRegex(ValueError, 'manifest'):
                    publish(directory)
                mutate.assert_not_called()

    def test_publish_requires_every_build_check_to_have_passed(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.dict(os.environ, self.publish_environment(), clear=True), \
                patch('tools.release_artifacts.verify_source'), \
                patch('tools.release_artifacts.subprocess.run') as mutate:
            self.manifest_directory(directory, checks=dict(frozen='passed', source='passed', installer={}))
            with self.assertRaisesRegex(ValueError, 'evidence'):
                publish(directory)
            mutate.assert_not_called()

    def test_publish_skips_an_existing_version_and_a_moved_main_without_mutating(self):
        for tags, reason in ((['v' + VERSION], 'already released'), (['v0.0.1'], 'newer commit')):
            with tempfile.TemporaryDirectory() as directory, \
                    patch.dict(os.environ, self.publish_environment(), clear=True), \
                    patch('tools.release_artifacts.verify_source'), \
                    patch('tools.release_artifacts.existing_tags', return_value=tags), \
                    patch('tools.release_artifacts.gh_json', return_value={'object': {'sha': 'b' * 40}}), \
                    patch('tools.release_artifacts.subprocess.run') as mutate:
                self.manifest_directory(directory)
                with self.subTest(reason=reason), self.assertRaisesRegex(Superseded, reason):
                    publish(directory)
                mutate.assert_not_called()

    def test_publish_creates_a_public_release_from_the_exact_files_only(self):
        listed = {'draft': False, 'html_url': 'https://example.test',
                  'assets': [dict(name=name) for name in (*expected_files(VERSION), 'build-manifest.json')]}
        def api(*args):
            return {'object': {'sha': 'a' * 40}} if 'heads/main' in args[0] else listed if 'releases/tags' in args[0] else {}
        with tempfile.TemporaryDirectory() as directory, \
                patch.dict(os.environ, self.publish_environment(), clear=True), \
                patch('tools.release_artifacts.verify_source'), \
                patch('tools.release_artifacts.existing_tags', return_value=['v0.0.1']), \
                patch('tools.release_artifacts.gh_json', side_effect=api), \
                patch('tools.release_artifacts.subprocess.run') as mutate:
            self.manifest_directory(directory)
            publish(directory)
        command = mutate.call_args.args[0]
        self.assertEqual(command[:3], ['gh', 'release', 'create'])
        self.assertNotIn('--draft', command)
        self.assertNotIn('--clobber', command)
        self.assertEqual(command[command.index('--target') + 1], 'a' * 40)
        self.assertEqual(sum(item.endswith('.exe') for item in command), 1)

    def test_release_workflow_publishes_only_from_main_with_least_privilege(self):
        text = (Path(release_artifacts.ROOT) / '.github/workflows/release.yml').read_text()
        self.assertIn("branches: [main]", text)
        self.assertEqual(text.count('contents: write'), 1)
        self.assertIn("needs.plan.outputs.release == 'true'", text)
        self.assertNotIn('pull_request', text)
        self.assertNotIn('--clobber', text)


class VersionBumpTests(unittest.TestCase):
    def test_repository_copies_of_the_version_agree(self):
        self.assertEqual(bump_version.check(), VERSION)

    def test_bump_updates_both_files_and_refuses_lower_or_malformed_versions(self):
        with tempfile.TemporaryDirectory() as directory:
            app, installer = Path(directory) / 'metadata.py', Path(directory) / 'windows.iss'
            app.write_text("# app\nVERSION = '2.4.0'\n")
            installer.write_text('[Setup]\n  #define AppVersion "2.4.0"\n')
            with patch.object(bump_version, 'METADATA', app), patch.object(bump_version, 'INSTALLER', installer):
                self.assertEqual(bump_version.bump('2.5.0'), ('2.4.0', '2.5.0'))
                self.assertIn("VERSION = '2.5.0'", app.read_text())
                self.assertIn('#define AppVersion "2.5.0"', installer.read_text())
                for bad in ('2.5.0', '2.4.9', '2.10', 'v3.0.0', '3.0.0; rm'):
                    with self.subTest(bad=bad), self.assertRaises(ValueError):
                        bump_version.bump(bad)
                self.assertEqual(bump_version.bump('2.10.0')[1], '2.10.0')
                installer.write_text('  #define AppVersion "9.9.9"\n')
                with self.assertRaisesRegex(ValueError, 'says'):
                    bump_version.check()


if __name__ == '__main__':
    unittest.main()
