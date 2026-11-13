"""Focus display handoff with the real live/core code and a controlled queue.

The queue deliberately completes before its dirty copy. These are contract
tests for the focus-owned adapter, not tests of the global compositor or proof
of physical display scheduling. No shared UI source or hardware is touched.
"""
import ctypes as C
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from tests.test_focus_live import FAKES, Match, Policy

ROOT = Path(__file__).resolve().parents[1]
IDLE, UPDATED, RETRY, LOST, STOPPED = range(5)
FULL, BARRIER = 0, 1

QUEUE = r'''
#include "focus_ui.h"
static struct FocusUi adapter;
static struct FocusUiScene current;
static unsigned jobs[32],job_count,pixels,dirty_copy,clears,barriers;
static int bad_scene,fail_job,omit_receipt,change_epoch,late_draw,fail_present;

static int read_scene(void *p,struct FocusUiScene *out) {
    (void)p; *out=current; return !bad_scene;
}
static int submit(void *p,enum FocusUiJob job) {
    (void)p;
    if (job_count<32) jobs[job_count++]=job;
    if (fail_job==(int)job+1) return 0;
    /* Dequeue of the next job, not the previous completion signal, closes
     * the dirty-copy lifetime. A late old paint is also processed first. */
    dirty_copy=0;
    if (late_draw) {
        late_draw=0;
        pixels|=focus_ui_after_stock(&adapter,&current,(void *)1)!=0;
    }
    if (job==FOCUS_UI_REDRAW) {
        pixels=0; clears++;
        if (!omit_receipt)
            pixels=focus_ui_after_stock(&adapter,&current,(void *)1)!=0;
        dirty_copy=1;
    } else barriers++;
    if (fail_present) current.presentable=0;
    if (change_epoch) { current.epoch++; change_epoch=0; }
    return 1;
}
void ui_test_init(const struct FocusLivePolicy *p) {
    test_init(p,1);
    current=(struct FocusUiScene){.foreground=FOCUS_UI_FULL_FOREGROUND,
        .epoch=7,.normal_still=1,.presentable=1};
    struct FocusUiServices services={0,read_scene,submit};
    focus_ui_init(&adapter,&live,&services);
    job_count=pixels=dirty_copy=clears=barriers=0;
    bad_scene=fail_job=omit_receipt=change_epoch=late_draw=fail_present=0;
}
int ui_test_poll(int allowed) { return focus_ui_poll(&adapter,allowed); }
int ui_test_leave(void) { return focus_ui_quiesce(&adapter); }
int ui_test_stop(void) { return focus_ui_stop(&adapter); }
void ui_test_enable(int on) { focus_ui_set_enabled(&adapter,on); }
void ui_test_calibrate(void) { focus_ui_calibrate(&adapter); }
unsigned ui_test_value(unsigned which) {
    switch(which) {
    case 0:return pixels; case 1:return dirty_copy; case 2:return clears;
    case 3:return barriers; case 4:return job_count; case 5:return adapter.owns_pixels;
    case 6:return adapter.last_result; case 7:return adapter.stopped;
    case 8:return requested.enabled; case 9:return adapter.paint_token!=0;
    default:return 0;
    }
}
unsigned ui_test_job(unsigned index) { return index<job_count && index<32?jobs[index]:99; }
void ui_test_scene(unsigned field,unsigned value) {
    switch(field) {
    case 0:current.epoch=value;break;
    case 1:current.normal_still=value;break;
    case 2:current.camera_orientation=value;break;
    case 3:current.displayed_orientation=value;break;
    case 4:current.transition_pending=value;break;
    case 5:current.presentable=value;break;
    case 6:current.removing=value;break;
    case 7:current.foreground=value?0x4d33946c0:FOCUS_UI_FULL_FOREGROUND;break;
    }
}
void ui_test_failure(unsigned field,int value) {
    switch(field) {
    case 0:bad_scene=value;break; case 1:fail_job=value;break;
    case 2:omit_receipt=value;break; case 3:change_epoch=value;break;
    case 4:late_draw=value;break; case 5:fail_present=value;break;
    }
}
int ui_test_worker(unsigned epoch,unsigned foreground,unsigned orientation) {
    struct FocusUiScene s=current;
    s.epoch=epoch;s.foreground=foreground?0x4d33946c0:FOCUS_UI_FULL_FOREGROUND;
    s.displayed_orientation=orientation;
    return focus_ui_after_stock(&adapter,&s,(void *)1);
}
'''


class FocusUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cc = shutil.which('clang') or shutil.which('cc')
        if not cc:
            raise RuntimeError('C compiler required')
        cls.tmp = tempfile.TemporaryDirectory(prefix='bf-focus-ui-')
        cls.addClassCleanup(cls.tmp.cleanup)
        d = Path(cls.tmp.name)
        (d/'queue.c').write_text(FAKES+QUEUE)
        subprocess.run([cc, '-std=c11', '-O2', '-shared', '-fPIC', '-Wall', '-Wextra', '-Werror',
                        '-I', str(ROOT/'bfplus'), str(d/'queue.c'),
                        *(str(ROOT/'bfplus'/n) for n in
                          ('focus_ui.c','focus_live.c','focus_guide.c','focus_phase.c')),
                        '-o', str(d/'ui.so')], check=True, capture_output=True, text=True)
        cls.lib = C.CDLL(str(d/'ui.so'))
        cls.lib.ui_test_init.argtypes = [C.POINTER(Policy)]

    def setUp(self):
        # Same explicitly synthetic policy as the live-runtime tests.
        self.policy = Policy(Match(128,24,128,32,900,100,4),0,64,96,768,200,3,48,512,50,5000,96)
        self.lib.ui_test_init(C.byref(self.policy))

    def value(self, name):
        return self.lib.ui_test_value(dict(pixels=0,dirty=1,clears=2,barriers=3,
            count=4,owns=5,result=6,stopped=7,acquiring=8,armed=9)[name])

    def jobs(self):
        return [self.lib.ui_test_job(i) for i in range(self.value('count'))]

    def start(self):
        self.assertEqual(self.lib.ui_test_poll(1),UPDATED)
        self.assertEqual(self.value('pixels'),1)
        self.assertEqual(self.value('acquiring'),1)

    def assert_inhibited(self):
        self.assertEqual(self.value('armed'),0)
        self.assertEqual(self.value('acquiring'),0)
        self.assertEqual(self.lib.ui_test_worker(7,0,0),0)

    def test_paint_follows_full_stock_and_never_submits_from_worker(self):
        self.start()
        self.assertEqual(self.jobs(),[FULL])
        count=self.value('count')
        self.assertEqual(self.lib.ui_test_worker(7,0,0),1)
        self.assertEqual(self.value('count'),count)
        self.assertEqual(self.lib.ui_test_worker(6,0,0),0)
        self.assertEqual(self.lib.ui_test_worker(7,1,0),0)
        self.assertEqual(self.lib.ui_test_worker(7,0,1),0)
        self.assertEqual(self.lib.ui_test_poll(1),IDLE)
        self.assertEqual(self.value('count'),count)

    def test_leave_erases_then_crosses_dirty_copy_barrier(self):
        self.start()
        self.assertEqual(self.value('dirty'),1)
        self.lib.ui_test_failure(4,1)  # old queued callback during retirement
        self.assertEqual(self.lib.ui_test_leave(),1)
        self.assertEqual(self.jobs(),[FULL,FULL,BARRIER])
        self.assertEqual(self.value('pixels'),0)
        self.assertEqual(self.value('dirty'),0)
        self.assertEqual(self.value('owns'),0)
        self.assert_inhibited()
        self.assertEqual(self.lib.ui_test_leave(),1)
        self.assertEqual(self.jobs(),[FULL,FULL,BARRIER])

    def test_pending_transition_drains_old_scene_before_new_scene_can_paint(self):
        self.start()
        self.lib.ui_test_scene(4,1)
        self.assertEqual(self.lib.ui_test_poll(1),IDLE)
        self.assertEqual(self.jobs(),[FULL,FULL,BARRIER])
        self.assertEqual(self.value('pixels'),0)
        self.lib.ui_test_scene(0,8)
        self.lib.ui_test_scene(4,0)
        self.assertEqual(self.lib.ui_test_poll(1),UPDATED)
        self.assertEqual(self.lib.ui_test_worker(7,0,0),0)
        self.assertEqual(self.lib.ui_test_worker(8,0,0),1)

    def test_portrait_request_and_explicit_unsupported_layout_erase(self):
        for field,value,allowed in ((2,1,1),(2,3,1),(2,0,0)):
            with self.subTest(field=field,value=value,allowed=allowed):
                self.setUp(); self.start()
                self.lib.ui_test_scene(field,value)
                self.assertEqual(self.lib.ui_test_poll(allowed),IDLE)
                self.assertEqual(self.jobs(),[FULL,FULL,BARRIER])
                self.assertEqual(self.value('pixels'),0)
                self.assert_inhibited()

    def test_off_drains_and_on_demands_a_fresh_runtime_generation(self):
        self.start()
        generation=self.lib.test_generation()
        self.lib.ui_test_enable(0)
        self.assertEqual(self.lib.ui_test_poll(1),IDLE)
        self.assertEqual(self.value('pixels'),0)
        self.assert_inhibited()
        self.lib.ui_test_enable(1)
        self.assertEqual(self.lib.ui_test_poll(1),UPDATED)
        self.assertGreater(self.lib.test_generation(),generation)
        self.assertEqual(self.lib.test_confirmed(),0)

    def test_failed_redraw_receipt_or_barrier_holds_scene_and_can_retry(self):
        for field,value in ((1,1),(1,2),(2,1)):
            with self.subTest(field=field,value=value):
                self.setUp(); self.start()
                self.lib.ui_test_failure(field,value)
                self.assertEqual(self.lib.ui_test_leave(),0)
                self.assertEqual(self.value('owns'),1)
                self.assertEqual(self.value('result'),RETRY)
                self.assert_inhibited()
                self.lib.ui_test_failure(field,0)
                self.assertEqual(self.lib.ui_test_leave(),1)
                self.assertEqual(self.value('pixels'),0)
                self.assertEqual(self.value('dirty'),0)

    def test_native_completion_with_failed_presentation_is_not_release(self):
        self.start()
        self.lib.ui_test_failure(5,1)
        self.assertEqual(self.lib.ui_test_leave(),0)
        self.assertEqual(self.value('result'),RETRY)
        self.assertEqual(self.value('owns'),1)
        self.assert_inhibited()

    def test_lost_scene_never_repaints_old_root_over_new_owner(self):
        for field,value in ((0,8),(1,0),(3,1),(7,1)):
            with self.subTest(field=field,value=value):
                self.setUp(); self.start()
                self.lib.ui_test_scene(field,value)
                self.assertEqual(self.lib.ui_test_leave(),0)
                self.assertEqual(self.value('result'),LOST)
                self.assertEqual(self.jobs(),[FULL])
                self.assert_inhibited()

    def test_epoch_change_during_drain_is_not_release(self):
        self.start()
        self.lib.ui_test_failure(3,1)
        self.assertEqual(self.lib.ui_test_leave(),0)
        self.assertEqual(self.value('result'),LOST)
        self.assertEqual(self.value('owns'),1)
        self.assert_inhibited()

    def test_removal_is_terminal_and_waits_for_successful_drain(self):
        self.start()
        self.lib.ui_test_failure(1,2)
        self.assertEqual(self.lib.ui_test_stop(),0)
        self.assertEqual(self.value('stopped'),0)
        self.assertEqual(self.lib.test_tables(),0)
        self.assert_inhibited()
        self.lib.ui_test_enable(1)
        self.lib.ui_test_calibrate()
        self.lib.ui_test_failure(1,0)
        self.assertEqual(self.lib.ui_test_stop(),1)
        self.assertEqual(self.value('stopped'),1)
        count=self.value('count')
        self.assertEqual(self.lib.ui_test_poll(1),STOPPED)
        self.assertEqual(self.lib.ui_test_stop(),1)
        self.assertEqual(self.value('count'),count)
        self.assertEqual(self.value('pixels'),0)
        self.assertEqual(self.value('dirty'),0)

    def test_host_removal_flag_enters_stop_path_in_ui_task(self):
        self.start()
        self.lib.ui_test_scene(6,1)
        self.assertEqual(self.lib.ui_test_poll(1),STOPPED)
        self.assertEqual(self.value('stopped'),1)
        self.assertEqual(self.jobs(),[FULL,FULL,BARRIER])
        self.assertEqual(self.lib.test_tables(),0)
        self.assertEqual(self.value('dirty'),0)
        self.assert_inhibited()

    def test_unsupported_start_and_failed_snapshot_never_arm(self):
        self.lib.ui_test_scene(7,1)
        self.assertEqual(self.lib.ui_test_poll(1),IDLE)
        self.assertEqual(self.jobs(),[])
        self.assert_inhibited()
        self.lib.ui_test_scene(7,0)
        self.lib.ui_test_failure(0,1)
        self.assertEqual(self.lib.ui_test_poll(1),IDLE)
        self.assertEqual(self.jobs(),[])
        self.assert_inhibited()

    def test_update_failure_inhibits_until_another_checked_full_redraw(self):
        self.lib.ui_test_failure(2,1)
        self.assertEqual(self.lib.ui_test_poll(1),RETRY)
        self.assert_inhibited()
        self.lib.ui_test_failure(2,0)
        self.assertEqual(self.lib.ui_test_poll(1),UPDATED)
        self.assertEqual(self.value('pixels'),1)


if __name__ == '__main__':
    unittest.main()
