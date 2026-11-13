"""Single-attempt segmented loader helpers. Importing this module accesses no USB.

Pass an already-open bfplus_ptp.PTP context. Its process lock, reentrant I/O
lock and persisted write cooldown remain authoritative. Parent supplies target
and hook checks and durable phase recording; no legacy installer is imported.
"""
from dataclasses import asdict, dataclass, field, replace
import copy
import hashlib
import secrets
import struct
import time
from types import MappingProxyType
import zlib

ABI = 1
CONTROL_MAGIC = 0x313044414f4c4642
GUARD_MAGIC = 0x3130304452474642
CONTROL_BYTES = GUARD_BYTES = 256
TRANSFER_MAX = 0x4000
# Maximum-size transfers lost framing and left a command header in resident RAM.
# Keep actual segmented transactions at 4 KiB; the staging hard cap stays 16 KiB.
READ_MAX = 0x1000
WRITE_MAX = 0x1000
MEMORY_MAX = 0x10000
SCRATCH_MAX = 0x1000000
PORTRAIT_SCRATCH = 0x155000
STAGE_OFFSET = 0xc000
TRANSPORT_BYTES = 0x10080
RAM_MIN, RAM_END = 0x400d20c00, 0x500000000
CALLBACK, ORIGINAL = 0x4d729bd00, 0x4d31254f0
L2_SLOT, L2_RO = 0x4d71484c8, 0x4d3200781
PREPARE, COMMIT, REMOVE = 1, 2, 3
EMPTY, PREPARING, COMMITTING, COMMITTED, REMOVING, REMOVED, FAILED = range(7)
FORMAT = 'bfplus-segmented-v1'
LAUNCH_PREFIX = bytes.fromhex(
    '090000102a1140912b003bd56b4d50d38c0080d28b21cb9a297a0bd529010b8b'
    '3f010aeba3ffff549f3b03d51f7108d59f3b03d5df3f03d532000014')
CONTROL = struct.Struct('<QIIQQ4I8Q4I4Q32s2Q6Q')
GUARD = struct.Struct('<QII7QII32sQQI31I')


class LoaderError(RuntimeError):
    """Fail closed. This API never retries a write or uncertain command."""


def require(condition, message):
    if not condition:
        raise LoaderError(message)


@dataclass(frozen=True)
class Control:
    magic: int = CONTROL_MAGIC
    abi_version: int = ABI
    struct_size: int = CONTROL_BYTES
    request_nonce: int = 0
    done: int = 0
    command: int = PREPARE
    mode: int = 0
    result: int = 0
    storage_rc: int = 0
    identity_nonce: int = 0
    owner: int = 0
    resident: int = 0
    guard: int = 0
    image_size: int = 0
    memory_size: int = 0
    scratch_size: int = 0
    entry_offset: int = 0
    image_crc32: int = 0
    phase: int = EMPTY
    entry_result: int = 0
    reserved0: int = 0
    el: int = 0
    ctr: int = 0
    mair: int = 0
    tcr: int = 0
    image_sha256: bytes = bytes(32)
    transport_buffer: int = 0
    allocation_size: int = 0
    reserved: tuple = (0,)*6

    def pack(self):
        d = asdict(self)
        require(len(self.image_sha256) == 32 and len(self.reserved) == 6, 'Invalid control arrays')
        values = [v for k, v in d.items() if k != 'reserved']
        return CONTROL.pack(*values, *self.reserved)

    @classmethod
    def unpack(cls, raw):
        require(len(raw) == CONTROL_BYTES, 'Short loader control read')
        values = CONTROL.unpack(raw)
        return cls(*values[:28], tuple(values[28:]))


def _layout(image_size, memory_size, scratch_size, entry_offset, mode=0):
    require(all(type(v) is int for v in (image_size, memory_size, scratch_size, entry_offset, mode)),
            'Layout fields must be integers')
    require(4 <= image_size <= memory_size <= MEMORY_MAX and memory_size % 64 == 0,
            'Require 4 <= image <= memory <= 0x10000 and 64-byte memory alignment')
    require(0 <= scratch_size <= SCRATCH_MAX and scratch_size % 64 == 0,
            'Scratch must be 64-byte aligned and at most 16 MiB')
    require(0 <= entry_offset <= image_size-4 and entry_offset % 4 == 0,
            'Resident entry must be an aligned instruction inside initialized bytes')
    require(mode in (0, 1), 'Unsupported resident mode')


@dataclass(frozen=True)
class ResidentImage:
    image: bytes
    memory_size: int
    entry_offset: int
    scratch_size: int = PORTRAIT_SCRATCH
    expected_sha256: str | None = None

    def __post_init__(self):
        require(isinstance(self.image, (bytes, bytearray, memoryview)), 'Resident image must be bytes')
        object.__setattr__(self, 'image', bytes(self.image))
        _layout(len(self.image), self.memory_size, self.scratch_size, self.entry_offset)
        if self.expected_sha256 is not None:
            require(self.expected_sha256 == self.sha256, 'Resident artifact SHA-256 mismatch')

    @property
    def sha256(self):
        return hashlib.sha256(self.image).hexdigest()

    @property
    def crc32(self):
        return zlib.crc32(self.image)


@dataclass(frozen=True)
class LoaderArtifact:
    image: bytes
    symbols: dict
    expected_sha256: str | None = None

    def __post_init__(self):
        object.__setattr__(self, 'image', bytes(self.image))
        object.__setattr__(self, 'symbols', MappingProxyType(dict(self.symbols)))
        s = self.symbols
        require(0 < len(self.image) <= TRANSFER_MAX and self.image.startswith(LAUNCH_PREFIX),
                'Unsupported loader size or fixed launcher prefix')
        require(s.get('launch') == 0 and s.get('bootstrap') == 0x100 and
                s.get('__image_end') == len(self.image) and s.get('__end') == len(self.image),
                'Loader symbol extents differ from immutable artifact')
        offset = s.get('loader_control', -1)
        require(type(offset) is int and 0x100 <= offset <= len(self.image)-CONTROL_BYTES and offset % 64 == 0,
                'Invalid separate loader control offset')
        require(not any(self.image[offset:offset+CONTROL_BYTES]), 'Loader artifact already has live control')
        if self.expected_sha256 is not None:
            require(self.expected_sha256 == self.sha256, 'Loader artifact SHA-256 mismatch')

    @property
    def sha256(self):
        return hashlib.sha256(self.image).hexdigest()


@dataclass(frozen=True)
class Checks:
    # preflight(p, command, record) returns the current read-buffer address.
    # It must verify target fingerprints and exact original/installed hook state.
    check_callback: object
    idle: object
    preflight: object

    def __post_init__(self):
        require(all(callable(f) for f in (self.check_callback, self.idle, self.preflight)),
                'All parent verification callbacks are required')


@dataclass(frozen=True)
class Poll:
    timeout: float = 15.0
    interval: float = 0.2

    def __post_init__(self):
        require(0 < self.interval <= 1 and self.interval <= self.timeout <= 60, 'Invalid read-only polling bounds')


@dataclass
class Prepared:
    """Returned by prepare(); there is deliberately no manifest-resume API."""
    artifact: LoaderArtifact
    package: ResidentImage
    control: Control
    phase: str
    _transport: object = field(repr=False)
    _lock_file: object = field(repr=False)


def _read(p, address, size):
    require(0 < size <= TRANSFER_MAX, 'Read exceeds transport cap')
    chunks = []
    for offset in range(0, size, READ_MAX):
        count = min(READ_MAX, size-offset)
        raw = bytes(p.read(address+offset, count))
        require(len(raw) == count, 'Inexact transport read; no retry')
        chunks.append(raw)
    return b''.join(chunks)


def _qword(p, address):
    return struct.unpack('<Q', _read(p, address, 8))[0]


def _callback(p, checks):
    checks.check_callback(p)
    require(_qword(p, CALLBACK) == ORIGINAL, 'Storage callback is not restored; no retry')


def _open(p):
    # The existing PTP context owns the process flock throughout its lifetime.
    # Its RLock also serializes this complete multi-transfer operation against
    # other threads using the same transport. Nested p.read/write are reentrant.
    require(hasattr(p, '_io_lock') and getattr(p, '_lock_file', None) is not None,
            'Use the shared, already-open bfplus_ptp.PTP transport context')
    p._require_open()


def _nonce(*used):
    for _ in range(16):
        n = secrets.randbits(64)
        if n and n not in used:
            return n
    raise LoaderError('Unable to obtain a fresh command nonce')


def _record(artifact, package, control, phase, **extra):
    fields = asdict(control)
    fields['image_sha256'] = control.image_sha256.hex()
    return {'format': FORMAT, 'abi_version': ABI, 'phase': phase,
            'loader_sha256': artifact.sha256, 'resident_sha256': package.sha256,
            'control': fields, **extra}


def _emit(on_phase, record):
    require(callable(on_phase), 'A durable manifest-phase callback is required')
    on_phase(copy.deepcopy(record))


def _uncertain(on_phase, record, error):
    try:
        _emit(on_phase, {**record, 'phase': 'uncertain', 'error': str(error)})
    except BaseException as persistence_error:
        error.add_note(f'Could not persist uncertain phase: {persistence_error}')


def _allocation(c):
    _layout(c.image_size, c.memory_size, c.scratch_size, c.entry_offset, c.mode)
    n = GUARD_BYTES+4095+c.memory_size+c.scratch_size
    require(c.allocation_size == n and RAM_MIN <= c.owner <= RAM_END-n, 'Invalid guarded allocation extent')
    base = (c.owner+GUARD_BYTES+4095) & ~4095
    require(c.resident == base and c.guard == base-GUARD_BYTES and
            base+c.memory_size+c.scratch_size <= c.owner+n, 'Invalid resident/guard alignment')
    for start, end in ((c.transport_buffer, c.transport_buffer+TRANSPORT_BYTES),
                       (0x4d3000000, 0x4d7400000)):
        require(not (c.owner < end and start < c.owner+n), 'Allocation overlaps protected transport/firmware')


def _guard(p, c, phase):
    _allocation(c)
    g = GUARD.unpack(_read(p, c.guard, GUARD_BYTES))
    expected = (GUARD_MAGIC, ABI, phase, c.identity_nonce, c.owner, c.resident,
                c.image_size, c.memory_size, c.scratch_size, c.entry_offset,
                c.image_crc32, c.mode, c.image_sha256, c.allocation_size, c.request_nonce, 0)
    require(g[:16] == expected and not any(g[16:]), 'Guard identity, nonce, extents or phase mismatch')


def _readback(p, address, expected, poll):
    deadline = time.monotonic()+poll.timeout
    while True:
        if _read(p, address, len(expected)) == expected:
            return
        require(time.monotonic() < deadline, 'Exact readback failed; no rewrite or trigger retry')
        time.sleep(poll.interval)


def _full_image(p, c, package):
    actual = b''.join(_read(p, c.resident+i, min(READ_MAX, c.image_size-i))
                      for i in range(0, c.image_size, READ_MAX))
    require(actual == package.image and hashlib.sha256(actual).hexdigest() == package.sha256 and
            zlib.crc32(actual) == c.image_crc32, 'Complete resident readback/hash mismatch; no commit')


def _command(p, artifact, package, c, checks, on_phase, phase_name, poll):
    record = _record(artifact, package, c, phase_name)
    _callback(p, checks)
    checks.idle(p)
    buf = checks.preflight(p, c.command, copy.deepcopy(record))
    require(type(buf) is int and RAM_MIN <= buf <= RAM_END-TRANSPORT_BYTES and buf % 4096 == 0,
            'Invalid transport read-buffer allocation')
    c = replace(c, transport_buffer=buf)
    if c.command != PREPARE:
        _allocation(c)
    stage = buf+STAGE_OFFSET
    record = _record(artifact, package, c, phase_name, stage=stage)
    _emit(on_phase, record)  # Must persist intent before the first write.
    data = bytearray(artifact.image)
    offset = artifact.symbols['loader_control']
    data[offset:offset+CONTROL_BYTES] = c.pack()
    try:
        for start in range(0, len(data), WRITE_MAX):
            _callback(p, checks)
            p.write(stage+start, bytes(data[start:start+WRITE_MAX]))
        _readback(p, stage, data, poll)
        _callback(p, checks)
        checks.idle(p)
        # This uses the SAME PTP.write cooldown/lock as every resident chunk.
        p.write(CALLBACK, struct.pack('<Q', stage))
        deadline = time.monotonic()+poll.timeout
        while True:
            result = Control.unpack(_read(p, stage+offset, CONTROL_BYTES))
            if result.done == c.request_nonce:
                break
            require(time.monotonic() < deadline, 'No fresh completion nonce; outcome uncertain, no retry')
            time.sleep(poll.interval)
        _callback(p, checks)
        require(_qword(p, L2_SLOT) == L2_RO, 'L2 permissions not restored; no retry')
        record = _record(artifact, package, result, phase_name, stage=stage)
        # Device output may change only these fields, plus allocation outputs on PREPARE.
        allowed = {'owner', 'resident', 'guard', 'allocation_size'} if c.command == PREPARE else set()
        allowed |= {'done', 'result', 'storage_rc', 'phase', 'entry_result', 'el', 'ctr', 'mair', 'tcr'}
        require(all(getattr(c, k) == getattr(result, k) for k in asdict(c) if k not in allowed),
                'Loader completion identity differs from command')
        require(result.storage_rc == 0, f'Storage writer failed ({result.storage_rc:#x}); outcome uncertain')
        require(result.result == 0 and result.entry_result == 0,
                f'Loader stopped: result={result.result}, resident={result.entry_result}; no retry')
        expected_phase = {PREPARE: PREPARING, COMMIT: COMMITTED, REMOVE: REMOVED}[c.command]
        require(result.phase == expected_phase and result.el == 4, 'Unexpected completion phase/EL')
        _guard(p, result, expected_phase)
        final_name = {PREPARE: 'prepared', COMMIT: 'committed', REMOVE: 'removed'}[c.command]
        final_record = _record(artifact, package, result, final_name, stage=stage)
        require(checks.preflight(p, c.command, copy.deepcopy(final_record)) == buf,
                'Postcondition verification changed the transport allocation')
        return result
    except BaseException as error:
        error.loader_record = record
        _uncertain(on_phase, record, error)
        raise


def prepare(p, artifact, package, *, checks, on_phase, mode=0, poll=Poll()):
    """Allocate an unreferenced region. Never resume this capability from disk."""
    _layout(len(package.image), package.memory_size, package.scratch_size, package.entry_offset, mode)
    with p._io_lock:
        _open(p)
        nonce = _nonce()
        c = Control(request_nonce=nonce, identity_nonce=nonce, mode=mode,
                    image_size=len(package.image), memory_size=package.memory_size,
                    scratch_size=package.scratch_size, entry_offset=package.entry_offset,
                    image_crc32=package.crc32, image_sha256=bytes.fromhex(package.sha256))
        c = _command(p, artifact, package, c, checks, on_phase, 'preparing', poll)
        session = Prepared(artifact, package, c, 'prepared', p, p._lock_file)
        record = _record(artifact, package, c, 'prepared')
        try:
            _emit(on_phase, record)
        except BaseException as error:
            session.phase = 'uncertain'
            _uncertain(on_phase, record, error)
            raise
        return session


def _session(p, session, required):
    _open(p)
    require(isinstance(session, Prepared) and session._transport is p and
            session._lock_file is p._lock_file and session.phase == required,
            'Stale, interrupted, reused or cross-session allocation; do not resume')


def load(p, session, *, checks, on_phase, poll=Poll()):
    """Write every initialized byte once, in order; verify each chunk and full identity."""
    with p._io_lock:
        _session(p, session, 'prepared')
        c, artifact, package = session.control, session.artifact, session.package
        session.phase = 'loading'
        record = _record(artifact, package, c, 'loading', written=0)
        try:
            _callback(p, checks)
            checks.idle(p)
            require(checks.preflight(p, COMMIT, copy.deepcopy(record)) == c.transport_buffer,
                    'Transport allocation changed during loading')
            for offset in range(0, len(package.image), WRITE_MAX):
                _guard(p, c, PREPARING)
                _callback(p, checks)
                chunk = package.image[offset:offset+WRITE_MAX]
                record = _record(artifact, package, c, 'loading', written=offset,
                                 next_offset=offset, next_size=len(chunk))
                _emit(on_phase, record)
                p.write(c.resident+offset, chunk)
                _readback(p, c.resident+offset, chunk, poll)
                _callback(p, checks)
            _guard(p, c, PREPARING)
            _full_image(p, c, package)
            session.phase = 'verified'
            _emit(on_phase, _record(artifact, package, c, 'verified', written=len(package.image)))
            return session
        except BaseException as error:
            session.phase = 'uncertain'
            _uncertain(on_phase, getattr(error, 'loader_record', record), error)
            raise


def commit(p, session, *, checks, on_phase, poll=Poll()):
    with p._io_lock:
        _session(p, session, 'verified')
        c, artifact, package = session.control, session.artifact, session.package
        record = _record(artifact, package, c, 'committing')
        session.phase = 'committing'
        try:
            _callback(p, checks)
            _guard(p, c, PREPARING)
            _full_image(p, c, package)  # Recheck after any caller work since load().
            c = replace(c, command=COMMIT, request_nonce=_nonce(c.identity_nonce, c.request_nonce),
                        done=0, result=0, storage_rc=0, entry_result=0)
            c = _command(p, artifact, package, c, checks, on_phase, 'committing', poll)
            session.control, session.phase = c, 'committed'
            record = _record(artifact, package, c, 'committed')
            _emit(on_phase, record)
            return record
        except BaseException as error:
            session.phase = 'uncertain'
            _uncertain(on_phase, getattr(error, 'loader_record', record), error)
            raise


def execute(p, artifact, package, *, checks, on_phase, mode=0, poll=Poll()):
    """Complete PREPARE -> load/readback -> COMMIT in one transport lock scope."""
    with p._io_lock:
        session = prepare(p, artifact, package, checks=checks, on_phase=on_phase, mode=mode, poll=poll)
        load(p, session, checks=checks, on_phase=on_phase, poll=poll)
        return commit(p, session, checks=checks, on_phase=on_phase, poll=poll)


def remove(p, artifact, package, record, *, checks, on_phase, poll=Poll()):
    """Call the exact installed resident's remover; never reupload or free it.

    Legacy records are intentionally rejected for routing to the parent's
    preserved legacy remover. preflight must validate the exact installed
    hook manifest/state/code identity, not merely firmware fingerprints.
    """
    require(record.get('format') == FORMAT and record.get('abi_version') == ABI,
            'Not a segmented-v1 record; use the exact legacy removal path')
    require(record.get('phase') == 'committed', 'Installation completion uncertain; inspect, do not retry')
    require(record.get('loader_sha256') == artifact.sha256 and record.get('resident_sha256') == package.sha256,
            'Removal requires the exact immutable loader and resident artifacts')
    fields = dict(record['control'])
    fields['image_sha256'] = bytes.fromhex(fields['image_sha256'])
    fields['reserved'] = tuple(fields['reserved'])
    c = Control(**fields)
    require((c.image_size, c.memory_size, c.scratch_size, c.entry_offset, c.image_crc32, c.image_sha256) ==
            (len(package.image), package.memory_size, package.scratch_size, package.entry_offset,
             package.crc32, bytes.fromhex(package.sha256)), 'Saved resident layout/identity mismatch')
    with p._io_lock:
        _open(p)
        _callback(p, checks)
        _guard(p, c, COMMITTED)
        c = replace(c, command=REMOVE, phase=COMMITTED,
                    request_nonce=_nonce(c.identity_nonce, c.request_nonce), done=0,
                    result=0, storage_rc=0, entry_result=0)
        c = _command(p, artifact, package, c, checks, on_phase, 'removing', poll)
        result = _record(artifact, package, c, 'removed')
        try:
            _emit(on_phase, result)
        except BaseException as error:
            _uncertain(on_phase, result, error)
            raise
        return result
