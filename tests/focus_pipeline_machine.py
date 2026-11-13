"""Offline native capture -> live -> phase/guide/painter execution fixture.

Reuse the BF 1.04 capture fixture's firmware fingerprint, router, receiver,
waits, IRQ, sender and explicitly synthetic service leaves. No capture/live/
matcher/guide/painter function is replaced. Even the native rectangle routine
runs against mapped RAM. Observers only read the actual request/frame ABI.

The clock, imagery and policy are synthetic. This is not optical, RTOS, DMA,
cache-coherence, bank-ownership, physical-color or display-lifecycle evidence.
Build artifacts exist only in the caller's TemporaryDirectory. No production
build/loader/transport module is imported and no installation is performed.
"""

import ctypes as C
from dataclasses import replace
from pathlib import Path
import random
import shutil
import struct
import subprocess
from types import SimpleNamespace

from tests import focus_capture_machine as capture
from tests.test_focus_live import Frame as LiveFrame


TICKS_PER_MS = 24000
FRAME_INTERVAL_MS = 60
MAX_AGE_MS = 200
SURFACE = capture.DATA + 0x4000
PIXELS = 0x44a000000
FRAMEBUFFER_BYTES = 2048 * 682
BACKGROUND, GRAY, WHITE, GREEN = 0xa5a5, 0x888f, 0xffff, 0x0f0f
RECTANGLE = 0x4d3325ca0

# Expressions use public C fields; Python does not guess FocusLive offsets.
OBSERVATIONS = {
    "state": "guide.state", "generation": "guide.generation",
    "confirmed": "guide.confirmed", "have_sample": "guide.have_sample",
    "calibration": "live.calibration", "count": "live.calibration_count",
    "zero_q8": "live.zero_q8", "calibration_epoch": "live.calibration_epoch",
    "source_epoch": "live.last_source_epoch", "sequence": "live.last_sequence",
    "acquired_ticks": "live.last_acquired_ticks",
    "after_ticks": "live.request_after_ticks",
    "capture_reason": "live.last_capture_reason",
    "software_checks": "live.last_software_checks_passed",
    "match_valid": "live.last_match.valid",
    "displacement_q8": "live.last_match.displacement_q8",
    "tile0_valid": "live.last_tiles[0].valid", "tile1_valid": "live.last_tiles[1].valid",
    "spatial_rejection": "live.last_spatial_rejection",
    "match_ticks": "live.last_match_ticks", "view_seq": "live.view_seq",
}

BRIDGE = r'''
#include <stddef.h>
#include "focus_live.h"
static struct FocusGuide guide;
static struct FocusLive live;
/* Deliberately synthetic test policy, copied from test_focus_live.py.
 * These numbers are NOT production defaults or optical calibration. */
static const struct FocusLivePolicy policy = {
    .match={128,24,128,32,900,100,4},
    .enter_q8=64, .leave_q8=96, .large_q8=768, .max_age_ms=200,
    .confirmation_frames=3, .calibration_span_q8=48,
    .calibration_zero_limit_q8=512, .calibration_spacing_ms=50,
    .calibration_timeout_ms=5000, .spatial_disagreement_q8=96
};
void pipeline_init(void) { focus_live_init(&live,&guide,&policy,1); }
int pipeline_poll(int allowed) { return focus_live_poll(&live,allowed); }
void pipeline_calibrate(void) { focus_live_calibrate(&live); }
int pipeline_draw(void *surface) { return focus_live_draw(&live,surface); }
'''


def build_pipeline(directory):
    """Keep capture's compiler/fingerprint/ABI failures fatal, missing inputs skip."""
    base = capture.build_resident(directory)
    d = Path(directory)
    tools = {name: shutil.which(name) or f"/opt/homebrew/opt/{package}/bin/{name}"
             for name, package in (("clang", "llvm"), ("ld.lld", "lld"),
                                   ("llvm-nm", "llvm"), ("llvm-objcopy", "llvm"))}
    # Also audit the older live-only fixture's ABI, including every field size.
    # Actual data flow below is a native pointer, never a Python Frame offer.
    bridge = [BRIDGE, f'_Static_assert(sizeof(struct FocusCaptureFrame) == '
              f'{C.sizeof(LiveFrame)}, "live fixture frame size");']
    for name, ctype in LiveFrame._fields_:
        bridge.append(f'_Static_assert(offsetof(struct FocusCaptureFrame, {name}) == '
                      f'{getattr(LiveFrame, name).offset}, "live fixture {name} offset");')
        bridge.append(f'_Static_assert(sizeof(((struct FocusCaptureFrame *)0)->{name}) == '
                      f'{C.sizeof(ctype)}, "live fixture {name} size");')
    bridge.append(f'const uint64_t *pipeline_snapshot(void) {{ static uint64_t s[{len(OBSERVATIONS)}];')
    bridge.extend(f's[{i}]=(uint64_t)({expr});' for i, expr in enumerate(OBSERVATIONS.values()))
    bridge.append('return s; }')
    (d / "pipeline_bridge.c").write_text("\n".join(bridge))
    flags = ["--target=aarch64-none-elf", "-Oz", "-std=c11", "-ffreestanding",
             "-fno-builtin", "-fno-stack-protector", "-fno-unwind-tables",
             "-fno-asynchronous-unwind-tables", "-mgeneral-regs-only", "-ffixed-x18",
             "-fno-jump-tables", "-ffunction-sections", "-fdata-sections", "-mcmodel=tiny",
             "-fpie", "-fvisibility=hidden", "-Wall", "-Wextra", "-Werror"]
    objects = [d / name for name in ("focus_capture.o", "runtime.o", "router.o")]
    sources = [capture.ROOT / "touch_focus" / name for name in
               ("focus_live.c", "focus_guide.c", "focus_guide_render.c", "focus_phase.c")]
    for source in [*sources, d / "pipeline_bridge.c"]:
        obj = d / (source.stem + ".o")
        subprocess.run([tools["clang"], *flags, "-I", str(capture.ROOT / "touch_focus"),
                        "-c", str(source), "-o", str(obj)], check=True)
        objects.append(obj)
    # Bound the scalar matcher's text so only its entry needs a Python hook.
    # All its AArch64 instructions still execute; nothing substitutes a result.
    linker = (d / "resident.ld").read_text().replace(
        ".text : { *(.text*) }", """.text : {
 *(EXCLUDE_FILE (*focus_phase.o) .text*)
 __pipeline_phase_begin = .;
 *focus_phase.o(.text*)
 __pipeline_phase_end = .;
 }""")
    assert "__pipeline_phase_begin" in linker, "capture fixture linker contract changed"
    (d / "pipeline.ld").write_text(linker)
    elf, binary = d / "pipeline.elf", d / "pipeline.bin"
    subprocess.run([tools["ld.lld"], "-T", str(d / "pipeline.ld"),
                    *(str(obj) for obj in objects), "-o", str(elf)], check=True)
    assert not subprocess.check_output([tools["llvm-nm"], "--undefined-only", str(elf)], text=True).strip()
    subprocess.run([tools["llvm-objcopy"], "-O", "binary", str(elf), str(binary)], check=True)
    symbols = {}
    for line in subprocess.check_output([tools["llvm-nm"], "--defined-only", str(elf)], text=True).splitlines():
        fields = line.split()
        if len(fields) == 3:
            symbols[fields[2]] = int(fields[0], 16)
    blob = binary.read_bytes()
    assert 0 < len(blob) <= symbols["__image_end"] - capture.CODE <= symbols["__end"] - capture.CODE <= 0x10000
    layout_size = 8 * (1 + 2 * len(capture.Frame.fields))
    old = base.symbols["capture_test_frame_layout"] - capture.CODE
    new = symbols["capture_test_frame_layout"] - capture.CODE
    assert blob[new:new + layout_size] == base.blob[old:old + layout_size]
    decoder = capture.Cs(capture.CS_ARCH_ARM64, capture.CS_MODE_LITTLE_ENDIAN)
    instructions = {ins.address: ins.mnemonic for off in range(0, len(blob) - 3, 4)
                    for ins in decoder.disasm(blob[off:off + 4], capture.CODE + off)}
    return replace(base, blob=blob, symbols=symbols, instructions=instructions)


class PipelineMachine(capture.CaptureMachine):
    def __init__(self, resident):
        self.polling = False
        self.requests, self.frames, self.releases, self.matches, self.rectangles = [], [], [], [], []
        super().__init__(resident)
        self.uc.mem_map(PIXELS, 0x200000)
        # Keep all inherited instruction observers except inside pure phase
        # arithmetic. Firmware calls/waits and the native painter run unchanged.
        self.uc.hook_del(self.hooks.pop(0))
        for start, end in ((capture.FW, capture.FW + 0x4400000 - 1),
                           (capture.CODE, self.symbols["__pipeline_phase_begin"] - 1),
                           (capture.STACK, capture.STACK + 0xffff),
                           (self.symbols["focus_phase_match"], self.symbols["focus_phase_match"])):
            self.hooks.append(self.uc.hook_add(capture.UC_HOOK_CODE, self.hook, begin=start, end=end))
        self.token = 0
        self.call("pipeline_init")
        self.poll()

    @property
    def state(self):
        address = self.call("pipeline_snapshot")
        values = struct.unpack("<" + "Q" * len(OBSERVATIONS), self.read(address, 8 * len(OBSERVATIONS)))
        result = dict(zip(OBSERVATIONS, values))
        for name in ("zero_q8", "displacement_q8"):
            if result[name] >= 1 << 63:
                result[name] -= 1 << 64
        return SimpleNamespace(**result)

    @property
    def live_request(self):
        return self.requests[-1]

    def calibrate(self):
        self.call("pipeline_calibrate")

    def poll(self, allowed=1):
        # The real three-window matcher needs more than the capture fixture's
        # 400k instruction limit. Receiver runs retain that original limit.
        u, r = self.uc, capture.r
        u.reg_write(r.UC_ARM64_REG_X0, allowed)
        u.reg_write(r.UC_ARM64_REG_SP, capture.STACK_TOP)
        u.reg_write(r.UC_ARM64_REG_LR, capture.STOP)
        self.stop = capture.STOP
        saved = self.saved_registers()
        self.polling = True
        try:
            u.emu_start(self.symbols["pipeline_poll"], capture.STOP, count=12000000)
            assert u.reg_read(r.UC_ARM64_REG_PC) == capture.STOP, "live poll instruction budget exhausted"
            assert self.suspended is None
            self.assert_preserved(saved, capture.STACK_TOP)
            assert not self.held, "live poll leaked an acquired capture slot"
            return u.reg_read(r.UC_ARM64_REG_X0)
        finally:
            self.polling = False

    def imagery(self, shift):
        rng = random.Random(9001)
        rows = [bytes(rng.randrange(32, 96) for _ in range(capture.WIDTH))
                for _ in range(capture.HEIGHT)]
        planes = (b"".join(rows), b"".join(bytes(row[(x - shift) % capture.WIDTH]
                                                   for x in range(capture.WIDTH)) for row in rows))
        for pair in capture.BANKS:
            for base, pixels in zip(pair, planes):
                for y in range(capture.HEIGHT):
                    self.uc.mem_write(base + capture.ROI + y * capture.STRIDE,
                                      pixels[y * capture.WIDTH:(y + 1) * capture.WIDTH])
        return planes

    def receive(self, shift=1, advance_ms=FRAME_INTERVAL_MS):
        self.tick += advance_ms * TICKS_PER_MS
        self.token += 1
        pixels = self.imagery(shift)
        self.irq()
        calls, returns, queued = len(self.native_calls), len(self.native_returns), len(self.queue)
        pending = self.read(capture.PENDING, 0x158)
        priming = bool(self.get(capture.FIRST, 1))
        result = self.receiver(self.token)
        return SimpleNamespace(result=result, priming=priming, pixels=pixels,
                               pending=pending, calls=self.native_calls[calls:],
                               returns=self.native_returns[returns:], waits=self.wait_index,
                               queued=self.queue[queued:])

    def draw(self):
        self.rectangles.clear()
        desc = bytearray(32)
        struct.pack_into("<HH", desc, 0, 682, 0)
        struct.pack_into("<Q", desc, 8, PIXELS + 64)
        struct.pack_into("<H", desc, 0x10, 2048)
        struct.pack_into("<H", desc, 0x14, 682)
        self.uc.mem_write(SURFACE, bytes(desc))
        self.uc.mem_write(PIXELS, b"\xa5" * (FRAMEBUFFER_BYTES + 128))
        result = self.call("pipeline_draw", SURFACE)
        framebuffer = self.read(PIXELS + 64, FRAMEBUFFER_BYTES)
        assert self.read(PIXELS, 64) == self.read(PIXELS + 64 + FRAMEBUFFER_BYTES, 64) == b"\xa5" * 64
        return SimpleNamespace(result=result, colors=set(memoryview(framebuffer).cast("H")) - {BACKGROUND},
                               dirty=struct.unpack("<HH", self.read(SURFACE, 4)),
                               rectangles=tuple(self.rectangles))

    def hook(self, u, pc, size, opaque):
        r = capture.r
        if pc == self.symbols["focus_capture_request"]:
            pointer = u.reg_read(r.UC_ARM64_REG_X0)
            self.requests.append(capture.Request.from_buffer_copy(self.read(pointer, C.sizeof(capture.Request))))
        elif self.polling and pc == self.symbols["focus_capture_acquire"]:
            def acquired(machine):
                pointer = u.reg_read(r.UC_ARM64_REG_X0)
                if pointer:
                    machine.hold(pointer)
                    machine.frames.append((pointer, machine.frame(pointer)))
            self.at(u.reg_read(r.UC_ARM64_REG_LR), acquired)
        elif self.polling and pc == self.symbols["focus_capture_release"]:
            pointer = u.reg_read(r.UC_ARM64_REG_X0)
            assert pointer in self.held
            def released(machine):
                original = machine.held.pop(pointer)
                assert machine.read(pointer, len(original)) == original, "live code mutated its capture"
                machine.releases.append(pointer)
            self.at(u.reg_read(r.UC_ARM64_REG_LR), released)
        elif pc == self.symbols["focus_phase_match"]:
            a, b, config = (u.reg_read(getattr(r, f"UC_ARM64_REG_X{i}")) for i in range(3))
            self.matches.append((a, b, struct.unpack("<7H", self.read(config, 14))))
        elif pc == RECTANGLE:
            assert u.reg_read(r.UC_ARM64_REG_X0) == SURFACE
            rect = struct.unpack("<4H", self.read(u.reg_read(r.UC_ARM64_REG_X1), 8))
            self.rectangles.append((*rect, u.reg_read(r.UC_ARM64_REG_X2)))
            # Do not return here: execute the firmware's rectangle painter.
        super().hook(u, pc, size, opaque)
