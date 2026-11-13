# BF 1.04 portrait menu rendering

> Historical experiment: the user requested removal of automatic UI rotation
> and LCD menu controls. These adapters are unlinked from the current replacement
> build. The installed image is retained until the reduced native-aspect build
> completes verification and replacement.

The full integration is documented in [UI-INTEGRATION.md](UI-INTEGRATION.md).
**BF+ → Auto Rotate UI** controls the shared OSD orientation. Settings, BF+ and
owned option pickers use the renderer described below; other stock scenes use
the canonical foreground/background compositor and proportional portrait fit.
This document records the native font/pixel evidence and the full-size owned
menu renderer API. It is not an exhaustive whole-camera validation report.

The initialized resident image now exceeds 16 KiB and uses the separate
segmented loader. The staging/per-transfer cap remains 16 KiB, resident extent
is bounded by 64 KiB, and combined scratch is 4,888,576 bytes. Builds derive
actual image/BSS extents from their own immutable symbol/layout manifest.

The render boundary and pixel formats are established. The two portrait sensor
values are established, but their physical left/right polarity is unresolved.
The header provisionally assigns raw 1 to CW and raw 3 to CCW. No verified
native 90-degree menu switch was found in the bounded investigation below.

## Evidence and sensor reader

Firmware runtime base: `0x4d3000000`, local `decoded-V104/rtos-alt.bin`.
SHA-256: `f747c1350f00526b9c68c65aaef44d6e7b644b0169992342e12f059c42e150dc`.
Glyph asset: `decoded-V104/09_2004.bin`, SHA-256
`4bb8640e089026324aceeca21387ac14a2e95ec3fe29a1b29c064ab45f9a70a2`.

`orientation_read()` calls the native `u32(void)` getter at **`0x4d31e36b0`**.
It returns zero before boot flag byte `0x4d72bc3c4` is set. Once initialized,
the native getter takes the mutex via `0x4d3033950` with timeout 100, performs
cache work with `0x4d3074b70` / `0x4d3074b50` on `0x400d00800`, length `0x400`,
and reads **`u32` at `(*(u64 *)0x4d702a200) + 0x74`**. It releases through
`0x4d3033970`. The header normalizes values outside 0..3 to zero. Use this
reader rather than an unsynchronized direct load. It is not interrupt-safe:
the native routine takes a mutex. On lock failure the native code logs and
continues its read; that error path has not been exercised by the tests.

The two original metadata conversion blocks were executed in Unicorn:

| Raw sensor | Capture block `0x4d32fd990` | Movie-frame block `0x4d32e9870` | Header treatment |
| --- | --- | --- | --- |
| 0 | 1 | 1 | Stock landscape path |
| 1 | 8 | 6 | Portrait, provisional CW |
| 2 | 3 | 3 | Stock path; no new 180-degree rendering |
| 3 | 6 | 8 | Portrait, provisional CCW |
| Other | 1 | 1 | Normalize to 0 |

Both blocks store the mapped orientation at `[x19+0x5c]`. The capture block
belongs to `0x4d32fd780`, called at `0x4d32fe4e0` and `0x4d32fe948` during
capture/metadata preparation. The opposite mapping belongs to `0x4d32e9740`,
called at `0x4d32eb240`. That caller prepares extracted movie-frame JPEGs:
the diagnostic at `0x4d3df5578`, referenced by literal `0x4d32eb2e0`, says
`[Debug] %.1fMB over MovCutFrame, May be broken jpeg`.

These consumer purposes explain why choosing one mapping by address alone is
unsafe. They establish quarter-turn versus landscape classification; they do
not establish which way the physical camera was tilted. Both render and touch
must use the same convention if polarity is later corrected. The separate
angle reader `0x4d31e35b0(int *,int *)` reads shared offsets `+0x6c/+0x70`;
`0x4d31e3b90()` reads the float at `+0x68`. Neither is needed here.

## Verified render boundary and formats

The display worker invokes foreground at **`0x4d31ad2a4`**, then cleans that
surface at `0x4d31ad2c0` through `0x4d3074b50`. It invokes background at
**`0x4d31ad30c`**, then cleans its color and alpha planes at `0x4d31ad328` and
`0x4d31ad350`. Display bank switching follows through `0x4d321de60`.
These ordering claims are from original instructions, not a hardware trace.
Render and present before returning from the foreground callback. Leave cache
maintenance and bank switching to the stock worker. Do not rotate an already
rotated back buffer: the renderer rebuilds scratch and fully overwrites the
destination on every successful draw. It marks dirty rows `[0,682)`.

The 32-byte `OrientationSurface` is binary compatible with the native surface:

| Offset | Field |
| --- | --- |
| 0, 2 | `u16 dirty_first, dirty_end` |
| 8 | Pixel pointer |
| 16, 18, 20 | `u16 color_pitch, alpha_pitch, height` (pitches in bytes) |
| 24 | `u64 alpha_offset` relative to the pixel pointer |

Foreground is **two bytes per pixel**, RGB444 in the high 12 bits, alpha in
the low nibble. `0x0000` is transparent, `0x000f` opaque black, `0xffff` opaque
white. Background is **YUV422, four bytes per pair of pixels, plus one separate
alpha byte per pixel**. It is not packed four-byte RGBA. The standard background
uses color pitch 2048, alpha pitch 1024, alpha offset `0x155000`.

| Native function | Address | Contract used |
| --- | --- | --- |
| Foreground rectangle | `0x4d3325ca0` | `(surface, u16[4]{x,y,w,h}, raw_color)` |
| Text parser/rasterizer | `0x4d3328180` | `(surface, text_descriptor)` |
| Text width | `0x4d3327e50` | `(font, &text_pointer, 0)` |
| Text height | `0x4d3328000` | `(font, &text_pointer)` |
| Background rectangle | `0x4d3328cc0` | `(surface, u16[4], YUV_alpha_color)` |

Text takes a **palette index**, unlike rectangles. Palette `0x4d70346d0`
has four-byte entries: index 1 starts with `0xffff` (white), index 6 with
`0xbbbf` (gray), index 17 with `0x000f` (black). Native-pixel tests check title
white and value gray. The compact header draws no automatic title or row
chevrons. Titles are supplied unchanged by the menu integration. **ASCII `<` and `>`
produce no pixels in native fonts 4, 5, or 6**: a `"< BF+"` title does not give
a visible back indicator. Use a plain `"Back BF+"` / `"Back [option]"` title
for a visible affordance without extra rendering code. The real stock back
arrow uses `0x4d332d8d0(surface, xy, 1, flags, 4, 0x45)` with `u16 xy[2]` and
two `u32 flags[2]={1,0}`. That call was emulated and produced pixels; it is not
included in this size-constrained header. Null row values stay blank for all
flags; existing read-only values are retained.

The integrated fixed back titles were measured and rendered with the original
font-6 parser. Each is 60 pixels high and fits the 618×64 text guard without
scaling. Fixed literals avoid a dynamic title-copy loop.

| Title | Native width |
| --- | ---: |
| `Back BF+` | 213 |
| `Back Focus Zoom` | 379 |
| `Back MF Detection` | 408 |
| `Back Aspect Ratio` | 392 |

The native text descriptor is 40 bytes:
`{u16 x,y,w,h; const char *text; u64 measured; u32 color,font; u16 flags,pad[3];}`.
Flag 4 vertically centers the glyph cell. The original parser **does not clip
glyph writes to its rectangle** (`memcpy` at `0x4d332841c`). Consequently this
renderer measures each string first and draws directly into the portrait
surface only if width is at most **618** and height at most **64**. Unsupported
dimensions reject the whole frame: scratch can change, but physical output is
not published. There is no scaling, wrapping, or line buffer. Native font size
is preserved. Current BF+ labels/values fit and pass the native-pixel fixture.
Dimension guards do not detect missing glyphs such as ASCII chevrons.
Font 6 supports mixed-case ASCII; owned labels
start with `ESC,6` because the native row default font 5 lacks many lowercase
glyphs. Localized text beyond the supported measured bounds must fall back.

The stock row painter `0x4d3363df0` hardcodes a 1024-wide layout and cannot
simply be given a 682-wide surface. `IM_DISP_Set_OSD_Reverse_Display` at
`0x4d30854f0` writes the reverse-control register for layers 4/8; the direct
caller found at `0x4d321dc54` passes zero during setup. This does not establish
a quarter-turn menu mode. Image rotation `0x4d32f8de0` leads to the hardware
image/YUV path `0x4d30b63a0`; foreground compatibility and safe runtime use
remain unverified. The renderer uses neither function.

## Stable API and allocation

Include the header after `u8/u16/u32/u64/uptr` typedefs. All pre-existing
function signatures and the two structure layouts are unchanged. The existing
`orientation_text` line-buffer argument is now ignored for ABI compatibility.
`ORIENTATION_BYTES` is the scratch size, separate from the uploaded image and
the zero-initialized resident state.

1. Reserve **`ORIENTATION_BYTES = 1,396,736 = 0x155000` bytes** for portrait
   pixels. The current bootstrap makes one allocation containing the resident
   image/state, alignment allowance, and scratch. With
   `resident_size = __end - __start`, it calls
   the native allocator for resident memory, alignment, a loader guard and
   `UI_SCRATCH_BYTES` (owned portrait plus both canonical planes) and checks the low return byte. The resident base is
   aligned to 4096 bytes; scratch starts at `base + resident_size`, after the
   zero-initialized tail. Scratch is outside both the uploaded prefix and the
   linker-bounded resident state, without requiring a second allocation.
   Allocation failure prevents installation. The allocator was not invoked on
   hardware during this investigation. Retain scratch while callbacks can
   use it; only the single display worker draws into it.
2. Read sensor state in a suitable UI/update path. Queue a full menu repaint
   when the wanted portrait orientation changes. The shared integration owns
   paired redraws for every intercepted OSD scene, while this renderer handles
   the owned Settings/BF+ layouts.
3. In foreground, call
   `orientation_render(surface, buffer, raw, title, rows, count, selected, first)`.
   `rows` must contain `count` binary-compatible 32-byte menu rows with valid,
   NUL-terminated label/value pointers. `first` is a row index. The renderer
   disregards stock row y coordinates. A successful draw returns 1. On 0,
   destination pixels/dirty fields are unpublished; draw the stock fallback.
   Scratch may have changed. Do not call the stock row painter on scratch.
4. For a successfully selected portrait frame, background calls
   `orientation_background(surface)`. It fills the full physical 1024×682
   background with `0x008080ff` (Y=0, neutral chroma, alpha=255). No rotated
   background allocation is needed. Supply valid physical color/alpha pitches
   and storage; this helper assumes the callback's standard surface contract.
5. Latch the orientation actually drawn, then map input with
   `orientation_touch(out20, original_packet, displayed_raw)` before hit testing.
   Use **displayed**, not the latest sensor reading; reset drag ownership on
   orientation or scene changes. Only latch portrait after render succeeds.
   Coordinate foreground/background decisions so a fallback is a whole frame.

The foreground destination must have even byte pitch at least 2048 and height
exactly 682; `orientation_present` validates those fields and non-null pointers.
It preserves pitch padding. Scratch is tightly packed, must not alias the
destination, and is not a generic caller-sized surface. Low-level text/rectangle
helpers assume valid internal scratch descriptors and coordinates. The public
render entry owns their bounds; arbitrary external calls are not clipped.

Geometry shared with menu input:

| Element | Logical coordinates |
| --- | --- |
| Surface | x=0..681, y=0..1023 |
| Header | y=0..95 |
| Back indicator | Fixed menu title text; no automatic chevron |
| Title text | x=32..649, within y=16..79 |
| Rows | seven at y=`96+128*(index-first)` |
| Label/value | x=32..649; value begins 64 pixels below label |
| Selected marker | x=8..13, full 128-pixel row height |
| Bottom unused strip | y=992..1023; must not activate a nonexistent eighth row |

Use `first + (logical_y-96)/128` only for y=96..991, then check `<count`.
Clamp `first` to a valid viewport and ensure the selected row is visible. The
renderer permits an empty tail but does not scroll or clamp selection itself.
Preserve native disabled/read-only input rules: drawing a label or value does
not authorize activation. Null values remain blank regardless of row flags.
An existing value such as Version `1.0` is retained, and the renderer never
modifies row metadata. Activation remains in the menu input handler.

Provisional transforms (u,v logical; x,y physical):

| Raw | Logical to physical | Physical to logical |
| --- | --- | --- |
| 1 | `(1023-v, u)` | `(y, 1023-x)` |
| 3 | `(v, 681-u)` | `(681-y, x)` |

`orientation_touch` copies all 20 bytes and transforms the three independent
u16 coordinate pairs at offsets 0, 4, 8 with byte accesses, including unaligned
packets. Bytes 12..19 remain identical (including flags at +16). Out-of-range
physical pairs become `(65535,65535)` in portrait; both components stay invalid
after the axis swap. Nonportrait packets copy unchanged. There is no gesture
state in this helper: a stationary tap can arrive with flag 1 and no BEGIN.
BEGIN/UPDATE/END and coalesced flags are passed through unchanged. Scroll/tap
state and action dispatch remain in the menu handler.

## Offline validation and size

Run without invoking the full builder:

```sh
.venv/bin/python -m unittest tests.test_orientation -v
```

The 14 tests compile tiny-model PIC AArch64 with `-Os` and `-Oz`, function/data
sections, and linker GC. They check relocation types and missing runtime
symbols, execute pure paths at two load addresses, compare all 698,368 rotated
pixels in both directions, check padded pitches/canaries and inverse touch,
and reject bad destination descriptors. Packed touch coverage includes three
different coordinate pairs, invalid sentinels, source preservation, stationary
taps without BEGIN, and unchanged gesture flags. Sensor tests execute the
original getter with only mutex/cache services stubbed and execute both native
metadata mappings.

Native render tests execute the original text parser, glyph rasterizers,
rectangle routines and libc using local assets; only the language getter
`0x4d3321f70` is stubbed to English. They check menu-supplied title color,
read-only/null values, first/last scroll windows, oversized-text rejection,
the last legal text line, scratch/output canaries immediately after the smaller
allocation, and padded background color/alpha planes. Row tables
and strings are memory-protected against writes during rendering. Firmware or
glyph tests explicitly skip when their local files are absent. Pure compiled
rotation/touch tests do not require firmware. Native painters use caller-saved
x18; fixed-x18 preservation is checked on the renderer's pure paths.

An additional bounded emulation check executed the original Settings updater
at `0x4d3372a20` and its native language/resource lookup, rather than supplying
synthetic row labels. Only availability getters `0x4d330f690`, `0x4d330f6b0`
and the setting reader `0x4d33212d0` returned fixed zero values, alongside the
fixture's language getter. The ten resulting labels measured, in row order,
492, 590, 471, 581, 362, 331, 493, 405, 550, and 475 pixels wide; all were
58 pixels high. The first Settings viewport, including its native row value,
rendered successfully through the compact header. This is one-off evidence,
not an added regression test or proof for every language/settings combination.

`tests/test_touch_orientation.py` supplies the nine integrated checks reported
above: published-orientation input, both rotation directions, scrolling and
taps, picker commits/back/cancel, interrupted drags, portrait-to-landscape
restoration, oversized-text fallback with matching background/input, disabled
updates, and scratch placement after the resident tail. Those integration
fixtures stub text metrics/drawing; native pixel fidelity is covered separately
by `tests/test_orientation.py` and the additional Settings check.

The native fixture relocates initialized data to `0x4d7000000` from firmware
file offsets `0xebdfb0..0xf03e70`, loads bitmap data at `0x403c18800`, and maps
the native glyph workspace at `0x402174800`. These mappings produced readable
native pixels. Optional `BF_ORIENTATION_PREVIEW=/existing/temp/directory`
retains PNGs for visual inspection without adding generated repository files.
Reviewed native pixels show legible titles, labels and Version values, with
the last visible row wholly inside the portrait surface. The compact version
uses the integrated fixed textual back labels; ASCII `<` is blank.

Standalone code plus rodata, retaining read/portrait/touch/render/background
roots: **1,144 bytes at -Os; 1,136 bytes at -Oz** with the local LLVM compiler.
The test fixture's additional diagnostic entry points are excluded from that
measurement. Removing line scaling and chevron loops saved **484 bytes at
-Oz** versus the preceding 1,620-byte prototype, and saved 131,072 bytes of
scratch allocation. The combined linked image is reported at 16,384 bytes;
the standalone measurement is not a prediction of the full link. No further
header size changes were applied after the combined build reached the cap.

Remaining limits: physical sensor polarity, on-camera allocation availability,
frame timing/rotation throughput, orientation-update latency, concurrent
callback lifetime, actual display output, and all-language coverage are not
hardware-verified. The scene/input integration has offline coverage described
above. Nothing here claims that
native live status, every popup, or every nested menu now rotates.
