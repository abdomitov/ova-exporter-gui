"""Additional QA boundary cases; synthetic data, no VMware connection."""
import os
import hashlib
import io
from pathlib import Path
from types import SimpleNamespace
import tkinter as tk
import unittest
import tarfile
import tempfile
from unittest.mock import Mock, patch

from app import App
from jobs import JobManager
from output_paths import validate_output_name
from secure_storage import WindowsDataProtection
from test_app import close_root
from vsphere import VSphere, endpoint


class DestinationQATests(unittest.TestCase):
    def setUp(self):
        self.root=tk.Tk()
        self.root.withdraw()
        settings=Mock()
        settings.profiles.return_value=[]
        self.app=App(self.root,settings=settings,remember_theme=False,tool_store=False,
                     tool_locator=lambda *args:Path(__file__),update_checks=False)
        self.addCleanup(lambda:close_root(self.root))
        self.app.new_download()
        self.wizard=self.app.wizard
        self.addCleanup(self.wizard.destroy_wizard)
        self.wizard.client=SimpleNamespace(authority='192.0.2.99',logout=Mock())
        vm=dict(id='qa-vm',name='QA fixture',power='poweredOff',cpu='2',ram='2048',capacity=1024**3,path='')
        self.wizard.machines=[vm]
        self.wizard.show_vms()
        self.wizard.tree.selection_set(vm['id'])
        self.wizard.selection_changed()
        self.wizard.folder.set(str(Path(__file__).resolve().parent))
        self.wizard.filename.set('qa-fixture-never-written.ova')

    def test_blank_folder_is_not_silently_current_directory(self):
        self.wizard.folder.set('')
        with patch('wizard.threading.Thread') as worker,patch('wizard.messagebox.showerror') as error:
            self.wizard.export()
        worker.assert_not_called()
        error.assert_called_once()
        self.assertFalse(self.wizard.busy)

    def test_disconnected_destination_is_reported_without_starting_export(self):
        with patch('wizard.shutil.disk_usage',side_effect=OSError('QA drive unavailable')), \
                patch('wizard.threading.Thread') as worker,patch('wizard.messagebox.showerror') as error:
            self.wizard.export()
        worker.assert_not_called()
        error.assert_called_once()
        self.assertIn('QA drive unavailable',error.call_args.args[1])
        self.assertFalse(self.wizard.busy)

    def test_filename_reserves_room_for_incomplete_package_and_unicode(self):
        for name in ('x'*232+'.ova','\U0001f680'*116+'.ova'):
            with self.subTest(name_length=len(name)),self.assertRaises(ValueError):
                validate_output_name(name)
        self.assertEqual(validate_output_name('x'*227+'.ova'),'x'*227+'.ova')

    def test_sign_in_refresh_and_task_registration_with_synthetic_sessions(self):
        from vsphere import fingerprint
        certificate=b'qa-session-certificate'
        self.app.settings.trusted_pin.return_value=fingerprint(certificate)
        self.wizard.address.set('192.0.2.99')
        self.wizard.username.set('fixture-user')
        self.wizard.password.set('fixture-password-never-saved')
        vm=self.wizard.machines[0]
        client=Mock(authority='192.0.2.99',product='QA VMware')
        client.inventory.return_value=[vm]
        client.fork.return_value=Mock(authority='192.0.2.99')
        def inline(target,**kwargs):
            return SimpleNamespace(start=target)
        self.wizard.client=None
        with patch('wizard.VSphere',return_value=client),patch('wizard.threading.Thread',side_effect=inline):
            self.wizard.authenticate('192.0.2.99',certificate)
            self.wizard.poll()
            self.assertEqual(self.wizard.password.get(),'')
            self.assertEqual(self.wizard.step,2)
            client.login.assert_called_once_with('fixture-user','fixture-password-never-saved')
            client.inventory.return_value=[vm,dict(vm,id='qa-vm-2',name='Second fixture')]
            self.wizard.refresh()
            self.wizard.poll()
            self.assertEqual(len(self.wizard.tree.get_children()),2)
            self.wizard.tree.selection_set(vm['id'])
            self.wizard.selection_changed()
            with patch.object(self.app.manager,'start') as start:
                self.wizard.export()
                self.wizard.poll()
                start.assert_called_once()
        self.assertTrue(self.wizard.closed)
        self.assertIsNone(self.app.wizard)
        self.assertEqual(len(self.app.dashboard.cards),1)
        self.app.settings.remember_profile.assert_not_called()


class ExportPipelineQATests(unittest.TestCase):
    @staticmethod
    def package(corrupt=False):
        payloads={'fixture.ovf':b'<Envelope/>','fixture.vmdk':b'QA synthetic virtual disk'}
        manifest='\n'.join(f'SHA256({name})= {hashlib.sha256(data).hexdigest()}' for name,data in payloads.items())
        if corrupt:
            payloads['fixture.vmdk']+=b'corruption'
        payloads['fixture.mf']=manifest.encode()
        output=io.BytesIO()
        with tarfile.open(fileobj=output,mode='w') as archive:
            for name,data in payloads.items():
                entry=tarfile.TarInfo(name)
                entry.size=len(data)
                archive.addfile(entry,io.BytesIO(data))
        return output.getvalue()

    def run_pipeline(self,directory,*,corrupt=False,returncode=0,existing=False):
        directory=Path(directory)
        tool=directory/'qa-ovftool-fixture.exe'
        tool.write_bytes(b'Not executable; Popen is always mocked')
        target=directory/'fixture.ova'
        if existing:
            target.write_bytes(b'existing package must be preserved')
        vm=dict(id='qa-vm',name='QA fixture',power='poweredOff')
        client=Mock(authority='192.0.2.88',certificate=b'qa-certificate',cookie='qa-cookie')
        client.inventory.return_value=[vm]
        client.export_readiness.return_value=(True,'QA fixture ready')
        client.clone_ticket.return_value='qa-session-ticket'
        events=[]
        manager=JobManager(tool,lambda kind,payload:events.append((kind,payload)))
        job=manager.add(client,vm,target)
        process=Mock(pid=123456)
        process.poll.return_value=returncode
        process.wait.return_value=returncode
        process.stdout=io.StringIO('PROGRESS\n+ 20\n+ 100\nRESULT\n+ SUCCESS\n' if not returncode else
                                 'ERROR\n+ <Errors><Error><LocalizedMsg>QA tool failure</LocalizedMsg></Error></Errors>\n')
        process.stdin=io.StringIO()
        def export_fixture(command,**kwargs):
            Path(command[-1]).write_bytes(self.package(corrupt))
            return process
        with patch('jobs.subprocess.Popen',side_effect=export_fixture) as spawn, \
                patch('jobs.shutil.disk_usage',return_value=SimpleNamespace(free=1024**3)):
            manager.run(job)
        self.assertFalse(manager.active)
        self.assertFalse(manager.waiting)
        self.assertEqual(job.secret,'')
        client.logout.assert_called_once()
        process.terminate.assert_not_called()
        return job,events,spawn

    def test_successful_worker_writes_verifies_and_finalizes_only_valid_package(self):
        with tempfile.TemporaryDirectory() as directory:
            job,events,spawn=self.run_pipeline(directory)
            self.assertEqual(job.state,'done')
            self.assertTrue(job.target.is_file())
            self.assertFalse(list(Path(directory).glob('*.incomplete-*.ova')))
            self.assertIn('verifying',[payload[1] for kind,payload in events])
            self.assertEqual(events[-1][1][1],'done')
            spawn.assert_called_once()
            self.assertNotIn('qa-session-ticket','\n'.join(job.log_lines))

    def test_checksum_failure_preserves_incomplete_file_without_finalizing(self):
        with tempfile.TemporaryDirectory() as directory:
            job,events,spawn=self.run_pipeline(directory,corrupt=True)
            self.assertEqual(job.state,'failed')
            self.assertFalse(job.target.exists())
            self.assertEqual(len(list(Path(directory).glob('*.incomplete-*.ova'))),1)
            self.assertIn('Checksum mismatch','\n'.join(job.log_lines))

    def test_tool_failure_is_reported_and_existing_outputs_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            job,events,spawn=self.run_pipeline(directory,returncode=1)
            self.assertEqual(job.state,'failed')
            self.assertIn('QA tool failure','\n'.join(job.log_lines))
            self.assertFalse(job.target.exists())
        with tempfile.TemporaryDirectory() as directory:
            job,events,spawn=self.run_pipeline(directory,existing=True)
            self.assertEqual(job.state,'failed')
            spawn.assert_not_called()
            self.assertEqual(job.target.read_bytes(),b'existing package must be preserved')


class ProtocolQATests(unittest.TestCase):
    def response(self,body):
        response=Mock(status=200)
        response.read.return_value=body
        response.getheader.return_value=None
        connection=Mock()
        connection.sock.getpeercert.return_value=b'qa-certificate'
        connection.getresponse.return_value=response
        return connection,response

    def test_port_zero_is_rejected_instead_of_connecting_to_443(self):
        with self.assertRaises(ValueError):
            endpoint('192.0.2.10:0')

    def test_soap_rejects_dtd_entities_even_with_a_matching_certificate(self):
        text=('<!DOCTYPE root [<!ENTITY fixture "QA entity">]>'
              '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">'
              '<s:Body>&fixture;</s:Body></s:Envelope>')
        for body in (text.encode(),('<?xml version="1.0" encoding="utf-16"?>'+text).encode('utf-16')):
            with self.subTest(encoding=body[:4]):
                connection,response=self.response(body)
                with patch('vsphere.http.client.HTTPSConnection',return_value=connection), \
                        self.assertRaisesRegex(RuntimeError,'DTD|unsafe XML'):
                    VSphere('192.0.2.10',b'qa-certificate').call('QAReadOnly','')
                connection.close.assert_called_once()

    def test_soap_rejects_oversized_replies_before_xml_parsing(self):
        connection,response=self.response(b'x'*33_554_433)
        with patch('vsphere.http.client.HTTPSConnection',return_value=connection), \
                self.assertRaisesRegex(RuntimeError,'size limit|too large'):
            VSphere('192.0.2.10',b'qa-certificate').call('QAReadOnly','')
        response.read.assert_called_once_with(33_554_433)
        connection.close.assert_called_once()

    def test_matching_certificate_normal_soap_and_malformed_reply(self):
        body=(b'<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">'
              b'<s:Body><response xmlns="urn:vim25"/></s:Body></s:Envelope>')
        connection,response=self.response(body)
        with patch('vsphere.http.client.HTTPSConnection',return_value=connection):
            result=VSphere('192.0.2.10',b'qa-certificate').call('QAReadOnly','')
        self.assertTrue(result.tag.endswith('Envelope'))
        connection.request.assert_called_once()
        connection,response=self.response(b'not XML')
        with patch('vsphere.http.client.HTTPSConnection',return_value=connection),self.assertRaises(RuntimeError):
            VSphere('192.0.2.10',b'qa-certificate').call('QAReadOnly','')


@unittest.skipUnless(os.name=='nt','Windows DPAPI boundary')
class NativeProtectionQATests(unittest.TestCase):
    def test_native_dpapi_roundtrip_tamper_and_purpose_binding_in_memory(self):
        # No settings files or actual account data are read or written.
        protection=WindowsDataProtection()
        original=b'QA synthetic address 192.0.2.10 and user fixture-only'
        encrypted=protection.protect(original,'qa-fixture')
        self.assertNotIn(original,encrypted)
        self.assertEqual(protection.unprotect(encrypted,'qa-fixture'),original)
        with self.assertRaises(OSError):
            protection.unprotect(encrypted,'other-fixture')
        changed=encrypted[:-1]+bytes([encrypted[-1]^1])
        with self.assertRaises(OSError):
            protection.unprotect(changed,'qa-fixture')
