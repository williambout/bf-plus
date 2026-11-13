"""Freestanding guide execution and optional stock phase-worker gate checks.

No USB access. Native firmware stays local; only original code is compiled.
"""
import ctypes as C
from pathlib import Path
import subprocess
import tempfile
import unittest
import struct

from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_CODE
from unicorn import arm64_const as r
from touch_focus.build import tool
from tests.test_focus_guide import Guide, Config, Sample, Mark
from tests.test_focus_guide_probe import manual_table
from bf_focus_guide_probe import decode_manual_lenses, MANUAL_LENSES, SETTINGS

ROOT = Path(__file__).resolve().parents[1]
FIRMWARE = ROOT / 'decoded-V104/rtos-alt.bin'
CODE, STACK, DATA = 0x100000,0x200000,0x300000
STOP, PAINT = CODE+0xf000,CODE+0xf100


class GuideArmTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix='bf-guide-arm-')
        cls.addClassCleanup(cls.directory.cleanup)
        directory = Path(cls.directory.name)
        obj,elf,binary = [directory / name for name in ('guide.o','guide.elf','guide.bin')]
        compiler = tool('clang','/opt/homebrew/opt/llvm/bin/clang')
        linker = tool('ld.lld','/opt/homebrew/opt/lld/bin/ld.lld')
        objcopy = tool('llvm-objcopy','/opt/homebrew/opt/llvm/bin/llvm-objcopy')
        nm = tool('llvm-nm','/opt/homebrew/opt/llvm/bin/llvm-nm')
        subprocess.run([compiler,'--target=aarch64-none-elf','-std=c11','-Os',
                        '-ffreestanding','-fno-builtin','-fno-stack-protector',
                        '-fno-unwind-tables','-fno-asynchronous-unwind-tables',
                        '-mgeneral-regs-only','-ffixed-x18','-fno-jump-tables',
                        '-mcmodel=tiny','-fpie','-fvisibility=hidden','-Wall','-Wextra','-Werror',
                        '-c',str(ROOT/'touch_focus/focus_guide.c'),'-o',str(obj)],check=True)
        # No libc/runtime is supplied. This catches aggregate initialization or
        # arithmetic unexpectedly lowering to missing helper functions.
        subprocess.run([linker,'--image-base=0','-Ttext=0x100000','-e','focus_guide_init',
                        str(obj),'-o',str(elf)],check=True)
        subprocess.run([objcopy,'-O','binary',str(elf),str(binary)],check=True)
        cls.blob = binary.read_bytes()
        cls.symbols = {}
        for line in subprocess.check_output([nm,'--defined-only',str(elf)],text=True).splitlines():
            fields = line.split()
            if len(fields)==3: cls.symbols[fields[2]] = int(fields[0],16)

    def setUp(self):
        self.uc = Uc(UC_ARCH_ARM64,UC_MODE_ARM)
        for address in (CODE,STACK,DATA): self.uc.mem_map(address,0x10000)
        self.uc.mem_write(CODE,self.blob)
        self.marks = []
        self.uc.hook_add(UC_HOOK_CODE,self.hook)
        self.call('init',DATA)
        self.uc.mem_write(DATA+0x200,bytes(Config(10,16,80,200,800,3)))
        self.call('configure',DATA,DATA+0x200)
        self.call('mode',DATA,1,1,0)

    def hook(self,u,pc,size,opaque):
        if pc==PAINT:
            self.marks.append(Mark.from_buffer_copy(u.mem_read(u.reg_read(r.UC_ARM64_REG_X1),C.sizeof(Mark))))
            u.reg_write(r.UC_ARM64_REG_PC,u.reg_read(r.UC_ARM64_REG_LR))

    def call(self,name,*args):
        for index,value in enumerate(args): self.uc.reg_write(getattr(r,f'UC_ARM64_REG_X{index}'),value)
        self.uc.reg_write(r.UC_ARM64_REG_SP,STACK+0xf000)
        self.uc.reg_write(r.UC_ARM64_REG_LR,STOP)
        self.uc.reg_write(r.UC_ARM64_REG_X18,0xfeed1234)
        self.uc.emu_start(self.symbols['focus_guide_'+name],STOP,count=20000)
        self.assertEqual(self.uc.reg_read(r.UC_ARM64_REG_PC),STOP)
        self.assertEqual(self.uc.reg_read(r.UC_ARM64_REG_X18),0xfeed1234)
        return Guide.from_buffer_copy(self.uc.mem_read(DATA,C.sizeof(Guide)))

    def test_target_binary_directions_confirmation_render_expiry_and_hide(self):
        guide = self.call('update',DATA,0,1000)
        self.assertEqual(guide.state,1)
        for sequence,(error,expected) in enumerate(((100,2),(20,3),(-20,5),(-100,6),(0,1),(0,1),(0,4)),1):
            now = 1000+sequence*20
            sample = Sample(error,900,1,now,sequence,guide.generation)
            self.uc.mem_write(DATA+0x100,bytes(sample))
            guide = self.call('update',DATA,DATA+0x100,now)
            self.assertEqual(guide.state,expected)
        self.call('paint',DATA,now,PAINT,0)
        self.assertEqual(len(self.marks),11)
        self.assertEqual({mark.color for mark in self.marks},{2})
        self.marks.clear()
        self.call('paint',DATA,now+201,PAINT,0)
        self.assertEqual({mark.color for mark in self.marks},{0})
        self.call('mode',DATA,1,1,1)
        self.marks.clear()
        self.call('paint',DATA,now+220,PAINT,0)
        self.assertFalse(self.marks)


@unittest.skipUnless(FIRMWARE.is_file(),'requires supplied BF 1.04 segment05')
class StockPhaseGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.firmware = FIRMWARE.read_bytes()

    def gate(self,start,stops,lens,protocol=0,capability=0x78):
        u = Uc(UC_ARCH_ARM64,UC_MODE_ARM)
        u.mem_map(0x4d3000000,0x4400000)
        u.mem_write(0x4d3000000,self.firmware)
        u.mem_map(STACK,0x10000); u.mem_map(DATA,0x1000)
        u.reg_write(r.UC_ARM64_REG_SP,STACK+0xf000)
        u.mem_write(DATA,bytes((0,capability)))
        reached = []
        def hook(u,pc,size,opaque):
            if pc in stops:
                reached.append(pc); u.emu_stop(); return
            if pc==0x4d31d48c0: value = lens
            elif pc==0x4d31d5080: value = protocol
            elif pc in (0x4d31d53d0,0x4d31d54b0): value = DATA
            else: return
            u.reg_write(r.UC_ARM64_REG_X0,value)
            u.reg_write(r.UC_ARM64_REG_PC,u.reg_read(r.UC_ARM64_REG_LR))
        u.hook_add(UC_HOOK_CODE,hook)
        u.emu_start(start,0,count=1000)
        self.assertEqual(len(reached),1)
        return reached[0]

    def test_stock_initialization_and_per_frame_paths_require_compatible_lens(self):
        for start,skip,compute in ((0x4d32ca02c,0x4d32ca038,0x4d32ca0a0),
                                   (0x4d32c9f44,0x4d32c9f50,0x4d32ca0f8)):
            for lens,protocol,capability,allowed in ((0,0,0x78,False),(1,0,0x78,False),
                                                     (2,0,0x78,True),(2,0,0,False),
                                                     (2,1,0x0f,True),(2,1,0,False)):
                with self.subTest(start=hex(start),lens=lens,protocol=protocol,capability=capability):
                    self.assertEqual(self.gate(start,(skip,compute),lens,protocol,capability),
                                     compute if allowed else skip)


@unittest.skipUnless(FIRMWARE.is_file(), 'requires supplied BF 1.04 segment05')
class StockPhaseTableTests(unittest.TestCase):
    """Execute both native table-fill blocks; no hardware calls or USB access."""
    @classmethod
    def setUpClass(cls): cls.firmware = FIRMWARE.read_bytes()

    def machine(self):
        u = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
        u.mem_map(0x4d3000000, 0x4400000)
        u.mem_write(0x4d3000000, self.firmware)
        u.mem_map(STACK, 0x10000); u.mem_map(DATA, 0x2000)
        u.mem_write(DATA, bytes([0xa5])*0x2000)
        u.reg_write(r.UC_ARM64_REG_SP, STACK+0x8000)
        return u

    def test_no_contact_fallback_clears_bytes_despite_0x1000_argument(self):
        u = self.machine()
        left, right = DATA+0x100, DATA+0x800
        u.mem_write(STACK+0x8090, struct.pack('<QQ', left, right))
        # Executes original libc memset too, stopping before native SPT setup.
        u.emu_start(0x4d32ca038, 0x4d32ca058, count=10000)
        self.assertEqual(u.reg_read(r.UC_ARM64_REG_PC), 0x4d32ca058)
        for pointer in (left, right):
            self.assertEqual(bytes(u.mem_read(pointer, 512)), bytes(512))
            self.assertEqual(bytes(u.mem_read(pointer-16, 16)), bytes([0xa5])*16)
            self.assertEqual(bytes(u.mem_read(pointer+512, 16)), bytes([0xa5])*16)

    def test_native_reference_fill_uses_256_halfwords_of_0x1000(self):
        # Exercise aligned and misaligned vector-loop prologues from the real
        # initializer, without executing its lens table lookups or MMIO setup.
        for alignment in (0, 2, 4, 6, 8, 10, 12, 14):
            with self.subTest(alignment=alignment):
                u = self.machine()
                left, right = DATA+0x100+alignment, DATA+0x800+alignment
                u.mem_write(STACK+0x80c8, struct.pack('<QQ', left, right))
                u.emu_start(0x4d32c5b6c, 0x4d32c5d6c, count=10000)
                self.assertEqual(u.reg_read(r.UC_ARM64_REG_PC), 0x4d32c5d6c)
                for pointer in (left, right):
                    self.assertEqual(bytes(u.mem_read(pointer, 512)), b'\x00\x10'*256)
                    self.assertEqual(bytes(u.mem_read(pointer-16, 16)), bytes([0xa5])*16)
                    self.assertEqual(bytes(u.mem_read(pointer+512, 16)), bytes([0xa5])*16)


@unittest.skipUnless(FIRMWARE.is_file(), 'requires supplied BF 1.04 segment05')
class StockManualLensTests(unittest.TestCase):
    """Execute the real profile getters and electronic snapshot independently.

    This verifies the metadata distinction without enabling any camera code.
    Only RTOS event queries and libc copies are replaced with local stubs.
    """
    @classmethod
    def setUpClass(cls): cls.firmware = FIRMWARE.read_bytes()

    def setUp(self):
        self.uc = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
        self.uc.mem_map(0x4d3000000, 0x4400000)
        self.uc.mem_write(0x4d3000000, self.firmware)
        for address in (CODE, STACK, DATA): self.uc.mem_map(address, 0x10000)
        self.uc.mem_write(MANUAL_LENSES, struct.pack('<Q', DATA))
        self.uc.mem_write(SETTINGS, struct.pack('<Q', DATA + 0x104))
        self.uc.mem_write(DATA, bytes(manual_table()))
        self.uc.mem_write(DATA + 0x1b8, struct.pack('<I', 4))
        self.uc.hook_add(UC_HOOK_CODE, self.hook)

    def hook(self, u, pc, size, opaque):
        x0, x1, x2 = [u.reg_read(reg) for reg in
                      (r.UC_ARM64_REG_X0, r.UC_ARM64_REG_X1, r.UC_ARM64_REG_X2)]
        if pc == 0x4d3033890:  # no electronic lens-connected event
            u.mem_write(x1, bytes(16))
            u.reg_write(r.UC_ARM64_REG_X0, 0)
        elif pc == 0x4d3008200:
            self.assertLessEqual(x2, 0x80)
            u.mem_write(x0, bytes([x1 & 255]) * x2)
        elif pc == 0x4d3007fc0:
            self.assertLessEqual(x2, 0x80)
            u.mem_write(x0, bytes(u.mem_read(x1, x2)))
        else:
            return
        u.reg_write(r.UC_ARM64_REG_PC, u.reg_read(r.UC_ARM64_REG_LR))

    def call(self, address, *args):
        for index, value in enumerate(args):
            self.uc.reg_write(getattr(r, f'UC_ARM64_REG_X{index}'), value)
        self.uc.reg_write(r.UC_ARM64_REG_SP, STACK + 0xf000)
        self.uc.reg_write(r.UC_ARM64_REG_LR, STOP)
        self.uc.emu_start(address, STOP, count=1000)
        self.assertEqual(self.uc.reg_read(r.UC_ARM64_REG_PC), STOP)
        return self.uc.reg_read(r.UC_ARM64_REG_X0)

    def test_registered_lens_supplies_focal_length_but_not_electronic_phase_metadata(self):
        selected = self.call(0x4d3321150)
        self.assertEqual(selected, 4)
        output = DATA + 0x200
        self.call(0x4d33184c0, selected, output)
        self.assertEqual(bytes(self.uc.mem_read(output, 8)), bytes(manual_table()[0x38:0x40]))
        self.call(0x4d31489f0, output)
        self.assertEqual(struct.unpack('<H', self.uc.mem_read(output + 0x22, 2))[0], 350)
        decoded = decode_manual_lenses(bytes(self.uc.mem_read(DATA, 0x79)), selected)
        self.assertEqual(decoded['selected_profile']['focal_length_mm'] * 10, 350)
        # The phase initializer obtains its 128-byte lens snapshot from this
        # separate getter. The custom profile does not enter this path.
        self.uc.mem_write(output, b'\xa5' * 0x80)
        self.call(0x4d31d4910, output)
        self.assertEqual(bytes(self.uc.mem_read(output, 0x80)), bytes(0x80))

    def test_native_profile_getter_leaves_sentinel_selection_unread(self):
        output = DATA + 0x200
        self.uc.mem_write(output, b'\xa5' * 8)
        for selection in (10, 11, 255, 0xffffffff):
            self.call(0x4d33184c0, selection, output)
            self.assertEqual(bytes(self.uc.mem_read(output, 8)), b'\xa5' * 8)


if __name__=='__main__': unittest.main()
