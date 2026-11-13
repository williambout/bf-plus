"""Synthetic image correspondences, not optical calibration or real focus."""
import ctypes as C
from pathlib import Path
import random
import subprocess
import tempfile
import unittest

from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM
from unicorn import arm64_const as r
from touch_focus.build import tool

ROOT = Path(__file__).resolve().parents[1]


class Config(C.Structure):
    _fields_ = [(name, C.c_uint16) for name in ('width', 'height', 'stride', 'max_shift',
                'min_correlation', 'min_peak_margin', 'min_texture_rms')]


class Result(C.Structure):
    _fields_ = [('displacement_q8', C.c_int32)] + [(name, C.c_uint32) for name in
                ('valid', 'correlation', 'peak_margin', 'texture_rms')]


def images(shift=0, width=96, height=16, stride=128, exposure=False):
    rng = random.Random(9001)
    a, b = bytearray([0x31])*((height-1)*stride+width), bytearray([0xee])*((height-1)*stride+width)
    for y in range(height):
        row = [rng.randrange(32, 96) for _ in range(width)]
        for x in range(width):
            a[y*stride+x] = row[x]
            value = row[(x-shift) % width]
            b[y*stride+x] = value*2+17 if exposure else value
    return bytes(a), bytes(b)


class PhaseMatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix='bf-phase-match-')
        cls.addClassCleanup(cls.directory.cleanup)
        d = Path(cls.directory.name)
        cc = tool('clang', '/opt/homebrew/opt/llvm/bin/clang')
        source = ROOT/'touch_focus/focus_phase.c'
        subprocess.run([cc, '-std=c11', '-shared', '-fPIC', '-O2', '-Wall', '-Wextra', '-Werror',
                        str(source), '-o', str(d/'phase.dylib')], check=True)
        cls.lib = C.CDLL(str(d/'phase.dylib'))
        cls.lib.focus_phase_match.argtypes = (C.c_void_p, C.c_void_p, C.POINTER(Config))
        cls.lib.focus_phase_match.restype = Result
        subprocess.run([cc, '--target=aarch64-none-elf', '-Os', '-ffreestanding', '-fno-builtin',
                        '-fno-stack-protector', '-fno-unwind-tables', '-fno-asynchronous-unwind-tables',
                        '-mgeneral-regs-only', '-ffixed-x18', '-mcmodel=tiny', '-fpie',
                        '-fvisibility=hidden', '-Wall', '-Wextra', '-Werror',
                        '-c', str(source), '-o', str(d/'phase.o')], check=True)
        ld = tool('ld.lld', '/opt/homebrew/opt/lld/bin/ld.lld')
        objcopy = tool('llvm-objcopy', '/opt/homebrew/opt/llvm/bin/llvm-objcopy')
        nm = tool('llvm-nm', '/opt/homebrew/opt/llvm/bin/llvm-nm')
        subprocess.run([ld, '--image-base=0', '-Ttext=0x100000', '-e', 'focus_phase_match',
                        str(d/'phase.o'), '-o', str(d/'phase.elf')], check=True)
        subprocess.run([objcopy, '-O', 'binary', str(d/'phase.elf'), str(d/'phase.bin')], check=True)
        cls.arm = (d/'phase.bin').read_bytes()
        cls.entry = next(int(line.split()[0], 16) for line in subprocess.check_output(
            [nm, '--defined-only', str(d/'phase.elf')], text=True).splitlines()
            if line.split()[-1] == 'focus_phase_match')

    def setUp(self): self.config = Config(96, 16, 128, 16, 900, 100, 4)

    def match(self, a, b, config=None):
        return self.lib.focus_phase_match(C.create_string_buffer(a), C.create_string_buffer(b),
                                          C.byref(config or self.config))

    def test_known_positive_negative_and_zero_shifts_with_exposure_difference(self):
        for shift in (-15, -8, -1, 0, 1, 8, 15):
            for exposure in (False, True):
                with self.subTest(shift=shift, exposure=exposure):
                    result = self.match(*images(shift, exposure=exposure))
                    self.assertTrue(result.valid)
                    self.assertLess(abs(result.displacement_q8-shift*256), 8)
                    self.assertGreaterEqual(result.correlation, 990)

    def test_blank_clipped_low_texture_and_repeated_patterns_are_unavailable(self):
        for a, b in ((bytes(2016), bytes(2016)), (b'\xff'*2016, b'\xff'*2016),
                     (b'\x64\x65'*1008, b'\x64\x65'*1008),
                     (b'\x20\x60\xa0\x60'*504, b'\x20\x60\xa0\x60'*504)):
            with self.subTest(prefix=a[:4]): self.assertFalse(self.match(a, b).valid)

    def test_outside_search_limit_unrelated_noise_and_occlusion_are_unavailable(self):
        for shift in (-24, -16, 16, 24):
            self.assertFalse(self.match(*images(shift)).valid)
        a, b = images()
        rng = random.Random(12)
        noise = bytes(rng.randrange(256) for _ in a)
        self.assertFalse(self.match(a, noise).valid)
        self.assertFalse(self.match(a, b[:1024]+bytes(len(b)-1024)).valid)

    def test_invalid_or_missing_config_never_uses_invented_defaults(self):
        a, b = images()
        for field, bad in (('width', 15), ('width', 257), ('height', 0), ('height', 33),
                           ('stride', 95), ('stride', 2049), ('max_shift', 0), ('max_shift', 33),
                           ('min_correlation', 0), ('min_correlation', 1001),
                           ('min_peak_margin', 0), ('min_texture_rms', 0), ('min_texture_rms', 128)):
            with self.subTest(field=field, bad=bad):
                c = Config.from_buffer_copy(self.config); setattr(c, field, bad)
                self.assertFalse(self.match(a, b, c).valid)
        self.assertFalse(self.lib.focus_phase_match(None, None, None).valid)

    def test_maximum_supported_crop_and_contrast_do_not_overflow(self):
        width, height, stride = 256, 32, 256
        rng = random.Random(48)
        a = bytes(rng.choice((0, 255)) for _ in range(width*height))
        result = self.match(a, a, Config(width, height, stride, 32, 990, 100, 4))
        self.assertEqual(result.valid, 1)
        self.assertEqual(result.displacement_q8, 0)
        self.assertEqual(result.correlation, 1000)

    def test_aarch64_has_no_runtime_helpers_and_matches_native_result(self):
        for shift in (-7, 0, 9):
            a, b = images(shift, exposure=True)
            expected = self.match(a, b)
            u = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
            for base in (0x100000, 0x200000, 0x300000): u.mem_map(base, 0x10000)
            u.mem_write(0x100000, self.arm)
            u.mem_write(0x300000, a); u.mem_write(0x301000, b)
            u.mem_write(0x302000, bytes(self.config))
            for reg, val in ((r.UC_ARM64_REG_X0, 0x300000), (r.UC_ARM64_REG_X1, 0x301000),
                             (r.UC_ARM64_REG_X2, 0x302000), (r.UC_ARM64_REG_X8, 0x303000),
                             (r.UC_ARM64_REG_SP, 0x208000), (r.UC_ARM64_REG_LR, 0x10f000),
                             (r.UC_ARM64_REG_X18, 0xfeed1234)):
                u.reg_write(reg, val)
            u.emu_start(self.entry, 0x10f000, count=3000000)
            self.assertEqual(u.reg_read(r.UC_ARM64_REG_PC), 0x10f000)
            self.assertEqual(u.reg_read(r.UC_ARM64_REG_X18), 0xfeed1234)
            self.assertEqual(u.reg_read(r.UC_ARM64_REG_SP), 0x208000)
            self.assertEqual(bytes(u.mem_read(0x303000, C.sizeof(Result))), bytes(expected))


if __name__ == '__main__': unittest.main()
