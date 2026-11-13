"""Execute the actual Doom RGBX renderer on host memory, without a camera."""
from array import array
import ctypes as C
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
WIDTH, HEIGHT, SOURCE_BYTES = 1024, 682, 320 * 200 * 4
GUARD, CANARY = 64, 0xa5


class Surface(C.Structure):
    _fields_ = [('dirty_first', C.c_uint16), ('dirty_end', C.c_uint16),
                ('reserved', C.c_uint16 * 2), ('pixels', C.c_void_p),
                ('pitch', C.c_uint16), ('alpha_pitch', C.c_uint16),
                ('height', C.c_uint16), ('reserved22', C.c_uint16),
                ('alpha_offset', C.c_uint64)]


VIDEO_C = r'''
#include "bfplus/doom_video.h"
int present(struct DoomSurface *s,const uint8_t *p,size_t n) {
    return doom_video_present(s,p,n);
}
#ifdef GUARDED_MAIN
#include <stdlib.h>
#include <sys/mman.h>
#include <unistd.h>
int main(int argc,char **argv) {
    if (argc!=2) return 2;
    size_t page=(size_t)sysconf(_SC_PAGESIZE);
    size_t frame=320u*200u*4u, span=(2048u*682u+page-1)/page*page;
    uint8_t *pixels=mmap(NULL,span,PROT_READ,MAP_PRIVATE|MAP_ANON,-1,0);
    uint8_t *source=mmap(NULL,frame,PROT_READ,MAP_PRIVATE|MAP_ANON,-1,0);
    struct DoomSurface *s=mmap(NULL,page,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANON,-1,0);
    if (pixels==MAP_FAILED || source==MAP_FAILED || s==MAP_FAILED) return 3;
    *s=(struct DoomSurface){.dirty_first=123,.dirty_end=456,.pixels=pixels,
                           .pitch=2048,.height=682};
    size_t bytes=frame;
    int which=atoi(argv[1]);
    switch (which) {
    case 0: s->pixels=NULL; break;
    case 1: s->pixels=pixels+1; break;
    case 2: s->pitch=0; break;
    case 3: s->pitch=2046; break;
    case 4: s->pitch=2047; break;
    case 5: s->pitch=2049; break;
    case 6: s->pitch=65535; break;
    case 7: s->height=0; break;
    case 8: s->height=681; break;
    case 9: s->height=683; break;
    case 10: s->height=65535; break;
    case 11: s->alpha_offset=1; break;
    case 12: s->alpha_offset=UINT64_MAX; break;
    case 13: source=NULL; break;
    case 14: bytes=0; break;
    case 15: bytes=frame-1; break;
    case 16: s->pixels=(uint8_t *)(UINTPTR_MAX-(size_t)s->pitch*682+1); break;
    case 17: s->pixels=(uint8_t *)(UINTPTR_MAX-1); break;
    case 18: break; /* null descriptor */
    default: return 4;
    }
    if (mprotect(s,page,PROT_READ)) return 5;
    /* Descriptor, framebuffer and source are read-only: even a transient
       write before rejecting an invalid descriptor terminates this child. */
    return doom_video_present(which==18 ? NULL : s,source,bytes) ? 6 : 0;
}
#endif
'''


def reference_rows(rgbx):
    """Pixel-center nearest-neighbor reference for the specified 880x660 area."""
    colors = [(rgbx[i] // 16) * 4096 + (rgbx[i + 1] // 16) * 256 +
              (rgbx[i + 2] // 16) * 16 + 15 for i in range(0, SOURCE_BYTES, 4)]
    black = array('H', [15] * WIDTH).tobytes()
    rows = []
    for y in range(HEIGHT):
        if y < 11 or y >= 671:
            rows.append(black)
        else:
            sy = ((y - 11) * 200 + 100) // 660
            active = [colors[sy * 320 + (x * 320 + 160) // 880] for x in range(880)]
            rows.append(array('H', [15] * 72 + active + [15] * 72).tobytes())
    return rows


class DoomVideoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cc = shutil.which('cc') or shutil.which('clang')
        if not cc:
            raise unittest.SkipTest('host C compiler required')
        cls.directory = tempfile.TemporaryDirectory(prefix='bf-doom-video-')
        cls.addClassCleanup(cls.directory.cleanup)
        work = Path(cls.directory.name)
        source, library = work / 'video.c', work / 'video.so'
        source.write_text(VIDEO_C)
        flags = [cc, '-std=c11', '-D_DEFAULT_SOURCE', '-O2', '-Wall', '-Wextra',
                 '-Werror', '-I', str(ROOT), str(source)]
        subprocess.run([*flags, '-dynamiclib' if sys.platform == 'darwin' else '-shared',
                        '-fPIC', '-o', str(library)], check=True, capture_output=True)
        cls.guarded = work / 'guarded'
        subprocess.run([*flags, '-DGUARDED_MAIN', '-o', str(cls.guarded)],
                       check=True, capture_output=True)
        cls.lib = C.CDLL(str(library))
        cls.lib.present.argtypes = [C.POINTER(Surface), C.c_void_p, C.c_size_t]
        cls.lib.present.restype = C.c_int

    def render(self, rgbx, pitch=2048, alignment=0, trailing=b''):
        start = GUARD + alignment
        backing = (C.c_uint64 * ((start + pitch * HEIGHT + GUARD + 7) // 8))()
        C.memset(backing, CANARY, C.sizeof(backing))
        surface = Surface()
        C.memset(C.byref(surface), 0x79, C.sizeof(surface))
        surface.pixels = C.addressof(backing) + start
        surface.pitch, surface.height, surface.alpha_offset = pitch, HEIGHT, 0
        before = bytes(surface)
        source = C.create_string_buffer(b'\x5a' * GUARD + rgbx + trailing + b'\x5a' * GUARD)
        source_before = bytes(source)
        result = self.lib.present(C.byref(surface), C.addressof(source) + GUARD,
                                  len(rgbx) + len(trailing))
        self.assertEqual(result, 1)
        self.assertEqual(bytes(source), source_before)
        self.assertEqual((surface.dirty_first, surface.dirty_end), (0, HEIGHT))
        self.assertEqual(bytes(surface)[4:], before[4:], 'unrelated descriptor fields changed')
        output = bytes(backing)
        self.assertEqual(output[:start], bytes([CANARY]) * start)
        self.assertEqual(output[start + pitch * HEIGHT:], bytes([CANARY]) *
                         (len(output) - start - pitch * HEIGHT))
        rows = []
        for y in range(HEIGHT):
            offset = start + y * pitch
            self.assertEqual(output[offset + WIDTH * 2:offset + pitch],
                             bytes([CANARY]) * (pitch - WIDTH * 2), f'padding row {y}')
            rows.append(output[offset:offset + WIDTH * 2])
        return rows

    def test_rgbx_gradient_matches_entire_corrected_image_and_padded_canaries(self):
        rgbx = bytes(value for y in range(200) for x in range(320)
                     for value in (x & 255, y & 255, (3 * x + 5 * y) & 255, (x + y) & 255))
        expected = reference_rows(rgbx)
        for pitch, alignment in ((2048, 0), (2050, 2), (2114, 14), (4096, 0)):
            with self.subTest(pitch=pitch, alignment=alignment):
                rows = self.render(rgbx, pitch, alignment)
                for y, (actual, wanted) in enumerate(zip(rows, expected)):
                    self.assertEqual(actual, wanted, f'row {y}')

    def test_rgb444a4_channels_opaque_margins_and_exact_four_to_three_area(self):
        for rgba, expected in (((255, 0, 0, 0), 0xf00f),
                               ((0, 255, 0, 255), 0x0f0f),
                               ((0, 0, 255, 73), 0x00ff),
                               ((0xab, 0xcd, 0xef, 1), 0xacef),
                               ((255, 255, 255, 0), 0xffff)):
            with self.subTest(rgbx=rgba):
                rows = self.render(bytes(rgba) * (320 * 200))
                active_pixels = 0
                for y, row in enumerate(rows):
                    values = array('H')
                    values.frombytes(row)
                    if 11 <= y < 671:
                        self.assertEqual(values[:72].tolist(), [15] * 72)
                        self.assertEqual(values[72:952].tolist(), [expected] * 880)
                        self.assertEqual(values[952:].tolist(), [15] * 72)
                        active_pixels += values.count(expected)
                    else:
                        self.assertEqual(values.tolist(), [15] * WIDTH)
                self.assertEqual(active_pixels, 880 * 660)
                self.assertEqual(880 * 3, 660 * 4)

    def test_low_rgb_bits_x_byte_and_trailing_input_do_not_affect_pixels(self):
        rows = self.render(bytes((0xa0, 0xc0, 0xe0, 0)) * (320 * 200))
        changed = self.render(bytes((0xaf, 0xcf, 0xef, 255)) * (320 * 200),
                              trailing=b'ignored extra input')
        self.assertEqual(changed, rows)
        black = self.render(bytes((15, 15, 15, 255)) * (320 * 200))
        self.assertTrue(all(row == array('H', [15] * WIDTH).tobytes() for row in black))

    def test_invalid_descriptors_and_short_input_make_no_writes(self):
        names = ('null pixels', 'unaligned pixels', 'zero pitch', 'short pitch',
                 'short odd pitch', 'odd pitch', 'maximum odd pitch', 'zero height',
                 'short height', 'tall height', 'maximum height', 'separate alpha',
                 'maximum alpha offset', 'null input', 'empty input', 'short input',
                 'extent wraps address space', 'pointer near UINTPTR_MAX', 'null surface')
        for case, name in enumerate(names):
            with self.subTest(descriptor=name):
                result = subprocess.run([str(self.guarded), str(case)],
                                        capture_output=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
