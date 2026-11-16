"""Regression checks for responsive, bounded presentation work (fake data only)."""
from pathlib import Path
from types import SimpleNamespace
import tkinter as tk
import unittest
from unittest.mock import Mock, patch

from app import App
from task_view import TaskView
from test_app import close_root
from transfer_panel import stage_states


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
        self.app.queue.add(self.job)
        self.job.state='running'
        self.app.queue.handle(self.job.id,'running',None)
        self.root.update_idletasks()

    def connect(self,machines=None):
        flow=self.app.flow
        flow.emit('connected',(SimpleNamespace(authority='192.0.2.20',product='Fixture',logout=Mock()),
                               machines if machines is not None else [self.vm]))
        flow.poll()
        return flow

    def settle(self,milliseconds):
        finished=tk.BooleanVar(self.root,False)
        self.root.after(milliseconds,lambda:finished.set(True))
        self.root.wait_variable(finished)

    def test_event_burst_yields_to_input_and_does_not_repeat_tool_checks(self):
        for number in range(500):
            self.app.emit('job',(self.job.id,'progress',number/10))
        with patch.object(self.app,'refresh_tool') as locate, \
                patch.object(self.app.queue.panel,'draw') as draw, \
                patch.object(self.app.queue.list,'redraw_row') as row:
            self.app.poll()
            self.assertGreater(self.app.events.qsize(),0)
            self.assertGreaterEqual(self.app.events.qsize(),500-128)
            locate.assert_not_called()
            draw.assert_called_once()
            row.assert_called_once_with(self.job.id)
        heartbeat=[]
        self.root.after(0,lambda:heartbeat.append(True))
        self.root.update()
        self.assertEqual(heartbeat,[True])

    def test_tool_location_is_locked_while_tasks_are_unfinished(self):
        view=self.app.settings_view
        self.app.show('settings')
        self.assertEqual(str(view.tool_browse['state']),'disabled')
        self.assertEqual(str(view.tool_auto['state']),'disabled')
        self.assertIn('locked',view.tool_busy['text'])
        self.job.state='done'
        self.app.refresh_tool()
        self.assertEqual(str(view.tool_browse['state']),'normal')
        with patch.object(self.app,'save_tool_location') as save:
            view.tool_auto.invoke()
            save.assert_called_once_with(None)

    def test_navigation_switches_one_view_and_marks_it_in_the_rail(self):
        app=self.app
        self.assertEqual(app.current,'queue')
        self.assertEqual(app.nav['queue']['style'],'NavActive.TButton')
        app.nav['settings'].invoke()
        self.assertEqual(app.current,'settings')
        self.assertTrue(app.settings_view.winfo_manager())
        self.assertFalse(app.queue.winfo_manager())
        self.assertEqual(app.nav['queue']['style'],'Nav.TButton')
        app.nav['new'].invoke()
        self.assertEqual(app.current,'new')
        self.assertFalse(app.settings_view.winfo_manager())
        self.root.event_generate('<Control-Key-1>')
        app.navigate('queue')
        self.assertEqual(app.current,'queue')

    def test_theme_choice_updates_every_canvas_and_is_not_saved_when_disabled(self):
        app=self.app
        original=app.theme.mode
        other='dark' if original=='light' else 'light'
        with patch('pathlib.Path.write_text') as write:
            app.settings_view.mode_buttons[other].invoke()
            write.assert_not_called()
        self.assertEqual(app.theme.mode,other)
        self.assertEqual(app.queue.panel.colors,app.theme.colors)
        self.assertEqual(app.queue.list.colors,app.theme.colors)
        self.assertEqual(app.queue.list.canvas['background'],app.theme.colors['surface'])
        self.assertEqual(app.settings_view.mode_buttons[other]['style'],'TabActive.TButton')
        self.assertIn(original.capitalize(),app.theme_button['text'])
        app.theme_button.invoke()
        self.assertEqual(app.theme.mode,original)

    def test_empty_inventory_and_no_search_match_explain_disabled_export(self):
        self.app.new_download()
        wizard=self.connect()
        wizard.search.set('No such machine')
        wizard.show_vms()
        self.assertIn('No matching VMs',wizard.inventory_empty['text'])
        self.assertTrue(wizard.inventory_empty.winfo_manager())
        self.assertEqual(str(wizard.continue_btn['state']),'disabled')
        wizard.search.set('')
        wizard.show_vms()
        self.assertFalse(wizard.inventory_empty.winfo_manager())
        wizard.machines=[]
        wizard.show_vms()
        self.assertIn('No virtual machines',wizard.inventory_empty['text'])
        self.assertEqual(str(wizard.continue_btn['state']),'disabled')

    def test_running_vm_is_listed_on_request_but_cannot_continue(self):
        self.app.new_download()
        running=dict(self.vm,id='fake-on',name='Running VM',power='poweredOn')
        wizard=self.connect([self.vm,running])
        self.assertEqual(wizard.tree.get_children(),('fake-1',))
        wizard.power_off_only.set(False)
        wizard.show_vms()
        self.assertEqual(set(wizard.tree.get_children()),{'fake-1','fake-on'})
        wizard.tree.selection_set('fake-on')
        wizard.selection_changed()
        self.assertEqual(str(wizard.continue_btn['state']),'disabled')
        self.assertIn('never powers a VM off',wizard.detail.get())
        wizard.show_step(3)
        self.assertEqual(wizard.step,2)

    def test_inventory_sorts_by_clicked_column_and_keeps_selection(self):
        self.app.new_download()
        machines=[dict(self.vm,id='a',name='beta',capacity=3*1024**3),
                  dict(self.vm,id='b',name='Alpha',capacity=9*1024**3),
                  dict(self.vm,id='c',name='gamma',capacity=1*1024**3)]
        wizard=self.connect(machines)
        self.assertEqual(wizard.tree.get_children(),('b','a','c'))
        wizard.tree.selection_set('a')
        wizard.selection_changed()
        wizard.sort_by('disk')
        self.assertEqual(wizard.tree.get_children(),('c','a','b'))
        wizard.sort_by('disk')
        self.assertEqual(wizard.tree.get_children(),('b','a','c'))
        self.assertEqual(wizard.tree.selection(),('a',))
        self.assertIn('▾',wizard.tree.heading('disk','text'))

    def test_search_shortcut_opens_vm_list_and_focuses_search(self):
        self.root.deiconify()
        wizard=self.connect()
        wizard.search.set('Example')
        self.app.show('queue')
        self.root.focus_force()
        self.root.update()
        self.root.event_generate('<Control-f>')
        self.root.update()
        self.assertEqual(self.app.current,'new')
        self.assertEqual(wizard.step,2)
        self.assertEqual(self.root.focus_get(),wizard.search_entry)
        self.assertTrue(wizard.search_entry.selection_present())

    def test_status_keeps_errors_visible_and_removes_routine_repetition(self):
        wizard=self.app.flow
        wizard.status.set('Operation failed: illustrative server error')
        self.assertEqual(wizard.status_display.get(),'Operation failed: illustrative server error')
        self.assertEqual(wizard.status_label['style'],'Error.TLabel')
        wizard.status.set('Connected. Select a powered-off VM.')
        self.assertEqual(wizard.status_display.get(),'')
        wizard.status.set('Refreshing virtual machines…')
        self.assertEqual(wizard.status_display.get(),'Refreshing virtual machines…')
        self.assertEqual(wizard.status_label['style'],'Muted.TLabel')

    def test_save_folder_dialog_updates_folder_and_free_space(self):
        wizard=self.connect()
        wizard.tree.selection_set('fake-1')
        wizard.selection_changed()
        wizard.show_step(3)
        folder=str(Path(__file__).resolve().parent)
        with patch('export_flow.filedialog.askdirectory',return_value=folder) as choose, \
                patch('export_flow.shutil.disk_usage',return_value=SimpleNamespace(free=500*1024**3)):
            wizard.browse()
        self.assertIs(choose.call_args.kwargs['parent'],self.root)
        self.assertEqual(wizard.folder.get(),folder)
        self.assertIn('500.0 GB free',wizard.space.get())
        with patch('export_flow.shutil.disk_usage',return_value=SimpleNamespace(free=1024**2)):
            wizard.update_space()
        self.assertIn('less than',wizard.space.get())
        self.assertEqual(wizard.space_label['style'],'Warning.Surface.TLabel')
        wizard.folder.set('Z:/fixture-folder-that-does-not-exist')
        wizard.update_space()
        self.assertIn('does not exist',wizard.space.get())

    def test_empty_queue_action_and_first_task_transition(self):
        from queue_view import QueueView
        start=Mock()
        settings=Mock()
        queue=QueueView(self.root,start,lambda job_id:None,open_settings=settings,theme=self.app.theme)
        queue.set_tool_ready(False)
        queue.empty_action.invoke()
        start.assert_not_called()
        settings.assert_called_once()
        queue.set_tool_ready(True)
        queue.empty_action.invoke()
        start.assert_called_once()
        queue.add(self.job)
        self.assertFalse(queue.empty.winfo_manager())
        self.assertEqual(queue.selected,self.job.id)

    def test_minimum_window_keeps_connect_button_and_transfer_track_visible(self):
        self.root.deiconify()
        self.root.geometry('960x600')
        self.root.update()
        self.settle(120)
        panel=self.app.queue.panel
        self.assertGreater(panel.canvas.winfo_width(),300)
        self.assertTrue(panel.canvas.find_withtag('stage_track'))
        self.app.new_download()
        self.root.update()
        wizard=self.app.flow
        button=wizard.connect_btn
        self.assertTrue(button.winfo_ismapped())
        self.assertLessEqual(button.winfo_rooty()+button.winfo_height(),
                             wizard.winfo_rooty()+wizard.winfo_height())
        self.assertEqual(wizard.password_entry['show'],'\u2022')

    def test_batched_transitions_keep_final_state_and_refresh_tool_once(self):
        for kind,value in [('progress',42),('verifying',None),('done','Checksums verified'),('progress',12)]:
            self.app.emit('job',(self.job.id,kind,value))
        self.job.state='done'
        with patch.object(self.app,'refresh_tool') as locate, \
                patch.object(self.app.queue.panel,'draw') as draw:
            self.app.poll()
            locate.assert_called_once()
            draw.assert_called_once()
        self.assertEqual(self.app.queue.cards[self.job.id].state,'done')
        self.assertEqual(self.app.queue.panel.value,100)
        self.assertEqual(self.app.queue.counts()['done'],1)
        self.assertEqual(self.app.nav['queue']['text'],'Exports')

    def test_hidden_transfer_panel_does_no_drawing_and_catches_up_when_shown(self):
        queue=self.app.queue
        panel=queue.panel
        with patch.object(panel,'draw',wraps=panel.draw) as draw:
            self.app.show('settings')
            queue.handle(self.job.id,'progress',73)
            draw.assert_not_called()
            self.app.show('queue')
            draw.assert_called_once()
            self.assertEqual(panel.value,73)
            queue.show_tab('log')
            draw.reset_mock()
            queue.handle(self.job.id,'progress',80)
            draw.assert_not_called()
            queue.show_tab('transfer')
            draw.assert_called_once()
        self.assertEqual(panel.value,80)
        self.assertEqual(queue.selected,self.job.id)

    def test_filter_coalesces_typing_and_blocks_stale_export_selection(self):
        self.app.new_download()
        wizard=self.connect([self.vm,dict(self.vm,id='fake-2',name='Another VM')])
        wizard.tree.selection_set('fake-1')
        wizard.selection_changed()
        wizard.show_step(3)
        self.assertEqual(str(wizard.export_btn['state']),'normal')
        with patch.object(wizard,'show_vms',wraps=wizard.show_vms) as show:
            for text in ('A','An','Another'):
                wizard.search.set(text)
            self.assertEqual(str(wizard.export_btn['state']),'disabled')
            wizard.selection_changed()
            self.assertEqual(str(wizard.export_btn['state']),'disabled')
            with patch('export_flow.threading.Thread') as worker:
                wizard.export_enter()
                wizard.export()
                worker.assert_not_called()
                self.assertFalse(wizard.busy)
            show.assert_not_called()
            self.settle(170)
            show.assert_called_once()
        self.assertEqual(wizard.tree.get_children(),('fake-2',))
        self.assertFalse(wizard.tree.selection())
        self.assertEqual(str(wizard.export_btn['state']),'disabled')
        self.assertEqual(wizard.step,2)  # The destination step closes with its VM.

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

    def test_stage_track_follows_the_export_sequence(self):
        self.assertEqual(stage_states('queued',0),['todo']*4)
        self.assertEqual(stage_states('preparing',0),['active','todo','todo','todo'])
        self.assertEqual(stage_states('exporting',40),['done','active','todo','todo'])
        self.assertEqual(stage_states('verifying',100),['done','done','active','todo'])
        self.assertEqual(stage_states('cleaning',100),['done','done','done','active'])
        self.assertEqual(stage_states('cleaning',40),['done','warning','todo','active'])
        self.assertEqual(stage_states('done',100),['done']*4)
        self.assertEqual(stage_states('done_warning',100),['done','done','done','warning'])
        self.assertEqual(stage_states('error',40),['done','problem','todo','todo'])
        self.assertEqual(stage_states('error',0),['problem','todo','todo','todo'])
        self.assertEqual(stage_states('cancelling',40),['done','warning','todo','todo'])
        self.assertEqual(stage_states('stalled',100),['done','done','problem','todo'])
        self.assertEqual(stage_states('cleanup_required',40),['done','warning','todo','problem'])
        queue=self.app.queue
        queue.handle(self.job.id,'progress',40)
        canvas=queue.panel.canvas
        fill=canvas.coords(canvas.find_withtag('progress_fill')[0])
        track=canvas.coords(canvas.find_withtag('stage_track')[1])
        self.assertAlmostEqual((fill[2]-fill[0])/(track[2]-track[0]),0.4,delta=0.01)

    def test_full_error_is_readable_below_panel_without_covering_it(self):
        self.root.deiconify()
        self.root.update()
        self.settle(140)
        detail='Illustrative server error. '*80
        self.job.state='failed'
        self.app.queue.handle(self.job.id,'failed',detail)
        self.assertEqual(self.app.queue.message['text'],detail)
        canvas=self.app.queue.panel.canvas
        summary=canvas.itemcget(canvas.find_withtag('transfer_detail')[0],'text')
        self.assertLess(len(summary),100)
        self.assertNotIn(detail,summary)
        self.root.update_idletasks()
        self.settle(60)
        body=self.app.queue.detail_scroll
        self.assertLess(body.canvas.yview()[1],1)
        self.assertGreaterEqual(body.inner.winfo_height(),body.inner.winfo_reqheight())
        canvas=body.canvas
        with patch.object(self.root,'winfo_containing',return_value=canvas):
            canvas.event_generate('<MouseWheel>',delta=-120,x=10,y=10)
            self.root.update()
        self.assertGreater(body.canvas.yview()[0],0)

    def test_copy_path_and_open_folder_use_the_selected_task(self):
        queue=self.app.queue
        queue.copy_button.invoke()
        self.assertEqual(self.root.clipboard_get(),str(self.job.target))
        self.assertIn('copied',self.app.caption.get())
        with patch('queue_view.os.startfile',create=True) as launch:
            queue.folder_button.invoke()
            launch.assert_called_once_with(str(self.job.target.parent))
        with patch('queue_view.os.startfile',create=True,side_effect=OSError('fixture')):
            queue.folder_button.invoke()
        self.assertIn('could not be opened',self.app.caption.get())
