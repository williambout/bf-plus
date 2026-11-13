# Frozen BF+ Doom engine, ABI 1

The API is in `bfdoom.h`: `uint64_t bfdoom_entry(uint32_t op, void *arg)`.
Return values are sign-extended status codes. INIT, TICK, FRAME, STOP, INFO,
and raw KEY operations use the structures in that header.

The resident supplies the entire immutable IWAD and a separate writable heap.
INIT with flags=0 starts the title; `BFDOOM_AUTOSTART` starts medium skill on
the first map. TICK accepts wrapping milliseconds and held button bits,
retains fractional 35 Hz timing, and limits catch-up to four frames per call.
The first TICK establishes the clock. FRAME supplies 320x200 **R,G,B,255
bytes**, pitch 1280, plus indexed pixels and the current RGB palette.
STOP restores pristine engine state and releases all references to host
buffers. Call STOP before freeing buffers or unloading the module.

One singleton and one calling thread are supported. There are no native
callbacks, firmware calls, network calls, or filesystem access. Engine exit,
allocation failures, and reported engine errors unwind to entry and return
a status instead of terminating or spinning. INFO copies the last error text.
WAD directory bounds are checked, but this legacy engine is not a sandbox
for malicious or arbitrary malformed lump contents. Use known compatible
complete IWADs. Save/load, audio output, multiplayer, PWAD overlays, and DEH
extensions are outside this adapter. The renderer retains vanilla Doom limits.

## Offline build and tests

Run from the repository root with Clang, lld, and LLVM utilities installed:

```sh
python3 -m bfplus.doom_engine.build_module --host
.venv/bin/python -m unittest tests.test_doom_engine -v
```

Use `--sdl` to additionally build the playable native SDL2 harness (requires
SDL2 and pkg-config). `--sanitize` builds an AddressSanitizer host harness.
Neither is a dependency of the freestanding module. The optional explicit
test-data download is `python3 -m bfplus.doom_engine.fetch_test_wad`.

All output goes under `.touch-focus/doom-engine/`. The normal BF+ build does
not compile this engine. The separate module builder emits `build/bfdoom.elf`
and `build/module.json`; camera packaging and loading are handled elsewhere.

## Frozen artifact

Verified with Apple Clang 21.0.0 and lld. Build-path strings are normalized;
the canonical build and tested module have identical SHA-256:

`329c456981156ea0bacc89d42dd429f61fa9f3c40b19fa18e965fddbb706c88b`

| Quantity | Bytes / value |
| --- | ---: |
| ELF file | 1,145,512 |
| Loaded memory extent | 1,079,273 |
| Executable code | 317,288 |
| Engine state snapshot, inside supplied heap | 701,224 |
| Recommended supplied heap | 25,165,824 (24 MiB) |
| Doom zone reserved inside that heap | 22,020,096 (21 MiB) |
| Dedicated stack used in AArch64 test | 262,144 (256 KiB) |
| Entry offset / ELF e_entry | 310280 |
| Relocations | 1,236, all R_AARCH64_RELATIVE |

The ELF is AArch64 little-endian ET_DYN linked at zero, with nonoverlapping
RX/R/RW PT_LOAD segments, no writable executable segment, and no unresolved
symbols. Relocations write only initialized writable data. The module avoids
FP/SIMD, system-call instructions, and x18. Load/zero the segments and apply
relative relocations before calling entry. The resident remains responsible
for memory permissions, cache synchronization, and the dedicated stack.

Reserve approximately 29.3 MiB total for the classic shareware WAD, module,
24 MiB heap, and 256 KiB stack, plus loader overhead. Freedoom requires about
52.7 MiB total because its complete IWAD is roughly 28.8 MB. The classic
3,500-tick native smoke run reserved 23,402,640 bytes inside the supplied heap;
that figure includes the entire Doom zone, not just its live level objects.

## Observed verification

All nine tests passed in 11.238 seconds. Doom shareware 1.9, Freedoom1, and
Freedoom2 passed AddressSanitizer checks for title → New Game → first map,
walking, turning, firing (ammo decreases), opening a real map door through
USE, quit, missing-COLORMAP error unwinding, and five fresh-heap restarts with
identical frames. The door fixture places the real player in front of a real
door; the public USE input performs the opening. Freedoom2 MAP01 has manual
door types 31/117 rather than type 1.

The classic native smoke also completed 3,500 requested ticks (3,501 rendered
frames, 3,459 gameplay tics; transition wipes account for the difference).
Frame FNV-1a hash was 41052158. RGBX exactly matched indexed pixels plus palette.

The exact frozen AArch64 ELF was relocated to an arbitrary base in Unicorn
and executed with FP disabled and a 256 KiB stack. Its framebuffer matched
native output byte-for-byte after 80 calls, x18 and callee-saved registers
were preserved, and quit/reinit/stop returned correctly. Timing tests cover
35 Hz accumulation, clock wrap, backwards clocks, and bounded catch-up.
Allocation exhaustion returns cleanly and a subsequent init succeeds.

ASan instrumentation remains enabled on the engine and allocator; only the
bounded state snapshot copy bypasses ASan because it intentionally traverses
padding between global objects. Heap accounting and guard checks additionally
verify the supplied arena boundaries. These are host/emulation results;
physical camera performance and integration remain the loader's validation.
