"""Regression checks for responsive, bounded presentation work (fake data only)."""
from pathlib import Path
from types import SimpleNamespace
import tkinter as tk
import unittest
from unittest.mock import Mock, patch

from app import App
from task_view import TaskView
from test_app import close_root


class ResponsiveUITests(unittest.TestCase):
    def setUp(self):
        self.root=tk.Tk()
        self.root.withdraw()
        self.callback_errors=[]
        self.root.report_callback_exception=lambda kind,value,trace:self.callback_errors.append(value)
        def cleanup():
            close_root(self.root)
            self.assertEqual(self.callback_errors,[])
        self.addCleanup(cleanup)
        settings=Mock()
        settings.profiles.return_value=[]
        self.app=App(self.root,settings=settings,remember_theme=False,tool_store=False,
                     tool_locator=lambda *args:Path(__file__),update_checks=False)
        self.vm={'id':'fake-1','name':'Example VM','power':'poweredOff','cpu':'4',
                 'ram':'8192','capacity':1024**3,'path':'[Demo] example.vmx'}
        client=SimpleNamespace(authority='192.0.2.10',logout=Mock())
        self.job=self.app.manager.add(client,self.vm,Path('fake-never-written.ova'))
        self.app.dashboard.add(self.job)
        self.app.dashboard.tree.selection_set(self.job.id)
        self.app.dashboard.selection_changed()
        self.job.state='running'
        self.app.dashboard.handle(self.job.id,'running',None)
        self.root.update_idletasks()

    def test_event_burst_yields_to_input_and_does_not_repeat_tool_checks(self):
        for number in range(500):
            self.app.emit('job',(self.job.id,'progress',number/10))
        with patch.object(self.app,'refresh_tool') as locate, \
                patch.object(self.app.dashboard.panel,'draw') as draw:
            self.app.poll()
            self.assertGreater(self.app.events.qsize(),0)
            self.assertGreaterEqual(self.app.events.qsize(),500-128)
            locate.assert_not_called()
            draw.assert_called_once()
        heartbeat=[]
        self.root.after(0,lambda:heartbeat.append(True))
        self.root.update()
        self.assertEqual(heartbeat,[True])

    def test_ready_tool_settings_menu_keeps_location_actions_available(self):
        self.job.state='done'
        self.app.refresh_tool()
        choose=Mock()
        detect=Mock()
        self.app.tool_browse.configure(command=choose)
        self.app.tool_auto.configure(command=detect)
        self.app.tool_menu.invoke(0)
        self.app.tool_menu.invoke(1)
        choose.assert_called_once()
        detect.assert_called_once()
        self.job.state='running'
        self.app.refresh_tool()
        self.assertEqual(str(self.app.tool_manage['state']),'disabled')

    def test_header_update_menu_still_runs_manual_check(self):
        updater=self.app.updater
        updater.enabled=True
        updater.menu.entryconfigure(0,state='normal')
        with patch.object(updater,'check') as check:
            updater.menu.invoke(0)
            check.assert_called_once_with(manual=True)

    def test_empty_inventory_and_no_search_match_explain_disabled_export(self):
        self.app.new_download()
        wizard=self.app.wizard
        self.addCleanup(wizard.destroy_wizard)
        wizard.client=SimpleNamespace(authority='192.0.2.20',logout=Mock())
        wizard.machines=[self.vm]
        wizard.search.set('No such machine')
        wizard.show_vms()
        self.assertIn('No matching VMs',wizard.inventory_empty['text'])
        self.assertTrue(wizard.inventory_empty.winfo_manager())
        self.assertEqual(str(wizard.export_btn['state']),'disabled')
        wizard.search.set('')
        wizard.show_vms()
        self.assertFalse(wizard.inventory_empty.winfo_manager())
        wizard.machines=[]
        wizard.show_vms()
        self.assertIn('No virtual machines',wizard.inventory_empty['text'])
        self.assertEqual(str(wizard.export_btn['state']),'disabled')

    def test_search_shortcut_opens_chooser_and_focuses_search(self):
        self.root.deiconify()
        self.app.new_download()
        wizard=self.app.wizard
        self.addCleanup(wizard.destroy_wizard)
        wizard.client=SimpleNamespace(authority='192.0.2.20',logout=Mock())
        wizard.search.set('Example')
        wizard.root.focus_force()
        self.root.update()
        wizard.root.event_generate('<Control-f>')
        self.root.update()
        self.assertEqual(wizard.step,2)
        self.assertEqual(wizard.root.focus_get(),wizard.search_entry)
        self.assertTrue(wizard.search_entry.selection_present())

    def test_chooser_status_keeps_errors_visible_and_removes_routine_repetition(self):
        self.app.new_download()
        wizard=self.app.wizard
        self.addCleanup(wizard.destroy_wizard)
        wizard.status.set('Operation failed: illustrative server error')
        self.assertTrue(wizard.status_label.winfo_manager())
        self.assertEqual(wizard.status_label['style'],'Error.TLabel')
        self.assertEqual(wizard.login_connection_label['style'],'Error.TLabel')
        wizard.status.set('Connected. Select a powered-off VM.')
        self.assertFalse(wizard.status_label.winfo_manager())
        wizard.status.set('Refreshing virtual machines…')
        self.assertTrue(wizard.status_label.winfo_manager())

    def test_save_folder_dialog_belongs_to_setup_window(self):
        self.app.new_download()
        wizard=self.app.wizard
        self.addCleanup(wizard.destroy_wizard)
        with patch('wizard.filedialog.askdirectory',return_value='C:/Fake-Exports') as choose:
            wizard.browse()
        self.assertIs(choose.call_args.kwargs['parent'],wizard.root)
        self.assertEqual(wizard.folder.get(),'C:/Fake-Exports')

    def test_empty_dashboard_action_and_first_task_transition(self):
        from dashboard import Dashboard
        start=Mock()
        dashboard=Dashboard(self.root,start,lambda job_id:None)
        dashboard.set_tool_ready(False)
        dashboard.empty_action.invoke()
        start.assert_not_called()
        dashboard.set_tool_ready(True)
        dashboard.empty_action.invoke()
        start.assert_called_once()
        dashboard.add(self.job)
        self.assertFalse(dashboard.empty.winfo_manager())
        self.assertEqual(tuple(map(str,dashboard.tree['show'])),('headings',))

    def test_compact_connection_keeps_all_credentials_visible_and_reflows_back(self):
        self.root.deiconify()
        self.app.new_download()
        wizard=self.app.wizard
        self.addCleanup(wizard.destroy_wizard)
        wizard.root.geometry('600x420')
        self.root.update()
        body=wizard.accordion.bodies[1]
        self.assertTrue(wizard.form_compact)
        field=wizard.login_entries[2]
        self.assertLessEqual(field.winfo_rooty()+field.winfo_height(),
                             body.canvas.winfo_rooty()+body.canvas.winfo_height())
        wizard.root.geometry('740x700')
        self.root.update()
        self.assertFalse(wizard.form_compact)
        self.assertTrue(wizard.login_intro_frame.winfo_ismapped())
        self.assertEqual(wizard.login_entries[2]['show'],'\u2022')

    def test_batched_transitions_keep_final_state_and_refresh_tool_once(self):
        for kind,value in [('progress',42),('verifying',None),('done','Checksums verified'),('progress',12)]:
            self.app.emit('job',(self.job.id,kind,value))
        self.job.state='done'
        with patch.object(self.app,'refresh_tool') as locate, \
                patch.object(self.app.dashboard.panel,'draw') as draw:
            self.app.poll()
            locate.assert_called_once()
            draw.assert_called_once()
        self.assertEqual(self.app.dashboard.cards[self.job.id].state,'done')
        self.assertEqual(self.app.dashboard.panel.value,100)
        self.assertEqual(self.app.dashboard.metrics[1].get(),'1')

    def test_hidden_chart_does_no_drawing_and_can_reopen_same_task(self):
        dashboard=self.app.dashboard
        dashboard.hide_details()
        with patch.object(dashboard.panel,'draw',wraps=dashboard.panel.draw) as draw:
            dashboard.handle(self.job.id,'progress',73)
            draw.assert_not_called()
            dashboard.details_button.invoke()
            draw.assert_called_once()
        self.assertEqual(dashboard.panel.value,73)
        self.assertEqual(len(dashboard.panes.panes()),2)
        self.assertEqual(dashboard.tree.selection(),(self.job.id,))

    def test_user_divider_position_survives_layout_changes(self):
        self.root.deiconify()
        self.root.update()
        dashboard=self.app.dashboard
        dashboard.panes.sashpos(0,190)
        with patch.object(dashboard.panes,'identify',return_value=0):
            event=SimpleNamespace(x=10,y=190)
            dashboard.start_split_drag(event)
            dashboard.finish_split_drag(event)
        ratio=dashboard.split_ratio
        self.assertGreater(ratio,0)
        self.root.geometry('1000x720')
        self.root.update()
        dashboard.fit_detail()
        self.assertAlmostEqual(dashboard.panes.sashpos(0)/dashboard.panes.winfo_height(),ratio,delta=0.015)

    def test_filter_coalesces_typing_and_blocks_stale_export_selection(self):
        self.app.new_download()
        wizard=self.app.wizard
        self.addCleanup(wizard.destroy_wizard)
        wizard.client=SimpleNamespace(authority='192.0.2.20',logout=Mock())
        wizard.machines=[self.vm,dict(self.vm,id='fake-2',name='Another VM')]
        wizard.show_vms()
        wizard.tree.selection_set('fake-1')
        wizard.selection_changed()
        self.assertEqual(str(wizard.export_btn['state']),'normal')
        with patch.object(wizard,'show_vms',wraps=wizard.show_vms) as show:
            for text in ('A','An','Another'):
                wizard.search.set(text)
            self.assertEqual(str(wizard.export_btn['state']),'disabled')
            wizard.selection_changed()
            self.assertEqual(str(wizard.export_btn['state']),'disabled')
            with patch('wizard.threading.Thread') as worker:
                wizard.export_enter()
                worker.assert_not_called()
                self.assertFalse(wizard.busy)
            show.assert_not_called()
            finished=tk.BooleanVar(self.root,False)
            self.root.after(170,lambda:finished.set(True))
            self.root.wait_variable(finished)
            show.assert_called_once()
        self.assertEqual(wizard.tree.get_children(),('fake-2',))
        self.assertFalse(wizard.tree.selection())
        self.assertEqual(str(wizard.export_btn['state']),'disabled')

    def test_fractional_progress_history_stays_bounded(self):
        view=TaskView(self.job)
        view.update('running',None)
        for index in range(10001):
            view.update('progress',index/100)
            view.update('sample',dict(speed=index,bytes=index,elapsed=index))
        self.assertLessEqual(len(view.history),101)
        self.assertEqual(view.history[-1],(100,10000))
        self.assertEqual(view.peak,10000)
        view.update('progress',105)
        self.assertEqual(view.percent,100)

    def test_full_error_is_readable_below_chart_without_covering_graph(self):
        self.root.deiconify()
        self.root.update()
        settled=tk.BooleanVar(self.root,False)
        self.root.after(140,lambda:settled.set(True))
        self.root.wait_variable(settled)
        detail='Illustrative server error. '*80
        self.job.state='failed'
        self.app.dashboard.handle(self.job.id,'failed',detail)
        self.assertEqual(self.app.dashboard.message['text'],detail)
        canvas=self.app.dashboard.panel.canvas
        summary=canvas.itemcget(canvas.find_withtag('transfer_detail')[0],'text')
        self.assertLess(len(summary),100)
        self.assertNotIn(detail,summary)
        self.root.update_idletasks()
        body=self.app.dashboard.detail_scroll
        self.assertLess(body.canvas.yview()[1],1)
        self.assertGreaterEqual(body.inner.winfo_height(),body.inner.winfo_reqheight())
        canvas=body.canvas
        with patch.object(self.root,'winfo_containing',return_value=canvas):
            canvas.event_generate('<MouseWheel>',delta=-120,x=10,y=10)
            self.root.update()
        self.assertGreater(body.canvas.yview()[0],0)

    def test_short_window_switches_between_list_and_details_without_tiny_panes(self):
        def resize(width, height):
            self.root.geometry(f'{width}x{height}')
            settled=tk.BooleanVar(self.root,False)
            attempts=0
            def check():
                nonlocal attempts
                attempts+=1
                if ((self.root.winfo_width(),self.root.winfo_height())==(width,height)
                        or attempts>=100):
                    settled.set(True)
                else:
                    self.root.after(20,check)
            self.root.after(20,check)
            self.root.wait_variable(settled)
            self.assertEqual((self.root.winfo_width(),self.root.winfo_height()),(width,height))
            self.root.update()
        self.root.deiconify()
        resize(640,420)
        self.app.resize_layout()
        self.root.update_idletasks()
        dashboard=self.app.dashboard
        self.assertFalse(dashboard.tree.winfo_ismapped())
        self.assertTrue(dashboard.detail_scroll.winfo_ismapped())
        dashboard.details_button.invoke()
        self.root.update_idletasks()
        self.assertTrue(dashboard.tree.winfo_ismapped())
        self.assertFalse(dashboard.detail_scroll.winfo_ismapped())
        dashboard.details_button.invoke()
        # The hosted desktop can clamp a 760px client area to 749px.
        # 700px still exercises the >=600px split layout within its work area.
        resize(1000,700)
        self.app.resize_layout()
        self.root.update_idletasks()
        self.assertEqual(len(dashboard.panes.panes()),2)
        self.assertTrue(dashboard.tree.winfo_ismapped())
