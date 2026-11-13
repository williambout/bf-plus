"""Continuous PAS software regressions against local, native BF 1.04 code.

Run: .venv/bin/python -B -m unittest tests.test_focus_capture -v

No USB/camera access, transport imports or shared build outputs. SVC results
and interrupt schedules are chosen test inputs; these tests do not simulate
kernel scheduling or establish hardware frame attribution/cache coherence.
See focus_capture_machine.py for the native/stub boundary. All frame offsets
and field sizes come from the compiled public header, never private structs.
"""

import struct
import tempfile
import unittest

from tests.focus_capture_machine import (
    AGE, CONFIG, COPY_TIME, DATA, EVENT, FIRST, GATE_SITE, GUARD, HEIGHT,
    IDENTITY, INVALIDATE, IRQ, IRQ_CALLBACK, IRQ_FAILED, ISLAND,
    IRQ_SITE, LEFT_TABLE, LENS, MAX_AGE, MAX_COPY, PAIR_SITE, PENDING, PROFILE,
    PROGRAM, PROGRAM_SITE, RECEIVER, REQUEST_CHANGED, RIGHT_TABLE, ROI, SCENE,
    SCENE_CHANGED, SELECTION, SEND, SEND_SITE, STACK, STACK_TOP, STRIDE, TORN,
    TRACK, WAIT, WAIT_FAILED, WIDTH, WRITER, BANKS, PLANE_BYTES,
    CaptureMachine, Identity, build_resident,
)


class FocusCaptureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="bf-continuous-pas-tests-")
        cls.addClassCleanup(cls.directory.cleanup)
        cls.resident = build_resident(cls.directory.name)

    def machine(self):
        m = CaptureMachine(self.resident)
        self.addCleanup(m.close)
        return m

    def take(self, m, reason=0):
        pointer = m.acquire()
        self.assertNotEqual(pointer, 0, "expected a published capture attempt")
        frame = m.frame(pointer)
        self.assertEqual((frame.guard_before, frame.guard_after), (GUARD, GUARD))
        self.assertEqual(frame.hardware_coherence_unproven, 1)
        self.assertEqual(frame.lifecycle_continuity_unproven, 1)
        self.assertEqual(m.status.hardware_coherence_unproven, 1)
        if reason:
            self.assertEqual(frame.software_checks_passed, 0)
            self.assertTrue(frame.reason & reason, f"reason {frame.reason:#x} lacks {reason:#x}")
        else:
            self.assertEqual(frame.reason, 0, f"unexpected rejection {frame.reason:#x}")
            self.assertEqual(frame.software_checks_passed, 1)
            self.assertGreater(frame.source_epoch, 0)
            self.assertGreater(frame.program_sequence, 0)
            self.assertGreater(frame.consume_sequence, 0)
        return pointer, frame

    def assert_no_raw_reads(self, m):
        self.assertEqual(m.raw_reads, [])
        self.assertEqual(m.invalidations, [])

    def test_continuous_captures_advance_actual_sensor_stamps_and_copy_owned_pixels(self):
        m = self.machine()
        m.request(epoch=37, after_ticks=m.tick - 10000)
        first_stamp = m.tick - 200
        self.assertEqual(m.receiver(1, stamp=first_stamp), 0)
        self.assertEqual(m.acquire(), 0)  # existing pending data was not observed
        self.assert_no_raw_reads(m)
        sequences, stamps, programs, consumes, epochs = [], [], [], [], []
        for token in range(2, 8):
            pending = m.read(PENDING, 0x158)
            expected_stamp = struct.unpack_from("<Q", pending, 0x10)[0]
            pair = struct.unpack_from("<2Q", pending, 0x138)
            m.paint_planes(token)
            expected_pixels = tuple(m.pixels(base) for base in pair)
            m.irq()
            self.assertEqual(m.receiver(token, stamp=m.tick - 73), 0)
            pointer, frame = self.take(m)
            self.assertEqual(frame.acquired_ticks, expected_stamp)
            self.assertEqual(frame.epoch, 37)
            self.assertEqual(frame.identity.key(), m.identity().key())
            self.assertEqual(frame.pixels, expected_pixels)
            self.assertEqual(frame.wait_results, (0, 0))
            self.assertEqual(frame.wait_flags, (1, 3))
            self.assertLess(frame.acquired_ticks, frame.copy_start_ticks)
            self.assertLessEqual(frame.copy_start_ticks, frame.copy_end_ticks)
            self.assertEqual(m.queue[-1][0x18:0x170], pending)
            self.assertEqual(m.status.last_acquired_ticks, expected_stamp)
            sequences.append(frame.sequence)
            stamps.append(frame.acquired_ticks)
            programs.append(frame.program_sequence)
            consumes.append(frame.consume_sequence)
            epochs.append(frame.source_epoch)
            frozen = m.held[pointer]
            m.paint_planes(token + 20)  # DMA RAM changes cannot change owned RAM
            self.assertEqual(m.read(pointer, len(frozen)), frozen)
            m.release(pointer)
        for values in (sequences, stamps, programs, consumes):
            self.assertTrue(all(a < b for a, b in zip(values, values[1:])), values)
        self.assertEqual(stamps[0], first_stamp)
        self.assertEqual(len(set(epochs)), 1)
        self.assertEqual((m.status.enabled, m.status.published, m.status.accepted,
                          m.status.rejected, m.status.dropped), (1, 6, 6, 0, 0))
        self.assertEqual(m.acquire(), 0)

    def test_native_invalidate_loop_precedes_each_exact_bounded_roi_read(self):
        m = self.machine()
        m.ready()
        pair = struct.unpack("<2Q", m.read(PENDING + 0x138, 16))
        m.receiver(2)
        self.take(m)
        expected_reads, expected_lines, expected_invalidations = [], [], []
        for base in pair:
            start = base + ROI
            aligned = start & ~63
            length = (start & 63) + (HEIGHT - 1) * STRIDE + WIDTH
            end = aligned + ((length + 63) & ~63)
            self.assertGreaterEqual(aligned, base)
            self.assertLessEqual(end, base + PLANE_BYTES)
            expected_invalidations.append((aligned, length))
            lines = list(range(aligned, end, 64))
            expected_lines.extend(lines)
            expected_reads.extend((start + row * STRIDE + x, 1)
                                  for row in range(HEIGHT) for x in range(WIDTH))
            self.assertLess(m.events.index(("dc", lines[-1], 64)),
                            m.events.index(("read", start, 1)))
        self.assertEqual(m.invalidations, expected_invalidations)
        self.assertEqual(m.dc, expected_lines)
        self.assertEqual(m.raw_reads, expected_reads)

    def test_hot_attach_inside_old_waits_does_not_permanently_poison_tracking(self):
        m = self.machine()
        m.request()
        sp = STACK + 0xe000
        for site, mask, mode, offset in ((GATE_SITE, 0x20000001, 1, 0x48),
                                         (PAIR_SITE, 3, 0x20, 0x4c)):
            args = (77, mask, mode, sp + offset)
            calls = len(m.native_calls)
            self.assertEqual(m.call_site(site, args, sp=sp), 0)
            self.assertEqual(m.native_calls[calls:], [(WAIT, args)])
        self.assertEqual(m.acquire(), 0)
        self.assert_no_raw_reads(m)
        m.receiver(1)
        m.irq()
        m.receiver(2)
        self.take(m)

    def test_disabled_adapter_forwards_originals_once_without_raw_reads(self):
        m = self.machine()
        m.receiver(1)
        m.irq([0x111] * 8)
        m.receiver(2)
        self.assertEqual(m.acquire(), 0)
        self.assertEqual(m.status.published, 0)
        self.assert_no_raw_reads(m)
        self.assertEqual([sum(pc == target for pc, _ in m.native_calls)
                          for target in (PROGRAM, WAIT, IRQ, SEND)], [2, 4, 1, 2])
        waits = [args for pc, args in m.native_calls if pc == WAIT]
        self.assertEqual([args[:3] for args in waits], [(77, 0x20000001, 1), (77, 3, 0x20)] * 2)
        self.assertEqual([args[3] for args in waits],
                         [STACK_TOP - 0x70 + 0x48, STACK_TOP - 0x70 + 0x4c] * 2)
        self.assertEqual(len(m.queue), 2)

    def test_held_mailbox_makes_producer_drop_without_overwrite_or_blocking(self):
        m = self.machine()
        m.ready()
        m.receiver(2)
        held, old = self.take(m)
        reads, invalidations = len(m.raw_reads), len(m.invalidations)
        for token in range(3, 8):
            m.paint_planes(token)
            m.irq()
            self.assertEqual(m.receiver(token), 0)
            self.assertEqual(m.acquire(), 0)
        self.assertEqual((m.status.accepted, m.status.dropped), (1, 5))
        self.assertEqual((len(m.raw_reads), len(m.invalidations)), (reads, invalidations))
        self.assertEqual(len(m.queue), 7)
        m.release(held)
        m.irq()
        m.receiver(8)
        replacement, frame = self.take(m)
        self.assertEqual(replacement, held)
        self.assertGreater(frame.acquired_ticks, old.acquired_ticks)
        self.assertEqual(m.status.dropped, 5)
        m.release(replacement)

    def test_ready_mailbox_overwrite_returns_latest_and_no_stale_frame(self):
        m = self.machine()
        m.ready()
        m.receiver(2)
        m.irq()
        expected_stamp = m.get(PENDING + 0x10)
        m.receiver(3)
        pointer, frame = self.take(m)
        self.assertEqual(frame.sequence, m.status.last_sequence)
        self.assertEqual(frame.acquired_ticks, expected_stamp)
        self.assertEqual(m.acquire(), 0)
        m.release(pointer)
        self.assertEqual(m.acquire(), 0, "older READY frame must not reappear")

    def test_unread_mailbox_keeps_latest_across_many_productions(self):
        m = self.machine()
        m.ready()
        m.receiver(2)
        for token in range(3, 9):
            m.irq()
            expected_stamp = m.get(PENDING + 0x10)
            m.paint_planes(token)
            m.receiver(token)
        _, frame = self.take(m)
        self.assertEqual(frame.acquired_ticks, expected_stamp)
        self.assertEqual(frame.sequence, m.status.last_sequence)
        self.assertEqual(m.status.dropped, 0)
        self.assertEqual(m.status.accepted, 7)

    def test_release_survives_irq_clearing_exclusive_monitor(self):
        m = self.machine()
        m.ready()
        m.receiver(2)
        first, _ = self.take(m)
        # An interrupt before the release store must not leave the slot owned
        # forever. This also catches release implemented with a one-shot CAS.
        m.before_atomic_store = lambda machine: machine.preempt_irq([1, 1])
        m.release(first)
        self.assertEqual([target for target, _ in m.preemptions], [IRQ_CALLBACK])
        m.irq()
        m.receiver(3)
        replacement, _ = self.take(m)
        self.assertEqual(replacement, first)
        self.assertEqual(m.status.dropped, 0)
        m.release(replacement)

    def test_ui_acquire_during_second_plane_copy_never_exposes_partial_frame(self):
        for older_ready in (False, True):
            with self.subTest(older_ready=older_ready), self.machine() as m:
                m.ready()
                if older_ready:
                    m.receiver(2)
                    old_sequence = m.status.last_sequence
                    m.irq()
                reads_before = len(m.raw_reads)
                acquired = []

                def during_copy(machine):
                    self.assertEqual(len(machine.raw_reads) - reads_before, WIDTH * HEIGHT)
                    machine.preempt("focus_capture_acquire", after=lambda p: acquired.append(machine.hold(p)))

                m.at(INVALIDATE, during_copy, occurrence=2)
                m.receiver(3 if older_ready else 2)
                self.assertEqual(len(acquired), 1)
                # Even when overwriting an older READY frame, the one mailbox
                # belongs to the producer throughout both planes of its copy.
                self.assertEqual(acquired[0], 0)
                pointer, frame = self.take(m)
                self.assertEqual(frame.sequence, m.status.last_sequence)
                self.assertNotEqual(pointer, acquired[0])
                if older_ready:
                    self.assertGreater(frame.sequence, old_sequence)

    def test_scene_lens_and_profile_changes_reject_before_any_raw_read(self):
        changes = {
            "scene mode": lambda m: m.put(0x4d70346a0, 3, 4),
            "scene tab": lambda m: m.put(0x4d70346a4, 13, 4),
            "scene handler": lambda m: m.put(SCENE + 16, 0),
            "electronic lens": lambda m: setattr(m, "lens_kind", 1),
            "second lens class": lambda m: setattr(m, "lens_kind", 2),
            "selected slot": lambda m: m.set_identity(slot=5),
            "first profile word": lambda m: m.set_identity(profile=(1, 0x90abcdef)),
            "second profile word": lambda m: m.set_identity(profile=(0x12345678, 2)),
        }
        for name, change in changes.items():
            with self.subTest(change=name), self.machine() as m:
                m.ready()
                change(m)
                m.receiver(2)
                self.take(m, SCENE_CHANGED)
                self.assert_no_raw_reads(m)
                self.assertEqual(len(m.queue), 2)

    def test_invalid_writer_configuration_rejects_before_raw_reads(self):
        changes = (("descriptor mode", WRITER + 8, 2, 4),
                   ("writer mode", 0x4d70342e4, 2, 4),
                   ("channel count", 0x4d72fba22, 8, 1),
                   ("pair1 stride", 0x4d72fba28, 512, 8),
                   ("pair2 stride", 0x4d72fba30, 1536, 8),
                   ("depth", WRITER + 0x39, 10, 1),
                   ("unmeasured width", WRITER + 0x30, 1513, 2),
                   ("unmeasured height", WRITER + 0x32, 333, 2),
                   ("secondary width", WRITER + 0x40, 505, 2),
                   ("secondary height", WRITER + 0x42, 335, 2),
                   ("secondary row bytes", WRITER + 0x44, 1024, 2),
                   ("secondary format", WRITER + 0x48, 13, 1),
                   ("secondary depth", WRITER + 0x49, 10, 1),
                   ("unmeasured sensor mode", 0x4d703459c, 3, 4),
                   ("unsupported sensor mode", 0x4d703459c, 13, 4),
                   ("event handle", EVENT, 78, 4))
        for name, address, value, size in changes:
            with self.subTest(change=name), self.machine() as m:
                m.ready()
                m.put(address, value, size)
                m.receiver(2)
                self.take(m, CONFIG)
                self.assert_no_raw_reads(m)

    def test_next_program_cannot_reuse_pending_source_in_either_pair(self):
        for which in (0, 1):
            with self.subTest(overlapping_pair=which+1), self.machine() as m:
                m.ready()
                pending_pair=tuple(struct.unpack('<2Q',m.read(PENDING+0x138,16)))
                # Ordinary selector arithmetic normally separates generations.
                # Deliberately reset it without a native FIRST marker: all
                # pointers remain individually legal, but the next writer
                # would reuse the exact plane about to be copied.
                m.put(0x4d72fba38,(BANKS.index(pending_pair)-which)%4,1)
                calls=len(m.native_calls)
                m.receiver(2)
                self.take(m,IDENTITY)
                self.assert_no_raw_reads(m)
                self.assertEqual([pc for pc,_ in m.native_calls[calls:]],
                                 [PROGRAM,WAIT,WAIT,SEND])
                self.assertEqual(len(m.queue),2)
                self.assertIn((SEND_SITE,m.send_rc),m.native_returns)

    def test_secondary_program_tuple_must_be_whitelisted_and_distinct(self):
        for change in ('alias primary','foreign left','foreign right'):
            with self.subTest(change=change), self.machine() as m:
                m.ready()

                def corrupt_next(machine):
                    primary=STACK_TOP-0x70+0x50
                    secondary=STACK_TOP-0x70+0x60
                    if change=='alias primary':
                        machine.uc.mem_write(secondary,machine.read(primary,16))
                    else:
                        machine.put(secondary+(8 if change=='foreign right' else 0),0xdeadbeef)

                m.at(PROGRAM_SITE,corrupt_next)
                m.receiver(2)
                self.take(m,IDENTITY)
                self.assert_no_raw_reads(m)
                self.assertEqual(len(m.queue),2)

    def test_pending_identity_and_nonadvancing_sensor_generations_reject_before_reads(self):
        for change in ("pointer", "descriptor", "pending stamp", "same stamp", "older stamp"):
            with self.subTest(change=change), self.machine() as m:
                m.ready()
                stamp = m.get(PENDING + 0x10)
                next_stamp = None
                if change == "pointer":
                    m.put(PENDING + 0x138, 0xdeadbeef)
                elif change == "descriptor":
                    m.put(PENDING + 0x28, 0xfeedface, 4)
                elif change == "pending stamp":
                    m.put(PENDING + 0x10, stamp + 1)
                else:
                    next_stamp = stamp if change == "same stamp" else stamp - 1
                m.receiver(2, stamp=next_stamp)
                self.take(m, TRACK if next_stamp is not None else IDENTITY)
                self.assert_no_raw_reads(m)

    def test_time_gates_reject_expired_and_future_samples_before_reads(self):
        for change in ("expired", "clock before acquisition", "program clock regressed", "zero stamp"):
            with self.subTest(change=change), self.machine() as m:
                m.request()
                m.receiver(1, stamp=0 if change == "zero stamp" else None)
                m.irq()
                old_stamp = m.get(PENDING + 0x10)
                next_stamp = None
                if change == "expired":
                    m.tick += MAX_AGE + 1
                elif change == "clock before acquisition":
                    m.at(SEND_SITE, lambda machine: setattr(machine, "tick", old_stamp - 1))
                elif change == "program clock regressed":
                    m.tick -= 100000
                    next_stamp = old_stamp + 1
                m.receiver(2, stamp=next_stamp)
                self.take(m, TRACK if change == "program clock regressed" else AGE)
                self.assert_no_raw_reads(m)

    def test_request_epoch_cutoff_and_identity_never_relabel_cached_sensor_frame(self):
        for change in ("epoch", "cutoff only", "identity"):
            with self.subTest(change=change), self.machine() as m:
                m.ready()
                old_identity = m.identity().key()
                old_stamp = m.get(PENDING + 0x10)
                epoch = 2 if change == "epoch" else 1
                if change == "identity":
                    m.set_identity(slot=5)
                cutoff = m.tick
                m.request(epoch=epoch, after_ticks=cutoff)
                m.receiver(2, stamp=cutoff)
                pointer, frame = self.take(m, REQUEST_CHANGED)
                self.assertEqual(frame.epoch, 1)
                self.assertEqual(frame.acquired_ticks, old_stamp)
                self.assertEqual(frame.identity.key(), old_identity)
                self.assert_no_raw_reads(m)
                m.release(pointer)
                m.irq()
                m.receiver(3)
                _, fresh = self.take(m)
                self.assertEqual(fresh.epoch, epoch)
                self.assertGreaterEqual(fresh.acquired_ticks, cutoff)
                self.assertEqual(fresh.identity.key(), m.identity().key())

    def test_failed_waits_keep_native_stale_outputs_and_submission_then_recover(self):
        for which in (0, 1):
            for result, normalized in ((-0x320001, 0xffffffcd), (7, 7)):
                with self.subTest(wait=which, result=result), self.machine() as m:
                    m.ready()
                    m.wait_results[which] = (result, None)
                    m.put(STACK_TOP - 0x70 + 0x48 + which * 4, (1, 3)[which], 4)
                    m.receiver(2)
                    pointer, frame = self.take(m, WAIT_FAILED)
                    self.assertEqual(frame.wait_results[which], normalized)
                    self.assertEqual(frame.wait_flags[which], (1, 3)[which])
                    self.assertIn(((GATE_SITE, PAIR_SITE)[which], normalized), m.native_returns)
                    self.assert_no_raw_reads(m)
                    self.assertEqual(len(m.queue), 2)
                    m.release(pointer)
                    m.wait_results = [(0, 1), (0, 3)]
                    m.irq()
                    m.receiver(3)
                    # A failed native wait breaks continuity. The next consume
                    # seeds a fresh boundary; it cannot certify the old window.
                    warmup, rejected = self.take(m, TRACK)
                    self.assert_no_raw_reads(m)
                    m.release(warmup)
                    m.irq()
                    m.receiver(4)
                    _, fresh = self.take(m)
                    self.assertGreater(fresh.source_epoch,rejected.source_epoch)

    def test_second_wait_stop_bit_rejects_even_with_clear_gate_and_native_send(self):
        m = self.machine()
        m.ready()
        m.wait_results = [(0, 1), (0, 0x20000003)]
        pending = m.read(PENDING, 0x158)
        m.receiver(2)
        _, frame = self.take(m, WAIT_FAILED)
        self.assertEqual(frame.wait_results, (0, 0))
        self.assertEqual(frame.wait_flags, (1, 0x20000003))
        self.assert_no_raw_reads(m)
        self.assertEqual(len(m.queue), 2)
        self.assertEqual(m.queue[-1][0x18:0x170], pending)
        self.assertIn((SEND_SITE, m.send_rc), m.native_returns)

    def test_missing_wait_bits_reject_despite_native_submission(self):
        for flags in ((0, 3), (1, 1), (1, 2)):
            with self.subTest(flags=flags), self.machine() as m:
                m.ready()
                m.wait_results = [(0, flags[0]), (0, flags[1])]
                m.receiver(2)
                self.take(m, WAIT_FAILED)
                self.assert_no_raw_reads(m)
                self.assertEqual(len(m.queue), 2)

    def test_successful_wait_flags_need_both_fresh_observed_pair_irqs(self):
        for words in ((), (1, 0), (0, 1), (0, 0, 1, 1)):
            with self.subTest(irq=words), self.machine() as m:
                m.request()
                m.receiver(1)
                if words:
                    m.irq(words)
                m.receiver(2)
                self.take(m, IRQ_FAILED)
                self.assert_no_raw_reads(m)

    def test_old_error_only_irq_is_not_erased_by_new_program_or_done_bits(self):
        for words in ((0x10, 0), (0, 0x100), (0x111, 1)):
            with self.subTest(irq=words), self.machine() as m:
                m.request()
                m.receiver(1)
                m.irq(words)
                m.irq()
                m.receiver(2)
                self.take(m, IRQ_FAILED)
                self.assert_no_raw_reads(m)
                self.assertTrue(m.logs, "native IRQ error logger must still execute")

    def test_error_in_overlap_or_during_copy_taints_both_intervals_then_recovers(self):
        for during_copy in (False, True):
            with self.subTest(during_copy=during_copy), self.machine() as m:
                m.ready()

                def inject(machine):
                    if during_copy:
                        self.assertEqual(len(machine.raw_reads), WIDTH * HEIGHT)
                    machine.preempt_irq([0, 0x100])

                m.at(INVALIDATE if during_copy else GATE_SITE, inject, occurrence=2 if during_copy else 1)
                m.receiver(2)
                pointer, _ = self.take(m, IRQ_FAILED)
                self.assertEqual(len(m.invalidations), 2 if during_copy else 0)
                self.assertEqual(len(m.preemptions), 1)
                m.release(pointer)
                reads = len(m.raw_reads)
                m.irq()
                m.receiver(3)
                pointer, _ = self.take(m, IRQ_FAILED)
                self.assertEqual(len(m.raw_reads), reads)
                m.release(pointer)
                m.irq()
                m.receiver(4)
                self.take(m)
                self.assertEqual(len(m.queue), 4)

    def test_done_irq_during_copy_preserves_explicit_unproven_hardware_status(self):
        m = self.machine()
        m.ready()
        m.at(INVALIDATE, lambda machine: machine.preempt_irq([1, 1]), occurrence=2)
        m.receiver(2)
        self.take(m)
        self.assertEqual(len(m.preemptions), 1)

    def test_overlapping_generations_cannot_share_old_completion_credit(self):
        m = self.machine()
        m.request()
        m.receiver(1)
        # G2 has already been programmed when A+B arrive for the consume of
        # G1. The same counters must not independently qualify both frames.
        m.at(GATE_SITE, lambda machine: machine.preempt_irq([1, 1]))
        m.receiver(2)
        pointer, first = self.take(m)
        m.release(pointer)
        reads = len(m.raw_reads)
        m.receiver(3)  # chosen successful flags, but no newly observed IRQ
        pointer, stale = self.take(m, IRQ_FAILED)
        self.assertGreater(stale.consume_sequence, first.consume_sequence)
        self.assertGreater(stale.program_sequence, first.program_sequence)
        self.assertEqual(len(m.raw_reads), reads)
        m.release(pointer)
        m.irq()
        m.receiver(4)
        self.take(m)

    def test_irq_between_kernel_consume_and_public_wait_return_is_not_next_credit(self):
        m = self.machine()
        m.ready()
        # The SVC leaf has already supplied the chosen success/flag word.
        # A reassertion here can remain latched for a later kernel wait, but
        # the adapter intentionally requires evidence AFTER this return.
        native_wait_ret = 0x4d3033830
        m.at(native_wait_ret, lambda machine: machine.preempt_irq([1, 1]), occurrence=2)
        m.receiver(2)
        pointer, _ = self.take(m)
        m.release(pointer)
        reads = len(m.raw_reads)
        m.receiver(3)
        self.take(m, IRQ_FAILED)
        self.assertEqual(len(m.raw_reads), reads)
        self.assertEqual(len(m.preemptions), 1)

    def test_failed_original_irq_event_set_cannot_supply_completion_evidence(self):
        for result in (7, 0xfffffff7):
            with self.subTest(event_set_result=result), self.machine() as m:
                m.request()
                m.receiver(1)
                m.event_rc = result
                m.irq()
                self.assertIn((IRQ_SITE, result), m.native_returns)
                self.assertEqual(len(m.event_sets), 1)
                m.receiver(2)
                self.take(m, IRQ_FAILED)
                self.assert_no_raw_reads(m)
                self.assertEqual(len(m.queue), 2)

    def test_irq_original_still_inflight_rejects_capture_before_raw_reads(self):
        m = self.machine()
        m.request()
        m.receiver(1)
        # The observer has entered, but the original native callback has not
        # set an event or returned. Model receiver/IRQ overlap on another task.
        m.at(IRQ, lambda machine: machine.preempt(RECEIVER, machine.prepare_receiver(2)))
        m.irq()
        self.assertEqual(len(m.preemptions), 1)
        self.take(m, IRQ_FAILED)
        self.assert_no_raw_reads(m)
        self.assertEqual(len(m.queue), 2)
        self.assertEqual(len(m.event_sets), 1, "original IRQ must still execute exactly once")

    def test_changes_during_copy_reject_publication_after_first_plane(self):
        changes = (
            ("scene", lambda m: m.put(SCENE, 0), SCENE_CHANGED),
            ("profile", lambda m: m.set_identity(profile=(0x12345678, 0)), SCENE_CHANGED),
            ("writer", lambda m: m.put(WRITER + 0x39, 10, 1), CONFIG),
            ("pending metadata", lambda m: m.put(PENDING + 0x28, 0xface, 4), TORN),
            ("native reinit", lambda m: m.put(FIRST, 1, 1), TORN),
            ("new request", lambda m: m.preempt("focus_capture_request", (m.prepare_request(epoch=2),)), REQUEST_CHANGED),
            ("disabled request", lambda m: m.preempt("focus_capture_request", (m.prepare_request(enabled=0),)), REQUEST_CHANGED),
            ("copy timeout", lambda m: setattr(m, "tick", m.tick + MAX_COPY + 1), COPY_TIME),
            ("backwards clock", lambda m: setattr(m, "tick", m.tick - 2 * m.tick_step), COPY_TIME),
            ("aged during copy", lambda m: setattr(m, "tick", m.tick + MAX_AGE + 1), AGE),
        )
        for name, change, reason in changes:
            with self.subTest(change=name), self.machine() as m:
                m.ready()

                def after_first_plane(machine):
                    self.assertEqual(len(machine.raw_reads), WIDTH * HEIGHT)
                    change(machine)

                m.at(INVALIDATE, after_first_plane, occurrence=2)
                m.receiver(2)
                self.take(m, reason)
                self.assertEqual(m.status.accepted, 0)
                self.assertEqual(m.status.rejected, 1)
                self.assertEqual(len(m.queue), 2)
                self.assertIn((SEND_SITE, m.send_rc), m.native_returns)

    def test_shutdown_during_copy_hides_pending_frame_and_cannot_reenable(self):
        m = self.machine()
        m.ready()
        m.receiver(2)
        # Leave the first accepted frame READY so the producer can overwrite
        # it. A held mailbox would drop before entering the copy at all.
        m.irq()
        m.at(INVALIDATE, lambda machine: machine.preempt("focus_capture_shutdown"), occurrence=2)
        m.receiver(3)
        self.assertEqual(m.status.enabled, 0)
        self.assertEqual(m.status.accepted, 1)
        self.assertTrue(m.status.last_reason & TORN)
        self.assertEqual(m.acquire(), 0, "shutdown gates acquisition, including queued records")
        published, reads = m.status.published, len(m.raw_reads)
        m.request(epoch=99)
        m.call("focus_sensor_enable_tables", 1)
        m.irq()
        m.receiver(4)
        self.assertEqual((m.status.enabled, m.status.published), (0, published))
        self.assertEqual(len(m.raw_reads), reads)
        self.assertEqual(m.acquire(), 0)
        self.assertEqual(len(m.queue), 4)

    def test_shutdown_keeps_already_held_frame_immutable_and_release_safe(self):
        m = self.machine()
        m.ready()
        m.receiver(2)
        held, _ = self.take(m)
        published, reads = m.status.published, len(m.raw_reads)
        m.call("focus_capture_shutdown")
        m.irq()
        m.receiver(3)
        self.assertEqual((m.status.enabled, m.status.published), (0, published))
        self.assertEqual(len(m.raw_reads), reads)
        self.assertEqual(m.acquire(), 0)
        m.release(held)  # lifetime remains valid through shutdown

    def test_shutdown_while_consumer_claims_slot_returns_no_frame(self):
        m = self.machine()
        m.ready()
        m.receiver(2)
        m.before_atomic_store = lambda machine: machine.preempt("focus_capture_shutdown")
        self.assertEqual(m.acquire(), 0)
        self.assertEqual(m.status.enabled, 0)
        self.assertEqual(len(m.preemptions), 1)

    def test_normal_reinitialization_changes_source_epoch_and_recovers_after_warmup(self):
        m = self.machine()
        m.ready()
        m.receiver(2)
        pointer, first = self.take(m)
        m.release(pointer)
        m.put(FIRST, 1, 1)
        m.receiver(3)  # native priming path does not wait or submit
        self.assertEqual(m.acquire(), 0)
        self.assertEqual(len(m.queue), 2)
        m.irq()
        m.receiver(4)  # first successful consume after reset establishes floor
        pointer, warmup = self.take(m, IRQ_FAILED)
        self.assertGreater(warmup.source_epoch, first.source_epoch)
        m.release(pointer)
        m.irq()
        m.receiver(5)
        _, frame = self.take(m)
        self.assertEqual(frame.epoch, first.epoch)
        self.assertEqual(frame.source_epoch, warmup.source_epoch)
        self.assertGreater(frame.sequence, first.sequence)
        self.assertGreater(frame.program_sequence, first.program_sequence)
        self.assertGreater(frame.consume_sequence, first.consume_sequence)
        self.assertEqual(m.status.enabled, 1)

    def test_transient_program_failure_taints_overlap_then_recovers_without_rearm(self):
        m = self.machine()
        m.ready()
        m.bank_rc = 0x42
        m.receiver(2)
        pointer, _ = self.take(m, TRACK)
        m.release(pointer)
        self.assert_no_raw_reads(m)
        m.bank_rc = 0
        m.irq()
        m.receiver(3)
        pointer, _ = self.take(m, TRACK)
        m.release(pointer)
        self.assert_no_raw_reads(m)
        m.irq()
        m.receiver(4)
        self.take(m)
        self.assertEqual(m.status.enabled, 1)

    def test_observation_gap_recovers_from_new_programming_without_resetting_resident(self):
        m = self.machine()
        m.ready()
        m.wait_index = 0
        sp = STACK + 0xe000
        m.call_site(GATE_SITE, (77, 0x20000001, 1, sp + 0x48), sp=sp)
        m.receiver(2)
        pointer, _ = self.take(m, TRACK)
        m.release(pointer)
        self.assert_no_raw_reads(m)
        m.irq()
        m.receiver(3)
        self.take(m)

    def test_gate_cancel_bypasses_consume_and_skip_consumes_without_submission(self):
        m = self.machine()
        m.ready()
        m.receiver(2, skip=1)  # sends G1, seeds skipped G2
        pointer, first = self.take(m)
        m.release(pointer)
        m.irq()
        m.receiver(3)  # G2 is consumed but not sent
        self.assertEqual(m.acquire(), 0)
        self.assertEqual(len(m.queue), 2)
        m.irq()
        m.receiver(4)
        pointer, after_skip = self.take(m)
        m.release(pointer)
        self.assertEqual(after_skip.sequence, first.sequence + 1)
        self.assertEqual(after_skip.program_sequence, first.program_sequence + 2)
        self.assertEqual(after_skip.consume_sequence, first.consume_sequence + 2)
        m.wait_results[0] = (0, 0x20000001)
        before = len(m.native_calls)
        m.receiver(5)
        self.assertEqual(len(m.queue), 3)
        self.assertEqual(sum(pc == WAIT for pc, _ in m.native_calls[before:]), 1)
        self.assertEqual(m.acquire(), 0)
        m.wait_results[0] = (0, 1)
        m.irq()
        m.receiver(6)
        warmup, rejected = self.take(m, TRACK)
        self.assertEqual(rejected.program_sequence, after_skip.program_sequence + 2)
        self.assertEqual(rejected.consume_sequence, after_skip.consume_sequence + 1)
        self.assertEqual(rejected.sequence, after_skip.sequence + 1)
        m.release(warmup)
        m.irq()
        m.receiver(7)
        _, after_gate = self.take(m)
        self.assertEqual(after_gate.program_sequence, after_skip.program_sequence + 3)
        self.assertEqual(after_gate.consume_sequence, after_skip.consume_sequence + 2)
        self.assertEqual(after_gate.sequence, after_skip.sequence + 2)
        self.assertGreater(after_gate.source_epoch,after_skip.source_epoch)

    def test_direct_native_arguments_returns_and_callee_saved_state_preserved(self):
        # Every run checks SP, platform x18, x19..x29 and d8..d15. Direct BL
        # execution sees returns that the full receiver immediately overwrites.
        for enabled in (False, True):
            for site, target, args, result in (
                (PROGRAM_SITE, PROGRAM, (DATA, DATA + 16, 0xabc, 0xdef), 0x42),
                (GATE_SITE, WAIT, (77, 0x20000001, 1, STACK + 0xe048), 0xffffffcd),
                (PAIR_SITE, WAIT, (77, 3, 0x20, STACK + 0xe04c), 0xffffffcd),
                (IRQ_SITE, IRQ, (DATA + 0x420, 0xabc, 0xdef, 0x123), 0x99),
                (SEND_SITE, SEND, (PENDING + 4, PENDING, 0, 0x123), 0xfffffff7),
            ):
                with self.subTest(enabled=enabled, site=hex(site)), self.machine() as m:
                    if enabled:
                        m.request()
                    m.uc.mem_write(DATA, struct.pack("<4Q", *BANKS[0], *BANKS[1]))
                    m.put(DATA + 0x420, 1, 4)
                    m.bank_rc, m.event_rc = 0x42, 0x99
                    m.wait_results = [(-0x320001, None)] * 2
                    self.assertEqual(m.call_site(site, args, sp=STACK + 0xe000), result)
                    self.assertEqual(m.native_calls, [(target, args)])
                    self.assert_no_raw_reads(m)

    def test_accepted_copy_preserves_original_sender_return_and_arguments(self):
        m = self.machine()
        m.ready()
        m.send_rc = 0x12345678
        pending = m.read(PENDING, 0x158)
        before = len(m.native_calls)
        self.assertEqual(m.receiver(2), 0)
        self.take(m)
        self.assertIn((SEND_SITE, m.send_rc), m.native_returns)
        self.assertEqual([pc for pc, _ in m.native_calls[before:]], [PROGRAM, WAIT, WAIT, SEND])
        args = next(args for pc, args in m.native_calls[before:] if pc == SEND)
        self.assertEqual(args[:3], (PENDING + 4, PENDING, 0))
        self.assertEqual(m.queue[-1][0x18:0x170], pending)

    def test_native_lens_getters_support_unregistered_slots_without_profile_reads(self):
        for slot in (4, 10, 0xffffffff):
            with self.subTest(slot=slot), self.machine() as m:
                m.set_identity(slot=slot)
                output = DATA + 0xa00
                self.assertEqual(m.call("focus_sensor_context", output), 1)
                self.assertEqual(Identity.from_buffer_copy(m.read(output, 12)).key(), m.identity().key())
                self.assertIn(LENS, m.getter_calls)
                self.assertIn(SELECTION, m.getter_calls)
                self.assertEqual(PROFILE in m.getter_calls, slot < 10)
                m.ready()
                m.receiver(2)
                _, frame = self.take(m)
                self.assertEqual(frame.identity.key(), m.identity().key())

    def test_profile_change_between_native_getters_rejects_context(self):
        m = self.machine()
        output = DATA + 0xa00
        m.uc.mem_write(output, b"\xa5" * 12)
        m.at(PROFILE, lambda machine: machine.set_identity(profile=(1, 2)), occurrence=2)
        self.assertEqual(m.call("focus_sensor_context", output), 0)
        self.assertEqual(m.read(output, 12), b"\xa5" * 12)

    def test_table_enable_and_profile_passthrough_remain_separate_from_capture(self):
        m = self.machine()
        output = DATA + 0xa00
        m.run(ISLAND, (4, output, 0xdeadbeef))
        self.assertEqual(m.read(output, 8), struct.pack("<2I", *m.identity().profile))
        self.assert_no_raw_reads(m)
        for enabled, shutdown in ((False, False), (True, False), (True, True)):
            with self.subTest(enabled=enabled, shutdown=shutdown):
                if shutdown:
                    m.call("focus_capture_shutdown")
                m.call("focus_sensor_enable_tables", int(enabled))
                m.uc.mem_write(LEFT_TABLE - 16, b"\xa5" * (1024 + 32))
                m.put(STACK_TOP + 0x90, LEFT_TABLE)
                m.put(STACK_TOP + 0x98, RIGHT_TABLE)
                m.run(0x4d32ca038, stop=0x4d32ca058)
                expected = b"\x00\x10" * 512 if enabled and not shutdown else bytes(1024)
                self.assertEqual(m.read(LEFT_TABLE, 1024), expected)
                self.assertEqual(m.read(LEFT_TABLE - 16, 16), b"\xa5" * 16)
                self.assertEqual(m.read(RIGHT_TABLE + 512, 16), b"\xa5" * 16)


if __name__ == "__main__":
    unittest.main()
