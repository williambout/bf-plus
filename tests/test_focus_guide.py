"""Run the original C guide with synthetic, calibrated measurements; no USB.

These tests validate the guide, not availability/calibration of BF phase data.
The small values below are deliberately test units, not camera thresholds.
"""
import ctypes as C
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
HIDDEN, UNAVAILABLE, FAR_LARGE, FAR_SMALL, FOCUSED, NEAR_SMALL, NEAR_LARGE = range(7)
GRAY, WHITE, GREEN = range(3)
RECT, TRIANGLE = range(2)
U32 = C.c_uint32


class Config(C.Structure):
    _fields_ = [(name, U32) for name in (
        'focus_enter', 'focus_leave', 'large_adjustment', 'max_age_ms',
        'min_confidence', 'confirmation_frames')]


class Sample(C.Structure):
    _fields_ = [('defocus', C.c_int32)] + [(name, U32) for name in (
        'confidence', 'valid', 'captured_ms', 'sequence', 'generation')]


class Guide(C.Structure):
    _fields_ = [('config', Config), ('last', Sample)] + [(name, U32) for name in (
        'enabled', 'manual_focus', 'magnified', 'target_id', 'generation',
        'have_sample', 'confirmed')] + [('x', C.c_uint16), ('y', C.c_uint16), ('state', C.c_int)]


class Mark(C.Structure):
    _fields_ = [('shape', C.c_int), ('color', C.c_int),
                ('x', C.c_int16 * 3), ('y', C.c_int16 * 3)]


Paint = C.CFUNCTYPE(None, C.c_void_p, C.POINTER(Mark))


def compile_guide(directory):
    compiler = shutil.which('clang') or shutil.which('cc')
    if not compiler:
        raise RuntimeError('A C compiler is required for focus guide tests')
    library = Path(directory) / 'focus_guide.so'
    subprocess.run([compiler, '-std=c11', '-Os', '-shared', '-fPIC', '-Wall', '-Wextra',
                    '-Werror', '-pedantic', str(ROOT / 'touch_focus/focus_guide.c'),
                    '-o', str(library)], check=True, capture_output=True, text=True)
    lib = C.CDLL(str(library))
    signatures = {
        'init': [C.POINTER(Guide)],
        'configure': [C.POINTER(Guide), C.POINTER(Config)],
        'mode': [C.POINTER(Guide), C.c_int, C.c_int, C.c_int],
        'target': [C.POINTER(Guide), C.c_int, C.c_int, U32],
        'update': [C.POINTER(Guide), C.POINTER(Sample), U32],
        'paint': [C.POINTER(Guide), U32, Paint, C.c_void_p],
    }
    for name, signature in signatures.items():
        function = getattr(lib, 'focus_guide_' + name)
        function.argtypes, function.restype = signature, None
    return lib


class FocusGuideTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix='bf-guide-test-')
        cls.addClassCleanup(cls.directory.cleanup)
        cls.lib = compile_guide(cls.directory.name)

    def setUp(self):
        self.g = Guide()
        self.lib.focus_guide_init(C.byref(self.g))
        self.config = Config(10, 16, 80, 200, 800, 3)
        self.lib.focus_guide_configure(C.byref(self.g), C.byref(self.config))
        self.lib.focus_guide_mode(C.byref(self.g), 1, 1, 0)
        self.now = 1000
        self.sequence = 0

    def update(self, defocus=0, **fields):
        self.sequence = (self.sequence + 1) & 0xffffffff
        self.now = (self.now + 20) & 0xffffffff
        values = dict(defocus=defocus, confidence=900, valid=1,
                      captured_ms=self.now, sequence=self.sequence, generation=self.g.generation)
        values.update(fields)
        sample = Sample(**values)
        self.lib.focus_guide_update(C.byref(self.g), C.byref(sample), self.now)
        return sample

    def replay(self, sample, now=None):
        self.lib.focus_guide_update(C.byref(self.g), C.byref(sample),
                                   self.now if now is None else now)

    def focus(self):
        for _ in range(3):
            sample = self.update()
        self.assertEqual(self.g.state, FOCUSED)
        return sample

    def paint(self, now=None):
        marks = []
        @Paint
        def collect(_, pointer):
            mark = pointer.contents
            marks.append((mark.shape, mark.color, tuple(mark.x), tuple(mark.y)))
        self.lib.focus_guide_paint(C.byref(self.g), self.now if now is None else now,
                                  collect, None)
        return marks

    def test_default_is_disabled_centered_and_uncalibrated(self):
        self.lib.focus_guide_init(C.byref(self.g))
        self.assertEqual((self.g.state, self.g.x, self.g.y), (HIDDEN, 512, 341))
        self.assertFalse(self.paint())
        self.lib.focus_guide_mode(C.byref(self.g), 1, 1, 0)
        self.update()
        self.assertEqual(self.g.state, UNAVAILABLE)

    def test_both_directions_and_adjustment_boundaries(self):
        for error, state in ((11,FAR_SMALL),(79,FAR_SMALL),(80,FAR_LARGE),
                             (-11,NEAR_SMALL),(-79,NEAR_SMALL),(-80,NEAR_LARGE),
                             (2147483647,FAR_LARGE),(-2147483648,NEAR_LARGE)):
            with self.subTest(error=error):
                self.update(error)
                self.assertEqual(self.g.state,state)

    def test_focus_requires_distinct_fresh_measurements(self):
        sample = self.update(10)
        for _ in range(8):
            self.replay(sample)
        self.assertEqual((self.g.state,self.g.confirmed),(UNAVAILABLE,1))
        self.update(-10)
        self.assertEqual(self.g.state,UNAVAILABLE)
        self.update(0)
        self.assertEqual(self.g.state,FOCUSED)

    def test_hysteresis_and_loss_of_focus(self):
        self.focus()
        for error in (11,-16,16):
            self.update(error)
            self.assertEqual(self.g.state,FOCUSED)
        self.update(17)
        self.assertEqual(self.g.state,FAR_SMALL)
        self.update(11)
        self.assertEqual(self.g.state,FAR_SMALL)
        self.focus()

    def test_unfocused_frame_breaks_confirmation_streak(self):
        self.update(0); self.update(11); self.update(0); self.update(0)
        self.assertEqual((self.g.state,self.g.confirmed),(UNAVAILABLE,2))

    def test_stale_measurement_expires_in_painter_without_producer(self):
        self.focus()
        self.assertEqual({m[1] for m in self.paint(self.now+200)}, {GREEN})
        self.assertEqual({m[1] for m in self.paint(self.now+201)}, {GRAY})
        self.assertEqual((self.g.state,self.g.confirmed),(UNAVAILABLE,0))

    def test_missing_publication_does_not_immediately_discard_fresh_result(self):
        self.focus()
        self.lib.focus_guide_update(C.byref(self.g), None, self.now+100)
        self.assertEqual(self.g.state,FOCUSED)
        self.lib.focus_guide_update(C.byref(self.g), None, self.now+201)
        self.assertEqual(self.g.state,UNAVAILABLE)

    def test_gap_resets_hysteresis_as_well_as_confirmation(self):
        self.focus()
        self.now += 201
        self.update(14)
        self.assertEqual((self.g.state,self.g.confirmed),(FAR_SMALL,0))
        self.focus()

    def test_invalid_frames_never_confirm_and_cannot_be_rewritten(self):
        for changes in (dict(valid=0), dict(valid=2), dict(confidence=799),
                        dict(confidence=1001), dict(generation=self.g.generation+1)):
            with self.subTest(changes=changes):
                self.focus()
                sample = self.update(**changes)
                self.assertEqual(self.g.state,UNAVAILABLE)
                if 'generation' not in changes:
                    sample.valid, sample.confidence = 1,900
                    self.replay(sample)
                    self.assertEqual(self.g.state,UNAVAILABLE)
                self.update()
                self.assertEqual(self.g.confirmed,1)

    def test_same_sequence_with_changed_payload_invalidates_existing_result(self):
        for name, value in (('defocus',20),('captured_ms',1020),('confidence',850),('valid',0)):
            with self.subTest(field=name):
                sample = self.focus()
                setattr(sample,name,value)
                self.replay(sample)
                self.assertEqual(self.g.state,UNAVAILABLE)

    def test_old_sequences_and_timestamps_cannot_restore_confirmation(self):
        sample = self.focus()
        old = Sample.from_buffer_copy(sample)
        old.sequence -= 1
        self.replay(old)
        self.replay(sample)
        self.assertEqual((self.g.state,self.g.confirmed),(UNAVAILABLE,0))
        self.update(captured_ms=self.now-40)
        self.assertEqual(self.g.state,UNAVAILABLE)
        self.focus()

    def test_sequence_alone_cannot_refresh_acquisition(self):
        sample = self.focus()
        self.update(captured_ms=sample.captured_ms)
        self.assertEqual(self.g.state,UNAVAILABLE)
        self.assertEqual(self.g.confirmed,0)

    def test_future_and_too_old_timestamps_are_rejected(self):
        for age in (-1,201,0x80000000):
            with self.subTest(age=age):
                self.focus()
                self.update(captured_ms=(self.now+20-age)&0xffffffff)
                self.assertEqual(self.g.state,UNAVAILABLE)

    def test_clock_and_sequence_wrap(self):
        self.now = 0xffffffd0
        self.sequence = 0xfffffffd
        self.focus()
        self.assertEqual(self.g.last.sequence,0)
        self.assertEqual(self.g.last.captured_ms,12)
        self.assertEqual({m[1] for m in self.paint(212)},{GREEN})
        self.assertEqual({m[1] for m in self.paint(213)},{GRAY})

    def test_mode_changes_hide_guide_and_reject_pretransition_samples(self):
        for mode in ((0,1,0),(1,0,0),(1,1,1)):
            with self.subTest(mode=mode):
                sample = self.focus()
                self.lib.focus_guide_mode(C.byref(self.g),*mode)
                self.assertEqual(self.g.state,HIDDEN)
                self.assertFalse(self.paint())
                self.lib.focus_guide_mode(C.byref(self.g),1,1,0)
                self.replay(sample)
                self.assertEqual(self.g.state,UNAVAILABLE)

    def test_position_and_identity_changes_discard_old_samples(self):
        for x,y,target in ((700,350,0),(700,350,1),(700,350,2)):
            with self.subTest(target=target):
                sample = self.focus()
                self.lib.focus_guide_target(C.byref(self.g),x,y,target)
                self.replay(sample)
                self.assertEqual(self.g.state,UNAVAILABLE)
                self.assertEqual((self.g.x,self.g.y,self.g.target_id),(x,y,target))

    def test_unchanged_mode_and_target_do_not_break_confirmation(self):
        self.focus()
        generation = self.g.generation
        self.lib.focus_guide_mode(C.byref(self.g),1,1,0)
        self.lib.focus_guide_target(C.byref(self.g),512,341,0)
        self.assertEqual((self.g.state,self.g.generation),(FOCUSED,generation))

    def test_reconfiguration_rejects_old_samples(self):
        sample = self.focus()
        self.lib.focus_guide_configure(C.byref(self.g),C.byref(self.config))
        self.replay(sample)
        self.assertEqual(self.g.state,UNAVAILABLE)
        self.focus()

    def test_bad_configurations_fail_closed(self):
        for name, value in (('focus_enter',0),('focus_enter',16),('focus_leave',80),
                            ('large_adjustment',2147483648),('max_age_ms',0),
                            ('max_age_ms',0x80000000),('min_confidence',0),
                            ('min_confidence',1001),('confirmation_frames',0),
                            ('confirmation_frames',121)):
            with self.subTest(field=name,value=value):
                config = Config.from_buffer_copy(self.config)
                setattr(config,name,value)
                self.lib.focus_guide_configure(C.byref(self.g),C.byref(config))
                for _ in range(3): self.update()
                self.assertEqual(self.g.state,UNAVAILABLE)
                self.assertEqual({m[1] for m in self.paint()},{GRAY})
        self.lib.focus_guide_configure(C.byref(self.g),None)
        self.update()
        self.assertEqual(self.g.state,UNAVAILABLE)

    def test_colors_and_unknown_shape_are_unambiguous(self):
        marks = self.paint()
        self.assertEqual({m[0] for m in marks},{RECT})
        self.assertEqual({m[1] for m in marks},{GRAY})
        self.update(80)
        marks = self.paint()
        self.assertEqual(sum(m[0]==TRIANGLE for m in marks),3)
        self.assertEqual({m[1] for m in marks},{WHITE})
        self.focus()
        self.assertEqual({m[1] for m in self.paint()},{GREEN})

    def test_adjustment_spread_increases_and_direction_swaps_sides(self):
        pointers = {}
        for error in (20,80,-20,-80,2147483647):
            self.update(error)
            pointers[error] = [m for m in self.paint() if m[0]==TRIANGLE]
        def spread(marks): return marks[2][2][2] - marks[1][2][2]
        self.assertGreater(spread(pointers[80]),spread(pointers[20]))
        self.assertEqual(spread(pointers[80]),spread(pointers[-80]))
        self.assertEqual(pointers[80],pointers[2147483647])
        self.assertLess(pointers[20][0][3][2],pointers[20][0][3][0])
        self.assertGreater(pointers[-20][0][3][2],pointers[-20][0][3][0])

    def test_all_geometry_stays_in_display_at_clamped_extremes(self):
        for x in (-2147483648,512,2147483647):
            for y in (-2147483648,341,2147483647):
                self.lib.focus_guide_target(C.byref(self.g),x,y,0)
                for error in (-2147483648,-20,0,20,2147483647):
                    for _ in range(3): self.update(error)
                    for shape,_,xs,ys in self.paint():
                        count = 2 if shape==RECT else 3
                        self.assertTrue(all(0<=p<=1024 for p in xs[:count]))
                        self.assertTrue(all(0<=p<=682 for p in ys[:count]))
                        if shape==RECT:
                            self.assertLess(xs[0],xs[1]); self.assertLess(ys[0],ys[1])


if __name__ == '__main__': unittest.main()
