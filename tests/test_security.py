"""Adversarial fixtures only: no server, installer execution or real settings."""
import io
import tarfile
import tkinter as tk
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

from app import App
from connection_settings import ConnectionSettings
from exporter import export_command, verify_ova
from jobs import JobManager
from metadata import VERSION
from test_app import close_root, response
from test_connection_settings import FakeProtection
from test_updates import DIGEST, Response, release_row
from updates import GitHubRedirect, UpdateClient, safe_url, select_release
from vsphere import VSphere, probe


class TrustSecurityTests(unittest.TestCase):
    def test_certificate_prompts_default_to_decline_and_do_not_start_login(self):
        for saved in (None, ':'.join(['AA'] * 32)):
            with self.subTest(previous_pin=saved):
                settings = Mock()
                settings.profiles.return_value = []
                settings.trusted_pin.return_value = saved
                root = tk.Tk()
                root.withdraw()
                try:
                    app = App(root, settings=settings, remember_theme=False, tool_store=False,
                              tool_locator=lambda *args: Path(__file__), update_checks=False)
                    app.new_download()
                    wizard = app.wizard
                    wizard.username.set('synthetic-user')
                    wizard.password.set('synthetic-password')
                    with patch('wizard.messagebox.askyesno', return_value=False) as ask, \
                            patch('wizard.threading.Thread') as worker:
                        wizard.authenticate('192.0.2.10', b'fixture-certificate')
                    self.assertEqual(ask.call_args.kwargs.get('default'), 'no')
                    settings.trust_certificate.assert_not_called()
                    worker.assert_not_called()
                    self.assertEqual(wizard.password.get(), '')
                    wizard.destroy_wizard()
                finally:
                    close_root(root)

    def test_wrong_certificate_blocks_cookie_and_login_body_before_request(self):
        client = VSphere('example.test', b'approved-certificate')
        client.cookie = 'vmware_soap_session="synthetic-only"'
        connection = Mock()
        connection.sock.getpeercert.return_value = b'attacker-certificate'
        with patch('vsphere.http.client.HTTPSConnection', return_value=connection):
            with self.assertRaisesRegex(RuntimeError, 'certificate changed'):
                client.call('Login', '<password>synthetic-only</password>')
        connection.request.assert_not_called()
        connection.getresponse.assert_not_called()
        connection.close.assert_called_once()

    def test_certificate_discovery_never_sends_an_http_request(self):
        connection = Mock()
        connection.sock.getpeercert.return_value = b'certificate-only'
        with patch('vsphere.http.client.HTTPSConnection', return_value=connection):
            self.assertEqual(probe('example.test'), b'certificate-only')
        connection.request.assert_not_called()
        connection.close.assert_called_once()

    def test_xml_in_credentials_stays_literal_text(self):
        client = VSphere('example.test', b'fixture')
        service = response('<returnval><sessionManager type="SessionManager">s</sessionManager>'
                           '<viewManager type="ViewManager">v</viewManager>'
                           '<propertyCollector type="PropertyCollector">p</propertyCollector>'
                           '<rootFolder type="Folder">r</rootFolder></returnval>')
        hostile = '&</password><PowerOnVM_Task/>\"\''
        with patch.object(client, 'call', side_effect=[service, response('')]) as call:
            client.login(hostile, hostile)
        import xml.etree.ElementTree as ET
        body = ET.fromstring('<body>' + call.call_args.args[1] + '</body>')
        self.assertEqual(body.findtext('password'), hostile)
        self.assertEqual(body.findtext('userName'), hostile)
        self.assertIsNone(body.find('PowerOnVM_Task'))


class UpdateSecurityTests(unittest.TestCase):
    def test_redirects_reject_external_hosts_protocols_userinfo_and_ports(self):
        from urllib.request import Request
        request = Request('https://github.com/fixture')
        for url in ('file:///fixture.exe', 'http://github.com/fixture',
                    'https://github.com.evil.test/payload', 'https://evil.test/github.com',
                    'https://github.com@evil.test/payload',
                    'https://user:secret@github.com/payload', 'https://github.com:8443/payload'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                GitHubRedirect().redirect_request(request, None, 302, '', {}, url)

    def test_public_metadata_api_is_separate_from_asset_hosts(self):
        for url in ('https://github.com/fixture',
                    'https://release-assets.githubusercontent.com/fixture'):
            with self.assertRaises(ValueError):
                safe_url(url, api=True)

    def test_final_response_url_is_revalidated_and_closed_before_read(self):
        opener = Mock()
        reply = Mock()
        reply.geturl.return_value = 'https://evil.test/fixture'
        opener.open.return_value = reply
        with self.assertRaises(ValueError):
            UpdateClient(opener).open('https://github.com/fixture')
        reply.read.assert_not_called()
        reply.close.assert_called_once()

    def test_forged_release_paths_never_trigger_a_download(self):
        release = select_release([release_row()], VERSION)
        attacks = [dict(filename='../payload.exe'), dict(size=True),
                   dict(installer_url='https://github.com/other/project/payload.exe'),
                   dict(checksum_url='https://evil.test/checksum'),
                   dict(version='../9.0.0')]
        for fields in attacks:
            client = UpdateClient(Mock())
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                client.download(replace(release, **fields), 'must-not-create')
            client.opener.open.assert_not_called()

    def test_untrusted_checksum_cannot_authorize_a_different_filename(self):
        import tempfile
        release = select_release([release_row()], VERSION)
        opener = Mock()
        opener.open.return_value = Response((DIGEST + '  payload.exe\n').encode(), release.checksum_url)
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError, 'checksum'):
                UpdateClient(opener).download(release, folder)
            self.assertEqual(list(Path(folder).iterdir()), [])
        self.assertEqual(opener.open.call_count, 1)

    def test_oversized_release_metadata_is_not_parsed(self):
        client = UpdateClient(Mock())
        reply = Mock()
        reply.__enter__ = Mock(return_value=reply)
        reply.__exit__ = Mock(return_value=False)
        reply.read.return_value = b'x' * 2_000_001
        with patch.object(client, 'open', return_value=reply), patch('updates.json.loads') as parse:
            with self.assertRaisesRegex(ValueError, 'large'):
                client.check(VERSION)
        parse.assert_not_called()


class ExportSecurityTests(unittest.TestCase):
    def archive(self, entry, data=b''):
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode='w') as archive:
            descriptor = tarfile.TarInfo('vm.ovf')
            archive.addfile(descriptor, io.BytesIO())
            archive.addfile(entry, io.BytesIO(data))
        stream.seek(0)
        return stream

    def test_links_devices_and_directories_are_rejected_without_extraction(self):
        for kind in (tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.CHRTYPE,
                     tarfile.BLKTYPE, tarfile.FIFOTYPE, tarfile.DIRTYPE):
            member = tarfile.TarInfo('vm.vmdk')
            member.type, member.linkname = kind, '../outside'
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, 'non-file'):
                verify_ova(self.archive(member))

    def test_pax_overridden_traversal_is_rejected(self):
        member = tarfile.TarInfo('disk.vmdk')
        member.pax_headers = {'path': '../outside.vmdk'}
        with self.assertRaisesRegex(ValueError, 'Unsafe'):
            verify_ova(self.archive(member))

    def test_archive_metadata_is_bounded_before_body_is_read(self):
        for kind in (tarfile.XHDTYPE, tarfile.XGLTYPE, tarfile.GNUTYPE_LONGNAME,
                     tarfile.GNUTYPE_LONGLINK):
            member = tarfile.TarInfo('oversized-metadata')
            member.type, member.size = kind, 2_000_001
            # Only a 512-byte header exists. Do not allocate or consume a bomb.
            fixture = io.BytesIO(member.tobuf(format=tarfile.USTAR_FORMAT))
            original_read = tarfile._Stream.read
            def guarded_read(stream, size):
                if size > 2_000_000:
                    raise AssertionError('Parser attempted an unbounded metadata read.')
                return original_read(stream, size)
            with self.subTest(kind=kind), patch.object(tarfile._Stream, 'read', guarded_read):
                with self.assertRaisesRegex(ValueError, 'metadata.*limit'):
                    verify_ova(fixture)

    def test_chained_metadata_is_bounded_before_python_recursion_limits(self):
        header = tarfile.TarInfo('metadata')
        header.type, header.size = tarfile.GNUTYPE_LONGNAME, 2
        fixture = io.BytesIO((header.tobuf(format=tarfile.USTAR_FORMAT) + b'x\0' + b'\0' * 510) * 34)
        with self.assertRaisesRegex(ValueError, 'metadata.*limit'):
            verify_ova(fixture)

    def test_metadata_total_and_header_count_are_bounded(self):
        member = tarfile.TarInfo('vm.vmdk')
        member.pax_headers = {'comment': 'small metadata'}
        with patch('exporter.MAX_TAR_METADATA_TOTAL', 1):
            with self.assertRaisesRegex(ValueError, 'metadata.*limit'):
                verify_ova(self.archive(member))
        with patch('exporter.MAX_TAR_HEADERS', 1):
            with self.assertRaisesRegex(ValueError, 'header count'):
                verify_ova(self.archive(tarfile.TarInfo('vm.vmdk')))

    def test_sparse_encodings_are_rejected_before_map_allocation(self):
        for headers in ({'GNU.sparse.size': '1000'}, {'GNU.sparse.map': '0,10'},
                        {'GNU.sparse.major': '1', 'GNU.sparse.minor': '0'}):
            member = tarfile.TarInfo('vm.vmdk')
            member.pax_headers = headers
            with self.subTest(headers=headers), self.assertRaisesRegex(ValueError, 'Sparse'):
                verify_ova(self.archive(member))
        member = tarfile.TarInfo('vm.vmdk')
        member.type = tarfile.GNUTYPE_SPARSE
        with self.assertRaisesRegex(ValueError, 'Sparse'):
            verify_ova(self.archive(member))

    def test_ordinary_pax_and_gnu_long_names_still_verify(self):
        import hashlib
        for format in (tarfile.PAX_FORMAT, tarfile.GNU_FORMAT):
            output = io.BytesIO()
            members = {'vm.ovf': b'<Envelope/>', 'folder/' + 'disk-' * 25 + '.vmdk': b'disk'}
            members['vm.mf'] = '\n'.join(f'SHA256({name})= {hashlib.sha256(data).hexdigest()}'
                                       for name, data in members.items()).encode()
            with tarfile.open(fileobj=output, mode='w', format=format) as archive:
                for name, data in members.items():
                    entry = tarfile.TarInfo(name)
                    entry.size = len(data)
                    archive.addfile(entry, io.BytesIO(data))
            output.seek(0)
            self.assertEqual(verify_ova(output), 2)

    def test_shell_metacharacters_remain_individual_process_arguments(self):
        ticket = 'synthetic-ticket;&$(never-run)'
        output = Path('fixture & never-run.ova')
        command = export_command('ovftool.exe', 'example.test', 'vm-1;never-run',
                                 ticket, 'AA:BB', output)
        self.assertEqual(len(command), 6)
        self.assertEqual(command[2], '--I:sourceSessionTicket=' + ticket)
        self.assertEqual(command[-1], str(output))

    def test_session_ticket_and_cookie_are_redacted_from_task_logs(self):
        client = Mock(authority='example.test', cookie='synthetic-cookie')
        manager = JobManager('fixture-not-executed.exe', Mock())
        job = manager.add(client, {'id': 'vm-fixture', 'name': 'fixture'}, Path('fixture.ova'))
        job.secret = 'synthetic-ticket'
        text = manager.record(job, 'synthetic-ticket synthetic-cookie vi://user:secret@example.test/vm')
        for secret in ('synthetic-ticket', 'synthetic-cookie', 'user:secret'):
            self.assertNotIn(secret, text)
        self.assertIsNone(manager.log_dir)

    def test_saved_settings_reject_credential_fields_before_encryption(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            store = ConnectionSettings(directory, FakeProtection())
            for extra in ('password', 'cookie', 'ticket', 'token'):
                with self.subTest(extra=extra), self.assertRaises(ValueError):
                    store.write(store.profiles_path, 'connections',
                                [dict(address='example.test', username='fixture', **{extra: 'synthetic'})])
            self.assertEqual(list(Path(directory).iterdir()), [])

