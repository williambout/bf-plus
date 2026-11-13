"""Original BF 1.04 file ABI and compiled doom_storage.h, entirely offline.

The actual public entries, controller adapters, FS wrappers, and ordinary
memory/string routines execute in Unicorn. File-service dispatch is modeled
synchronously; storage, semaphores, task waiting, logging, and clock/delay
syscalls are mocked. The logical J: mount is synthetic. No camera, USB, host
file writes, firmware build, or .touch-focus artifacts are used.
"""
import hashlib
from pathlib import Path
import shutil
import struct
import subprocess
import unittest

try:
    from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_CODE
    from unicorn import arm64_const as r
except ImportError:
    Uc = None


ROOT = Path(__file__).resolve().parents[1]
FIRMWARE = ROOT / 'decoded-V104/rtos-alt.bin'
IMAGE_HASH = 'f747c1350f00526b9c68c65aaef44d6e7b644b0169992342e12f059c42e150dc'
BASE, RAM = 0x4d3000000, 0x600000000
STOP, RETURN, MESSAGE = RAM, RAM + 0x1000, RAM + 0x3000
PATH, OUT, BUFFER, CODE = RAM + 0x4000, RAM + 0x5000, RAM + 0x6000, RAM + 0x8000
HANDLE = 0x123456789  # Deliberately exceeds a 32-bit descriptor.
OPEN, READ, SEEK, CLOSE = 0x4d313b9e0, 0x4d313bb50, 0x4d313bc60, 0x4d313baf0


class FileMachine:
    def __init__(self, firmware):
        self.uc = u = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
        u.mem_map(BASE, (len(firmware) + 4095) & ~4095)
        u.mem_write(BASE, firmware)
        u.mem_map(0x4d7000000, 0x400000)
        u.mem_write(0x4d7000000, firmware[0xebdfb0:0xf03e70])
        u.mem_map(RAM, 0x10000)
        u.reg_write(r.UC_ARM64_REG_CPACR_EL1, 3 << 20)
        # Test-only drive table: logical J maps to physical drive character 0.
        u.mem_write(0x4d729ce80 + 9 * 9, b'J\0')
        u.mem_write(0x4d72a1ee0 + 9 * 24 + 16, b'0')
        u.mem_write(PATH, b'J:\\DOOM.BFP\0')
        self.data = b'IWAD' + bytes(range(60))
        self.position = 0
        self.open_fails = self.read_fails = self.lock_fails = False
        self.calls = []
        u.hook_add(UC_HOOK_CODE, self.hook)

    def x(self, index):
        return self.uc.reg_read(getattr(r, 'UC_ARM64_REG_X' + str(index)))

    def put(self, address, value, size=8):
        self.uc.mem_write(address, (value & ((1 << (8 * size)) - 1)).to_bytes(size, 'little'))

    def get(self, address, size=8):
        return int.from_bytes(self.uc.mem_read(address, size), 'little')

    def cstring(self, address):
        return bytes(self.uc.mem_read(address, 600)).split(b'\0')[0]

    def finish_mock(self, value=0):
        self.uc.reg_write(r.UC_ARM64_REG_X0, value & ((1 << 64) - 1))
        self.uc.reg_write(r.UC_ARM64_REG_PC, self.uc.reg_read(r.UC_ARM64_REG_LR))

    def hook(self, u, pc, size, opaque):
        if pc == 0x4d313d350:
            callback, completion, source, length, result = [self.x(i) for i in range(5)]
            assert completion == 0 and length <= 0x42c
            self.continuation = u.reg_read(r.UC_ARM64_REG_LR)
            self.result_pointer = result
            u.mem_write(MESSAGE, bytes(0x460))
            self.put(MESSAGE + 0x10, callback)
            self.put(MESSAGE + 0x28, result)
            u.mem_write(MESSAGE + 0x30, bytes(u.mem_read(source, length)))
            self.calls.append(('dispatch', callback, length))
            u.reg_write(r.UC_ARM64_REG_X0, MESSAGE)
            u.reg_write(r.UC_ARM64_REG_LR, RETURN)
            u.reg_write(r.UC_ARM64_REG_PC, callback)
        elif pc == RETURN:
            self.put(self.result_pointer, self.x(0), 4)
            u.reg_write(r.UC_ARM64_REG_LR, self.continuation)
            self.finish_mock(0)  # Enqueue succeeded; worker has already run.
        elif pc in (0x4d3141040, 0x4d31410a0, 0x4d3140eb0, 0x4d3140f70):
            self.finish_mock()  # Wait, semaphore signal, and logging.
        elif pc == 0x4d31410b0:
            self.finish_mock(-50 if self.lock_fails else 0)
        elif pc == 0x4d352bb60:
            self.calls.append(('fopen', self.cstring(self.x(0)), self.cstring(self.x(1))))
            self.position = 0
            self.finish_mock(0 if self.open_fails else HANDLE)
        elif pc == 0x4d352bc20:
            assert self.x(1) == 1 and self.x(3) == HANDLE
            requested = self.x(2)
            data = b'' if self.read_fails else self.data[self.position:self.position + requested]
            if data:
                u.mem_write(self.x(0), data)
            self.position += len(data)
            self.calls.append(('fread', requested, len(data)))
            self.finish_mock(len(data))
        elif pc == 0x4d352bb40:
            self.finish_mock(0 if self.read_fails else 1)  # feof on short read.
        elif pc == 0x4d352bb10:
            self.finish_mock(5 if self.read_fails or self.open_fails else 0)
        elif pc == 0x4d352bc40:
            assert self.x(0) == HANDLE
            offset, whence = self.x(1), self.x(2)
            offset -= (1 << 64) if offset >> 63 else 0
            self.position = offset + (self.position if whence == 1 else
                                      len(self.data) if whence == 2 else 0)
            self.calls.append(('fseek', offset, whence))
            self.finish_mock()
        elif pc == 0x4d352bb50:
            self.put(self.x(1), self.position)
            self.finish_mock()
        elif pc == 0x4d352bb20:
            self.calls.append(('fclose', self.x(0)))
            self.finish_mock()
        elif pc == 0x4d3001690:
            self.calls.append(('delay_syscall_argument', self.x(0)))
            self.finish_mock()
        elif pc == 0x4d3001770:
            u.mem_write(self.x(0), struct.pack('<II', 0x123, 0xabcdef))
            self.finish_mock()

    def run(self, address, *arguments):
        self.uc.reg_write(r.UC_ARM64_REG_SP, RAM + 0xf000)
        self.uc.reg_write(r.UC_ARM64_REG_LR, STOP)
        for i, value in enumerate(arguments):
            self.uc.reg_write(getattr(r, 'UC_ARM64_REG_X' + str(i)), value & ((1 << 64) - 1))
        self.uc.emu_start(address, STOP, count=200000)
        assert self.uc.reg_read(r.UC_ARM64_REG_PC) == STOP, 'instruction budget exhausted'
        return self.x(0)


class FirmwareCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if Uc is None:
            raise unittest.SkipTest('unicorn required')
        if not FIRMWARE.is_file():
            raise unittest.SkipTest('decoded-V104/rtos-alt.bin required')
        cls.firmware = FIRMWARE.read_bytes()
        if hashlib.sha256(cls.firmware).hexdigest() != IMAGE_HASH:
            raise AssertionError('BF 1.04 segment-05 firmware identity mismatch')

    def setUp(self):
        self.m = FileMachine(self.firmware)


class NativeDoomStorageTests(FirmwareCase):
    def test_open_read_only_and_caller_path_unchanged(self):
        self.assertEqual(self.m.run(OPEN, PATH, 0), HANDLE)
        self.assertEqual(self.m.cstring(PATH), b'J:\\DOOM.BFP')
        self.assertEqual(self.m.calls[-1], ('fopen', b'0:\\DOOM.BFP', b'r'))

    def test_open_failure(self):
        self.m.open_fails = True
        self.assertEqual(self.m.run(OPEN, PATH, 0), 0)

    def test_open_null_path(self):
        self.assertEqual(self.m.run(OPEN, 0, 0), 0)
        self.assertEqual(self.m.calls, [])

    def test_open_rejects_528_byte_path(self):
        self.m.uc.mem_write(PATH, b'Z' * 528 + b'\0')
        self.assertEqual(self.m.run(OPEN, PATH, 0), 0)
        self.assertEqual(self.m.calls, [])

    def check_read(self, requested, expected_status, expected_count):
        self.m.uc.mem_write(OUT, b'\xaa' * 16)
        self.assertEqual(self.m.run(READ, HANDLE, BUFFER, requested, OUT), expected_status)
        self.assertEqual(self.m.get(OUT, 4), expected_count)
        self.assertEqual(bytes(self.m.uc.mem_read(OUT + 4, 12)), b'\xaa' * 12)

    def test_read_exact_and_u32_count(self):
        self.check_read(12, 0, 12)
        self.assertEqual(bytes(self.m.uc.mem_read(BUFFER, 12)), self.m.data[:12])

    def test_read_short_eof_and_u32_count(self):
        self.m.position = 12
        self.check_read(100, 4, 52)

    def test_read_at_eof(self):
        self.m.position = len(self.m.data)
        self.check_read(1, 4, 0)

    def test_read_non_eof_error(self):
        self.m.read_fails = True
        self.check_read(12, 1, 0)

    def test_read_semaphore_timeout(self):
        self.m.lock_fails = True
        self.check_read(12, 1, 0)

    def check_seek(self, offset, whence, expected):
        self.m.uc.mem_write(OUT, b'\xaa' * 16)
        self.assertEqual(self.m.run(SEEK, HANDLE, offset, whence, OUT), 0)
        self.assertEqual(self.m.calls[-1], ('fseek', offset, whence))
        self.assertEqual(self.m.get(OUT), expected)
        self.assertEqual(bytes(self.m.uc.mem_read(OUT + 8, 8)), b'\xaa' * 8)

    def test_seek_end_u64_output(self):
        self.check_seek(0, 2, 64)

    def test_seek_negative_offset(self):
        self.check_seek(-12, 2, 52)

    def test_seek_absolute(self):
        self.check_seek(4, 0, 4)

    def test_seek_relative(self):
        self.m.position = 4
        self.check_seek(8, 1, 12)

    def test_seek_invalid_whence(self):
        self.assertEqual(self.m.run(SEEK, HANDLE, 0, 3, OUT), 1)
        self.assertEqual(self.m.calls, [])

    def test_seek_null_position(self):
        self.assertEqual(self.m.run(SEEK, HANDLE, 0, 0, 0), 1)
        self.assertEqual(self.m.calls, [])

    def test_close_64_bit_handle(self):
        self.m.run(CLOSE, HANDLE)
        self.assertEqual(self.m.calls[-1], ('fclose', HANDLE))

    def test_sleep_adds_one_to_kernel_delay(self):
        self.assertEqual(self.m.run(0x4d3033660, 28), 0)
        self.assertEqual(self.m.calls[-1], ('delay_syscall_argument', 29))

    def test_timestamp_combines_kernel_high_and_low_words(self):
        self.assertEqual(self.m.run(0x4d3033bb0, OUT), 0)
        self.assertEqual(self.m.get(OUT), (0x123 << 32) | 0xabcdef)


def compile_storage_probes():
    """Compile to stdout and read just .text/symbols from this trusted ELF64.

    No pyelftools dependency or temporary files. Reject relocations rather than
    pretending to link them; these probes use fixed native function addresses.
    """
    llvm = Path('/opt/homebrew/opt/llvm/bin/clang')
    compiler = str(llvm) if llvm.is_file() else shutil.which('clang')
    if not compiler:
        raise unittest.SkipTest('AArch64-capable clang required')
    source = b'''#include "bfplus/doom_storage.h"
DoomFile probe_open(const char *p) { return doom_file_open(p); }
int32_t probe_read(DoomFile f,void *p,uint32_t n) { return doom_file_read(f,p,n); }
void probe_close(DoomFile f) { doom_file_close(f); }
'''
    result = subprocess.run(
        [compiler, '--target=aarch64-none-elf', '-O2', '-ffreestanding',
         '-fno-builtin', '-fno-stack-protector', '-Wall', '-Wextra', '-Werror',
         '-I', str(ROOT), '-x', 'c', '-c', '-o', '-', '-'],
        input=source, capture_output=True, timeout=30)
    if result.returncode:
        raise AssertionError(result.stderr.decode())
    obj = result.stdout
    assert obj[:6] == b'\x7fELF\x02\x01'
    assert struct.unpack_from('<H', obj, 18)[0] == 183  # EM_AARCH64.
    shoff = struct.unpack_from('<Q', obj, 40)[0]
    shsize, shnum, shstr = struct.unpack_from('<HHH', obj, 58)
    sections = [struct.unpack_from('<IIQQQQIIQQ', obj, shoff + i * shsize)
                for i in range(shnum)]

    def data(section):
        return obj[section[4]:section[4] + section[5]]

    def name(strings, offset):
        return strings[offset:].split(b'\0')[0].decode()

    names = data(sections[shstr])
    by_name = {name(names, s[0]): s for s in sections}
    assert not any(s[1] in (4, 9) and s[5] for s in sections), 'unlinked relocations'
    code = data(by_name['.text'])
    assert len(code) <= 0x2000, 'probe overlaps emulator stack'
    sym = by_name['.symtab']
    strings, symbols = data(sections[sym[6]]), {}
    for at in range(sym[4], sym[4] + sym[5], sym[9]):
        no, info, other, ndx, value, size = struct.unpack_from('<IBBHQQ', obj, at)
        symbol = name(strings, no)
        if symbol.startswith('probe_'):
            assert sections[ndx] == by_name['.text']
            symbols[symbol] = CODE + value
    assert set(symbols) == {'probe_open', 'probe_read', 'probe_close'}
    return code, symbols


class CompiledDoomStorageTests(FirmwareCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.code, cls.symbols = compile_storage_probes()

    def setUp(self):
        super().setUp()
        self.m.uc.mem_write(CODE, self.code)

    def call(self, name, *arguments):
        return self.m.run(self.symbols['probe_' + name], *arguments)

    def test_open_uses_native_read_only_chain(self):
        self.assertEqual(self.call('open', PATH), HANDLE)
        self.assertEqual(self.m.calls[-1], ('fopen', b'0:\\DOOM.BFP', b'r'))

    def test_read_exact_returns_count(self):
        self.assertEqual(self.call('read', HANDLE, BUFFER, 12), 12)

    def test_read_short_returns_count(self):
        self.m.position = 12
        self.assertEqual(self.call('read', HANDLE, BUFFER, 100), 52)

    def test_read_eof_returns_zero(self):
        self.m.position = len(self.m.data)
        self.assertEqual(self.call('read', HANDLE, BUFFER, 1), 0)

    def test_read_native_error_returns_minus_one(self):
        self.m.read_fails = True
        self.assertEqual(self.call('read', HANDLE, BUFFER, 1), 0xffffffff)

    def test_read_lock_timeout_returns_minus_one(self):
        self.m.lock_fails = True
        self.assertEqual(self.call('read', HANDLE, BUFFER, 1), 0xffffffff)

    def test_read_invalid_or_zero_length_avoids_native_calls(self):
        for file, buffer, count, expected in (
                (0, BUFFER, 1, 0xffffffff), (HANDLE, 0, 1, 0xffffffff),
                (HANDLE, BUFFER, 0x80000000, 0xffffffff), (HANDLE, 0, 0, 0)):
            with self.subTest(file=file, buffer=buffer, count=count):
                self.assertEqual(self.call('read', file, buffer, count), expected)
        self.assertEqual(self.m.calls, [])

    def test_close_reaches_native_close(self):
        self.call('close', HANDLE)
        self.assertEqual(self.m.calls[-1], ('fclose', HANDLE))

    def test_null_close_and_null_or_empty_open_avoid_native_calls(self):
        self.call('close', 0)
        self.assertEqual(self.call('open', 0), 0)
        self.m.uc.mem_write(PATH, b'\0')
        self.assertEqual(self.call('open', PATH), 0)
        self.assertEqual(self.m.calls, [])


if __name__ == '__main__':
    unittest.main()
