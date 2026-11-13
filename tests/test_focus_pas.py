"""Original no-contact PAS adapter in AArch64, with local native firmware.

No camera access. Executes the native fallback and byte-fill routine. Only the
electronic-lens class query and the profile getter's leaf are observed/stubbed.
"""
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest

from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_CODE
from unicorn import arm64_const as r
from touch_focus.build import tool
from bf_touch_focus import branch_instruction

ROOT = Path(__file__).resolve().parents[1]
FIRMWARE = ROOT/'decoded-V104/rtos-alt.bin'
CODE, STACK, DATA = 0x440000000, 0x100000, 0x200000
ISLAND, NATIVE = 0x4d3321190, 0x4d3000000
LEFT, RIGHT = 0x41a0d1c94, 0x41a0d1e94


@unittest.skipUnless(FIRMWARE.is_file(), 'requires supplied BF 1.04 segment05')
class FocusPasTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.firmware = FIRMWARE.read_bytes()
        cls.directory = tempfile.TemporaryDirectory(prefix='bf-pas-arm-')
        cls.addClassCleanup(cls.directory.cleanup)
        d = Path(cls.directory.name)
        (d/'pas.c').write_text('''
typedef unsigned char u8;
typedef unsigned short u16;
typedef unsigned int u32;
typedef unsigned long long u64;
typedef u64 uptr;
static u32 lens(void) { return ((u32 (*)(void))(uptr)0x4d31d48c0ULL)(); }
#include "focus_pas.h"
''')
        (d/'pas.ld').write_text('''SECTIONS {
 . = 0; .text : { *(.text*) } .rodata : { *(.rodata*) }
 .data : { *(.data*) } .bss : { *(.bss*) }
 /DISCARD/ : { *(.comment) *(.note*) *(.eh_frame*) }
}''')
        cc = tool('clang', '/opt/homebrew/opt/llvm/bin/clang')
        ld = tool('ld.lld', '/opt/homebrew/opt/lld/bin/ld.lld')
        nm = tool('llvm-nm', '/opt/homebrew/opt/llvm/bin/llvm-nm')
        objcopy = tool('llvm-objcopy', '/opt/homebrew/opt/llvm/bin/llvm-objcopy')
        subprocess.run([cc, '--target=aarch64-none-elf', '-Os', '-ffreestanding',
                        '-fno-builtin', '-fno-stack-protector', '-fno-unwind-tables',
                        '-fno-asynchronous-unwind-tables', '-mgeneral-regs-only',
                        '-ffixed-x18', '-mcmodel=tiny', '-fpie', '-fvisibility=hidden',
                        '-Wall', '-Wextra', '-Werror', '-I', str(ROOT/'touch_focus'),
                        '-c', str(d/'pas.c'), '-o', str(d/'pas.o')], check=True)
        subprocess.run([ld, '-T', str(d/'pas.ld'), '-e', 'focus_pas_wrapper',
                        str(d/'pas.o'), '-o', str(d/'pas.elf')], check=True)
        subprocess.run([objcopy, '-O', 'binary', str(d/'pas.elf'), str(d/'pas.bin')], check=True)
        cls.blob = (d/'pas.bin').read_bytes()
        cls.symbols = {}
        for line in subprocess.check_output([nm, '--defined-only', str(d/'pas.elf')], text=True).splitlines():
            fields = line.split()
            if len(fields) == 3: cls.symbols[fields[2]] = int(fields[0], 16)

    def setUp(self):
        self.u = u = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
        u.mem_map(NATIVE, 0x4400000); u.mem_write(NATIVE, self.firmware)
        for base in (CODE, STACK, DATA, LEFT & ~0xffff): u.mem_map(base, 0x10000)
        u.mem_write(CODE, self.blob)
        u.mem_write(LEFT-16, bytes([0xa5])*(1024+32))
        self.lens = 0
        self.profile_calls = []
        self.lens_calls = 0
        self.memset_calls = 0
        def observe(u, pc, size, _):
            if pc == 0x4d31d48c0:
                self.lens_calls += 1
                u.reg_write(r.UC_ARM64_REG_X0, self.lens)
            elif pc == 0x4d31a2d00:
                self.profile_calls.append((u.reg_read(r.UC_ARM64_REG_X0), u.reg_read(r.UC_ARM64_REG_X1)))
                u.mem_write(u.reg_read(r.UC_ARM64_REG_X1), b'profile!')
            elif pc == 0x4d3008200:
                self.memset_calls += 1
                return  # execute real native memset
            else: return
            u.reg_write(r.UC_ARM64_REG_PC, u.reg_read(r.UC_ARM64_REG_LR))
        u.hook_add(UC_HOOK_CODE, observe)
        # Original branch island encoding; relocates to the test payload.
        u.mem_write(ISLAND, struct.pack('<IIQ', 0x58000050, 0xd61f0200,
                                        CODE+self.symbols['focus_pas_wrapper']))
        for call in (0x4d32ca044, 0x4d32ca054):
            u.mem_write(call, struct.pack('<I', branch_instruction(call, ISLAND, True)))

    def run_code(self, start, stop):
        self.u.reg_write(r.UC_ARM64_REG_SP, STACK+0x8000)
        self.u.reg_write(r.UC_ARM64_REG_LR, stop)
        for n in range(18, 30): self.u.reg_write(getattr(r, f'UC_ARM64_REG_X{n}'), 0xabc000+n)
        self.u.emu_start(start, stop, count=30000)
        self.assertEqual(self.u.reg_read(r.UC_ARM64_REG_PC), stop)
        self.assertEqual(self.u.reg_read(r.UC_ARM64_REG_SP), STACK+0x8000)
        for n in range(18, 30): self.assertEqual(self.u.reg_read(getattr(r, f'UC_ARM64_REG_X{n}')), 0xabc000+n)

    def config(self, enabled=1):
        self.u.mem_write(CODE+self.symbols['focus_pas'], struct.pack('<4I', enabled, 0, 0, 0))

    def state(self):
        return struct.unpack('<4I', self.u.mem_read(CODE+self.symbols['focus_pas'], 16))

    def fallback(self):
        self.u.mem_write(STACK+0x8090, struct.pack('<QQ', LEFT, RIGHT))
        self.run_code(0x4d32ca038, 0x4d32ca058)
        self.assertEqual(bytes(self.u.mem_read(LEFT-16, 16)), bytes([0xa5])*16)
        self.assertEqual(bytes(self.u.mem_read(RIGHT+512, 16)), bytes([0xa5])*16)

    def test_enabled_no_contact_fallback_fills_native_reference_values(self):
        self.config(); self.fallback()
        self.assertEqual(bytes(self.u.mem_read(LEFT, 1024)), b'\x00\x10'*512)
        self.assertEqual(self.state(), (1, 2, 0, 0))
        self.assertEqual(self.memset_calls, 0)

    def test_disabled_default_preserves_exact_stock_zero_fill(self):
        self.fallback()
        self.assertEqual(bytes(self.u.mem_read(LEFT, 1024)), bytes(1024))
        self.assertEqual(self.state(), (0, 0, 2, 0))
        self.assertEqual(self.memset_calls, 2)

    def test_other_lens_classes_do_not_gain_manual_override(self):
        for kind in (1, 2, 0xffffffff):
            with self.subTest(kind=kind):
                self.lens = kind; self.config(); self.fallback()
                self.assertEqual(bytes(self.u.mem_read(LEFT, 1024)), bytes(1024))
                self.assertEqual(self.state(), (1, 0, 2, kind))

    def test_native_profile_calls_pass_through_with_original_guard(self):
        self.config()
        for slot in (0, 9, 10):
            self.u.reg_write(r.UC_ARM64_REG_X0, slot)
            self.u.reg_write(r.UC_ARM64_REG_X1, DATA)
            self.u.reg_write(r.UC_ARM64_REG_X2, 0xdeadbeef)
            self.run_code(ISLAND, CODE+0xf000)
        self.assertEqual(self.profile_calls, [(0, DATA), (9, DATA)])
        self.assertEqual(self.lens_calls, 0)
        self.assertEqual(self.memset_calls, 0)
        self.assertEqual(self.state(), (1, 0, 0, 0))

    def test_wrong_destination_value_length_or_enable_retains_memset(self):
        for address, value, size, enabled in ((RIGHT, 0x1000, 512, 1),
                                             (LEFT, 0x20, 512, 1),
                                             (LEFT, 0x1000, 510, 1),
                                             (LEFT, 0x1000, 512, 2)):
            with self.subTest(address=address, value=value, size=size, enabled=enabled):
                self.config(enabled)
                for reg, val in ((r.UC_ARM64_REG_X0, address), (r.UC_ARM64_REG_X1, value),
                                 (r.UC_ARM64_REG_X2, size)):
                    self.u.reg_write(reg, val)
                self.run_code(CODE+self.symbols['focus_pas_wrapper'], 0x4d32ca048)
                self.assertEqual(bytes(self.u.mem_read(address, size)), bytes([value & 255])*size)
                self.assertEqual(self.state(), (enabled, 0, 1, 0))


if __name__ == '__main__': unittest.main()
