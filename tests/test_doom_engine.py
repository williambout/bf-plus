"""Offline engine ABI, native gameplay, and freestanding module verification.

Optional real IWADs live only in .touch-focus/. Fetch redistributable data with
python -m bfplus.doom_engine.fetch_test_wad; tests never access the network.
"""
import ctypes as C
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import unittest

from bfplus.doom_engine.build_module import build, inspect_elf, tool
from bfplus.doom_engine.prepare_engine import UPSTREAM_SHA256

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "bfplus/doom_engine"
OUT = ROOT / ".touch-focus/doom-engine/tests"
HEAP = 24 * 1024 * 1024
IWADS = [ROOT / ".touch-focus/doom-shareware/doom1.wad", *[
    ROOT / ".touch-focus/doom-engine/freedoom-0.13.0" / name
    for name in ("freedoom1.wad", "freedoom2.wad")]]
if os.environ.get("BFDOOM_TEST_WAD"):
    IWADS.insert(0, Path(os.environ["BFDOOM_TEST_WAD"]))
IWADS = list(dict.fromkeys(p for p in IWADS if p.is_file()))


class Config(C.Structure):
    _fields_ = [("abi", C.c_uint32), ("size", C.c_uint32), ("wad", C.c_void_p),
                ("wad_size", C.c_uint64), ("heap", C.c_void_p), ("heap_size", C.c_uint64),
                ("flags", C.c_uint32), ("reserved", C.c_uint32)]


class Tick(C.Structure):
    _fields_ = [("ms", C.c_uint32), ("keys", C.c_uint32)]


class Frame(C.Structure):
    _fields_ = [("rgbx", C.c_void_p), ("indexed", C.c_void_p), ("palette", C.c_void_p),
                ("width", C.c_uint32), ("height", C.c_uint32), ("pitch", C.c_uint32), ("sequence", C.c_uint32)]


class Info(C.Structure):
    _fields_ = [("abi", C.c_uint32), ("status", C.c_int32), ("used", C.c_uint64),
                ("peak", C.c_uint64), ("capacity", C.c_uint64), ("state", C.c_uint64),
                ("zone", C.c_uint64), ("sequence", C.c_uint32), ("game_tics", C.c_uint32),
                ("message", C.c_char * 256)]


class DoomEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.metadata = build(OUT, host=True)
        cls.lib = C.CDLL(str(OUT / ("libbfdoom.dylib" if sys.platform == "darwin" else "libbfdoom.so")))
        cls.lib.bfdoom_entry.argtypes = [C.c_uint32, C.c_void_p]
        cls.lib.bfdoom_entry.restype = C.c_int64
        if IWADS:
            cls.wad_data = IWADS[0].read_bytes()
            cls.wad = C.create_string_buffer(cls.wad_data)

    def call(self, op, arg=None):
        return self.lib.bfdoom_entry(op, C.byref(arg) if arg is not None else None)

    def setUp(self):
        self.call(3)
        self.heap = C.create_string_buffer(HEAP + 128)
        C.memset(C.addressof(self.heap), 0xA5, 64)
        C.memset(C.addressof(self.heap) + HEAP + 64, 0x5A, 64)

    def tearDown(self):
        self.call(3)
        self.assertEqual(bytes(self.heap[:64]), b"\xa5" * 64)
        self.assertEqual(bytes(self.heap[HEAP+64:]), b"\x5a" * 64)

    def config(self, wad=None, heap_size=HEAP, flags=1):
        if wad is None:
            if not IWADS:
                self.skipTest("Real IWAD unavailable; run bfplus.doom_engine.fetch_test_wad")
            wad = self.wad
        return Config(1, C.sizeof(Config), C.addressof(wad), len(wad)-1,
                      C.addressof(self.heap)+64, heap_size, flags, 0)

    def init(self, **kwargs):
        cfg = self.config(**kwargs)
        self.assertEqual(self.call(0, cfg), 0, self.info().message)
        return cfg

    def info(self):
        result = Info()
        self.assertEqual(self.call(4, result), 0)
        return result

    def frame(self):
        f = Frame()
        self.assertEqual(self.call(2, f), 0)
        self.assertEqual((f.width, f.height, f.pitch), (320, 200, 1280))
        return f

    def test_pinned_source_and_module_contract(self):
        self.assertEqual(hashlib.sha256((SOURCE / "vendor/PureDOOM.h").read_bytes()).hexdigest(), UPSTREAM_SHA256)
        self.assertEqual(inspect_elf(OUT / "bfdoom.elf"), self.metadata)
        self.assertLess(self.metadata["memory_size"], 4*1024*1024)
        self.assertGreater(self.metadata["relative_relocations"], 0)
        undefined = subprocess.check_output([tool("llvm-nm"), "--undefined-only", OUT / "bfdoom.elf"], text=True)
        self.assertEqual(undefined.strip(), "")
        dis = subprocess.check_output([tool("llvm-objdump"), "-d", "--no-show-raw-insn", OUT / "bfdoom.elf"], text=True)
        for line in dis.splitlines():
            instruction = re.match(r"\s*[0-9a-f]+:\s+(.+)", line)
            if not instruction:
                continue
            operands = instruction[1].split("//", 1)[0].split("<", 1)[0]
            self.assertIsNone(re.search(r"\b(?:[vqdsh][0-9]+|x18|w18)\b", operands), line)
            self.assertIsNone(re.search(r"\b(?:svc|hvc|smc|brk)\b", operands), line)

    def test_invalid_api_and_idempotent_stop(self):
        self.assertEqual(self.call(99), -2)
        self.assertEqual(self.call(0), -2)
        self.assertEqual(self.call(1, Tick(0, 0)), -1)
        self.assertEqual(self.call(2, Frame()), -1)
        self.assertEqual(self.call(3), 0)
        self.assertEqual(self.call(3), 0)
        self.assertEqual(C.sizeof(Config), 48)
        self.assertEqual(C.sizeof(Frame), 40)
        self.assertEqual(C.sizeof(Info), 312)

    def test_invalid_wad_and_ranges_are_rejected(self):
        for raw in (b"", b"PWAD" + bytes(20), b"IWAD" + struct.pack("<II", 0xFFFFFFFF, 12),
                    b"IWAD" + struct.pack("<II", 1, 0xFFFFFFFF)):
            wad = C.create_string_buffer(raw)
            self.assertEqual(self.call(0, self.config(wad=wad)), -3)
        wad = C.create_string_buffer(b"IWAD" + bytes(8))
        cfg = self.config(wad=wad)
        cfg.abi = 2
        self.assertEqual(self.call(0, cfg), -2)
        cfg.abi = 1; cfg.heap = cfg.wad
        self.assertEqual(self.call(0, cfg), -2)
        cfg.heap = C.addressof(self.heap)+64; cfg.wad_size = 2**64-1
        self.assertEqual(self.call(0, cfg), -2)

    def test_allocation_failure_unwinds_and_next_init_works(self):
        # Structurally valid IWAD with an oversized directory exhausts the
        # small heap inside doom_init, exercising the nonlocal error boundary.
        count = 65535
        raw = bytearray(b"IWAD" + struct.pack("<II", count, 12+10752) + bytes(10752))
        raw += struct.pack("<II8s", 12, 10752, b"PLAYPAL")
        raw += struct.pack("<II8s", 0, 0, b"MAP01") * (count-1)
        wad = C.create_string_buffer(bytes(raw))
        self.assertEqual(self.call(0, self.config(wad=wad, heap_size=8*1024*1024)), -4)
        self.assertIn(b"heap exhausted", self.info().message)
        self.assertEqual(self.info().used, 0)
        self.assertEqual(self.call(2, Frame()), -1)
        self.init()
        self.assertGreater(self.frame().rgbx, 0)

    def test_rgbx_palette_and_heap_accounting(self):
        self.init()
        for ms in range(0, 2500, 20):
            self.assertEqual(self.call(1, Tick(ms, 0)), 0)
        f = self.frame()
        rgbx = C.string_at(f.rgbx, 320*200*4)
        indices = C.string_at(f.indexed, 320*200)
        palette = C.string_at(f.palette, 768)
        expected = b"".join(palette[i*3:i*3+3] + b"\xff" for i in indices)
        self.assertEqual(rgbx, expected)
        self.assertGreater(len(set(indices)), 32)
        info = self.info()
        self.assertLessEqual(info.used, info.peak)
        self.assertLessEqual(info.peak, info.capacity)
        self.assertGreater(info.zone, 4*1024*1024)
        self.assertEqual(info.state, self.metadata["state_bytes"])

    def test_35hz_wrap_backwards_and_bounded_catchup(self):
        self.init()
        before = self.info().sequence
        for ms in range(1001):
            self.assertEqual(self.call(1, Tick(ms, 0)), 0)
        self.assertEqual(self.info().sequence - before, 35)
        before = self.info().sequence
        self.call(1, Tick(1000, 0))
        self.assertEqual(self.info().sequence, before)
        self.call(1, Tick(100000, 0))
        self.assertEqual(self.info().sequence-before, 4)
        self.call(1, Tick(100, 0))  # backwards clock rebases without spinning
        self.assertEqual(self.info().sequence-before, 4)
        self.init()
        before = self.info().sequence
        for delta in range(1001):
            self.call(1, Tick((0xFFFFFF00+delta) & 0xFFFFFFFF, 0))
        self.assertEqual(self.info().sequence-before, 35)

    def test_input_changes_game_and_reinitialization_is_deterministic(self):
        def run(mask):
            self.init()
            for i in range(180):
                self.assertEqual(self.call(1, Tick(i*29, mask if i > 60 else 0)), 0)
            return hashlib.sha256(C.string_at(self.frame().rgbx, 256000)).digest()
        baseline = run(0)
        self.assertNotEqual(baseline, run(1 | 8 | 16))
        self.assertEqual(baseline, run(0))
        self.assertEqual(self.call(1, Tick(10000, 1 << 31)), -2)

    def test_real_wad_title_gameplay_doors_errors_and_reset_with_asan(self):
        if not IWADS:
            self.skipTest("Real IWAD unavailable")
        native = OUT / "native-selftest-asan"
        subprocess.run([tool("clang"), "-std=gnu11", "-O1", "-fwrapv", "-ffreestanding", "-fno-builtin",
                        "-fno-stack-protector", "-fvisibility=hidden", "-fsanitize=address", "-g",
                        "-I", str(OUT), SOURCE / "native_selftest.c", OUT / "host-jump.o", "-o", native], check=True)
        for wad in IWADS:
            with self.subTest(wad=wad.name):
                result = subprocess.run([native, wad], capture_output=True, text=True, timeout=60)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("PASS title/new-game", result.stdout)

    def test_relocated_aarch64_executes_with_fp_disabled(self):
        try:
            from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM
            from unicorn import arm64_const as r
        except ImportError:
            self.skipTest("Optional Unicorn runtime not installed; ELF link check still required")
        if not IWADS:
            self.skipTest("Real IWAD unavailable")
        raw = (OUT / "bfdoom.elf").read_bytes()
        base, hp, wp, sp, ap, end = 0x10000000, 0x20000000, 0x30000000, 0x40000000, 0x50000000, 0x60000000
        page = lambda n: (n+4095) & ~4095
        u = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
        for address, size in ((base, self.metadata["memory_size"]), (hp, HEAP), (wp, len(self.wad_data)),
                              (sp, 256*1024), (ap, 4096), (end, 4096)):
            u.mem_map(address, page(size))
        for s in self.metadata["segments"]:
            u.mem_write(base+s["vaddr"], raw[s["offset"]:s["offset"]+s["filesz"]])
        h = struct.unpack_from("<16sHHIQQQIHHHHHH", raw)
        for i in range(h[12]):
            sec = struct.unpack_from("<IIQQQQIIQQ", raw, h[6]+i*h[11])
            if sec[1] == 4:
                for p in range(sec[4], sec[4]+sec[5], sec[9]):
                    target, kind, addend = struct.unpack_from("<QQq", raw, p)
                    self.assertEqual(kind, 1027)
                    u.mem_write(base+target, struct.pack("<Q", base+addend))
        for s in self.metadata["segments"]:
            # ELF R/W/X bits become Unicorn X/W/R bits.
            perm = ((s["flags"] & 4) >> 2) | (s["flags"] & 2) | ((s["flags"] & 1) << 2)
            u.mem_protect(base+s["vaddr"], page(s["memsz"]), perm)
        u.mem_write(wp, self.wad_data)
        u.mem_protect(wp, page(len(self.wad_data)), 1)
        u.reg_write(r.UC_ARM64_REG_CPACR_EL1, 0)
        def arm_call(op, payload=b""):
            if payload:
                u.mem_write(ap, payload)
            u.reg_write(r.UC_ARM64_REG_X0, op); u.reg_write(r.UC_ARM64_REG_X1, ap if payload else 0)
            u.reg_write(r.UC_ARM64_REG_SP, sp+256*1024-16); u.reg_write(r.UC_ARM64_REG_LR, end)
            for n in range(18, 30):
                u.reg_write(getattr(r, f"UC_ARM64_REG_X{n}"), 0xBAD000+n)
            u.emu_start(base+self.metadata["entry"], end, count=500000000)
            self.assertEqual(u.reg_read(r.UC_ARM64_REG_PC), end, "Unbounded engine call")
            self.assertEqual(u.reg_read(r.UC_ARM64_REG_SP), sp+256*1024-16)
            for n in range(18, 30):
                self.assertEqual(u.reg_read(getattr(r, f"UC_ARM64_REG_X{n}")), 0xBAD000+n)
            return C.c_int64(u.reg_read(r.UC_ARM64_REG_X0)).value
        cfg = struct.pack("<IIQQQQII", 1, 48, wp, len(self.wad_data), hp, HEAP, 1, 0)
        self.assertEqual(arm_call(0, cfg), 0)
        for i in range(80):
            self.assertEqual(arm_call(1, struct.pack("<II", i*29, 0)), 0)
        self.assertEqual(arm_call(2, bytes(40)), 0)
        rgbx, indexed, palette, w, height, pitch, seq = struct.unpack("<QQQIIII", u.mem_read(ap, 40))
        arm_pixels = bytes(u.mem_read(rgbx, 256000))
        self.assertEqual((w, height, pitch), (320, 200, 1280))
        self.init()
        for i in range(80):
            self.call(1, Tick(i*29, 0))
        self.assertEqual(arm_pixels, C.string_at(self.frame().rgbx, 256000))
        # Exercise the nonlocal quit path on ARM as well as on the host.
        self.assertEqual(arm_call(5, struct.pack("<II", 0xC4, 1)), 0)
        self.assertEqual(arm_call(5, struct.pack("<II", ord('y'), 1)), 1)
        self.assertEqual(arm_call(0, cfg), 0)
        self.assertEqual(arm_call(3), 0)


if __name__ == "__main__":
    unittest.main()
