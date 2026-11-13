"""Exercise calibration -> fresh frames -> guide -> renderer with synthetic
images. Camera services are explicit fakes; this is not optical validation."""
import ctypes as C
from pathlib import Path
import random
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
U32, U64 = C.c_uint32, C.c_uint64
HIDDEN, UNAVAILABLE, FAR_LARGE, FAR_SMALL, FOCUSED, NEAR_SMALL, NEAR_LARGE = range(7)
UNCALIBRATED, PENDING, CALIBRATING, CALIBRATED, FAILED = range(5)


class Identity(C.Structure):
    _fields_ = [('slot', U32), ('profile', U32*2)]


class Request(C.Structure):
    _fields_ = [('enabled', U32), ('epoch', U32), ('after_ticks', U64),
                ('identity', Identity), ('reserved', U32)]


class Frame(C.Structure):
    _fields_ = [(x, U64) for x in ('sequence', 'acquired_ticks', 'copy_start_ticks', 'copy_end_ticks')]
    _fields_ += [(x, U32) for x in ('epoch', 'software_checks_passed', 'reason', 'hardware_coherence_unproven')]
    _fields_ += [('identity', Identity), ('wait_results', U32*2), ('wait_flags', U32*2),
                 ('lifecycle_continuity_unproven', U32), ('guard_before', U64),
                 ('pixels', (C.c_uint8*3072)*2), ('guard_after', U64),
                 ('source_epoch', U64), ('program_sequence', U64), ('consume_sequence', U64)]


class Match(C.Structure):
    _fields_ = [(x, C.c_uint16) for x in ('width', 'height', 'stride', 'max_shift',
                'min_correlation', 'min_peak_margin', 'min_texture_rms')]


class Policy(C.Structure):
    _fields_ = [('match', Match), ('reserved', C.c_uint16)]
    _fields_ += [(x, U32) for x in ('enter_q8', 'leave_q8', 'large_q8', 'max_age_ms',
                'confirmation_frames', 'calibration_span_q8', 'calibration_zero_limit_q8',
                'calibration_spacing_ms', 'calibration_timeout_ms', 'spatial_disagreement_q8')]


FAKES = r'''
#include "focus_live.h"
static struct FocusGuide guide;
static struct FocusLive live;
static struct FocusCaptureRequest requested;
static struct FocusCaptureIdentity identity;
static struct FocusCaptureFrame offered;
static uint64_t ticks, clock_step;
static int supported, available, held, release_count, table_enabled, stopped;
static unsigned colors, marks;
uint64_t focus_sensor_ticks(void) { uint64_t old=ticks; ticks+=clock_step; return old; }
int focus_sensor_context(struct FocusCaptureIdentity *out) {
    if (!supported || stopped) return 0;
    *out=identity; return 1;
}
int focus_capture_same_identity(const struct FocusCaptureIdentity *a,const struct FocusCaptureIdentity *b) {
    return a->slot==b->slot && a->profile[0]==b->profile[0] && a->profile[1]==b->profile[1];
}
void focus_capture_request(const struct FocusCaptureRequest *r) {
    requested=r?*r:(struct FocusCaptureRequest){0};
}
void focus_sensor_enable_tables(int on) { table_enabled=!!on; }
void focus_capture_shutdown(void) { stopped=1; table_enabled=0; requested.enabled=0; }
const struct FocusCaptureFrame *focus_capture_acquire(void) {
    if (!available || held) return 0;
    available=0; held=1; return &offered;
}
void focus_capture_release(const struct FocusCaptureFrame *p) {
    if (p==&offered && held) { held=0; release_count++; }
}
void focus_guide_native_mark(void *surface,const struct FocusGuideMark *m) {
    (void)surface; colors|=1u<<m->color; marks++;
}
void test_init(const struct FocusLivePolicy *p,int on) {
    ticks=24000000; clock_step=0; supported=1; available=held=release_count=table_enabled=stopped=0;
    identity=(struct FocusCaptureIdentity){4,{0x001c0023,0x00000000}};
    requested=(struct FocusCaptureRequest){0};
    focus_live_init(&live,&guide,p,on);
}
void test_time(uint64_t value) { ticks=value; }
void test_clock_step(uint64_t value) { clock_step=value; }
void test_context(int valid,uint32_t slot,uint32_t p0,uint32_t p1) {
    supported=valid; identity=(struct FocusCaptureIdentity){slot,{p0,p1}};
}
void test_offer(const struct FocusCaptureFrame *f) { offered=*f; available=1; }
int test_poll(int allowed) { return focus_live_poll(&live,allowed); }
void test_calibrate(void) { focus_live_calibrate(&live); }
void test_enable(int on) { focus_live_set_enabled(&live,on); }
void test_stop(void) { focus_live_stop(&live); }
unsigned test_paint(void) {
    colors=marks=0; focus_live_draw(&live,(void *)1); return colors;
}
struct FocusCaptureRequest *test_request(void) { return &requested; }
int test_state(void) { return guide.state; }
unsigned test_calibration(void) { return live.calibration; }
unsigned test_count(void) { return live.calibration_count; }
unsigned test_confirmed(void) { return guide.confirmed; }
unsigned test_generation(void) { return guide.generation; }
int test_zero(void) { return live.zero_q8; }
unsigned test_spatial_rejection(void) { return live.last_spatial_rejection; }
unsigned test_primary_valid(void) { return live.last_match.valid; }
int test_releases(void) { return release_count; }
int test_held(void) { return held; }
int test_tables(void) { return table_enabled; }
unsigned test_frame_size(void) { return sizeof(struct FocusCaptureFrame); }
unsigned test_policy_size(void) { return sizeof(struct FocusLivePolicy); }
'''


class FocusLiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cc = shutil.which('clang') or shutil.which('cc')
        if not cc:
            raise RuntimeError('C compiler required')
        cls.tmp = tempfile.TemporaryDirectory(prefix='bf-focus-live-')
        cls.addClassCleanup(cls.tmp.cleanup)
        d = Path(cls.tmp.name)
        (d/'fakes.c').write_text(FAKES)
        subprocess.run([cc, '-std=c11', '-O2', '-shared', '-fPIC', '-Wall', '-Wextra', '-Werror',
                        '-I', str(ROOT/'touch_focus'), str(d/'fakes.c'),
                        *(str(ROOT/'touch_focus'/n) for n in
                          ('focus_live.c', 'focus_guide.c', 'focus_phase.c')),
                        '-o', str(d/'live.so')], check=True, capture_output=True, text=True)
        cls.lib = C.CDLL(str(d/'live.so'))
        cls.lib.test_init.argtypes = [C.POINTER(Policy), C.c_int]
        cls.lib.test_offer.argtypes = [C.POINTER(Frame)]
        cls.lib.test_time.argtypes = [U64]
        cls.lib.test_clock_step.argtypes = [U64]
        cls.lib.test_context.argtypes = [C.c_int, U32, U32, U32]
        cls.lib.test_request.restype = C.POINTER(Request)

    def setUp(self):
        self.policy = Policy(Match(128,24,128,32,900,100,4),0,64,96,768,200,3,48,512,50,5000,96)
        self.lib.test_init(C.byref(self.policy),1)
        self.assertEqual(C.sizeof(Frame),self.lib.test_frame_size())
        self.assertEqual(C.sizeof(Policy),self.lib.test_policy_size())
        self.now = 1000
        self.sequence = 0
        self.lib.test_poll(1)

    def request(self):
        return Request.from_buffer_copy(self.lib.test_request().contents)

    def tick(self, advance=100, allowed=1):
        self.now += advance
        self.lib.test_time(self.now*24000)
        return self.lib.test_poll(allowed)

    def frame(self,shift=0,advance=100,age=30,offer=True,**fields):
        self.sequence += 1
        self.now += advance
        self.lib.test_time(self.now*24000)
        request = self.request()
        stamp = (self.now-age)*24000
        f = Frame(sequence=self.sequence, acquired_ticks=stamp, copy_start_ticks=stamp+1000,
                  copy_end_ticks=stamp+2000, epoch=request.epoch,
                  software_checks_passed=1, hardware_coherence_unproven=1,
                  lifecycle_continuity_unproven=1,source_epoch=1,
                  program_sequence=self.sequence,consume_sequence=self.sequence,
                  identity=request.identity, guard_before=0xc0dec0de51a7beef,
                  guard_after=0xc0dec0de51a7beef)
        rng = random.Random(9001)
        for y in range(24):
            row = [rng.randrange(32,96) for _ in range(128)]
            for x in range(128):
                f.pixels[0][y*128+x]=row[x]
                f.pixels[1][y*128+x]=row[(x-shift)%128]
        for key,value in fields.items():
            setattr(f,key,value)
        if offer:
            self.offer(f)
        return f

    def offer(self,f,allowed=1):
        self.lib.test_offer(C.byref(f))
        changed = self.lib.test_poll(allowed)
        self.assertEqual(self.lib.test_held(),0)
        return changed

    def calibrate(self,shift=0):
        self.lib.test_calibrate()
        self.lib.test_poll(1)
        self.assertEqual(self.lib.test_calibration(),CALIBRATING)
        for _ in range(8):
            self.frame(shift)
        self.assertEqual(self.lib.test_calibration(),CALIBRATED)
        self.assertEqual(self.lib.test_state(),UNAVAILABLE)

    def focus(self,shift=0):
        for _ in range(3):
            f=self.frame(shift)
        self.assertEqual(self.lib.test_state(),FOCUSED)
        return f

    def test_requires_user_calibration_and_new_post_calibration_frames(self):
        for _ in range(10):
            self.frame()
        self.assertEqual(self.lib.test_state(),UNAVAILABLE)
        self.assertEqual(self.lib.test_calibration(),UNCALIBRATED)
        generation = self.lib.test_generation()
        self.calibrate(1)
        self.assertGreater(self.lib.test_generation(),generation)
        self.assertLess(abs(self.lib.test_zero()-256),8)
        self.frame(1); self.frame(1)
        self.assertEqual(self.lib.test_state(),UNAVAILABLE)
        self.frame(1)
        self.assertEqual(self.lib.test_state(),FOCUSED)
        self.assertEqual(self.lib.test_paint(),1<<2)

    def test_observed_plane_order_gives_correct_adjustment_direction(self):
        self.calibrate()
        for shift,state in ((-2,FAR_SMALL),(-5,FAR_LARGE),(2,NEAR_SMALL),(5,NEAR_LARGE)):
            with self.subTest(shift=shift):
                self.frame(shift)
                self.assertEqual(self.lib.test_state(),state)
                self.assertEqual(self.lib.test_paint(),1<<1)

    def test_duplicate_and_pre_request_frames_cannot_confirm(self):
        self.calibrate()
        f=self.frame()
        for _ in range(4):
            self.offer(f)
        self.assertEqual(self.lib.test_confirmed(),0)
        self.assertEqual(self.lib.test_state(),UNAVAILABLE)
        self.frame(acquired_ticks=self.request().after_ticks-1)
        self.assertEqual(self.lib.test_confirmed(),0)
        self.focus()

    def test_software_quality_guard_epoch_and_identity_failures_clear_green(self):
        cases=[dict(software_checks_passed=0,reason=16),dict(guard_after=0),
               dict(hardware_coherence_unproven=0),dict(age=201),dict(age=-1)]
        for changes in cases:
            with self.subTest(changes=changes):
                self.calibrate(); self.focus()
                self.frame(**changes)
                self.assertEqual(self.lib.test_state(),UNAVAILABLE)
        for mode in ('epoch','identity','pixels'):
            with self.subTest(mode=mode):
                self.calibrate(); self.focus()
                f=self.frame(offer=False)
                if mode=='epoch':
                    f.epoch-=1
                elif mode=='identity':
                    f.identity.slot+=1
                else:
                    C.memset(C.addressof(f.pixels),0,C.sizeof(f.pixels))
                self.offer(f)
                self.assertEqual(self.lib.test_state(),UNAVAILABLE)
                self.assertEqual(self.lib.test_paint(),1<<0)

    def test_profile_change_clears_zero_and_never_accepts_old_profile_frames(self):
        self.calibrate(); old=self.focus()
        self.lib.test_context(1,1,0x001c001c,0)
        self.tick()
        self.assertEqual(self.lib.test_calibration(),UNCALIBRATED)
        self.assertEqual(self.lib.test_state(),UNAVAILABLE)
        self.offer(old)
        self.assertEqual(self.lib.test_state(),UNAVAILABLE)
        self.assertEqual(self.lib.test_zero(),0)

    def test_mutating_profile_bytes_in_same_slot_invalidates_calibration(self):
        self.calibrate(); self.focus()
        self.lib.test_context(1,4,0x001c0023,1)
        self.tick()
        self.assertEqual(self.lib.test_calibration(),UNCALIBRATED)
        self.assertEqual(self.lib.test_state(),UNAVAILABLE)

    def test_expiry_without_producer_and_painter_never_refreshes_core(self):
        self.calibrate(); f=self.focus()
        old_confirmed=self.lib.test_confirmed()
        self.lib.test_time(f.acquired_ticks+201*24000)
        self.assertEqual(self.lib.test_paint(),1<<0)
        self.assertEqual(self.lib.test_confirmed(),old_confirmed)
        self.now=(f.acquired_ticks//24000)+201
        self.assertTrue(self.lib.test_poll(1))
        self.assertEqual(self.lib.test_state(),UNAVAILABLE)

    def test_hidden_scenes_and_disabled_layout_reject_late_overlay(self):
        for native in (False,True):
            with self.subTest(native=native):
                self.lib.test_context(1,4,0x001c0023,0)
                self.tick(); self.calibrate(); self.focus()
                if native:
                    self.lib.test_context(0,4,0x001c0023,0)
                    self.assertEqual(self.lib.test_paint(),0)
                    self.tick()
                else:
                    self.tick(allowed=0)
                self.assertEqual(self.lib.test_state(),HIDDEN)
                self.assertEqual(self.request().enabled,0)
                self.assertEqual(self.lib.test_paint(),0)

    def test_calibration_waits_for_full_view_and_restarts_after_magnification(self):
        self.lib.test_context(0,4,0x001c0023,0)
        self.tick()
        self.lib.test_calibrate()
        self.tick(6000)
        self.assertEqual(self.lib.test_calibration(),PENDING)
        self.lib.test_context(1,4,0x001c0023,0)
        self.tick()
        for _ in range(3): self.frame()
        self.assertEqual(self.lib.test_count(),3)
        self.lib.test_context(0,4,0x001c0023,0)
        self.tick()
        self.assertEqual(self.lib.test_calibration(),PENDING)
        self.lib.test_context(1,4,0x001c0023,0)
        self.tick()
        for _ in range(8): self.frame()
        self.assertEqual(self.lib.test_calibration(),CALIBRATED)

    def test_moving_focus_large_zero_missing_or_bad_quality_fail_calibration(self):
        self.lib.test_calibrate(); self.lib.test_poll(1)
        for i in range(8): self.frame(i%2)
        self.assertEqual(self.lib.test_calibration(),FAILED)
        self.assertEqual(self.lib.test_state(),UNAVAILABLE)
        self.lib.test_calibrate(); self.lib.test_poll(1)
        self.frame(3)
        self.assertEqual(self.lib.test_calibration(),FAILED)
        self.lib.test_calibrate(); self.lib.test_poll(1)
        for _ in range(7): self.frame()
        self.frame(software_checks_passed=0,reason=8)
        self.assertEqual(self.lib.test_count(),0)
        self.tick(5001)
        self.assertEqual(self.lib.test_calibration(),FAILED)

    def test_invalid_policy_cannot_start_calibration_or_acquisition(self):
        for field,value in (('enter_q8',0),('leave_q8',64),('max_age_ms',251),
                            ('calibration_span_q8',65),('calibration_zero_limit_q8',0),
                            ('calibration_spacing_ms',0),('confirmation_frames',1)):
            with self.subTest(field=field):
                p=Policy.from_buffer_copy(self.policy); setattr(p,field,value)
                self.lib.test_init(C.byref(p),1); self.lib.test_poll(1)
                self.lib.test_calibrate()
                self.assertEqual(self.lib.test_calibration(),UNCALIBRATED)
                self.assertEqual(self.request().enabled,0)
                self.assertNotEqual(self.lib.test_state(),FOCUSED)

    def test_disable_and_stop_inhibit_captures_and_paints_immediately(self):
        self.calibrate(); self.focus()
        self.lib.test_enable(0)
        self.assertEqual(self.lib.test_paint(),0)
        self.assertEqual(self.request().enabled,0)
        self.assertEqual(self.lib.test_tables(),0)

        self.lib.test_enable(1); self.tick(); self.focus()
        self.lib.test_stop()
        self.assertEqual(self.lib.test_state(),HIDDEN)
        self.assertEqual(self.lib.test_paint(),0)
        self.assertEqual(self.request().enabled,0)
        self.assertEqual(self.lib.test_tables(),0)

    def test_receiver_discontinuity_flushes_confirmation_and_keeps_session_zero(self):
        self.calibrate(1); self.focus(1)
        generation=self.lib.test_generation()
        self.frame(1,source_epoch=2)
        self.assertGreater(self.lib.test_generation(),generation)
        self.assertEqual(self.lib.test_state(),UNAVAILABLE)
        self.assertEqual(self.lib.test_calibration(),CALIBRATED)
        for _ in range(3): self.frame(1,source_epoch=3)
        self.assertEqual(self.lib.test_state(),FOCUSED)

    def test_last_frame_after_deadline_cannot_complete_calibration(self):
        self.lib.test_calibrate(); self.lib.test_poll(1)
        for _ in range(7): self.frame()
        self.frame(advance=5001)
        self.assertEqual(self.lib.test_calibration(),FAILED)
        self.assertEqual(self.lib.test_state(),UNAVAILABLE)

    def test_gap_in_calibration_requires_eight_new_contiguous_references(self):
        self.lib.test_calibrate(); self.lib.test_poll(1)
        for _ in range(7): self.frame()
        self.frame(advance=301)
        self.assertEqual(self.lib.test_calibration(),CALIBRATING)
        self.assertEqual(self.lib.test_count(),1)
        for _ in range(7): self.frame()
        self.assertEqual(self.lib.test_calibration(),CALIBRATED)

    def test_matching_time_cannot_refresh_an_expired_frame(self):
        self.calibrate(); self.focus()
        f=self.frame(age=195,offer=False)
        self.lib.test_clock_step(10*24000)
        self.offer(f)
        self.assertEqual(self.lib.test_state(),UNAVAILABLE)

    def test_disagreeing_subject_halves_veto_a_passing_primary(self):
        # Lower synthetic correlation/margin gates explicitly for this test
        # so the heterogeneous pair can pass the primary, then require the
        # independently calibrated spatial veto to reject it.
        self.policy.match.min_correlation=500
        self.policy.match.min_peak_margin=20
        self.lib.test_init(C.byref(self.policy),1); self.lib.test_poll(1)
        self.calibrate(); self.focus()
        f=self.frame(offer=False)
        for y in range(24):
            row=list(f.pixels[0][y*128:(y+1)*128])
            for x in range(128):
                f.pixels[1][y*128+x]=row[(x-(0 if x<64 else 3))%128]
        self.offer(f)
        self.assertEqual(self.lib.test_primary_valid(),1)
        self.assertNotEqual(self.lib.test_spatial_rejection(),0)
        self.assertEqual(self.lib.test_state(),UNAVAILABLE)


if __name__ == '__main__':
    unittest.main()
