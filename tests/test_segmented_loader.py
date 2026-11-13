"""Offline standalone AArch64 loader + host protocol tests. No USB or resident build."""
from dataclasses import replace
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch

from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN
from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_CODE, UC_HOOK_MEM_WRITE, UC_HOOK_MEM_READ
from unicorn import arm64_const as r

import bfplus_loader as host
from bfplus.loader_build import build, tool, FLAGS, SOURCE

BUF = 0x447570000
STAGE = BUF+host.STAGE_OFFSET
OWNER = 0x447701123
BASE = (OWNER+host.GUARD_BYTES+4095) & ~4095
STACK, LOG = 0x448f00000, 0x448e00000
STOP = STACK+0x100
FW = 0x4d3000000
HOOK, STOCK = 0x4d3398860, 0x4d3398940


@lru_cache(None)
def fixtures():
    with tempfile.TemporaryDirectory(prefix='bf-segmented-tests-') as directory:
        d = Path(directory)
        blob, symbols = build(d)
        # Actual C entry checks BSS, logs the ABI, and changes one representative
        # hook. This is original fixture code, not an imported production image.
        (d/'entry.c').write_text('''
#include "loader_abi.h"
#define Q(a) (*(volatile uint64_t *)(uintptr_t)(a))
uint32_t resident_entry(uint32_t op,const struct LoaderControl *c,uint64_t ctr) {
    const uint64_t log=0x448e00000ULL;
    Q(log)=Q(log)+1; Q(log+8)=op; Q(log+16)=c->identity_nonce;
    Q(log+24)=c->owner; Q(log+32)=c->resident; Q(log+40)=ctr;
    Q(log+48)=c->image_size; Q(log+56)=c->memory_size;
    Q(log+64)=c->scratch_size; Q(log+72)=c->mode;
    if (Q(log+120)) return (uint32_t)Q(log+120);
    if (!op) {
        volatile unsigned char *p=(volatile unsigned char *)(uintptr_t)c->resident;
        for (uint64_t i=c->image_size;i<c->memory_size;i++) if (p[i]) return 99;
        if (c->memory_size-c->image_size>=8) Q(c->resident+c->image_size)=0xaabbccdd;
        p[c->image_size-1]^=0x80; /* initialized state is mutable after install */
        Q(0x4d3398860ULL)=c->resident+0x234;
    } else {
        if (c->memory_size-c->image_size>=8 && Q(c->resident+c->image_size)!=0xaabbccdd) return 98;
        if (Q(0x4d3398860ULL)!=c->resident+0x234) return 97;
        Q(0x4d3398860ULL)=0x4d3398940ULL;
    }
    return 0;
}
''')
        (d/'entry.ld').write_text('SECTIONS { . = 0; .text : { *(.text*) } .rodata : { *(.rodata*) } /DISCARD/ : { *(.comment*) *(.note*) *(.eh_frame*) } }')
        subprocess.run([tool('clang'), *FLAGS, '-I', str(SOURCE), '-c', str(d/'entry.c'),
                        '-o', str(d/'entry.o')], check=True)
        subprocess.run([tool('ld.lld'), '-T', str(d/'entry.ld'), '-e', 'resident_entry',
                        str(d/'entry.o'), '-o', str(d/'entry.elf')], check=True)
        subprocess.run([tool('llvm-objcopy'), '-O', 'binary', str(d/'entry.elf'), str(d/'entry.bin')], check=True)
        entry = (d/'entry.bin').read_bytes()
        # Independently link the EXISTING launcher against a minimal entry at
        # +0x100. This compares linked prefix bytes, including its branch fixup.
        (d/'reference.S').write_text('.section .text.entry,"ax"\n.global bootstrap\nbootstrap: ret\n')
        (d/'reference.ld').write_text('SECTIONS { . = 0; .text : { *(.text.launch) . = 0x100; *(.text.entry) } }')
        subprocess.run([tool('clang'), '--target=aarch64-none-elf', '-c', str(d/'reference.S'),
                        '-o', str(d/'reference.o')], check=True)
        subprocess.run([tool('ld.lld'), '-e', 'launch', '-T', str(d/'reference.ld'),
                        str(d/'loader-launch.o'), str(d/'reference.o'), '-o', str(d/'reference.elf')], check=True)
        subprocess.run([tool('llvm-objcopy'), '-O', 'binary', str(d/'reference.elf'), str(d/'reference.bin')], check=True)
        return host.LoaderArtifact(blob, symbols), entry, (d/'reference.bin').read_bytes()[:0x100]


def package(size=0x8003, scratch=host.PORTRAIT_SCRATCH):
    _, entry, _ = fixtures()
    assert size > len(entry)
    image = entry+bytes((i*37+13) & 255 for i in range(size-len(entry)))
    return host.ResidentImage(image, (size+191)&~63, 0, scratch)


class Machine:
    def __init__(self, stage=STAGE):
        self.artifact = fixtures()[0]
        self.stage, self.buf = stage, stage-host.STAGE_OFFSET
        self.uc = u = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
        for base, size in ((self.buf, 0x20000), (OWNER & ~4095, 0x200000),
                           (STACK, 0x10000), (LOG, 0x10000), (FW, 0x4400000)):
            u.mem_map(base, size)
        u.mem_write(stage, self.artifact.image)
        u.mem_write(OWNER & ~4095, b'\xa5'*0x200000)
        for address, value, size in ((host.CALLBACK, host.ORIGINAL, 8), (host.L2_SLOT, host.L2_RO, 8),
                                      (0x4d72c2230, self.buf, 8), (0x4d703469c, 12, 4), (0x4d70346a0, 2, 4),
                                      (0x4d70346a4, 12, 4), (HOOK, STOCK, 8)):
            self.put(address, value, size)
        u.mem_write(0x4d7301c00, struct.pack('<4Q', 0x4d3398930, 0x4d33988b0, 0x4d3393730, 0x4d33936a0))
        self.el, self.ctr = 4, 0x8444c004
        self.owner, self.alloc_ok, self.storage_rc = OWNER, True, 0
        self.events = []
        self.entry_seen = 0
        self.before_entry = None
        for ins in Cs(CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN).disasm(self.artifact.image, stage):
            if ins.mnemonic in ('mrs', 'msr', 'dc', 'ic', 'dsb', 'dmb', 'isb', 'tlbi'):
                def system(u, pc, size, opaque, op=ins.mnemonic, args=ins.op_str):
                    if op == 'mrs':
                        dst, src = args.split(', ')
                        value = {'currentel': self.el, 'ctr_el0': self.ctr,
                                 'mair_el1': 0xff, 'tcr_el1': 0}[src.lower()]
                        u.reg_write(getattr(r, 'UC_ARM64_REG_'+dst.upper()), value)
                    elif op in ('dc', 'ic'):
                        parts = args.split(', ')
                        address = u.reg_read(getattr(r, 'UC_ARM64_REG_'+parts[1].upper())) if len(parts) == 2 else None
                        self.events.append((op, address))
                    u.reg_write(r.UC_ARM64_REG_PC, pc+4)
                u.hook_add(UC_HOOK_CODE, system, begin=ins.address, end=ins.address)
        for address in (0x4d330c850, host.ORIGINAL):
            u.hook_add(UC_HOOK_CODE, self.service, begin=address, end=address)
        u.hook_add(UC_HOOK_CODE, self.entry, begin=BASE, end=BASE)
        u.hook_add(UC_HOOK_MEM_WRITE, self.write)

    def read(self, address, size):
        return bytes(self.uc.mem_read(address, size))

    def put(self, address, value, size=8):
        self.uc.mem_write(address, int(value).to_bytes(size, 'little'))

    def get(self, address, size=8):
        return int.from_bytes(self.read(address, size), 'little')

    def service(self, u, pc, size, opaque):
        args = [u.reg_read(getattr(r, f'UC_ARM64_REG_X{i}')) for i in range(6)]
        if pc == 0x4d330c850:
            self.events.append(('allocate', *args[:4], args[5]))
            self.put(args[4], self.owner if self.alloc_ok else 0)
            result = int(self.alloc_ok)
        else:
            assert self.get(host.CALLBACK) == host.ORIGINAL
            self.events.append(('writer', *args[:3]))
            result = self.storage_rc
        u.reg_write(r.UC_ARM64_REG_X0, result)
        u.reg_write(r.UC_ARM64_REG_PC, u.reg_read(r.UC_ARM64_REG_LR))

    def entry(self, u, pc, size, opaque):
        self.entry_seen += 1
        self.events.append(('entry', u.reg_read(r.UC_ARM64_REG_X0)))
        if self.before_entry:
            self.before_entry(self)

    def write(self, u, access, address, size, value, opaque):
        control = self.stage+self.artifact.symbols['loader_control']
        if address in (host.CALLBACK, HOOK, control+24, BASE-256+12):
            self.events.append(('write', address, size, value))

    def run(self, control=None):
        if control is not None:
            self.uc.mem_write(self.stage+self.artifact.symbols['loader_control'], control.pack())
        self.put(host.CALLBACK, self.stage)
        for i, value in enumerate((7, 8, STACK+0x1000)):
            self.uc.reg_write(getattr(r, f'UC_ARM64_REG_X{i}'), value)
        self.uc.reg_write(r.UC_ARM64_REG_SP, STACK+0xf000)
        self.uc.reg_write(r.UC_ARM64_REG_LR, STOP)
        self.uc.emu_start(self.stage, STOP, count=20000000)
        assert self.uc.reg_read(r.UC_ARM64_REG_PC) == STOP, 'loader instruction budget exhausted'
        assert self.uc.reg_read(r.UC_ARM64_REG_X0) == self.storage_rc
        return host.Control.unpack(self.read(self.stage+self.artifact.symbols['loader_control'], 256))

    def request(self, p=None, nonce=101):
        p = p or package()
        return host.Control(request_nonce=nonce, identity_nonce=nonce, transport_buffer=self.buf,
                            image_size=len(p.image), memory_size=p.memory_size, scratch_size=p.scratch_size,
                            entry_offset=p.entry_offset, image_crc32=p.crc32,
                            image_sha256=bytes.fromhex(p.sha256))

    def prepare(self, p=None):
        return self.run(self.request(p))

    def commit(self, c):
        return self.run(replace(c, request_nonce=102, done=0, command=host.COMMIT))


class LoaderArmTests(unittest.TestCase):
    def test_fixed_launcher_pic_build_and_separate_control_abi(self):
        artifact, _, reference = fixtures()
        self.assertLess(len(artifact.image), 0x4000)
        self.assertEqual(artifact.image[:0x100], reference)
        self.assertEqual(artifact.image[:60], host.LAUNCH_PREFIX)
        self.assertEqual((host.CONTROL.size, host.GUARD.size), (256, 256))
        for stage in (STAGE, STAGE+0x2000000):
            m = Machine(stage)
            c = m.prepare()
            self.assertEqual((c.result, c.done, c.phase), (0, 101, host.PREPARING))

    def test_prepare_is_unreferenced_guarded_and_does_not_touch_image(self):
        m = Machine()
        p = package()
        c = m.prepare(p)
        self.assertEqual((c.resident, c.guard, c.owner), (BASE, BASE-256, OWNER))
        self.assertEqual(c.allocation_size, 256+4095+p.memory_size+p.scratch_size)
        self.assertEqual(m.get(HOOK), STOCK)
        self.assertEqual(m.entry_seen, 0)
        self.assertEqual(m.read(BASE, p.memory_size), b'\xa5'*p.memory_size)
        self.assertEqual(m.read(BASE-256-16, 16), b'\xa5'*16)
        g = host.GUARD.unpack(m.read(c.guard, 256))
        self.assertEqual((g[0], g[2], g[3], g[14]), (host.GUARD_MAGIC, host.PREPARING, 101, 101))
        writes = [e for e in m.events if e[0] == 'write']
        self.assertEqual(writes[0][1:], (host.CALLBACK, 8, host.ORIGINAL))
        done = m.stage+m.artifact.symbols['loader_control']+24
        last_done = max(i for i, e in enumerate(m.events) if e[:2] == ('write', done) and e[3] == 101)
        writer = max(i for i, e in enumerate(m.events) if e[0] == 'writer')
        self.assertGreater(last_done, writer)
        self.assertIn(('writer', 7, 8, STACK+0x1000), m.events)

    def test_commit_checks_crc_zeroes_bss_and_publishes_entire_large_resident(self):
        m = Machine(); p = package(0x8003); c = m.prepare(p)
        m.uc.mem_write(BASE, p.image)
        m.events.clear()
        def before_entry(machine):
            self.assertEqual(machine.read(BASE+len(p.image), p.memory_size-len(p.image)),
                             bytes(p.memory_size-len(p.image)))
            lines = set(range(BASE, BASE+p.memory_size, 64))
            for operation in ('dc', 'ic'):
                self.assertTrue(lines <= {e[1] for e in machine.events if e[0] == operation})
        m.before_entry = before_entry
        c = m.commit(c)
        self.assertEqual((c.result, c.phase, c.done), (0, host.COMMITTED, 102))
        self.assertEqual(m.get(HOOK), BASE+0x234)
        self.assertEqual(m.get(LOG+16), 101)
        self.assertEqual(m.get(LOG+24), OWNER)
        self.assertEqual(m.get(LOG+40), m.ctr)
        self.assertEqual(m.get(LOG+64), p.scratch_size)
        self.assertEqual(m.read(BASE+p.memory_size, 64), b'\xa5'*64)

    def test_removal_calls_existing_entry_without_crc_of_mutable_data_or_free(self):
        m = Machine(); p = package(); c = m.prepare(p)
        m.uc.mem_write(BASE, p.image); c = m.commit(c)
        self.assertNotEqual(hashlib.sha256(m.read(BASE, len(p.image))).hexdigest(), p.sha256)
        count = sum(e[0] == 'allocate' for e in m.events)
        c = m.run(replace(c, command=host.REMOVE, request_nonce=103, done=0))
        self.assertEqual((c.result, c.phase, m.entry_seen), (0, host.REMOVED, 2))
        self.assertEqual(m.get(HOOK), STOCK)
        self.assertEqual(m.get(BASE+len(p.image)), 0xaabbccdd)
        self.assertEqual(sum(e[0] == 'allocate' for e in m.events), count)
        again = m.run(replace(c, command=host.REMOVE, request_nonce=104, done=0))
        self.assertEqual(again.result, 9)
        self.assertEqual(m.entry_seen, 2)

    def test_missing_and_corrupted_image_never_execute_and_fail_the_guard(self):
        for corrupted in (False, True):
            m = Machine(); p = package(); c = m.prepare(p)
            if corrupted:
                m.uc.mem_write(BASE, p.image)
                m.put(BASE+0x4001, m.get(BASE+0x4001, 1)^1, 1)
            c = m.commit(c)
            self.assertEqual((c.result, c.phase, m.entry_seen), (10, host.FAILED, 0))
            self.assertEqual(m.get(HOOK), STOCK)
            self.assertEqual(m.read(BASE+len(p.image), 64), b'\xa5'*64)

    def test_stale_nonce_extent_identity_and_guard_state_rejected(self):
        for changes, expected in (({'identity_nonce': 999}, 8), ({'image_crc32': 1}, 8),
                                  ({'entry_offset': 4}, 8), ({'scratch_size': 0}, 7),
                                  ({'request_nonce': 101}, 13), ({'phase': host.COMMITTED}, 9),
                                  ({'resident': BASE+4096}, 7), ({'guard': BASE-512}, 7)):
            with self.subTest(changes=changes):
                m = Machine(); p = package(); c = m.prepare(p); m.uc.mem_write(BASE, p.image)
                request = replace(c, command=host.COMMIT, request_nonce=102, done=0)
                result = m.run(replace(request, **changes))
                self.assertEqual(result.result, expected)
                self.assertEqual(m.entry_seen, 0)
        m = Machine(); c = m.prepare(); m.put(BASE-256, 0)
        self.assertEqual(m.commit(c).result, 8)

    def test_invalid_extents_and_commands_fail_before_allocation(self):
        for changes, expected in (({'image_size': 0}, 5), ({'memory_size': 0x10040}, 5),
                                  ({'memory_size': 63}, 5), ({'scratch_size': 2**64-1}, 5),
                                  ({'entry_offset': 1}, 5), ({'entry_offset': 0x10000}, 5),
                                  ({'mode': 2}, 5), ({'command': 99}, 12),
                                  ({'abi_version': 2}, 1), ({'reserved0': 1}, 1),
                                  ({'request_nonce': 0}, 13), ({'done': 1}, 13),
                                  ({'transport_buffer': BUF+4096}, 7)):
            with self.subTest(changes=changes):
                m = Machine(); c = m.run(replace(m.request(), **changes))
                self.assertEqual(c.result, expected)
                self.assertFalse(any(e[0] == 'allocate' for e in m.events))
                self.assertEqual(m.get(host.CALLBACK), host.ORIGINAL)

    def test_allocator_failure_overflow_and_protected_overlap(self):
        for owner in (0, host.RAM_MIN-1, 2**64-1, host.RAM_END-64, BUF, FW):
            with self.subTest(owner=hex(owner)):
                m = Machine(); m.owner = owner
                c = m.prepare()
                self.assertEqual(c.result, 6 if owner == 0 else 7)
                self.assertEqual(m.get(HOOK), STOCK)
                self.assertEqual(m.entry_seen, 0)
        m = Machine(); m.alloc_ok = False
        self.assertEqual(m.prepare().result, 6)

    def test_el_l2_and_idle_gates_restore_callback_and_preserve_writer_arguments(self):
        for kind, code in (('el', 2), ('l2', 3), ('idle', 4)):
            m = Machine()
            if kind == 'el': m.el = 8
            elif kind == 'l2': m.put(host.L2_SLOT, host.L2_RO^0x80)
            else: m.put(0x4d70346a4, 3, 4)
            c = m.prepare()
            self.assertEqual(c.result, code)
            self.assertFalse(any(e[0] == 'allocate' for e in m.events))
            self.assertIn(('writer', 7, 8, STACK+0x1000), m.events)

    def test_entry_failure_and_writer_failure_are_distinct_from_success(self):
        m = Machine(); p = package(); c = m.prepare(p); m.uc.mem_write(BASE, p.image)
        m.put(LOG+120, 77)
        result = m.commit(c)
        self.assertEqual((result.result, result.entry_result, result.phase), (11, 77, host.FAILED))
        self.assertEqual(m.get(HOOK), STOCK)
        m = Machine(); c = m.prepare(p); m.uc.mem_write(BASE, p.image); m.storage_rc = 0xffffffff
        result = m.commit(c)
        self.assertEqual((result.result, result.storage_rc, result.phase), (0, 0xffffffff, host.COMMITTED))
        self.assertEqual(m.get(HOOK), BASE+0x234)

    def test_maximum_resident_and_future_global_ui_scratch_fit_guarded_allocation(self):
        entry = fixtures()[1]
        p = host.ResidentImage(entry.ljust(0x10000, b'\x17'), 0x10000, 0, 0x4a9800)
        m = Machine(); c = m.prepare(p)
        self.assertEqual((c.result, c.scratch_size), (0, 0x4a9800))
        self.assertEqual(c.allocation_size, 256+4095+0x10000+0x4a9800)
        m.uc.mem_write(BASE, p.image)
        c = m.commit(c)
        self.assertEqual((c.result, c.phase), (0, host.COMMITTED))
        self.assertEqual(m.get(LOG+64), 0x4a9800)
        self.assertEqual(m.read(BASE+0x10000, 64), b'\xa5'*64)

    def test_idle_and_l2_are_rechecked_after_crc_before_entry(self):
        for target, value, size, expected in ((0x4d70346a4, 3, 4, 4),
                                              (host.L2_SLOT, host.L2_RO^0x80, 8, 3)):
            with self.subTest(target=hex(target)):
                m = Machine(); p = package(); c = m.prepare(p); m.uc.mem_write(BASE, p.image)
                def interrupt(u, access, address, width, old, opaque):
                    m.put(target, value, size)
                hook = m.uc.hook_add(UC_HOOK_MEM_READ, interrupt,
                                     begin=BASE+len(p.image)-1, end=BASE+len(p.image)-1)
                result = m.commit(c)
                m.uc.hook_del(hook)
                self.assertEqual((result.result, result.phase), (expected, host.FAILED))
                self.assertEqual(m.entry_seen, 0)
                self.assertEqual(m.get(HOOK), STOCK)


class Clock:
    def __init__(self): self.now = 0.0
    def monotonic(self): return self.now
    def sleep(self, value): self.now += value


class MockPTP:
    """PTP-shaped emulator adapter: shared RLock and persisted-cooldown stand-in.

    The real transport's cooldown/flock has its own test_touch_ptp coverage.
    Here every read/write asserts the helper holds that same transport lock.
    """
    def __init__(self):
        self.m = Machine()
        self._io_lock, self._lock_file = threading.RLock(), object()
        self.clock = Clock()
        self.opened = True
        self.writes, self.reads, self.records = [], [], []
        self.fail_at = None
        self.on_read = None
        self.stale_completion = False
        self.preflights = []
        self.checks = host.Checks(self.callback, self.idle, self.preflight)

    def _require_open(self):
        if not self.opened: raise host.LoaderError('closed/broken transport')

    def read(self, address, size):
        # Model the conservative camera read boundary independently of host constants.
        assert self._io_lock._is_owned() and 0 < size <= 0x1000
        self.reads.append((address, size))
        raw = self.m.read(address, size)
        if self.on_read: raw = self.on_read(address, raw)
        return raw

    def write(self, address, data):
        assert self._io_lock._is_owned() and 0 < len(data) <= 0x1000
        self._require_open()
        # No helper can bypass this stand-in for PTP.write's durable cooldown.
        self.clock.sleep(10)
        self.writes.append((address, bytes(data), self.clock.now))
        if self.fail_at == len(self.writes):
            self.opened = False
            raise OSError('uncertain write failure')
        self.m.uc.mem_write(address, bytes(data))
        if address == host.CALLBACK:
            self.m.run()
            if self.stale_completion:
                self.m.put(STAGE+self.m.artifact.symbols['loader_control']+24, 0)

    def callback(self, p):
        assert p is self and self.m.get(host.CALLBACK) == host.ORIGINAL

    def idle(self, p):
        assert p is self and self.m.get(0x4d70346a0, 4) == 2 and self.m.get(0x4d70346a4, 4) == 12

    def preflight(self, p, command, record):
        assert p is self
        self.preflights.append((command, record['phase']))
        installed = record['phase'] == 'committed' or command == host.REMOVE and record['phase'] != 'removed'
        assert self.m.get(HOOK) == (BASE+0x234 if installed else STOCK)
        return BUF


class HostLoaderTests(unittest.TestCase):
    def setUp(self):
        self.p = MockPTP()
        self.artifact = fixtures()[0]
        self.pkg = package()
        for name in ('monotonic', 'sleep'):
            patcher = patch.object(host.time, name, getattr(self.p.clock, name))
            patcher.start(); self.addCleanup(patcher.stop)
        self.kw = {'checks': self.p.checks, 'on_phase': self.p.records.append,
                   'poll': host.Poll(timeout=0.4, interval=0.2)}

    def test_images_below_and_above_cap_short_final_chunk_and_exact_remove(self):
        for size in (0xfff, 0x1000, 0x1001, 0x3fff, 0x4000, 0x4001, 0x8003):
            with self.subTest(size=size):
                p = self.p = MockPTP()
                kw = {**self.kw, 'checks': p.checks, 'on_phase': p.records.append}
                pkg = package(size)
                record = host.execute(p, self.artifact, pkg, **kw)
                self.assertEqual(record['phase'], 'committed')
                chunks = [(a, b) for a, b, _ in p.writes if BASE <= a < BASE+pkg.memory_size]
                self.assertEqual(b''.join(b for _, b in chunks), pkg.image)
                self.assertEqual([a-BASE for a, _ in chunks], list(range(0, size, 0x1000)))
                self.assertEqual(len(p.writes), 4+len(chunks))
                self.assertTrue(all(b[2]-a[2] >= 10 for a, b in zip(p.writes, p.writes[1:])))
                self.assertTrue(all(n <= 0x1000 for _, n in p.reads))
                record = json.loads(json.dumps(record))  # Exact saved format for removal only.
                result = host.remove(p, self.artifact, pkg, record, **kw)
                self.assertEqual(result['phase'], 'removed')
                self.assertEqual(len(p.writes), 6+len(chunks))
                self.assertEqual(p.m.entry_seen, 2)
                self.assertIn((host.COMMIT, 'committed'), p.preflights)
                self.assertIn((host.REMOVE, 'removed'), p.preflights)

    def test_read_reassembles_exact_bytes_across_4k_transaction_boundaries(self):
        self.p.m.uc.mem_write(BASE, self.pkg.image)
        for size in (1, 0xfff, 0x1000, 0x1001, 0x3fff, 0x4000):
            with self.subTest(size=size), self.p._io_lock:
                self.p.reads.clear()
                self.assertEqual(host._read(self.p, BASE, size), self.pkg.image[:size])
                self.assertEqual(self.p.reads, [(BASE+i, min(0x1000, size-i))
                                               for i in range(0, size, 0x1000)])

    def test_maximum_loader_stage_uses_4k_writes_and_reads(self):
        artifact = host.LoaderArtifact(self.artifact.image.ljust(0x4000, b'\0'),
            {**self.artifact.symbols, '__image_end': 0x4000, '__end': 0x4000})
        session = host.prepare(self.p, artifact, self.pkg, **self.kw)
        self.assertEqual(session.phase, 'prepared')
        self.assertEqual([(a, len(b)) for a, b, _ in self.p.writes],
                         [(STAGE+i, 0x1000) for i in range(0, 0x4000, 0x1000)]+[(host.CALLBACK, 8)])
        staged = b''.join(b for a, b, _ in self.p.writes if STAGE <= a < STAGE+0x4000)
        control = artifact.symbols['loader_control']
        self.assertEqual(staged[:control], artifact.image[:control])
        self.assertEqual(staged[control+256:], artifact.image[control+256:])
        self.assertTrue(all(b[2]-a[2] >= 10 for a, b in zip(self.p.writes, self.p.writes[1:])))
        self.assertEqual([(a, n) for a, n in self.p.reads if n == 0x1000],
                         [(STAGE+i, 0x1000) for i in range(0, 0x4000, 0x1000)])
        self.assertEqual(self.p.m.entry_seen, 0)

    def test_interrupted_staging_never_triggers_or_reuploads(self):
        artifact = host.LoaderArtifact(self.artifact.image.ljust(0x4000, b'\0'),
            {**self.artifact.symbols, '__image_end': 0x4000, '__end': 0x4000})
        self.p.fail_at = 2
        with self.assertRaisesRegex(OSError, 'uncertain write'):
            host.prepare(self.p, artifact, self.pkg, **self.kw)
        self.assertEqual([(a, len(b)) for a, b, _ in self.p.writes],
                         [(STAGE, 0x1000), (STAGE+0x1000, 0x1000)])
        self.assertEqual(self.p.records[-1]['phase'], 'uncertain')
        self.assertEqual((self.p.m.entry_seen, self.p.m.get(host.CALLBACK)), (0, host.ORIGINAL))
        self.assertFalse(any(event[0] == 'allocate' for event in self.p.m.events))

    def test_subread_failure_stops_loading_without_retry_or_commit(self):
        for failure in ('short', 'oversized', 'exception'):
            with self.subTest(failure=failure):
                p = MockPTP()
                def fail(address, raw):
                    if address != BASE+0x1000: return raw
                    if failure == 'exception': raise OSError('read transport failed')
                    return raw[:-1] if failure == 'short' else raw+b'!'
                p.on_read = fail
                error = OSError if failure == 'exception' else host.LoaderError
                with self.assertRaises(error):
                    host.execute(p, self.artifact, self.pkg,
                                 **{**self.kw, 'checks': p.checks, 'on_phase': p.records.append})
                self.assertEqual([(a, n) for a, n in p.reads if BASE <= a < BASE+0x10000],
                                 [(BASE, 0x1000), (BASE+0x1000, 0x1000)])
                self.assertEqual([(a, len(b)) for a, b, _ in p.writes],
                                 [(STAGE, len(self.artifact.image)), (host.CALLBACK, 8),
                                  (BASE, 0x1000), (BASE+0x1000, 0x1000)])
                self.assertEqual((p.m.entry_seen, p.m.get(HOOK)), (0, STOCK))
                last = p.records[-1]
                self.assertEqual((last['phase'], last['written'], last['next_size']),
                                 ('uncertain', 0x1000, 0x1000))
                self.assertEqual(last['control']['command'], host.PREPARE)

    def test_commit_without_complete_load_and_repeated_load_are_rejected(self):
        session = host.prepare(self.p, self.artifact, self.pkg, **self.kw)
        before = len(self.p.writes)
        with self.assertRaisesRegex(host.LoaderError, 'Stale|interrupted'):
            host.commit(self.p, session, **self.kw)
        self.assertEqual(len(self.p.writes), before)
        host.load(self.p, session, **self.kw)
        before = len(self.p.writes)
        with self.assertRaises(host.LoaderError): host.load(self.p, session, **self.kw)
        self.assertEqual(len(self.p.writes), before)

    def test_stale_guard_or_transport_session_blocks_all_chunk_writes(self):
        for invalid_session in (False, True):
            p = MockPTP(); kw = {**self.kw, 'checks': p.checks, 'on_phase': p.records.append}
            session = host.prepare(p, self.artifact, self.pkg, **kw)
            if invalid_session: p._lock_file = object()
            else: p.m.put(BASE-256+16, 999)
            before = len(p.writes)
            with self.assertRaises(host.LoaderError): host.load(p, session, **kw)
            self.assertEqual(len(p.writes), before)
            self.assertEqual(p.m.entry_seen, 0)

    def test_corruption_after_verification_prevents_commit_without_writes(self):
        s = host.prepare(self.p, self.artifact, self.pkg, **self.kw)
        host.load(self.p, s, **self.kw)
        self.p.m.put(BASE+0x4001, self.p.m.get(BASE+0x4001, 1)^1, 1)
        before = len(self.p.writes)
        with self.assertRaisesRegex(host.LoaderError, 'readback/hash'):
            host.commit(self.p, s, **self.kw)
        self.assertEqual(len(self.p.writes), before)
        self.assertEqual(s.phase, 'uncertain')
        self.assertEqual(self.p.m.entry_seen, 0)

    def test_interrupted_chunk_write_never_retries_or_resumes(self):
        s = host.prepare(self.p, self.artifact, self.pkg, **self.kw)
        self.p.fail_at = 4  # Second resident chunk, after prepare upload+trigger.
        with self.assertRaises(OSError): host.load(self.p, s, **self.kw)
        self.assertEqual((len(self.p.writes), s.phase, self.p.m.entry_seen), (4, 'uncertain', 0))
        self.p.opened = True
        with self.assertRaises(host.LoaderError): host.load(self.p, s, **self.kw)
        self.assertEqual(len(self.p.writes), 4)

    def test_bad_loader_readback_and_stale_completion_never_retrigger(self):
        self.p.on_read = lambda a, raw: bytes(len(raw)) if a == STAGE else raw
        with self.assertRaisesRegex(host.LoaderError, 'readback'):
            host.prepare(self.p, self.artifact, self.pkg, **self.kw)
        self.assertEqual(len(self.p.writes), 1)
        self.p.on_read = None
        self.p.stale_completion = True
        with self.assertRaisesRegex(host.LoaderError, 'completion nonce'):
            host.prepare(self.p, self.artifact, self.pkg, **self.kw)
        self.assertEqual(len(self.p.writes), 3)
        self.assertEqual(self.p.records[-1]['phase'], 'uncertain')

    def test_writer_failure_after_real_commit_preserves_uncertain_receipt(self):
        s = host.prepare(self.p, self.artifact, self.pkg, **self.kw)
        host.load(self.p, s, **self.kw)
        self.p.m.storage_rc = 0xffffffff
        with self.assertRaisesRegex(host.LoaderError, 'Storage writer'):
            host.commit(self.p, s, **self.kw)
        self.assertEqual(self.p.m.get(HOOK), BASE+0x234)
        last = self.p.records[-1]
        self.assertEqual(last['phase'], 'uncertain')
        self.assertEqual(last['control']['phase'], host.COMMITTED)
        self.assertEqual(last['control']['done'], last['control']['request_nonce'])
        self.assertNotEqual(last['control']['request_nonce'], last['control']['identity_nonce'])

    def test_legacy_or_wrong_artifact_removal_is_rejected_without_writes(self):
        for record in ({'nonce': 123, 'resident': BASE}, {'format': host.FORMAT, 'abi_version': 2}):
            with self.assertRaisesRegex(host.LoaderError, 'legacy'):
                host.remove(self.p, self.artifact, self.pkg, record, **self.kw)
        self.assertEqual(self.p.writes, [])
        record = host.execute(self.p, self.artifact, self.pkg, **self.kw)
        before = len(self.p.writes)
        with self.assertRaisesRegex(host.LoaderError, 'exact immutable'):
            host.remove(self.p, self.artifact, package(0x8004), record, **self.kw)
        self.assertEqual(len(self.p.writes), before)

    def test_failed_durable_intent_callback_stops_before_any_write(self):
        def refuse(record): raise OSError('cannot persist manifest')
        with self.assertRaises(OSError):
            host.prepare(self.p, self.artifact, self.pkg, **{**self.kw, 'on_phase': refuse})
        self.assertEqual(self.p.writes, [])

    def test_parent_postcondition_failure_preserves_committed_uncertain_identity(self):
        original = self.p.preflight
        def reject(p, command, record):
            if record['phase'] == 'committed':
                raise host.LoaderError('Installed hook manifest mismatch')
            return original(p, command, record)
        checks = host.Checks(self.p.callback, self.p.idle, reject)
        with self.assertRaisesRegex(host.LoaderError, 'hook manifest'):
            host.execute(self.p, self.artifact, self.pkg, **{**self.kw, 'checks': checks})
        self.assertEqual(self.p.m.entry_seen, 1)
        self.assertEqual(self.p.records[-1]['phase'], 'uncertain')
        self.assertEqual(self.p.records[-1]['control']['phase'], host.COMMITTED)
        self.assertEqual(sum(a == host.CALLBACK for a, _, _ in self.p.writes), 2)


if __name__ == '__main__':
    unittest.main()
