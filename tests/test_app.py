import hashlib
import io
import tarfile
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

from exporter import export_command, progress_value, verify_ova, ProgressParser, TransferTracker
from vsphere import VSphere, endpoint


def response(content):
    return ET.fromstring('<root xmlns="urn:vim25">' + content + '</root>')


def close_root(root):
    root.update_idletasks()
    for token in root.tk.call('after', 'info'):
        # Cancel scheduling without deleting a command registered by a child.
        # Each widget releases its own Tcl command registry during destroy().
        root.tk.call('after', 'cancel', token)
    root.destroy()


class Tests(unittest.TestCase):
    def test_endpoint_rejects_credentials_and_paths(self):
        self.assertEqual(endpoint('https://vsphere.example.test/ui/')[2], 'vsphere.example.test')
        self.assertEqual(endpoint('192.0.2.10:443')[1], 443)
        for bad in ('http://host', 'https://user:pass@host', 'host/vm/test', 'host?x=1'):
            with self.assertRaises(ValueError):
                endpoint(bad)

    def test_command_has_no_password_and_selects_unique_vm(self):
        command = export_command('tool.exe', 'host', 'vm-41', 'single-use', 'AB:CD', 'out.ova')
        self.assertIn('--I:sourceSessionTicket=single-use', command)
        self.assertIn('vi://host/?moref=vim.VirtualMachine:vm-41', command)
        self.assertFalse(any('noSSLVerify' in arg for arg in command))

    def test_progress(self):
        self.assertEqual(progress_value('PROGRESS 42'), 42)
        self.assertEqual(progress_value('Disk progress: 1%'), 1)
        self.assertIsNone(progress_value('Completed successfully'))

    def test_machine_progress_sections_from_real_export(self):
        parser = ProgressParser()
        lines = ['PROGRESS', '+ 1', '+ 42', '+ 100', 'TARGET_ID', '+ D:\\VMs\\export.ova',
                 'RESULT', '+ SUCCESS', 'ERROR', '+ 90']
        values = [parser.feed(line) for line in lines]
        self.assertEqual(values, [None, 1, 42, 100, None, None, None, None, None, None])

    def test_transfer_rate_includes_stalls_and_uses_elapsed_time(self):
        tracker = TransferTracker(0)
        self.assertEqual(tracker.sample(1, 10_000_000)['speed'], 10_000_000)
        self.assertEqual(tracker.sample(2, 20_000_000)['speed'], 10_000_000)
        self.assertEqual(tracker.sample(7, 20_000_000)['speed'], 0)
        sample = tracker.sample(8, 30_000_000)
        self.assertAlmostEqual(sample['speed'], 10_000_000 / 6)
        self.assertEqual(sample['elapsed'], 8)
        self.assertEqual(sample['bytes'], 30_000_000)

    def test_remaining_time(self):
        from transfer_ui import remaining_text
        self.assertEqual(remaining_text(60, 50, 1_000_000), 'About 1:00 remaining')
        self.assertEqual(remaining_text(60, 0, 1_000_000), 'Calculating time remaining…')
        self.assertEqual(remaining_text(60, 50, 0), 'Waiting for data…')
        self.assertEqual(remaining_text(60, 100, 1_000_000), 'Finishing transfer…')

    def make_ova(self, corrupt=False, missing_manifest=False):
        output = io.BytesIO()
        members = {'vm.ovf': b'<Envelope/>', 'vm.vmdk': b'disk bytes' * 1000}
        manifest = '\n'.join(f'SHA256({name})= {hashlib.sha256(data).hexdigest()}' for name, data in members.items())
        if corrupt:
            members['vm.vmdk'] += b'corruption'
        if not missing_manifest:
            members['vm.mf'] = manifest.encode()
        with tarfile.open(fileobj=output, mode='w', format=tarfile.USTAR_FORMAT) as archive:
            for name, data in members.items():
                member = tarfile.TarInfo(name)
                member.size = len(data)
                archive.addfile(member, io.BytesIO(data))
        output.seek(0)
        return output

    def test_checksum_validation_and_corruption(self):
        self.assertEqual(verify_ova(self.make_ova()), 2)
        with self.assertRaisesRegex(ValueError, 'Checksum mismatch'):
            verify_ova(self.make_ova(corrupt=True))
        with self.assertRaisesRegex(ValueError, 'manifest'):
            verify_ova(self.make_ova(missing_manifest=True))

    def test_truncated_disk_rejected(self):
        truncated = io.BytesIO(self.make_ova().getvalue()[:2000])
        with self.assertRaises((ValueError, tarfile.ReadError)):
            verify_ova(truncated)

    def archive_with_names(self, extra_names=(), duplicate_manifest=False):
        """Hash the final literal-name payload, reproducing duplicate overwrite ambiguity."""
        members = [('vm.ovf', b'<Envelope/>'), ('vm.vmdk', b'original disk')]
        members.extend((name, b'additional payload') for name in extra_names)
        manifest = '\n'.join(f'SHA256({name})= {hashlib.sha256(data).hexdigest()}'
                             for name, data in dict(members).items()).encode()
        members.append(('vm.mf', manifest))
        if duplicate_manifest:
            members.append(('vm.mf', manifest))
        output = io.BytesIO()
        with tarfile.open(fileobj=output, mode='w', format=tarfile.USTAR_FORMAT) as archive:
            for name, data in members:
                entry = tarfile.TarInfo(name)
                entry.size = len(data)
                archive.addfile(entry, io.BytesIO(data))
        output.seek(0)
        return output

    def test_ambiguous_archive_member_names_are_rejected(self):
        for name in ('vm.ovf', 'vm.vmdk', './vm.vmdk', 'VM.VMDK'):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'Duplicate|ambiguous'):
                verify_ova(self.archive_with_names([name]))

    def test_duplicate_manifest_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Duplicate|ambiguous'):
            verify_ova(self.archive_with_names(duplicate_manifest=True))

    def test_unsafe_archive_paths_are_rejected_even_with_valid_checksums(self):
        for name in ('../escape.vmdk', '/absolute.vmdk', 'C:/escape.vmdk',
                     'folder\\escape.vmdk', 'disk.vmdk ', 'disk.vmdk.'):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'Unsafe'):
                verify_ova(self.archive_with_names([name]))

    def test_windows_output_filename_rules(self):
        from output_paths import validate_output_name
        for name in ('CON.ova', 'nul.ova', 'COM1.backup.ova', 'LPT9.ova',
                     'COM¹.ova', 'NUL .ova', 'CONIN$.ova', '../vm.ova',
                     'bad:name.ova', 'vm.ova ', 'vm.ova.', 'plain.zip', ''):
            with self.subTest(name=name), self.assertRaises(ValueError):
                validate_output_name(name)
        for name in ('virtual-machine.ova', 'COM10.ova', 'my.vm.OVA', 'CONSOLE.ova'):
            with self.subTest(name=name):
                self.assertEqual(validate_output_name(name), name)

    def test_explicit_ovftool_override_never_falls_back_to_another_binary(self):
        from tool_paths import find_ovftool
        from pathlib import Path
        expected = Path('C:/missing-user-selection/ovftool.exe')
        with patch.dict('os.environ', {'OVFTOOL_PATH': '"'+str(expected)+'"'}), \
                patch('tool_paths.shutil.which') as search, \
                patch.object(Path,'is_file',side_effect=AssertionError('Unexpected fallback search')):
            self.assertEqual(find_ovftool(Path('other-installation')),expected)
            search.assert_not_called()

    def test_inventory_pagination_and_view_cleanup(self):
        api = VSphere('host', b'certificate')
        api.refs = {'rootFolder': ('Folder', 'root'), 'viewManager': ('ViewManager', 'views'),
                    'propertyCollector': ('PropertyCollector', 'props')}
        objects = '<objects><obj type="VirtualMachine">vm-41</obj><propSet><name>name</name><val>Test &amp; VM</val></propSet><propSet><name>runtime.powerState</name><val>poweredOff</val></propSet></objects>'
        with patch.object(api, 'call', side_effect=[response('<returnval>view-1</returnval>'),
              response('<returnval>' + objects + '<token>next</token></returnval>'),
              response('<returnval/>'), response('')]) as call:
            machines = api.inventory()
            self.assertEqual(machines[0]['name'], 'Test & VM')
            self.assertEqual(call.call_args_list[2].args[0], 'ContinueRetrievePropertiesEx')
            self.assertEqual(call.call_args_list[-1].args[0], 'DestroyView')

    def test_certificate_change_prevents_credentials_being_sent(self):
        api = VSphere('host', b'expected')
        with patch('vsphere.http.client.HTTPSConnection') as factory:
            connection = factory.return_value
            connection.sock.getpeercert.return_value = b'changed'
            with self.assertRaisesRegex(RuntimeError, 'certificate changed'):
                api.call('Login', '<password>secret</password>')
            connection.request.assert_not_called()



if __name__ == '__main__':
    unittest.main(verbosity=2)
