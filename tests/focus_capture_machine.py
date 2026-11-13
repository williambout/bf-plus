"""Offline BF 1.04 execution fixture for the continuous PAS adapter.

Only the supplied firmware and canonical adapter sources are inputs. The test
resident, linker script and scalar C runtime live in a TemporaryDirectory; no
addon/build/transport module is imported and no firmware file is patched.

The receiver, bank selector, program wrapper, wait/error normalization, IRQ
callback, sender, Lens+ getters and invalidate loop execute native instructions.
Hardware programming/start/stop, the clock, SVC wait, event services, logger and
bounded native memcpy/memset are synthetic leaves. Lens+ reads mapped settings
and a mapped profile table. DC IVAC is recorded and skipped; barriers execute in
Unicorn. Injected preemptions clear the exclusive monitor with a real CLREX.
This models software interleavings, NOT RTOS scheduling, DMA, cache visibility,
event-consumption semantics, sensor bank ownership or hardware coherence.
"""

import ctypes as C
from dataclasses import dataclass
import hashlib
from pathlib import Path
import shutil
import struct
import subprocess
import unittest

try:
    from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN
except ModuleNotFoundError as exc:
    if exc.name != "capstone":
        raise
    Cs = None

try:
    from unicorn import (Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_CODE,
                         UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE)
    from unicorn import arm64_const as r
except ModuleNotFoundError as exc:
    if exc.name != "unicorn":
        raise
    Uc = None


ROOT = Path(__file__).resolve().parents[1]
FIRMWARE = ROOT / "decoded-V104/rtos-alt.bin"
FIRMWARE_SHA256 = "f747c1350f00526b9c68c65aaef44d6e7b644b0169992342e12f059c42e150dc"
FW, CODE, STACK, DATA = 0x4d3000000, 0x447702000, 0x448000000, 0x449000000
STOP, INTERRUPT_RETURN, CLEAR_EXCLUSIVE, RESUME = (STACK + n for n in (0x100, 0x200, 0x300, 0x304))
STACK_TOP, INTERRUPT_STACK = STACK + 0xf000, STACK + 0x8000
RECEIVER, IRQ_CALLBACK, ISLAND = 0x4d32befd0, 0x4d32ca240, 0x4d3321190
PROGRAM_SITE, GATE_SITE, PAIR_SITE, IRQ_SITE, SEND_SITE = (
    0x4d32bf008, 0x4d32bf194, 0x4d32bf1bc, 0x4d32ca268, 0x4d32bf1e0)
PROGRAM, WAIT, IRQ, SEND = 0x4d32cb880, 0x4d3033810, 0x4d32cab80, 0x4d32c9d20
SITES = {PROGRAM_SITE: PROGRAM, GATE_SITE: WAIT, PAIR_SITE: WAIT,
         IRQ_SITE: IRQ, SEND_SITE: SEND}
INVALIDATE, DC_IVAC = 0x4d3074b70, 0x4d3001404
LENS, SELECTION, PROFILE = 0x4d31d48c0, 0x4d3318480, 0x4d33184c0
PENDING, FIRST, WRITER, EVENT = 0x4d72faf50, 0x4d72faf4c, 0x4d72fb0a8, 0x4d73014b8
SCENE = 0x4d7301c00
SCENE_VALUES = (0x4d3398930, 0x4d33988b0, 0x4d3393730, 0x4d33936a0)
MANUAL_LENSES, SETTINGS = 0x4d72aa4e8, 0x4d7301b98
TABLE, SETTINGS_DATA, REQUEST_DATA = DATA + 0x1000, DATA + 0x2000, DATA + 0x800
LEFT_TABLE, RIGHT_TABLE = 0x41a0d1c94, 0x41a0d1e94
PLANES, PLANE_BYTES = 0x419b00000, 0x7d400
BANKS = ((0x419b58300, 0x419bd5700), (0x419c52b00, 0x419ccff00),
         (0x419d4d300, 0x419dca700), (0x419e47b00, 0x419ec4f00))
WIDTH, HEIGHT, STRIDE = 128, 24, 1536
ROI = 154 * STRIDE + 693
GUARD = 0xc0dec0de51a7beef
MAX_AGE, MAX_COPY = 2400000, 240000
TRACK, CONFIG, IDENTITY, WAIT_FAILED, IRQ_FAILED = 1, 2, 4, 8, 16
AGE, COPY_TIME, TORN, SCENE_CHANGED, REQUEST_CHANGED = 32, 64, 128, 256, 512


class Identity(C.LittleEndianStructure):
    _fields_ = [("slot", C.c_uint32), ("profile", C.c_uint32 * 2)]

    def key(self):
        return self.slot, tuple(self.profile)


class Request(C.LittleEndianStructure):
    _fields_ = [("enabled", C.c_uint32), ("epoch", C.c_uint32),
                ("after_ticks", C.c_uint64), ("identity", Identity),
                ("reserved", C.c_uint32)]


class Frame:
    """Decode public fields using offsets AND sizes exported by target C."""
    fields = ("sequence", "acquired_ticks", "copy_start_ticks", "copy_end_ticks",
              "epoch", "software_checks_passed", "reason", "hardware_coherence_unproven",
              "identity", "wait_results", "wait_flags", "lifecycle_continuity_unproven",
              "guard_before", "pixels", "guard_after", "source_epoch",
              "program_sequence", "consume_sequence")

    def __init__(self, data, layout):
        for name, (offset, size) in layout.items():
            raw = data[offset:offset + size]
            if name == "identity":
                value = Identity.from_buffer_copy(raw)
            elif name in ("wait_results", "wait_flags"):
                value = struct.unpack("<2I", raw)
            elif name == "pixels":
                assert size == 2 * WIDTH * HEIGHT
                value = (raw[:WIDTH * HEIGHT], raw[WIDTH * HEIGHT:])
            else:
                value = int.from_bytes(raw, "little")
            setattr(self, name, value)


class Status(C.LittleEndianStructure):
    _fields_ = [(name, C.c_uint32) for name in
                ("version", "enabled", "published", "accepted", "rejected",
                 "dropped", "last_reason", "hardware_coherence_unproven")] + [
                    (name, C.c_uint64) for name in
                    ("last_sequence", "last_acquired_ticks", "last_copy_ticks",
                     "source_epoch", "program_sequence", "consume_sequence")]


def branch(source, target):
    delta = target - source
    assert delta % 4 == 0 and -(1 << 27) <= delta < (1 << 27)
    return 0x94000000 | ((delta >> 2) & 0x3ffffff)


@dataclass
class Resident:
    blob: bytes
    symbols: dict
    instructions: dict
    firmware: bytes
    frame_size: int
    frame_layout: dict


def build_resident(directory):
    """Missing inputs skip; compiler, linker, ABI or fingerprint errors fail."""
    missing = [name for name, value in (("unicorn", Uc), ("capstone", Cs)) if value is None]
    if not FIRMWARE.is_file():
        missing.append(str(FIRMWARE))
    tools = {}
    for name, package in (("clang", "llvm"), ("ld.lld", "lld"),
                          ("llvm-nm", "llvm"), ("llvm-objcopy", "llvm")):
        path = shutil.which(name) or f"/opt/homebrew/opt/{package}/bin/{name}"
        if not Path(path).is_file():
            missing.append(name)
        tools[name] = path
    if missing:
        raise unittest.SkipTest("native PAS tests require " + ", ".join(missing))
    firmware = FIRMWARE.read_bytes()
    assert hashlib.sha256(firmware).hexdigest() == FIRMWARE_SHA256, "unexpected BF 1.04 firmware fingerprint"
    d = Path(directory)
    # Validate every public field decoded by ctypes against the target compiler.
    runtime = ['#include <stddef.h>\n#include "focus_capture.h"']
    runtime.append(f'_Static_assert(FOCUS_CAPTURE_WIDTH == {WIDTH} && '
                   f'FOCUS_CAPTURE_HEIGHT == {HEIGHT}, "fixed tested geometry");')
    for cls in (Identity, Request, Status):
        tag = "FocusCapture" + cls.__name__
        runtime.append(f'_Static_assert(sizeof(struct {tag}) == {C.sizeof(cls)}, "{tag} size");')
        for name, _ in cls._fields_:
            runtime.append(f'_Static_assert(offsetof(struct {tag}, {name}) == '
                           f'{getattr(cls, name).offset}, "{tag}.{name}");')
    runtime.append("const uint64_t capture_test_frame_layout[] = { sizeof(struct FocusCaptureFrame),")
    for name in Frame.fields:
        runtime.append(f"offsetof(struct FocusCaptureFrame, {name}), "
                       f"sizeof(((struct FocusCaptureFrame *)0)->{name}),")
    runtime.append("};")
    runtime.append("""
void *memcpy(void *dst, const void *src, size_t n) {
    volatile unsigned char *d = dst;
    const volatile unsigned char *s = src;
    for (size_t i = 0; i < n; ++i) d[i] = s[i];
    return dst;
}
void *memset(void *dst, int value, size_t n) {
    volatile unsigned char *d = dst;
    for (size_t i = 0; i < n; ++i) d[i] = (unsigned char)value;
    return dst;
}
""")
    (d / "runtime.c").write_text("\n".join(runtime))
    (d / "resident.ld").write_text(f"""ENTRY(focus_sensor_wrapper)
SECTIONS {{
 . = 0x{CODE:x};
 .text : {{ *(.text*) }}
 .rodata : {{ *(.rodata*) }}
 .data : {{ *(.data*) }}
 __image_end = .;
 .bss (NOLOAD) : {{ *(.bss*) *(COMMON) }}
 __end = .;
 /DISCARD/ : {{ *(.comment) *(.note*) *(.eh_frame*) }}
}}
""")
    flags = ["--target=aarch64-none-elf", "-Oz", "-std=c11", "-ffreestanding",
             "-fno-builtin", "-fno-stack-protector", "-fno-unwind-tables",
             "-fno-asynchronous-unwind-tables", "-mgeneral-regs-only", "-ffixed-x18",
             "-fno-jump-tables", "-ffunction-sections", "-fdata-sections", "-mcmodel=tiny",
             "-fpie", "-fvisibility=hidden", "-Wall", "-Wextra", "-Werror"]
    objects = []
    for source in (ROOT / "touch_focus/focus_capture.c", d / "runtime.c"):
        obj = d / (source.stem + ".o")
        subprocess.run([tools["clang"], *flags, "-I", str(ROOT / "touch_focus"),
                        "-c", str(source), "-o", str(obj)], check=True)
        objects.append(str(obj))
    router = d / "router.o"
    subprocess.run([tools["clang"], "--target=aarch64-none-elf", "-c",
                    str(ROOT / "touch_focus/focus_sensor_router.S"), "-o", str(router)], check=True)
    elf, binary = d / "resident.elf", d / "resident.bin"
    subprocess.run([tools["ld.lld"], "-T", str(d / "resident.ld"), *objects,
                    str(router), "-o", str(elf)], check=True)
    subprocess.run([tools["llvm-objcopy"], "-O", "binary", str(elf), str(binary)], check=True)
    assert not subprocess.check_output([tools["llvm-nm"], "--undefined-only", str(elf)], text=True).strip()
    symbols = {}
    for line in subprocess.check_output([tools["llvm-nm"], "--defined-only", str(elf)], text=True).splitlines():
        fields = line.split()
        if len(fields) == 3:
            symbols[fields[2]] = int(fields[0], 16)
    blob = binary.read_bytes()
    assert 0 < len(blob) <= symbols["__image_end"] - CODE <= symbols["__end"] - CODE <= 0x10000
    decoder = Cs(CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN)
    # Decode independently because the resident also contains literal pools.
    instructions = {ins.address: ins.mnemonic for off in range(0, len(blob) - 3, 4)
                    for ins in decoder.disasm(blob[off:off + 4], CODE + off)}
    layout = struct.unpack_from("<" + "Q" * (1 + 2 * len(Frame.fields)), blob,
                                symbols["capture_test_frame_layout"] - CODE)
    frame_layout = {name: (layout[1 + i * 2], layout[2 + i * 2])
                    for i, name in enumerate(Frame.fields)}
    return Resident(blob, symbols, instructions, firmware, layout[0], frame_layout)


class CaptureMachine:
    def __init__(self, resident):
        self.resident, self.symbols = resident, resident.symbols
        self.uc = u = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
        for address, size in ((FW, 0x4400000), (CODE, 0x10000), (STACK, 0x10000),
                              (DATA, 0x10000), (PLANES, 0x500000), (LEFT_TABLE & ~4095, 0x2000)):
            u.mem_map(address, size)
        u.mem_write(FW, resident.firmware)
        u.mem_write(CODE, resident.blob)
        u.mem_write(CLEAR_EXCLUSIVE, struct.pack("<II", 0xd5033f5f, 0xd503201f))
        u.reg_write(r.UC_ARM64_REG_CPACR_EL1, 3 << 20)
        # Patch only this emulator's RAM, using the actual shared router.
        u.mem_write(ISLAND, struct.pack("<IIQ", 0x58000050, 0xd61f0200,
                                       self.symbols["focus_sensor_wrapper"]))
        for site, target in SITES.items():
            assert self.get(site, 4) == branch(site, target), f"wrong BL at {site:#x}"
            self.put(site, branch(site, ISLAND), 4)
        for site in (0x4d32ca044, 0x4d32ca054):
            self.put(site, branch(site, ISLAND), 4)
        self.tick, self.tick_step, self.lens_kind = 10000000, 1200, 0
        self.wait_results, self.wait_index = [(0, 1), (0, 3)], 0
        self.bank_rc, self.start_rc, self.send_rc, self.event_rc = 0, 0, 0xfffffff7, 0
        self.native_calls, self.native_returns, self.queue = [], [], []
        self.invalidations, self.dc, self.raw_reads, self.events = [], [], [], []
        self.event_sets, self.logs, self.getter_calls = [], [], []
        self.held, self.callbacks, self.visits, self.preemptions = {}, {}, {}, []
        self.suspended, self.resume_pc, self.skip_schedule = None, None, None
        self.stop = STOP
        self.before_atomic_store = None
        self.put(0x4d70346a0, 2, 4)
        self.put(0x4d70346a4, 12, 4)
        u.mem_write(SCENE, struct.pack("<4Q", *SCENE_VALUES))
        self.put(MANUAL_LENSES, TABLE)
        self.put(SETTINGS, SETTINGS_DATA)
        self.set_identity()
        writer = bytearray(0x58)
        struct.pack_into("<I", writer, 8, 3)
        for off, width, stride in ((0x30, 1514, 1536), (0x40, 504, 512)):
            struct.pack_into("<3H", writer, off, width, 334, stride)
            writer[off + 8:off + 10] = bytes((14, 8))
        u.mem_write(WRITER, bytes(writer))
        self.put(0x4d70342e4, 3, 4)
        self.put(0x4d72fba22, 4, 1)
        self.put(0x4d72fba28, STRIDE)
        self.put(0x4d72fba30, 512)
        self.put(0x4d703459c, 2, 4)
        self.put(EVENT, 77, 4)
        self.put(FIRST, 0, 1)  # hot attachment to an existing pending frame
        self.put(0x4d72fba38, 0, 1)
        u.mem_write(DATA + 0x200, bytes((i * 7) & 255 for i in range(0x110)))
        old = bytearray(0x158)
        struct.pack_into("<3I", old, 4, 3, 0, 99)
        struct.pack_into("<3Q", old, 0x10, self.tick - 100000, self.tick + 700000, self.tick - 99000)
        struct.pack_into("<4Q", old, 0x138, *BANKS[2], *BANKS[3])
        u.mem_write(PENDING, bytes(old))
        self.paint_planes(0)
        self.hooks = [u.hook_add(UC_HOOK_CODE, self.hook),
                      u.hook_add(UC_HOOK_MEM_READ, self.read_hook, begin=PLANES, end=PLANES + 0x500000 - 1),
                      u.hook_add(UC_HOOK_MEM_WRITE, self.write_hook)]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        if self.uc is not None:
            for handle in self.hooks:
                self.uc.hook_del(handle)
            self.uc = None

    def put(self, address, value, size=8):
        self.uc.mem_write(address, (value & ((1 << (8 * size)) - 1)).to_bytes(size, "little"))

    def get(self, address, size=8):
        return int.from_bytes(self.uc.mem_read(address, size), "little")

    def read(self, address, size):
        return bytes(self.uc.mem_read(address, size))

    @property
    def status(self):
        return Status.from_buffer_copy(self.read(self.symbols["focus_capture_status"], C.sizeof(Status)))

    def frame(self, address):
        return Frame(self.read(address, self.resident.frame_size), self.resident.frame_layout)

    def set_identity(self, slot=4, profile=(0x12345678, 0x90abcdef)):
        self.put(SETTINGS_DATA + 0xb4, slot, 4)
        if slot < 10:
            self.uc.mem_write(TABLE + 0x10 + slot * 10, struct.pack("<2I", *profile))

    def identity(self):
        slot = self.get(SETTINGS_DATA + 0xb4, 4)
        profile = struct.unpack("<2I", self.read(TABLE + 0x10 + slot * 10, 8)) if slot < 10 else (0, 0)
        return Identity(slot, (C.c_uint32 * 2)(*profile))

    def prepare_request(self, epoch=1, after_ticks=None, identity=None, enabled=1):
        request = Request(enabled, epoch, self.tick - 1000 if after_ticks is None else after_ticks,
                          self.identity() if identity is None else identity, 0)
        self.uc.mem_write(REQUEST_DATA, bytes(request))
        return REQUEST_DATA

    def request(self, **kwargs):
        self.call("focus_capture_request", self.prepare_request(**kwargs))

    def acquire(self):
        return self.hold(self.call("focus_capture_acquire"))

    def hold(self, address):
        if address:
            assert address not in self.held, "acquired a slot already held by the consumer"
            self.held[address] = self.read(address, self.resident.frame_size)
        return address

    def release(self, address):
        self.call("focus_capture_release", address)
        self.held.pop(address, None)

    def paint_planes(self, serial):
        for bank, pair in enumerate(BANKS):
            for plane, base in enumerate(pair):
                for row in range(HEIGHT):
                    self.uc.mem_write(base + ROI + row * STRIDE,
                                      bytes((serial * 17 + bank * 41 + plane * 29 + row + x) & 255
                                            for x in range(WIDTH)))

    def pixels(self, base):
        return b"".join(self.read(base + ROI + row * STRIDE, WIDTH) for row in range(HEIGHT))

    def prepare_receiver(self, token=1, stamp=None, skip=0):
        stamp = self.tick - 200 if stamp is None else stamp
        self.uc.mem_write(DATA, struct.pack("<3I", 3, 0, token))
        self.uc.mem_write(DATA + 0x100, struct.pack("<3Q", stamp, stamp + 800000, stamp + 400))
        self.wait_index = 0
        return skip, DATA, DATA + 0x100, DATA + 0x200

    def receiver(self, token=1, stamp=None, skip=0):
        return self.run(RECEIVER, self.prepare_receiver(token, stamp, skip))

    def prepare_irq(self, words):
        assert len(words) <= 8
        self.uc.mem_write(DATA + 0x400, bytes(32) + struct.pack("<8I", *(list(words) + [0] * (8 - len(words)))))
        return (DATA + 0x400,)

    def irq(self, words=(1, 1)):
        return self.run(IRQ_CALLBACK, self.prepare_irq(words))

    def ready(self):
        self.request()
        self.receiver(1)
        self.irq()

    def at(self, pc, callback, occurrence=1):
        self.callbacks[pc, self.visits.get(pc, 0) + occurrence] = callback

    def preempt(self, target, args=(), after=None):
        """Called from an instruction checkpoint, never recursively emu_start."""
        assert self.suspended is None, "nested test preemption is unsupported"
        pc = self.uc.reg_read(r.UC_ARM64_REG_PC)
        self.suspended = (self.uc.context_save(), pc, self.saved_registers(), after, target)
        self.uc.reg_write(r.UC_ARM64_REG_SP, INTERRUPT_STACK)
        self.uc.reg_write(r.UC_ARM64_REG_LR, INTERRUPT_RETURN)
        for i, value in enumerate(args):
            self.uc.reg_write(getattr(r, f"UC_ARM64_REG_X{i}"), value)
        self.uc.reg_write(r.UC_ARM64_REG_PC, self.symbols[target] if isinstance(target, str) else target)

    def preempt_irq(self, words):
        self.preempt(IRQ_CALLBACK, self.prepare_irq(words))

    def saved_registers(self):
        return ({n: self.uc.reg_read(getattr(r, f"UC_ARM64_REG_X{n}")) for n in range(18, 30)},
                {n: self.uc.reg_read(getattr(r, f"UC_ARM64_REG_Q{n}")) & ((1 << 64) - 1) for n in range(8, 16)})

    def assert_preserved(self, saved, sp):
        assert self.uc.reg_read(r.UC_ARM64_REG_SP) == sp, "SP was not restored"
        actual = self.saved_registers()
        for kind, before, after in zip(("x", "d"), saved, actual):
            for n, value in before.items():
                assert after[n] == value, f"{kind}{n} was clobbered: {value:#x} -> {after[n]:#x}"

    def run(self, pc, args=(), stop=STOP, sp=STACK_TOP, registers=None):
        for n in range(18, 30):
            self.uc.reg_write(getattr(r, f"UC_ARM64_REG_X{n}"), 0x1234567800abc000 + n)
        for n in range(8, 16):
            self.uc.reg_write(getattr(r, f"UC_ARM64_REG_Q{n}"), (0x1122334455667788 << 64) | (0xabcde000 + n))
        for n, value in (registers or {}).items():
            self.uc.reg_write(getattr(r, f"UC_ARM64_REG_X{n}"), value)
        for n, value in enumerate(args):
            self.uc.reg_write(getattr(r, f"UC_ARM64_REG_X{n}"), value)
        self.uc.reg_write(r.UC_ARM64_REG_SP, sp)
        self.uc.reg_write(r.UC_ARM64_REG_LR, stop)
        self.stop = stop
        saved = self.saved_registers()
        self.uc.emu_start(pc, stop, count=400000)
        assert self.uc.reg_read(r.UC_ARM64_REG_PC) == stop, f"instruction budget exhausted at {self.uc.reg_read(r.UC_ARM64_REG_PC):#x}"
        assert self.suspended is None
        self.assert_preserved(saved, sp)
        for address, original in self.held.items():
            assert self.read(address, len(original)) == original, "held frame changed"
        return self.uc.reg_read(r.UC_ARM64_REG_X0)

    def call(self, name, *args):
        return self.run(self.symbols[name], args)

    def call_site(self, site, args, **kwargs):
        return self.run(site, args, stop=site + 4, **kwargs)

    def ret(self, value=0):
        self.uc.reg_write(r.UC_ARM64_REG_X0, value & ((1 << 64) - 1))
        self.uc.reg_write(r.UC_ARM64_REG_PC, self.uc.reg_read(r.UC_ARM64_REG_LR))

    def read_hook(self, u, access, address, size, value, opaque):
        self.raw_reads.append((address, size))
        self.events.append(("read", address, size))

    def write_hook(self, u, access, address, size, value, opaque):
        assert not PLANES <= address < PLANES + 0x500000, "adapter wrote hardware-owned RAM"
        for frame, data in self.held.items():
            assert address + size <= frame or address >= frame + len(data), f"write to held frame at {address:#x}"

    def hook(self, u, pc, size, opaque):
        # A slice may end inside a TB already cached by a whole receiver run.
        # Unicorn's emu_start(until=...) alone does not always split that TB.
        if pc == self.stop and self.suspended is None:
            u.emu_stop()
            return
        if pc == INTERRUPT_RETURN:
            context, self.resume_pc, saved, after, target = self.suspended
            self.assert_preserved(saved, INTERRUPT_STACK)
            result = u.reg_read(r.UC_ARM64_REG_X0)
            self.preemptions.append((target, result))
            if after:
                after(result)
            self.suspended = None
            u.context_restore(context)
            u.reg_write(r.UC_ARM64_REG_PC, CLEAR_EXCLUSIVE)
            return
        if pc == RESUME:
            self.skip_schedule = self.resume_pc
            u.reg_write(r.UC_ARM64_REG_PC, self.resume_pc)
            return
        resumed = pc == self.skip_schedule
        if resumed:
            self.skip_schedule = None
        else:
            self.visits[pc] = self.visits.get(pc, 0) + 1
            action = self.callbacks.pop((pc, self.visits[pc]), None)
            if action:
                action(self)
                if u.reg_read(r.UC_ARM64_REG_PC) != pc:
                    return
            if self.before_atomic_store and self.resident.instructions.get(pc) in ("stlr", "stlxr", "stxr"):
                action, self.before_atomic_store = self.before_atomic_store, None
                action(self)
                if u.reg_read(r.UC_ARM64_REG_PC) != pc:
                    return
        if pc in (PROGRAM, WAIT, IRQ, SEND):
            assert u.reg_read(r.UC_ARM64_REG_SP) % 16 == 0
            self.native_calls.append((pc, tuple(u.reg_read(getattr(r, f"UC_ARM64_REG_X{i}")) for i in range(4))))
        if pc - 4 in SITES:
            self.native_returns.append((pc - 4, u.reg_read(r.UC_ARM64_REG_X0)))
        if pc in (LENS, SELECTION, PROFILE):
            self.getter_calls.append(pc)  # run all three native getters
        if pc == 0x4d31a5c00:
            self.ret(self.tick)
            self.tick += self.tick_step
        elif pc == 0x4d32cb1d0:
            self.ret(self.bank_rc)
        elif pc == 0x4d32cb5c0:
            self.ret(self.start_rc)
        elif pc in (0x4d32cb700, 0x4d32ca910):
            self.ret()
        elif pc == 0x4d3001a78:
            assert self.wait_index < 2, "unexpected extra native wait"
            result, bits = self.wait_results[self.wait_index]
            self.wait_index += 1
            assert u.reg_read(r.UC_ARM64_REG_X4) == 0xffffffff
            if bits is not None:
                self.put(u.reg_read(r.UC_ARM64_REG_X3), bits, 4)
            u.reg_write(r.UC_ARM64_REG_X0, result & 0xffffffff)
            u.reg_write(r.UC_ARM64_REG_PC, pc + 4)
        elif pc == 0x4d3033890:
            output = u.reg_read(r.UC_ARM64_REG_X1)
            u.mem_write(output, struct.pack("<4I", 0, 0, 0, (0, 8, 0x1000)[self.lens_kind]))
            self.ret()
        elif pc == 0x4d30337d0:
            self.event_sets.append((u.reg_read(r.UC_ARM64_REG_X0), u.reg_read(r.UC_ARM64_REG_X1)))
            self.ret(self.event_rc)
        elif pc == 0x4d3008458:
            self.logs.append(u.reg_read(r.UC_ARM64_REG_X0))
            self.ret()
        elif pc in (0x4d3007fc0, 0x4d3008200):
            a, b, n = (u.reg_read(getattr(r, f"UC_ARM64_REG_X{i}")) for i in range(3))
            assert n <= 0x200, f"unexpected native memory helper size {n:#x}"
            u.mem_write(a, self.read(b, n) if pc == 0x4d3007fc0 else bytes([b & 255]) * n)
            self.ret(a)
        elif pc == 0x4d3033a30:
            pointer, n = u.reg_read(r.UC_ARM64_REG_X1), u.reg_read(r.UC_ARM64_REG_X2)
            assert n == 0x178
            self.queue.append(self.read(pointer, n))
            self.ret(self.send_rc)
        elif pc == INVALIDATE:
            args = u.reg_read(r.UC_ARM64_REG_X0), u.reg_read(r.UC_ARM64_REG_X1)
            self.invalidations.append(args)
            self.events.append(("invalidate", *args))
        elif pc == DC_IVAC:
            address = u.reg_read(r.UC_ARM64_REG_X0)
            self.dc.append(address)
            self.events.append(("dc", address, 64))
            u.reg_write(r.UC_ARM64_REG_PC, pc + 4)
