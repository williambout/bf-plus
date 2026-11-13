"""Offline transport tests. No USB discovery or camera operations are allowed.

Run: .venv/bin/python -m unittest discover -s tests -p test_touch_ptp.py -v
"""

from collections import deque
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import usb.core

import bf_touch_ptp as ptp


ADDRESS = 0x447581000  # Representative heap staging address, never accessed.


def frame(kind, code, tid, payload=b""):
    return ptp.HEADER.pack(12 + len(payload), kind, code, tid) + payload


def response(tid, code=ptp.OK, parameters=()):
    return frame(ptp.RESPONSE, code, tid, struct.pack(f"<{len(parameters)}I", *parameters))


def data(tid, payload, code=ptp.READ):
    return frame(ptp.DATA, code, tid, payload)


class FakeClock:
    def __init__(self, wall=1000.0, mono=500.0):
        self.wall, self.mono = wall, mono
        self.sleeps = []

    def time(self):
        return self.wall

    def monotonic(self):
        return self.mono

    def sleep(self, seconds):
        if not 0 < seconds <= ptp.COOLDOWN:
            raise AssertionError(f"Unexpected sleep: {seconds}")
        self.sleeps.append(seconds)
        self.advance(seconds)

    def advance(self, seconds):
        self.wall += seconds
        self.mono += seconds


class FakeEndpoint:
    def __init__(self, address, attributes=2):
        self.bEndpointAddress = address
        self.bmAttributes = attributes


class FakeInterface(list):
    bInterfaceNumber = 0

    def __init__(self):
        super().__init__([FakeEndpoint(0x01), FakeEndpoint(0x81), FakeEndpoint(0x82, 3)])


class FakeUSB:
    def __init__(self, incoming=(), *, open_status=ptp.SESSION_ALREADY_OPEN):
        self.incoming = deque([response(0, open_status), *incoming])
        self.writes = []
        self.read_calls = []
        self.fail_write = {}
        self.on_write = None
        self.on_read = None
        self.interface = FakeInterface()
        self.close_status = ptp.OK

    def get_active_configuration(self):
        return {(0, 0): self.interface}

    def write(self, endpoint, raw, timeout):
        assert endpoint == 1 and timeout > 0
        raw = bytes(raw)
        self.writes.append(raw)
        if self.on_write is not None:
            self.on_write(raw)
        action = self.fail_write.get(len(self.writes))
        if isinstance(action, BaseException):
            raise action
        if action is not None:
            return action
        _, kind, operation, tid = ptp.HEADER.unpack_from(raw)
        if kind == ptp.COMMAND and operation == ptp.CLOSE_SESSION:
            self.incoming.append(response(tid, self.close_status))
        return len(raw)

    def read(self, endpoint, size, timeout):
        assert endpoint == 0x81 and size == 0x8000 and timeout > 0
        self.read_calls.append((size, timeout))
        if self.on_read is not None:
            self.on_read()
        if not self.incoming:
            raise AssertionError("Transport unexpectedly requested another USB read")
        result = self.incoming.popleft()
        if isinstance(result, BaseException):
            raise result
        assert len(result) <= size
        return result

    def reset(self):
        raise AssertionError("Device reset is forbidden")

    def clear_halt(self, *args):
        raise AssertionError("Automatic clear-halt is forbidden")

    def commands(self, operation=None):
        return [raw for raw in self.writes
                if ptp.HEADER.unpack_from(raw)[1] == ptp.COMMAND
                and (operation is None or ptp.HEADER.unpack_from(raw)[2] == operation)]


class PTPTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.clock = FakeClock()
        self.claim = self.patch(ptp.usb.util, "claim_interface")
        self.release = self.patch(ptp.usb.util, "release_interface")
        self.dispose = self.patch(ptp.usb.util, "dispose_resources")
        self.find = self.patch(ptp.usb.core, "find", side_effect=AssertionError("Physical USB discovery forbidden"))
        for name in ("time", "monotonic", "sleep"):
            self.patch(ptp.time, name, side_effect=getattr(self.clock, name))

    def patch(self, target, name, **kwargs):
        patcher = mock.patch.object(target, name, **kwargs)
        self.addCleanup(patcher.stop)
        return patcher.start()

    def connect(self, device, **kwargs):
        return ptp.PTP(device=device, state_dir=self.directory, **kwargs)

    def state(self):
        return json.loads((self.directory / "cooldown.json").read_text())

    def test_constructor_does_not_access_usb_or_filesystem(self):
        ptp.PTP(state_dir=self.directory / "not-created")
        self.find.assert_not_called()
        self.assertFalse((self.directory / "not-created").exists())

    def test_discovery_uses_existing_vid_pid(self):
        device = FakeUSB()
        self.find.side_effect = None
        self.find.return_value = device
        with ptp.PTP(state_dir=self.directory):
            pass
        self.find.assert_called_once_with(idVendor=ptp.VID, idProduct=ptp.PID)

    def test_missing_device_releases_lock(self):
        self.find.side_effect = None
        self.find.return_value = None
        with self.assertRaisesRegex(ptp.TransportError, "not found"):
            with ptp.PTP(state_dir=self.directory):
                self.fail("Device missing")
        with self.connect(FakeUSB()):
            pass

    def test_borrowed_session_is_not_closed(self):
        device = FakeUSB()
        with self.connect(device):
            pass
        self.assertEqual(len(device.commands()), 1)
        self.claim.assert_called_once_with(device, 0)
        self.release.assert_called_once_with(device, 0)
        self.dispose.assert_called_once_with(device)

    def test_owned_session_is_closed(self):
        device = FakeUSB(open_status=ptp.OK)
        with self.connect(device):
            pass
        self.assertEqual(len(device.commands(ptp.CLOSE_SESSION)), 1)

    def test_open_error_fails_and_cleans_up(self):
        device = FakeUSB(open_status=0x2005)
        with self.assertRaises(ptp.ResponseError) as caught:
            with self.connect(device):
                self.fail("OpenSession should fail")
        self.assertEqual((caught.exception.operation, caught.exception.code, caught.exception.tid),
                         (ptp.OPEN_SESSION, 0x2005, 0))
        self.release.assert_called_once_with(device, 0)
        with self.connect(FakeUSB()):
            pass

    def test_bad_open_tid_is_rejected(self):
        device = FakeUSB()
        device.incoming[0] = response(9)
        with self.assertRaisesRegex(ptp.ProtocolError, "TID"):
            with self.connect(device):
                pass

    def test_missing_bulk_endpoint_fails_before_claim(self):
        device = FakeUSB()
        device.interface.pop(1)
        with self.assertRaisesRegex(ptp.TransportError, "bulk"):
            with self.connect(device):
                pass
        self.claim.assert_not_called()
        self.assertFalse(device.writes)

    def test_coalesced_data_and_response(self):
        device = FakeUSB([data(1, b"abcd") + response(1)])
        with self.connect(device) as camera:
            self.assertEqual(camera.read(ADDRESS, 4), b"abcd")
        self.assertEqual(len(device.read_calls), 2)
        raw = device.commands(ptp.READ)[0]
        self.assertEqual(ptp.HEADER.unpack_from(raw), (20, ptp.COMMAND, ptp.READ, 1))
        self.assertEqual(struct.unpack_from("<II", raw, 12), (ADDRESS - ptp.BASE, 4))

    def test_split_header_body_and_coalesced_partial_response(self):
        packet = data(1, b"hello") + response(1)
        chunks = [packet[:3], packet[3:9], packet[9:14], packet[14:21], packet[21:]]
        device = FakeUSB(chunks)
        with self.connect(device) as camera:
            self.assertEqual(camera.read(ADDRESS, 5), b"hello")

    def test_one_byte_fragments(self):
        packet = data(1, b"abc") + response(1)
        device = FakeUSB([packet[i:i + 1] for i in range(len(packet))])
        with self.connect(device) as camera:
            self.assertEqual(camera.read(ADDRESS, 3), b"abc")

    def test_qword(self):
        device = FakeUSB([data(1, struct.pack("<Q", ptp.ORIGINAL_CALLBACK)) + response(1)])
        with self.connect(device) as camera:
            self.assertEqual(camera.qword(ptp.CALLBACK_SLOT), ptp.ORIGINAL_CALLBACK)

    def test_max_read_and_last_offset(self):
        payload = bytes(ptp.MAX_READ)
        device = FakeUSB([data(1, payload) + response(1), data(2, b"x") + response(2)])
        with self.connect(device) as camera:
            self.assertEqual(camera.read(ADDRESS, ptp.MAX_READ), payload)
            self.assertEqual(camera.read(ptp.BASE + 0xFFFFFFFF, 1), b"x")
        self.assertEqual(struct.unpack_from("<II", device.commands(ptp.READ)[1], 12), (0xFFFFFFFF, 1))

    def test_invalid_read_ranges_submit_nothing(self):
        device = FakeUSB()
        with self.connect(device) as camera:
            for addr, size in ((ptp.BASE - 1, 1), (ptp.BASE + 0xFFFFFFFF, 2),
                               (ptp.BASE + 0x100000000, 1), (ADDRESS, 0),
                               (ADDRESS, -1), (ADDRESS, ptp.MAX_READ + 1),
                               (ADDRESS, True), (True, 1), (ADDRESS, 1.5)):
                with self.subTest(addr=addr, size=size), self.assertRaises(ValueError):
                    camera.read(addr, size)
        self.assertFalse(device.commands(ptp.READ))

    def test_malformed_frames_poison_context(self):
        cases = {
            "data TID": data(2, b"abcd"),
            "response TID": response(2),
            "data operation": data(1, b"abcd", code=ptp.WRITE),
            "response operation code": frame(ptp.RESPONSE, ptp.READ, 1),
            "type": frame(4, ptp.READ, 1),
            "short size": ptp.HEADER.pack(11, ptp.DATA, ptp.READ, 1),
            "huge size": ptp.HEADER.pack(0xFFFFFFFF, ptp.DATA, ptp.READ, 1),
            "short data": data(1, b"abc"),
            "long data": data(1, b"abcde"),
            "missing data": response(1),
            "duplicate data": data(1, b"abcd") + data(1, b"abcd"),
            "unaligned response": frame(ptp.RESPONSE, ptp.OK, 1, b"x"),
            "long response": frame(ptp.RESPONSE, ptp.OK, 1, bytes(24)),
        }
        for label, packet in cases.items():
            with self.subTest(label=label):
                device = FakeUSB([packet], open_status=ptp.OK)
                with self.connect(device) as camera:
                    with self.assertRaises(ptp.ProtocolError):
                        camera.read(ADDRESS, 4)
                    with self.assertRaises(ptp.StateError):
                        camera.read(ADDRESS, 4)
                self.assertEqual(len(device.commands(ptp.READ)), 1)
                self.assertFalse(device.commands(ptp.CLOSE_SESSION))

    def test_error_response_without_data_is_useful_and_keeps_sync(self):
        device = FakeUSB([response(1, 0x2002, (42,)), data(2, b"ok") + response(2)])
        with self.connect(device) as camera:
            with self.assertRaises(ptp.ResponseError) as caught:
                camera.read(ADDRESS, 2)
            self.assertEqual(caught.exception.parameters, (42,))
            self.assertEqual(caught.exception.code, 0x2002)
            self.assertIn("0x900b", str(caught.exception))
            self.assertEqual(camera.read(ADDRESS, 2), b"ok")

    def test_error_after_data_is_not_returned_as_success(self):
        device = FakeUSB([data(1, b"abcd") + response(1, 0x2019)])
        with self.connect(device) as camera:
            with self.assertRaises(ptp.ResponseError):
                camera.read(ADDRESS, 4)

    def test_trailing_bytes_prevent_next_submission(self):
        device = FakeUSB([data(1, b"a") + response(1) + b"junk"])
        with self.connect(device) as camera:
            self.assertEqual(camera.read(ADDRESS, 1), b"a")
            with self.assertRaisesRegex(ptp.ProtocolError, "Unconsumed"):
                camera.read(ADDRESS, 1)
        self.assertEqual(len(device.commands(ptp.READ)), 1)

    def test_truncated_frame_usb_failure_has_no_retry(self):
        device = FakeUSB([data(1, b"abcd")[:14], usb.core.USBTimeoutError("timed out")])
        with self.connect(device) as camera:
            with self.assertRaisesRegex(ptp.TransportError, "no retry"):
                camera.read(ADDRESS, 4)
        self.assertEqual(len(device.commands(ptp.READ)), 1)

    def test_empty_usb_read_has_no_retry(self):
        device = FakeUSB([b""])
        with self.connect(device) as camera:
            with self.assertRaises(ptp.TransportError):
                camera.read(ADDRESS, 1)
        self.assertEqual(len(device.read_calls), 2)

    def test_deadline_covers_all_fragments(self):
        device = FakeUSB([b"\x10", b"\0", b"\0"])
        with self.connect(device, timeout_ms=1000) as camera:
            device.on_read = lambda: self.clock.advance(0.6)
            with self.assertRaisesRegex(ptp.TransportError, "deadline"):
                camera.read(ADDRESS, 4)
        self.assertEqual(len(device.read_calls), 3)  # Open plus two fragments.

    def test_allowed_payload_trigger_and_config_writes(self):
        payload = bytes(0x1700)
        device = FakeUSB([response(1), response(2), response(3)])
        requests = [(ADDRESS, payload), (ptp.CALLBACK_SLOT, struct.pack("<Q", ADDRESS)),
                    (ADDRESS + 0x2000, struct.pack("<I", 1))]
        with self.connect(device) as camera:
            for addr, blob in requests:
                self.assertIsNone(camera.write(addr, blob))
        commands = device.commands(ptp.WRITE)
        self.assertEqual(len(commands), 3)
        self.assertFalse(device.commands(ptp.READ))  # Explicit caller callback policy.
        for command, (addr, blob) in zip(commands, requests):
            self.assertEqual(struct.unpack_from("<II", command, 12), (addr - ptp.BASE, len(blob)))
        self.assertEqual([raw[12:] for raw in device.writes if ptp.HEADER.unpack_from(raw)[1] == ptp.DATA],
                         [blob for _, blob in requests])
        self.assertEqual(self.clock.sleeps, [10.0, 10.0])

    def test_calibration_and_base_pointer_write_overlap_blocked(self):
        device = FakeUSB([response(1)])
        with self.connect(device) as camera:
            for addr, size in ((ptp.BASE, 1), (ptp.BASE + 0xFFFF, 2),
                               (ptp.BASE + 0x8000, 4), (ptp.BASE_SLOT - 1, 2),
                               (ptp.BASE_SLOT, 8), (ptp.BASE_SLOT + 7, 2)):
                with self.subTest(addr=addr), self.assertRaisesRegex(ValueError, "protected"):
                    camera.write(addr, bytes(size))
            self.assertFalse((self.directory / "cooldown.json").exists())
            camera.write(ptp.BASE + ptp.CALIBRATION_SIZE, b"x")
        self.assertEqual(len(device.commands(ptp.WRITE)), 1)

    def test_invalid_write_inputs_do_not_submit_or_reserve(self):
        device = FakeUSB()
        with self.connect(device) as camera:
            for addr, blob in ((ADDRESS, b""), (ADDRESS, bytes(ptp.MAX_WRITE + 1)),
                               (ptp.BASE - 1, b"x"), (ptp.BASE + 0xFFFFFFFF, b"xx")):
                with self.assertRaises(ValueError):
                    camera.write(addr, blob)
            for payload in (4, "abc", [1, 2]):
                with self.assertRaises(TypeError):
                    camera.write(ADDRESS, payload)
        self.assertFalse(device.commands(ptp.WRITE))
        self.assertFalse((self.directory / "cooldown.json").exists())

    def test_write_failures_are_not_retried_and_always_reserve_cooldown(self):
        cases = [(2, usb.core.USBError("command failed")), (2, 1),
                 (3, usb.core.USBTimeoutError("data failed")), (3, 1)]
        for index, failure in cases:
            with self.subTest(index=index, failure=failure):
                device = FakeUSB()
                device.fail_write[index] = failure
                reserved = []
                with self.connect(device) as camera:
                    device.on_write = lambda raw: reserved.append(self.state()["wall_time"])
                    with self.assertRaisesRegex(ptp.TransportError, "no retry"):
                        camera.write(ADDRESS, b"test")
                    with self.assertRaises(ptp.StateError):
                        camera.write(ADDRESS, b"test")
                self.assertEqual(len(device.commands(ptp.WRITE)), 1)
                self.assertEqual(len(device.writes), index)
                self.assertTrue(reserved)
                self.assertEqual(self.state()["wall_time"], self.clock.wall)

    def test_write_response_status_is_not_retried(self):
        device = FakeUSB([response(1, 0x2019)])
        with self.connect(device) as camera:
            with self.assertRaises(ptp.ResponseError):
                camera.write(ADDRESS, b"test")
        self.assertEqual(len(device.writes), 3)
        self.assertEqual(self.state()["wall_time"], self.clock.wall)

    def test_write_response_timeout_is_not_retried(self):
        device = FakeUSB([usb.core.USBTimeoutError("response timed out")])
        with self.connect(device) as camera:
            with self.assertRaises(ptp.TransportError):
                camera.write(ADDRESS, b"test")
        self.assertEqual(len(device.writes), 3)
        self.assertEqual(self.state()["wall_time"], self.clock.wall)

    def test_write_does_not_accept_data_response(self):
        device = FakeUSB([data(1, b"test", ptp.WRITE)])
        with self.connect(device) as camera:
            with self.assertRaises(ptp.ProtocolError):
                camera.write(ADDRESS, b"test")

    def test_failed_write_cooldown_survives_new_context(self):
        device = FakeUSB()
        device.fail_write[2] = usb.core.USBError("lost command")
        with self.connect(device) as camera:
            with self.assertRaises(ptp.TransportError):
                camera.write(ADDRESS, b"test")
        first = self.state()["wall_time"]
        self.clock.advance(3)
        with self.connect(FakeUSB([response(1)])) as camera:
            camera.write(ADDRESS, b"next")
        self.assertEqual(self.clock.sleeps, [7.0])
        self.assertGreaterEqual(self.state()["wall_time"] - first, 10)

    def test_cooldown_starts_after_slow_write_response(self):
        device = FakeUSB([response(1), response(2)])
        with self.connect(device) as camera:
            device.on_read = lambda: self.clock.advance(8)
            camera.write(ADDRESS, b"test")
            self.assertEqual(self.state()["wall_time"], 1008)
            device.on_read = None
            camera.write(ADDRESS, b"next")
        self.assertEqual(self.clock.sleeps, [10.0])

    def test_bad_cooldown_state_fails_closed(self):
        for content in ("bad json", "{}", "[]", "null",
                        '{"version":1,"wall_time":NaN,"monotonic_time":500}',
                        '{"version":1,"wall_time":1000,"monotonic_time":-1}'):
            with self.subTest(content=content):
                (self.directory / "cooldown.json").write_text(content)
                device = FakeUSB()
                with self.connect(device) as camera:
                    with self.assertRaises(ptp.StateError):
                        camera.write(ADDRESS, b"test")
                self.assertFalse(device.commands(ptp.WRITE))

    def test_persistence_failure_prevents_write_submission(self):
        device = FakeUSB()
        with self.connect(device) as camera:
            with mock.patch.object(ptp.os, "replace", side_effect=OSError("disk full")):
                with self.assertRaisesRegex(ptp.StateError, "persist"):
                    camera.write(ADDRESS, b"test")
        self.assertFalse(device.commands(ptp.WRITE))
        self.assertFalse(list(self.directory.glob(".cooldown-*")))

    def test_failed_data_phase_reservation_prevents_data_submission(self):
        device = FakeUSB()
        with self.connect(device) as camera:
            original = camera._stamp_write
            calls = 0

            def stamp():
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise ptp.StateError("data reservation failed")
                original()

            with mock.patch.object(camera, "_stamp_write", side_effect=stamp):
                with self.assertRaisesRegex(ptp.StateError, "data reservation"):
                    camera.write(ADDRESS, b"test")
                with self.assertRaises(ptp.StateError):
                    camera.write(ADDRESS, b"next")
        self.assertEqual(len(device.writes), 2)  # Open and one vendor command, no data.

    def test_failed_completion_stamp_stops_further_operations(self):
        device = FakeUSB([response(1)])
        with self.connect(device) as camera:
            original = camera._stamp_write
            calls = 0

            def stamp():
                nonlocal calls
                calls += 1
                if calls == 3:
                    raise ptp.StateError("completion reservation failed")
                original()

            with mock.patch.object(camera, "_stamp_write", side_effect=stamp):
                with self.assertRaisesRegex(ptp.StateError, "completion reservation"):
                    camera.write(ADDRESS, b"test")
                with self.assertRaises(ptp.StateError):
                    camera.write(ADDRESS, b"next")
        self.assertEqual(len(device.commands(ptp.WRITE)), 1)

    def test_forward_wall_jump_cannot_skip_monotonic_cooldown(self):
        with self.connect(FakeUSB([response(1)])) as camera:
            camera.write(ADDRESS, b"test")
        self.clock.wall += 10000
        with self.connect(FakeUSB([response(1)])) as camera:
            camera.write(ADDRESS, b"test")
        self.assertEqual(self.clock.sleeps, [10.0])

    def test_backward_clock_costs_one_bounded_cooldown(self):
        with self.connect(FakeUSB([response(1)])) as camera:
            camera.write(ADDRESS, b"test")
        self.clock.wall -= 100
        self.clock.mono -= 100
        with self.connect(FakeUSB([response(1)])) as camera:
            camera.write(ADDRESS, b"test")
        self.assertEqual(self.clock.sleeps, [10.0])

    def test_workspace_lock_excludes_another_context(self):
        device = FakeUSB()
        with self.connect(device):
            with self.assertRaises(ptp.BusyError):
                with self.connect(device):
                    self.fail("Second context acquired lock")
            self.dispose.assert_not_called()  # Failed contender must not touch the active device.
            self.release.assert_not_called()
        with self.connect(FakeUSB()):
            pass

    def test_lock_is_visible_to_another_process(self):
        script = """
import fcntl, sys
with open(sys.argv[1], 'a+b') as stream:
    try:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print('locked')
    else:
        print('available')
"""
        def check():
            return subprocess.check_output([sys.executable, "-c", script,
                                            str(self.directory / "transport.lock")], text=True).strip()
        with self.connect(FakeUSB()):
            self.assertEqual(check(), "locked")
        self.assertEqual(check(), "available")

    def test_cooldown_is_used_by_another_process(self):
        with self.connect(FakeUSB([response(1)])) as camera:
            camera.write(ADDRESS, b"test")
        # The child also uses ONLY fake USB and fake time; it must observe the
        # parent's durable reservation and wait the seven remaining seconds.
        script = """
import json, sys
from unittest import mock
sys.path.insert(0, 'tests')
from test_touch_ptp import FakeUSB, FakeClock, ADDRESS, response, ptp
clock = FakeClock(wall=1003, mono=503)
with mock.patch.object(ptp.usb.core, 'find', side_effect=AssertionError('no real USB')), \
     mock.patch.object(ptp.usb.util, 'claim_interface'), \
     mock.patch.object(ptp.usb.util, 'release_interface'), \
     mock.patch.object(ptp.usb.util, 'dispose_resources'), \
     mock.patch.object(ptp.time, 'time', clock.time), \
     mock.patch.object(ptp.time, 'monotonic', clock.monotonic), \
     mock.patch.object(ptp.time, 'sleep', clock.sleep):
    with ptp.PTP(device=FakeUSB([response(1)]), state_dir=sys.argv[1]) as camera:
        camera.write(ADDRESS, b'next')
print(json.dumps(clock.sleeps))
"""
        output = subprocess.check_output([sys.executable, "-c", script, str(self.directory)],
                                         cwd=Path(ptp.__file__).parent, text=True)
        self.assertEqual(json.loads(output), [7.0])
        self.assertEqual(self.state()["wall_time"], 1010)

    def test_close_failure_does_not_mask_caller_exception(self):
        device = FakeUSB(open_status=ptp.OK)
        device.close_status = 0x2002
        with self.assertRaisesRegex(ValueError, "caller") as caught:
            with self.connect(device):
                raise ValueError("caller error")
        self.assertIn("cleanup also failed", " ".join(caught.exception.__notes__))
        self.release.assert_called_once()

    def test_context_is_single_use_and_methods_require_open(self):
        camera = self.connect(FakeUSB())
        with self.assertRaises(ptp.StateError):
            camera.read(ADDRESS, 1)
        with camera:
            pass
        with self.assertRaises(ptp.StateError):
            camera.qword(ADDRESS)
        with self.assertRaises(ptp.StateError):
            with camera:
                pass


if __name__ == "__main__":
    unittest.main()
