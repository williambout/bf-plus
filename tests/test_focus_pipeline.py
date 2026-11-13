"""Small offline BF 1.04 receiver-to-indicator integration regressions.

Run: .venv/bin/python -B -m unittest tests.test_focus_pipeline -v

Actual separately compiled capture/live/phase/guide/painter objects share the
native capture ABI. Real receiver calls and waits remain in the execution path;
only the capture fixture's declared native service leaves are synthetic. Images
and policy are deliberately synthetic, never production defaults. These tests
make no hardware, optical calibration, DMA/cache, scheduling or presentation
claim. See focus_pipeline_machine.py and focus_capture_machine.py for limits.
"""

import ctypes as C
import struct
import tempfile
import unittest

from tests import focus_capture_machine as capture
from tests.focus_pipeline_machine import (
    GRAY, GREEN, WHITE, MAX_AGE_MS, TICKS_PER_MS, LiveFrame,
    PipelineMachine, build_pipeline,
)
from tests.test_focus_live import (
    UNAVAILABLE, FAR_SMALL, FOCUSED, NEAR_SMALL,
    UNCALIBRATED, CALIBRATING, CALIBRATED,
)


class FocusPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="bf-focus-pipeline-")
        cls.addClassCleanup(cls.directory.cleanup)
        cls.resident = build_pipeline(cls.directory.name)

    def machine(self):
        m = PipelineMachine(self.resident)
        self.addCleanup(m.close)
        return m

    def cycle(self, m, shift=1, poll=True):
        receipt = m.receive(shift)
        expected = [capture.PROGRAM] if receipt.priming else [capture.PROGRAM, capture.WAIT, capture.WAIT, capture.SEND]
        self.assertEqual(receipt.result, 0)
        self.assertEqual([pc for pc, _ in receipt.calls], expected)
        self.assertEqual(receipt.waits, 0 if receipt.priming else 2)
        self.assertEqual(len(receipt.queued), 0 if receipt.priming else 1)
        if not receipt.priming:
            waits = [args for pc, args in receipt.calls if pc == capture.WAIT]
            self.assertEqual([args[:3] for args in waits], [(77, 0x20000001, 1), (77, 3, 0x20)])
            self.assertEqual([args[3] for args in waits],
                             [capture.STACK_TOP - 0x70 + 0x48, capture.STACK_TOP - 0x70 + 0x4c])
            self.assertEqual(receipt.queued[0][0x18:0x170], receipt.pending)
            self.assertEqual(dict(receipt.returns)[capture.SEND_SITE] & 0xffffffff, m.send_rc)
        count = len(m.frames)
        if poll:
            m.poll()
            self.assertEqual(len(m.frames), len(m.releases))
            self.assertEqual(m.call("focus_capture_acquire"), 0, "consumer left a ready frame behind")
        if len(m.frames) == count:
            return None
        frame = m.frames[-1][1]
        self.assertEqual((frame.guard_before, frame.guard_after), (capture.GUARD, capture.GUARD))
        self.assertEqual((frame.hardware_coherence_unproven, frame.lifecycle_continuity_unproven), (1, 1))
        if frame.software_checks_passed:
            self.assertEqual(frame.reason, 0)
            self.assertEqual(frame.pixels, receipt.pixels)
            self.assertEqual(frame.acquired_ticks, struct.unpack_from("<Q", receipt.pending, 0x10)[0])
            self.assertEqual((frame.wait_results, frame.wait_flags), ((0, 0), (1, 3)))
        return frame

    def calibrate(self, m, shift=1):
        m.calibrate()
        m.poll()
        self.assertEqual(m.state.calibration, CALIBRATING)
        for _ in range(12):  # bounded native priming/request handoff, then eight references
            frame = self.cycle(m, shift)
            if m.state.calibration == CALIBRATED:
                self.assertIsNotNone(frame)
                self.assertEqual(m.state.count, 8)
                self.assertEqual(m.state.state, UNAVAILABLE)
                self.assertGreater(m.state.generation, frame.epoch)
                self.assertLess(abs(m.state.zero_q8 - shift * 256), 8)
                return frame
        self.fail(f"native pipeline did not calibrate: {m.state}")

    def focus(self, m, shift=1):
        for _ in range(7):
            frame = self.cycle(m, shift)
            if m.state.state == FOCUSED:
                self.assertEqual(m.state.confirmed, 3)
                return frame
        self.fail(f"native pipeline did not confirm: {m.state}")

    def assert_paint(self, m, color):
        paint = m.draw()
        self.assertEqual(paint.result, 1)
        self.assertEqual(paint.colors, {color})
        self.assertEqual(len(paint.rectangles), 11 if color == GRAY else 38)
        self.assertEqual(paint.dirty, (298 if color == GRAY else 283, 371))

    def test_capture_abi_and_calibration_generation_reach_real_native_pixels(self):
        m = self.machine()
        self.assertEqual(self.resident.frame_size, C.sizeof(LiveFrame))
        for name, ctype in LiveFrame._fields_:
            self.assertEqual(self.resident.frame_layout[name], (getattr(LiveFrame, name).offset, C.sizeof(ctype)))
        self.cycle(m)
        self.cycle(m)
        self.assertEqual(m.state.calibration, UNCALIBRATED)
        self.assert_paint(m, GRAY)
        # Leave a genuinely acquired old-generation publication in the mailbox.
        self.cycle(m, poll=False)
        old_epoch = m.live_request.epoch
        m.calibrate()
        self.assertGreater(m.live_request.epoch, old_epoch)
        matches = len(m.matches)
        m.poll()
        self.assertEqual(m.frames[-1][1].epoch, old_epoch)
        self.assertEqual(len(m.matches), matches)
        self.assertEqual(m.state.count, 0)
        for _ in range(10):
            reference = self.cycle(m)
            if m.state.calibration == CALIBRATED:
                break
        self.assertEqual(m.state.calibration, CALIBRATED)
        self.assertEqual(m.state.count, 8)
        self.assertGreater(m.live_request.epoch, reference.epoch)
        self.assertEqual(m.live_request.after_ticks, m.state.after_ticks)
        self.assertEqual((m.state.state, m.state.confirmed), (UNAVAILABLE, 0))
        self.assert_paint(m, GRAY)
        old = self.cycle(m)
        self.assertNotEqual(old.epoch, m.live_request.epoch)
        self.assertTrue(old.reason & capture.REQUEST_CHANGED)
        self.assertEqual(m.state.confirmed, 0)
        for confirmed in (1, 2, 3):
            frame = self.cycle(m)
            pointer = m.frames[-1][0]
            self.assertEqual(frame.epoch, m.live_request.epoch)
            self.assertGreaterEqual(frame.acquired_ticks, m.live_request.after_ticks)
            self.assertEqual(m.state.confirmed, confirmed)
            self.assertEqual(m.state.state, FOCUSED if confirmed == 3 else UNAVAILABLE)
            pixels = pointer + self.resident.frame_layout["pixels"][0]
            self.assertEqual(m.matches[-3:], [
                (pixels + offset, pixels + 3072 + offset, (width, 24, 128, 32, 900, 100, 4))
                for offset, width in ((0, 128), (0, 96), (32, 96))])
        self.assertEqual((m.state.match_valid, m.state.tile0_valid, m.state.tile1_valid), (1, 1, 1))
        self.assertEqual(m.state.spatial_rejection, 0)
        self.assert_paint(m, GREEN)
        for shift, state in ((3, NEAR_SMALL), (-1, FAR_SMALL)):
            self.cycle(m, shift)
            self.assertEqual(m.state.state, state)
            self.assert_paint(m, WHITE)

    def test_native_source_reset_flushes_confirmation_but_preserves_session_zero(self):
        m = self.machine()
        self.calibrate(m)
        before = self.focus(m)
        generation, zero = m.state.generation, m.state.zero_q8
        m.put(capture.FIRST, 1, 1)
        self.assertIsNone(self.cycle(m))  # original native priming: no waits/send
        warmup = self.cycle(m)
        self.assertGreater(warmup.source_epoch, before.source_epoch)
        self.assertTrue(warmup.reason & capture.IRQ_FAILED)
        self.assertEqual(m.state.confirmed, 0)
        self.assert_paint(m, GRAY)
        changed_source = self.cycle(m)
        self.assertEqual(changed_source.software_checks_passed, 1)
        self.assertEqual(changed_source.epoch, generation)
        self.assertGreater(m.state.generation, generation)
        self.assertEqual((m.state.state, m.state.confirmed), (UNAVAILABLE, 0))
        self.assertEqual((m.state.calibration, m.state.zero_q8), (CALIBRATED, zero))
        self.assertEqual(m.state.source_epoch, 0)
        handoff = self.cycle(m)
        self.assertTrue(handoff.reason & capture.REQUEST_CHANGED)
        self.assertEqual(m.state.confirmed, 0)
        for confirmed in (1, 2, 3):
            fresh = self.cycle(m)
            self.assertEqual(fresh.software_checks_passed, 1)
            self.assertGreater(fresh.source_epoch, changed_source.source_epoch)
            self.assertEqual(fresh.epoch, m.live_request.epoch)
            self.assertEqual(m.state.confirmed, confirmed)
        self.assertEqual(m.state.state, FOCUSED)
        self.assert_paint(m, GREEN)

    def test_freshness_survives_mailbox_delay_matching_time_and_paint_only_expiry(self):
        m = self.machine()
        self.calibrate(m)
        focused = self.focus(m)
        core = m.state
        m.tick = focused.acquired_ticks + (MAX_AGE_MS + 1) * TICKS_PER_MS
        self.assert_paint(m, GRAY)
        self.assertEqual(m.state, core, "painting must expire only its copied view")
        self.assertTrue(m.poll())
        self.assertEqual(m.state.state, UNAVAILABLE)
        for matching in (False, True):
            with self.subTest(delay="during match" if matching else "in mailbox"):
                # The first receiver after a stall can reject an old acquisition.
                # Two native cycles ensure the queued frame itself passed capture.
                self.cycle(m, poll=False)
                self.cycle(m, poll=False)
                self.assertEqual(m.status.last_reason, 0)
                stamp = m.status.last_acquired_ticks
                m.tick = stamp + (195 if matching else MAX_AGE_MS + 1) * TICKS_PER_MS
                m.tick_step = 10 * TICKS_PER_MS if matching else 1200
                matches, releases = len(m.matches), len(m.releases)
                m.poll()
                m.tick_step = 1200
                frame = m.frames[-1][1]
                self.assertEqual((frame.software_checks_passed, frame.reason), (1, 0))
                self.assertEqual(frame.acquired_ticks, stamp)
                self.assertEqual(len(m.releases), releases + 1)
                self.assertEqual(len(m.matches) - matches, 3 if matching else 0)
                self.assertEqual(m.state.match_valid, int(matching))
                if matching:
                    self.assertEqual(m.state.match_ticks, 10 * TICKS_PER_MS)
                self.assertEqual((m.state.state, m.state.confirmed), (UNAVAILABLE, 0))
                self.assert_paint(m, GRAY)

    def test_same_slot_profile_edit_rejects_queued_native_capture_and_old_zero(self):
        m = self.machine()
        self.calibrate(m)
        self.focus(m)
        self.cycle(m, poll=False)
        old_request, generation = m.live_request, m.state.generation
        m.set_identity(slot=old_request.identity.slot, profile=(0x12345678, 0x90abcdee))
        self.assertEqual(m.draw().colors, set())  # native getters gate late paints
        m.poll()
        self.assertEqual(m.frames[-1][1].identity.key(), old_request.identity.key())
        self.assertGreater(m.state.generation, generation)
        self.assertEqual((m.state.calibration, m.state.zero_q8), (UNCALIBRATED, 0))
        self.assertEqual((m.state.state, m.state.confirmed), (UNAVAILABLE, 0))
        self.assertEqual(m.live_request.identity.key(), m.identity().key())
        self.assert_paint(m, GRAY)
        self.calibrate(m, shift=-1)
        fresh = self.focus(m, shift=-1)
        self.assertEqual(fresh.identity.key(), m.identity().key())
        self.assertLess(m.state.zero_q8, 0)
        self.assert_paint(m, GREEN)


if __name__ == "__main__":
    unittest.main()
