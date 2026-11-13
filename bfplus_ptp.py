"""Small, single-attempt Sigma BF PTP RAM transport (firmware 1.04).

Usage::

    from bfplus_ptp import PTP, CALLBACK_SLOT, ORIGINAL_CALLBACK
    with PTP() as p:
        raw = p.read(address, size)       # 1..0x4000 bytes
        value = p.qword(address)          # little-endian uint64
        if p.qword(CALLBACK_SLOT) != ORIGINAL_CALLBACK:
            raise RuntimeError("unexpected storage callback")
        p.write(destination, blob)        # 1..0x4000 bytes, returns None

Callback checks, firmware checks, trigger policy, and readback verification
belong to the caller. write() performs no hidden callback reads: this permits
an explicitly checked callback trigger and recovery policy. An OK response
does NOT establish completion of the camera's asynchronous copy/save worker.
Every vendor write can cause a calibration flash save, even when targeting RAM.

One context exclusively locks <workspace>/.touch-focus/transport.lock. All
participating processes must use the same state_dir (the default is beside
this module); older tools do not honor this lock. cooldown.json is atomically
persisted before submission, including attempts that fail, and writes wait at
least ten seconds after the preceding attempt. Never delete this state to skip
a cooldown. The parent CLI must ignore .touch-focus/ in version control.

No device access occurs on import or construction. __enter__ finds/claims the
configured PTP interface and opens a session, accepting SessionAlreadyOpen.
Only a session opened here is closed on normal, synchronized cleanup. There
are no automatic retries, resets, endpoint drains, or clear-halt operations.
"""

import fcntl
import json
import math
import os
from pathlib import Path
import struct
import tempfile
import threading
import time

import usb.core
import usb.util

from live_stage import BASE, CALLBACK_SLOT, ORIGINAL_CALLBACK, PID, VID

HEADER = struct.Struct("<IHHI")
COMMAND, DATA, RESPONSE = 1, 2, 3
OPEN_SESSION, CLOSE_SESSION = 0x1002, 0x1003
READ, WRITE = 0x900B, 0x900A
OK, SESSION_ALREADY_OPEN = 0x2001, 0x201E
MAX_READ = MAX_WRITE = 0x4000
COOLDOWN = 10.0
CALIBRATION_SIZE = 0x10000
BASE_SLOT = 0x4D7301A00
DEFAULT_STATE_DIR = Path(__file__).resolve().parent / ".touch-focus"


class PTPError(Exception):
    """Base exception for transport, protocol, session, and local-state errors."""


class TransportError(PTPError):
    """USB transfer failed or was short; transaction outcome may be unknown."""


class ProtocolError(PTPError):
    """Unexpected PTP framing or transaction identity; stop using this context."""


class ResponseError(PTPError):
    """The camera returned a complete, correctly framed error response."""

    def __init__(self, operation, tid, code, parameters=()):
        self.operation, self.tid, self.code = operation, tid, code
        self.parameters = parameters
        super().__init__(f"PTP operation 0x{operation:04x}, TID {tid}: "
                         f"response 0x{code:04x}, parameters={parameters}")


class StateError(PTPError):
    """Context or cooldown state does not permit an operation."""


class BusyError(StateError):
    """Another cooperating transport context holds the workspace lock."""


class PTP:
    def __init__(self, *, device=None, state_dir=None, timeout_ms=8000):
        """device is an optional PyUSB-compatible test double/preselected device."""
        if type(timeout_ms) is not int or timeout_ms <= 0:
            raise ValueError("timeout_ms must be a positive integer")
        self.state_dir = Path(state_dir) if state_dir is not None else DEFAULT_STATE_DIR
        self.timeout_ms = timeout_ms
        self._device = device
        self._device_accessed = False
        self._lock_file = None
        self._io_lock = threading.RLock()
        self._claimed = self._opened = self._owned_session = self._broken = False
        self._used = False
        self._rx = bytearray()
        self._next_tid = 0

    def __enter__(self):
        with self._io_lock:
            if self._used:
                raise StateError("PTP contexts are single-use; construct a new PTP()")
            self._used = True
            self._pid = os.getpid()
            try:
                self.state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
                self._lock_file = (self.state_dir / "transport.lock").open("a+b")
                try:
                    fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError as exc:
                    raise BusyError(f"PTP transport already in use: {self.state_dir}") from exc
                if self._device is None:
                    self._device = usb.core.find(idVendor=VID, idProduct=PID)
                if self._device is None:
                    raise TransportError(f"Sigma BF MTP device {VID:04x}:{PID:04x} not found")
                self._device_accessed = True
                interface = self._device.get_active_configuration()[(0, 0)]
                self._interface = interface.bInterfaceNumber
                bulk = [ep for ep in interface if ep.bmAttributes & 3 == 2]
                outs = [ep for ep in bulk if ep.bEndpointAddress & 0x80 == 0]
                ins = [ep for ep in bulk if ep.bEndpointAddress & 0x80]
                if len(outs) != 1 or len(ins) != 1:
                    raise TransportError("PTP interface must have one bulk IN and one bulk OUT endpoint")
                self._out, self._in = outs[0].bEndpointAddress, ins[0].bEndpointAddress
                usb.util.claim_interface(self._device, self._interface)
                self._claimed = True
                status, _ = self._exchange(OPEN_SESSION, (1,), accepted=(OK, SESSION_ALREADY_OPEN))
                self._owned_session = status == OK
                self._opened = True
                return self
            except BaseException as exc:
                self._cleanup(exc)
                if isinstance(exc, usb.core.USBError):
                    raise TransportError(f"Cannot claim/open BF PTP interface: {exc}") from exc
                if isinstance(exc, OSError):
                    raise StateError(f"Cannot initialize PTP workspace state {self.state_dir}: {exc}") from exc
                raise

    def __exit__(self, exc_type, exc, traceback):
        with self._io_lock:
            cleanup_error = None
            try:
                if self._opened and self._owned_session and not self._broken:
                    self._exchange(CLOSE_SESSION)
            except BaseException as error:
                cleanup_error = error
            finally:
                self._opened = False
                self._cleanup(exc or cleanup_error)
            if cleanup_error is not None:
                if exc is None:
                    raise cleanup_error
                exc.add_note(f"PTP session cleanup also failed: {cleanup_error}")
        return False

    def _cleanup(self, original_error=None):
        errors = []
        if self._claimed:
            try:
                usb.util.release_interface(self._device, self._interface)
            except Exception as exc:
                errors.append(exc)
            self._claimed = False
        if self._device_accessed:
            try:
                usb.util.dispose_resources(self._device)
            except Exception as exc:
                errors.append(exc)
            self._device_accessed = False
        if self._lock_file is not None:
            self._lock_file.close()  # Closing releases flock, including on failure.
            self._lock_file = None
        if errors:
            detail = f"PTP resource cleanup failed: {errors!r}"
            if original_error is not None:
                original_error.add_note(detail)
            else:
                raise TransportError(detail) from errors[0]

    def _require_open(self):
        if not self._opened or self._broken:
            raise StateError("PTP context is not open or lost synchronization; no automatic recovery")
        if os.getpid() != self._pid:
            raise StateError("PTP contexts cannot be shared across a fork")

    @staticmethod
    def _range(addr, length, writing=False):
        limit = MAX_WRITE if writing else MAX_READ
        if type(addr) is not int or type(length) is not int:
            raise ValueError("address and length must be integers")
        if not 1 <= length <= limit:
            raise ValueError(f"{'write' if writing else 'read'} length must be 1..0x{limit:x}")
        if addr < BASE or addr - BASE + length > 0x100000000:
            raise ValueError(f"address range must fit unsigned 32-bit offsets from BASE=0x{BASE:x}")
        if writing:
            for start, end, name in ((BASE, BASE + CALIBRATION_SIZE, "calibration block"),
                                     (BASE_SLOT, BASE_SLOT + 8, "adjustment-base pointer")):
                if addr < end and addr + length > start:
                    raise ValueError(f"write overlaps protected {name} at 0x{start:x}..0x{end:x}")
        return addr - BASE

    def read(self, addr, n):
        """Read exactly n bytes; reject oversized reads rather than chunking."""
        offset = self._range(addr, n)
        with self._io_lock:
            self._require_open()
            _, data = self._exchange(READ, (offset, n), expected_data=n)
            return data

    def qword(self, addr):
        """Read one little-endian unsigned 64-bit value."""
        return struct.unpack("<Q", self.read(addr, 8))[0]

    def write(self, addr, payload):
        """Submit exactly once, with persisted cooldown; caller checks callback."""
        if not isinstance(payload, (bytes, bytearray, memoryview)):
            raise TypeError("payload must be bytes, bytearray, or memoryview")
        payload = bytes(payload)
        offset = self._range(addr, len(payload), writing=True)
        with self._io_lock:
            self._require_open()
            self._wait_for_write()
            self._stamp_write()  # Durable reservation even if command submission fails.
            try:
                self._exchange(WRITE, (offset, len(payload)), outgoing=payload)
            except BaseException as exc:
                try:
                    self._stamp_write()
                except Exception as state_exc:
                    self._broken = True
                    exc.add_note(f"Could not extend persisted write cooldown: {state_exc}")
                raise
            else:
                try:
                    self._stamp_write()  # Also wait ten seconds after a slow response.
                except BaseException:
                    self._broken = True
                    raise

    def _wait_for_write(self):
        path = self.state_dir / "cooldown.json"
        try:
            with path.open() as stream:
                state = json.load(stream)
        except FileNotFoundError:
            return
        except (OSError, ValueError) as exc:
            raise StateError(f"Cannot read cooldown state {path}; refusing write: {exc}") from exc
        try:
            wall, mono = state["wall_time"], state["monotonic_time"]
            if type(state["version"]) is not int or state["version"] != 1 or any(
                    type(t) not in (int, float) or not math.isfinite(t) or t < 0
                                            for t in (wall, mono)):
                raise ValueError("invalid version or timestamps")
        except (KeyError, TypeError, ValueError) as exc:
            raise StateError(f"Invalid cooldown state {path}; refusing write") from exc
        # Use the more conservative clock. A clock rollback/reboot costs a full
        # cooldown, rather than skipping it or waiting until a distant date.
        elapsed = max(0.0, min(time.time() - wall, time.monotonic() - mono))
        deadline = time.monotonic() + max(0.0, COOLDOWN - elapsed)
        while (remaining := deadline - time.monotonic()) > 0:
            time.sleep(min(remaining, COOLDOWN))

    def _stamp_write(self):
        path = self.state_dir / "cooldown.json"
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", dir=self.state_dir,
                                             prefix=".cooldown-", delete=False) as stream:
                temporary = stream.name
                json.dump({"version": 1, "wall_time": time.time(),
                           "monotonic_time": time.monotonic()}, stream, allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            directory = os.open(self.state_dir, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        except (OSError, ValueError) as exc:
            raise StateError(f"Cannot persist cooldown state {path}; refusing further submission: {exc}") from exc
        finally:
            if temporary is not None and os.path.exists(temporary):
                os.unlink(temporary)

    @staticmethod
    def _timeout(deadline):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TransportError("PTP transaction deadline exceeded; no retry was made")
        return max(1, math.ceil(remaining * 1000))

    def _send(self, raw, deadline):
        sent = self._device.write(self._out, raw, timeout=self._timeout(deadline))
        if sent != len(raw):
            raise TransportError(f"Short USB write: {sent!r}/{len(raw)} bytes; no retry was made")

    def _receive(self, operation, tid, expected_data, deadline):
        while len(self._rx) < HEADER.size:
            self._read_usb(deadline)
        size, kind, code, actual_tid = HEADER.unpack_from(self._rx)
        if size < HEADER.size:
            raise ProtocolError(f"Invalid PTP container size {size}; minimum is {HEADER.size}")
        if actual_tid != tid:
            raise ProtocolError(f"Wrong PTP TID {actual_tid}; expected {tid} for 0x{operation:04x}")
        if kind == DATA:
            if code != operation:
                raise ProtocolError(f"Wrong data operation 0x{code:04x}; expected 0x{operation:04x}")
            if expected_data is None or size != HEADER.size + expected_data:
                raise ProtocolError(f"Unexpected PTP data length {size - HEADER.size}; expected {expected_data}")
        elif kind == RESPONSE:
            if not (0x2000 <= code <= 0x2FFF or 0xA000 <= code <= 0xAFFF):
                raise ProtocolError(f"Invalid PTP response code 0x{code:04x}")
            if size > HEADER.size + 20 or (size - HEADER.size) % 4:
                raise ProtocolError(f"Invalid PTP response size {size}")
        else:
            raise ProtocolError(f"Unexpected PTP container type {kind}")
        while len(self._rx) < size:
            self._read_usb(deadline)
        payload = bytes(self._rx[HEADER.size:size])
        del self._rx[:size]  # Preserve a coalesced response or partial next header.
        return kind, code, payload

    def _read_usb(self, deadline):
        chunk = bytes(self._device.read(self._in, 0x8000, timeout=self._timeout(deadline)))
        if not chunk or len(chunk) > 0x8000:
            raise TransportError(f"Invalid USB read length {len(chunk)}; no retry was made")
        self._rx.extend(chunk)

    def _exchange(self, operation, params=(), *, outgoing=None, expected_data=None, accepted=(OK,)):
        tid = self._next_tid
        if tid > 0xFFFFFFFF:
            raise StateError("PTP transaction IDs exhausted; open a new context")
        self._next_tid += 1
        deadline = time.monotonic() + (30.0 if outgoing is not None else self.timeout_ms / 1000)
        try:
            if self._rx:
                raise ProtocolError("Unconsumed PTP bytes before next command; refusing submission")
            command = HEADER.pack(HEADER.size + 4 * len(params), COMMAND, operation, tid)
            self._send(command + struct.pack(f"<{len(params)}I", *params), deadline)
            if outgoing is not None:
                self._stamp_write()  # Reserve again just before the data phase.
                self._send(HEADER.pack(HEADER.size + len(outgoing), DATA, operation, tid) + outgoing, deadline)
            kind, status, data = self._receive(operation, tid, expected_data, deadline)
            received = None
            if kind == DATA:
                received = data
                kind, status, data = self._receive(operation, tid, None, deadline)
            parameters = struct.unpack(f"<{len(data) // 4}I", data)
            if status not in accepted:
                raise ResponseError(operation, tid, status, parameters)
            if expected_data is not None and received is None:
                raise ProtocolError(f"Missing data phase for 0x{operation:04x}, TID {tid}")
            return status, received
        except ResponseError:
            raise
        except BaseException as exc:
            self._broken = True
            if isinstance(exc, usb.core.USBError):
                raise TransportError(f"USB failure during 0x{operation:04x}, TID {tid}; "
                                     f"no retry was made: {exc}") from exc
            raise
