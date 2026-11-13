"""AArch64 guide painter + actual BF 1.04 rectangle routine, synthetic RAM.

Checks framebuffer writes and dirty rows, not physical colors or presentation.
No device access and no stubs in the drawing path.
"""
import ctypes as C
import hashlib
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest

from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM
from unicorn import arm64_const as r
from touch_focus.build import tool
from tests.test_focus_guide import (Config, Guide, Mark, Sample, Paint, compile_guide,
    HIDDEN, UNAVAILABLE, FAR_LARGE, FAR_SMALL, FOCUSED, NEAR_SMALL, NEAR_LARGE,
    GRAY, WHITE, GREEN, RECT, TRIANGLE)

ROOT = Path(__file__).resolve().parents[1]
FIRMWARE = ROOT/'decoded-V104/rtos-alt.bin'
FW_BASE, CODE, STACK, DATA, PIX = 0x4d3000000, 0x100000, 0x200000, 0x300000, 0x800000
STOP, MARK = CODE+0xf000, DATA+0x100
COLORS = {GRAY: 0x888f, WHITE: 0xffff, GREEN: 0x0f0f}


@unittest.skipUnless(FIRMWARE.is_file(), 'requires user-supplied decoded BF 1.04 firmware')
class NativeGuidePainterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.firmware = FIRMWARE.read_bytes()
        if hashlib.sha256(cls.firmware).hexdigest() != 'f747c1350f00526b9c68c65aaef44d6e7b644b0169992342e12f059c42e150dc':
            raise RuntimeError('Native drawing tests require the exact BF 1.04 firmware')
        cls.directory = tempfile.TemporaryDirectory(prefix='bf-guide-render-')
        cls.addClassCleanup(cls.directory.cleanup)
        d = Path(cls.directory.name)
        cls.lib = compile_guide(d)
        cc = tool('clang', '/opt/homebrew/opt/llvm/bin/clang')
        subprocess.run([cc, '--target=aarch64-none-elf', '-Oz', '-ffreestanding',
                        '-fno-builtin', '-fno-stack-protector', '-fno-unwind-tables',
                        '-fno-asynchronous-unwind-tables', '-mgeneral-regs-only',
                        '-ffixed-x18', '-mcmodel=tiny', '-fpie', '-fvisibility=hidden',
                        '-Wall', '-Wextra', '-Werror', '-c',
                        str(ROOT/'touch_focus/focus_guide_render.c'), '-o', str(d/'render.o')], check=True)
        ld = tool('ld.lld', '/opt/homebrew/opt/lld/bin/ld.lld')
        objcopy = tool('llvm-objcopy', '/opt/homebrew/opt/llvm/bin/llvm-objcopy')
        nm = tool('llvm-nm', '/opt/homebrew/opt/llvm/bin/llvm-nm')
        subprocess.run([ld, '--image-base=0', '-Ttext=0x100000', '-e', 'focus_guide_native_mark',
                        str(d/'render.o'), '-o', str(d/'render.elf')], check=True)
        if subprocess.check_output([nm, '--undefined-only', str(d/'render.elf')], text=True).strip():
            raise RuntimeError('Native painter has unresolved runtime dependencies')
        subprocess.run([objcopy, '-O', 'binary', str(d/'render.elf'), str(d/'render.bin')], check=True)
        cls.arm = (d/'render.bin').read_bytes()
        cls.entry = next(int(line.split()[0], 16) for line in subprocess.check_output(
            [nm, '--defined-only', str(d/'render.elf')], text=True).splitlines()
            if line.split()[-1] == 'focus_guide_native_mark')

    def setUp(self):
        self.u = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
        for address, size in ((FW_BASE, (len(self.firmware)+4095)&~4095),
                              (CODE, 0x10000), (STACK, 0x10000), (DATA, 0x10000), (PIX, 0x400000)):
            self.u.mem_map(address, size)
        self.u.mem_write(FW_BASE, self.firmware)
        self.u.mem_write(CODE, self.arm)
        self.u.reg_write(r.UC_ARM64_REG_CPACR_EL1, 3 << 20)

    def surface(self, pitch=2048, alignment=0, height=682, pixels=None, dirty=(682, 0)):
        self.pitch, self.start = pitch, 64+alignment
        self.before = bytes([0xa5])*(self.start+max(pitch, 2048)*682+64)
        self.u.mem_write(PIX, self.before)
        desc = bytearray([0x79])*32
        struct.pack_into('<HH', desc, 0, *dirty)
        struct.pack_into('<Q', desc, 8, PIX+self.start if pixels is None else pixels)
        struct.pack_into('<H', desc, 0x10, pitch)
        struct.pack_into('<H', desc, 0x14, height)
        self.desc = bytes(desc)
        self.u.mem_write(DATA, self.desc)

    def paint(self, mark, surface=DATA, mark_address=MARK):
        if mark is not None:
            self.u.mem_write(MARK, bytes(mark))
        self.u.reg_write(r.UC_ARM64_REG_X0, surface)
        self.u.reg_write(r.UC_ARM64_REG_X1, mark_address)
        self.u.reg_write(r.UC_ARM64_REG_SP, STACK+0x8000)
        self.u.reg_write(r.UC_ARM64_REG_LR, STOP)
        for n in range(18, 30):
            self.u.reg_write(getattr(r, f'UC_ARM64_REG_X{n}'), 0xfeed0000+n)
        self.u.emu_start(self.entry, STOP, count=2000000)
        self.assertEqual(self.u.reg_read(r.UC_ARM64_REG_PC), STOP)
        self.assertEqual(self.u.reg_read(r.UC_ARM64_REG_SP), STACK+0x8000)
        for n in range(18, 30):
            self.assertEqual(self.u.reg_read(getattr(r, f'UC_ARM64_REG_X{n}')), 0xfeed0000+n)
        if mark is not None:
            self.assertEqual(bytes(self.u.mem_read(MARK, C.sizeof(Mark))), bytes(mark))

    def check(self, pixels, dirty=None):
        expected = bytearray(self.before)
        for (x, y), color in pixels.items():
            offset = self.start+y*self.pitch+2*x
            expected[offset:offset+2] = struct.pack('<H', COLORS[color])
        self.assertEqual(bytes(self.u.mem_read(PIX, len(expected))), bytes(expected))
        desc = bytearray(self.desc)
        if dirty is None and pixels:
            rows = [y for _, y in pixels]
            old_start, old_end = struct.unpack_from('<HH', desc)
            dirty = min(old_start, min(rows)), max(old_end, max(rows)+1)
        if dirty is not None:
            struct.pack_into('<HH', desc, 0, *dirty)
        self.assertEqual(bytes(self.u.mem_read(DATA, 32)), bytes(desc))

    @staticmethod
    def rect_pixels(x0, y0, x1, y1, color):
        return {(x, y): color for y in range(max(y0, 0), min(y1, 682))
                for x in range(max(x0, 0), min(x1, 1024))}

    def test_rectangles_clip_before_unsigned_conversion_and_preserve_padding(self):
        cases = [(-3, -2, 5, 4), (1020, 679, 1030, 690), (-32768, 3, 7, 5),
                 (1018, 680, 32767, 32767), (-12, -10, -1, -1),
                 (1024, 682, 1030, 700), (8, 8, 3, 3), (5, 5, 5, 6)]
        for pitch in (2048, 2114, 4096):
            for alignment in range(0, 16, 2):
                for x0, y0, x1, y1 in cases:
                    with self.subTest(pitch=pitch, alignment=alignment, rect=(x0,y0,x1,y1)):
                        self.surface(pitch, alignment)
                        self.paint(Mark(RECT, WHITE, (x0,x1,0), (y0,y1,0)))
                        self.check(self.rect_pixels(x0,y0,x1,y1,WHITE))

    def test_triangle_includes_flat_base_and_single_pixel_tip_in_both_directions(self):
        # An independent integer lattice: four rows of a 6x3 triangle.
        rows = [(0, 6), (1, 5), (2, 4), (3, 3)]
        for direction in (-1, 1):
            for origin_x, origin_y in ((100,100), (-2,0), (1020,681)):
                for color in (GRAY, WHITE, GREEN):
                    with self.subTest(direction=direction, origin=(origin_x,origin_y), color=color):
                        self.surface(2114)
                        self.paint(Mark(TRIANGLE,color,(origin_x,origin_x+6,origin_x+3),
                                        (origin_y,origin_y,origin_y+3*direction)))
                        pixels = {}
                        for row, (left,right) in enumerate(rows):
                            y = origin_y+row*direction
                            if 0 <= y < 682:
                                pixels.update({(x,y): color for x in range(origin_x+left,origin_x+right+1)
                                               if 0 <= x < 1024})
                        self.check(pixels)

    def test_invalid_surface_mark_or_triangle_does_not_touch_framebuffer(self):
        mark = Mark(RECT, GREEN, (10,20,0), (20,30,0))
        for fields in ({'pitch':2047}, {'pitch':2049}, {'pitch':4098}, {'height':681},
                       {'pixels':0}, {'pixels':PIX+65}):
            with self.subTest(fields=fields):
                self.surface(**fields); self.paint(mark); self.check({})
        for invalid in (Mark(2,WHITE,(1,4,2),(1,1,4)), Mark(RECT,3,(1,4,0),(1,4,0)),
                        Mark(RECT,-1,(1,4,0),(1,4,0)), Mark(TRIANGLE,WHITE,(1,4,2),(1,2,4)),
                        Mark(TRIANGLE,WHITE,(1,4,2),(1,1,1)),
                        Mark(TRIANGLE,WHITE,(1,4,2),(1,1,34)),
                        Mark(TRIANGLE,WHITE,(1,4,5),(1,1,4))):
            self.surface(); self.paint(invalid); self.check({})
        self.surface(); self.paint(mark, surface=0); self.check({})
        self.paint(None, mark_address=0); self.check({})

    def test_dirty_region_extends_without_losing_existing_damage(self):
        self.surface(dirty=(10,600))
        self.paint(Mark(RECT,GRAY,(3,7,0),(200,205,0)))
        self.check(self.rect_pixels(3,200,7,205,GRAY), dirty=(10,600))

    def test_every_core_state_renders_actual_marks_and_never_writes_other_colors(self):
        g, config = Guide(), Config(10,16,80,200,800,3)
        for state, defocus in ((HIDDEN,None),(UNAVAILABLE,None),(FAR_LARGE,100),
                               (FAR_SMALL,30),(FOCUSED,0),(NEAR_SMALL,-30),(NEAR_LARGE,-100)):
            with self.subTest(state=state):
                self.lib.focus_guide_init(C.byref(g))
                self.lib.focus_guide_configure(C.byref(g), C.byref(config))
                self.lib.focus_guide_mode(C.byref(g), state != HIDDEN, 1, 0)
                if defocus is not None:
                    for sequence in range(1,4):
                        sample = Sample(defocus,900,1,1000+sequence*10,sequence,g.generation)
                        self.lib.focus_guide_update(C.byref(g), C.byref(sample), sample.captured_ms)
                self.assertEqual(g.state, state)
                marks = []
                @Paint
                def collect(_, pointer):
                    marks.append(Mark.from_buffer_copy(pointer.contents))
                self.lib.focus_guide_paint(C.byref(g),1030,collect,None)
                self.surface()
                for mark in marks:
                    self.paint(mark)
                framebuffer = bytes(self.u.mem_read(PIX+self.start,2048*682))
                values = set(C.c_uint16.from_buffer_copy(framebuffer, i).value
                             for i in range(0,len(framebuffer),2))
                if state == HIDDEN:
                    self.check({})
                    self.assertFalse(marks)
                else:
                    color = GRAY if state == UNAVAILABLE else GREEN if state == FOCUSED else WHITE
                    self.assertTrue(marks)
                    self.assertEqual(values, {0xa5a5, COLORS[color]})
                    self.assertEqual(bytes(self.u.mem_read(PIX,64)), b'\xa5'*64)
                    self.assertEqual(bytes(self.u.mem_read(PIX+self.start+2048*682,64)), b'\xa5'*64)


if __name__ == '__main__': unittest.main()
