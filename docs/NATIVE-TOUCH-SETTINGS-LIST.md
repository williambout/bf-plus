# Mixed Settings list touch — BF V104

`touch_focus/native_touch_settings_list.h` supplies scroll and tap handling for
the private-backed list reached from **normal Settings row 0**. It selects rows
through the original native dial input and activates only the two native action
rows through the original center key. Read-only rows remain read-only. Blank
separators and the scrollbar are not tap targets.

The header and isolated fixture are complete; integration into the shared UI
dispatch and patch map is owned separately. The header itself installs no hook
and writes no native selection, setting, viewport, descriptor or pixel data.
All verification described here is offline; no camera or USB I/O occurred.

## Native evidence and selection geometry

Artifact: `decoded-V104/rtos-alt.bin`, base `0x4d3000000`, SHA-256
`f747c1350f00526b9c68c65aaef44d6e7b644b0169992342e12f059c42e150dc`.
Local Capstone and Unicorn were used; unavailable REA registration was not
changed. Initialized data is mapped from file offset `0xebdfb0` to runtime
`0x4d7000000`, length `0x45ec0`, rather than read at its BSS/runtime file offset.

| Item | Verified address / behavior |
| --- | --- |
| Native input | `0x4d337d8e0`, published from literal `0x4d337e608` |
| Foreground | `0x4d337d180`, same callback for initial/full and incremental draws |
| Background | `0x4d337d4b0`; not a foreground capture source |
| Current / previous selection | u32 at `0x4d70431fc` / `0x4d7043200` |
| Scroll offset | u16 at `0x4d7043204` |
| Private foreground surface | Descriptor `0x4d7043220`, pixels `0x402972800`, pitch 2048, height 3105 |
| Viewport copy | `BL 0x4d337d28c → 0x4d3007fc0`; 540 rows from private offset to canvas Y142 |
| Native movement | `0x4d337d7e0` and positive-dial inline path in input; signed channel 0 moves exactly one index, magnitude ignored, clamps 0–19 |
| Native redraw queue | `(foreground, background, 0)` from `0x4d3564378`, passed to synchronous `0x4d3322d90` |
| Activation | Center/right paths `0x4d337da64..dad4` check flag bit 1; only index 4 calls `0x4d337cf90(0)`, index 9 calls `0x4d337cf90(1)` |

The native Y table at `0x4d3564328` and height table at `0x4d3564350` contain:

| Native indices | Local Y | Height | Kind / tap behavior |
| --- | --- | ---: | --- |
| 0–3 | 0, 90, 180, 270 | 90 | Read-only ordinary rows; select only |
| 4 | 360 | 90 | Native action, when enabled |
| 5 | 450 | 90 | Blank separator; no tap |
| 6–8 | 540, 630, 720 | 90 | Read-only ordinary rows; select only |
| 9 | 810 | 90 | Native action, when enabled |
| 10 | 900 | 90 | Blank separator; no tap |
| 11–13 | 990, 1215, 1440 | 225 | Read-only tall rows; select only |
| 14 | 1665 | 315 | Read-only tall row; select only |
| 15–19 | 1980, 2205, 2430, 2655, 2880 | 225 | Read-only tall rows; select only |

Ordinary records passed to `0x4d3363df0` start at `0x4d7043260`, stride 32.
Tall records passed to `0x4d3365d00` start at `0x4d70433c0`, stride 16.
Both expose Y at +0 and flags at +2; tall record +12 chooses 225 versus 315
pixels, as implemented in the original painter at `0x4d3365d24..d38`.
The adapter validates all 20 live geometries against this verified layout.

Screen coordinates satisfy `screen_y = 142 + local_y - scroll_offset`, clipped
to `[142,682)`. The adapter therefore hits partial visible tall rows correctly.
Native scroll offset is bounded by `3105 - 540 = 2565`. Hit X is `[0,1018)`,
excluding the native six-pixel scrollbar drawn at X1018. Native dial selection
can pass through separator indices, just as physical dial navigation does.

Default flags are `0x12` on read-only rows, `0x10` on separators and `0x02` on
action rows, with bit 0 added for selection. `0x4d337d050` can disable action
rows dynamically. Before center, both captured and current flags must match
and `(flags & 0x12) == 2`. The adapter never synthesizes center for another
index, even if an unexpected flag appears there. It does not duplicate or
rename the native actions.

## Capture boundary and parent integration

Per-row hooks are unnecessary for this adapter. Initial foreground fills the
private backing; incremental foreground updates old/current rows, then both
paths execute the **same full viewport copy**. Capturing only ordinary painter
calls would omit tall rows and retain an incorrect screen-space offset.

The new header exports this API, with the existing payload integer and event
types:

```c
u64 native_touch_settings_list_handler_for_draw(u64 callback);
u32 native_touch_settings_list_begin(u64 input, const void *canvas, u32 epoch);
void native_touch_settings_list_observe_copy(u32 token,
    const void *dst, const void *src, u64 bytes);
u32 native_touch_settings_list_end(u32 token, u32 displayed);
void native_touch_settings_list_reset(void);
void native_touch_settings_list_reorient(u32 epoch);
u32 native_touch_settings_list_input(struct Event *event, u64 input, u32 epoch);
```

Required integration:

1. Define `NATIVE_TOUCH_SETTINGS_LIST_ENABLED()` as the feature/mode gate,
   e.g. `(state.mode != 2)`. Do not tie this gate to input readiness: drawing
   legitimately occurs before readiness is published. Define
   `NATIVE_TOUCH_SETTINGS_LIST_TRANSFORM(out,source)` using `ui_map_packet`;
   it must fill a **separate 20-byte buffer**, including rejected coordinates.
2. Recognize foreground `0x4d337d180` as belonging to input `0x4d337d8e0`.
   Call `begin` with the exact canonical canvas descriptor supplied to the
   native foreground. Keep its nonzero token through display completion.
3. Add the sole new direct BL interception at `0x4d337d28c`, whose original
   target is `0x4d3007fc0`. Call `observe_copy(token,dst,src,bytes)` with the
   **unchanged original X0/X1/X2**, then call the original memcpy exactly once.
   Preserve its full **64-bit pointer return** and normal calling convention.
   The macro `NATIVE_TOUCH_SETTINGS_LIST_COPY_HOOKS(X)` declares this pair.
   Existing ordinary row observation sites do not need modification.
4. End each nonzero token exactly once. Pass `displayed=1` only after the
   corresponding foreground/frame is successfully published with matching
   epoch, depth and pending/node transition state. Abort or superseded frames
   end with zero. No copy, repeated copies, wrong operands, partial extents,
   live geometry/flag changes, or failed display can publish a hit map.
5. Dispatch the exact native input through `input(event, original, ui.epoch)`.
   Wire `reset` to scene/lifecycle cancellation and `reorient` to a successfully
   published rotation that reuses unchanged canonical pixels. Parent readiness
   and removal guards must prevent touch use during incomplete display changes.

`begin` accepts only a non-null foreground canvas with pitch 2048, height682,
an aligned non-wrapping pixel extent, and the exact input identity. Observation
requires the known private descriptor/pixels, source pointer including offset,
destination pointer including Y142 and exactly `540*2048` bytes. Geometry and
flags are copied by value, so no native row or temporary canvas pointer is
retained for later input.

Capture uses a nonblocking atomic gate and generation token. A nested capture
invalidates the owner instead of waiting; input never holds the capture gate
while calling native input or its synchronous draw queue. Original events are
forwarded once, unchanged. Synthetic events carry only one signed native dial
step or the center key. Before each additional step the adapter requires a new
valid displayed snapshot matching current native selection/offset/flags. Wrong
progress, reset, recursion, transition or failed redraw stops the sequence.

Native hierarchy initialization can draw before publishing its final depth
and idle fields. Capture retains that intended depth, but input requires
`[0x4d703469c] == 12`, `[0x4d70346a4] == 12` and the expected current depth.
Parent lifecycle cancellation remains mandatory for scene reentry.

Touch flags follow the actual driver's established contract: stationary taps
arrive as terminal flag 1 without BEGIN; BEGIN belongs to the first movement.
A vertical drag advances native selection in 90-pixel increments, including
through read-only positions; native code chooses the viewport offset. Release
after a drag never activates, and the following stationary tap works normally.
Horizontal/outside gestures, physical key/dial/side input and canceled epochs
cannot synthesize activation. Read-only row taps may move selection but do not
send center; disabled action rows likewise never activate.

## Offline verification and limits

```sh
.venv/bin/python -m unittest tests.test_native_touch_settings_list -v
```

**15 tests passed.** The fixture builds only this header and original test glue
with AArch64 tiny-model PIC, validates relocation kinds, then runs the relocated
binary in Unicorn. It is **3,744 initialized bytes / 3,904 bytes including BSS**
with the current compiler; these fixture sizes include test helpers and are not
a claim about production integration size.

The fixture executes original native input, movement, key decoders and full/
incremental foreground instructions. Its boot-data mapping and literal/Y/height
tables are checked against the supplied firmware. Coverage includes all 20
native positions in both directions, signed extreme dial values, both actions,
read-only/disabled rows, tall-row boundaries and clipping, viewport copy bounds,
unaligned immutable input packets, the inverse transform seam, drag release and
next tap, failed/absent/repeated captures, live metadata mutation, epoch/depth/
node gates, initial hierarchy publication, reorientation, nested capture,
recursive dispatch and mid-navigation failure.

Queue scheduling, text/row raster services, native actions and memory copying
are intercepted; the copy mock applies the original exact byte extent. These
tests establish selection/capture contracts, not translated text rendering,
native action results, live task timing, cache coherence or camera validation.
Shared UI transaction and installation tests remain necessary after integration.
This adapter covers the named mixed Settings child only; the separate dynamic
list, alternate Settings root and other widget families have different ABIs.
