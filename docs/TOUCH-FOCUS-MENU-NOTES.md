# BF+ settings insertion — V104 segment 05

Status: **native BF+ submenu implemented and tested offline.** The parent/user reported that the preceding main-list-toggle build and touch zoom worked on the camera. This worker has performed no USB, PTP, or other hardware I/O, and has not observed the new submenu on a camera.

The new eleventh row in the main settings list opens a native child scene:

```
Settings:
BF+                                      >

BF+:
Touch focus zoom                         ON / OFF
Version                                  v1.0
```

Center/right **press** opens BF+. Inside, up/down/dial selects either row; center/right on Touch focus zoom toggles resident `state.mode` 0/1. Version is read-only and displays exactly `v1.0`, independently of `State.version` (the internal protocol version). Left returns to Settings with BF+ still selected. Menu/playback exit actions retain the stock handlers and take priority over a simultaneous toggle/open. Touch and activation repeats do not open or toggle. All ten original settings rows remain present.

## Identity and evidence

- Analyze `decoded-V104/rtos-alt.bin`, derived from firmware segment 05 (`05_1002.bin`, image offset `0x15020`), base `0x4d3000000`.
- Supplied package SHA-256: `0c6cb624967c0d2254fa3e532ea25f389f09b007e9e31788df7e9682995e478b`.
- Address descriptions below are static observations unless explicitly labeled inference or proposal.
- The boot loop at `0x4d3000fa8..0x4d3000fcc` copies `0x45ec0` bytes from `0x4d3ebdfb0` to `0x4d7000000`. This proves the initialized-data mapping used here: `file VA = runtime VA - 0x3142050`.
- Stock entry path: quick-options selection 10 calls `0x4d33731c0` at `0x4d3332350` / `0x4d33324a4`. That entry pushes the scene at `0x4d3e88bc8`.
- Scene has init `0x4d3372ff0`, resume `0x4d3372d90`, suspend `0x4d33725f0`, exit `0x4d3372610`.
- Scratch `decoded-V104/agent-menu/verify-menu.py` executes relevant original firmware routines under Unicorn. Run `.venv/bin/python decoded-V104/agent-menu/verify-menu.py`. It never accesses a camera.

## Exact menu data and code

| Item | Address / details |
|---|---|
| Normal row table | `0x4d7042c18`, ten rows, stride `0x20`, length `0x140` |
| Alternate/service row table | `0x4d7042d58`, same capacity; leave this mode unchanged |
| Normal label IDs | `0x4d3e88ba0`, ten u32: `203,197,198,199,200,201,202,204,205,206` |
| Alternate label IDs | `0x4d3e88b70` |
| Alternate-mode flag | u8 `0x4d73025f4`; normal list when zero |
| Current row | u8 `0x4d73025f6` |
| Previous row | u8 `0x4d73025f7` |
| Full repaint flag | u8 `0x4d7042e98` |
| Highlight descriptor | `0x4d7042ea0`; first u16 is visible Y |
| Backing surface descriptor | `0x4d7042ec0` |
| Scroll origin | u16 `0x4d7042ee0`, initially `52` (`0x34`) |
| Row-data updater | `0x4d3372a20(w0=full_repaint)`; updates exactly ten rows |
| Input handler | `0x4d3373200(event_bundle*)` |
| Normal draw callback | `0x4d33726d0(surface*, params, length)` |
| Initial draw callback | `0x4d33729c0(surface*, params, length)`; synchronizes surface pitch and invokes normal draw |
| Stock row painter | `0x4d3363df0(surface*, row*)` |
| Generic text renderer | `0x4d3328180(surface*, text_descriptor*)` |
| Render-queue submission | `0x4d3322d90(callback_triple*, data, u16_length)` |
| UTF-8 decoder | `0x4d320ae20(text*, out_byte_length*)` |

The row layout is proven by loads in `0x4d3363df0` and stores in `0x4d3372a20`:

```c
struct Row {                 // sizeof == 32, alignment 8
    uint16_t y;              // backing-surface Y, stock: 52 + index*90
    uint8_t flags;           // bit0 selected; bit1 enabled; bit4 special/dim style
    uint8_t unused3;
    uint32_t unused4;
    const char *label;       // offset 8, UTF-8 or stock encoded resource string
    const char *value;       // offset 16; NULL means submenu arrow
    uint32_t value_font;     // offset 24, stock ordinary values use 4
    uint32_t unused28;
};
```

The label is painted at X=48, width=916, height=90, font 5. The value uses the same box with right alignment and `value_font`. Row10 has Y=`952` (`0x3b8`), flags 2 or 3, label=`"BF+"`, **NULL value** for a submenu arrow, and value_font=4. Child rows are Y142 and Y232. All strings belong to the resident allocation; ASCII uses the existing renderer without new language IDs.

**ON/OFF labels in this proposal are plain ASCII rendered by stock code.** Native localized ON/OFF resource IDs have not been semantically identified; do not describe these ASCII strings as localized stock resources. Other routines use glyph resources 0x96/0x98 for boolean-looking values, but their visual meaning has not been proven.

Backing surface observations:

- `+8` = buffer `0x402972800` in initialized data.
- `+0x10` = pitch in bytes, populated from active display surface; `+0x12` copied with it by initial draw callback.
- `+0x14` = allocated height `2520` (`0x9d8`); init clears pitch × height.
- New row extent `[952,1042)` is within that stock backing height. A second framebuffer allocation is unnecessary for this one added row.
- The normal draw routine copies a 630-row viewport from backing origin `scroll` to visible Y=52. To show row10 at the bottom, use scroll=`412` (`952-540`). Its visible Y is `592 = 52+952-412`, and last pixel row is 681.

## Concrete reversible pointer-only insertion

This path needs **no instruction-count patches and no second code L2 block**. Every pointer slot below lies in existing block `0x4d3200000..0x4d33fffff` (descriptor `0x4d71484c8`). Owned data/code remains resident until reboot or a proven quiescent teardown.

Allocate within the existing owned resident block:

1. An eleven-element `Row rows[11]` (352 bytes). At installation copy the **runtime** normal table's first 320 bytes, then initialize row10. The row updater continues updating the original ten entries in this clone.
2. A 48-byte copy of the draw callback table at `0x4d3564220`. It contains two callback triples:

   | Offset | Original pointer |
   |---|---|
   | +0 | `0x4d33726d0` normal foreground |
   | +8 | `0x4d3372680` normal background |
   | +16 | 0 |
   | +24 | `0x4d33729c0` initial foreground |
   | +32 | `0x4d3372f50` initial background |
   | +40 | 0 |

   Replace only +0 and +24 in the owned copy with resident draw wrappers.
3. An input wrapper, two main draw wrappers, and native child scene/draw callbacks with owned title and two rows.
4. `menu_parent_scene[4]`, cloning the stock Settings scene except its resume callback; the wrapper restores selection10 after stock resume's index bound check.

Publish these 14 64-bit pointer replacements after verifying each expected value (20 total including the parent's six live/zoom hooks):

| Pointer slot | Expected stock value | New value |
|---|---|---|
| `0x4d3372868` | `0x4d7042c18` | owned rows |
| `0x4d3372980` | `0x4d7042c18` | owned rows |
| `0x4d3372be8` | `0x4d7042c18` | owned rows |
| `0x4d3372d50` | `0x4d7042c18` | owned rows |
| `0x4d3372ef0` | `0x4d7042c18` | owned rows |
| `0x4d3373160` | `0x4d7042c18` | owned rows |
| `0x4d33738c8` | `0x4d7042c18` | owned rows |
| `0x4d3372d60` | `0x4d3564220` | owned callback table |
| `0x4d3372f00` | `0x4d3564220` | owned callback table |
| `0x4d3373170` | `0x4d3564220` | owned callback table |
| `0x4d33738e0` | `0x4d3564220` | owned callback table |
| `0x4d3372f38` | `0x4d3373200` | input wrapper |
| `0x4d33731a8` | `0x4d3373200` | input wrapper |
| `0x4d33731d0` | `0x4d3e88bc8` | owned `menu_parent_scene` |

The pointer search covers the entire extracted segment05 image, not just code. It found seven normal-table references, four callback-table references, two input-handler references, and one Settings scene-descriptor reference. No writes to `0x4d3564220` or the stock scene descriptor itself are needed.

Install while outside settings, so next stock scene initialization installs the input wrapper naturally. Otherwise the currently active callback slot must also be discovered and replaced; this investigation did not identify or modify that slot.

### Draw wrappers

Preserve the ordinary callback ABI and return the original result.

Before normal draw, when alternate-mode flag is zero:

1. Set row10 flags from current selection (`2 | (current==10)`), value NULL.
2. Call stock `0x4d3363df0(backing_surface, &rows[10])`.
3. Call original `0x4d33726d0` with the incoming arguments.

Before initial draw, first copy u16 fields `surface+0x10` and `surface+0x12` to backing descriptor at the same offsets; then prepare/paint row10, and call original `0x4d33729c0`.

Why this works: original full repaint draws only rows0..9 into the backing surface, then copies the viewport. It does not erase the separately prepainted row10. Its partial repaint directly indexes current and previous rows; both are safe because the redirected table has eleven entries. The stock updater at `0x4d3372a20` does not touch row10, so the wrappers manage its flags and value.

The initial background clears the visible target, and initial foreground calls `0x4d332ba70` before the stock foreground. This does not invalidate prepainting of the separate backing surface. The stock framebuffer-copy behavior was executed offline with marker pixels, including row10, as described below.

The stock scrollbar geometry remains calculated for ten rows. Correct it in the draw wrapper after the original callback if visual accuracy is required: erase its six-pixel strip (X=1018, Y=52, height=630), draw a thumb appropriate for 11 × 90 = 990 content pixels and 630 visible pixels. Suggested proportional thumb height 400, position `52 + (scroll-52)*230/360`, clamped. Use stock rectangle helper `0x4d3325ca0` with `u16 {x,y,width,height}` and 0 background / 0xffff foreground. This is a **proposed corrected geometry**, not the firmware's original formula. The old renderer hardcodes thumb height490 and movement46 per90 content pixels, so leaving it unchanged is a known cosmetic defect.

### Input wrapper

Use the key agent's proven indices: center0, left1, right2, down3, up4. Key payload offsets and stock key predicates are documented in `decoded-V104/agent-key/center-touch-findings.md`.

Handle only normal-mode events involving appended index10:

- At index9, a down press/repeat (`0x4d3323400(key,3)`) or positive dial step selects index10. Stock otherwise refuses this transition.
- Set previous=9, current=10, scroll=412, highlight-Y=592. Call `0x4d3372a20(0)` to deselect the stock rows, then enqueue the owned normal callback triple with `(data=NULL,length=0)` through `0x4d3322d90`.
- At index10, center/right **press edges** request the owned child scene using stock push `0x4d3324110`. First forward a filtered remainder so stock exits win. Require idle pending sentinel12, current index10 and hierarchy in1..10; a failed push does not arm restoration. Touch/repeat does not open the child.
- At index10, up or negative dial can pass to stock: its decrement path works, moves to9, and the cloned table safely includes previous row10. Draw wrapper clears row10 highlight from current selection.
- At index10, down/positive dial does nothing. All other events preserve stock exit/back/playback handling. For mixed bundles, avoid replaying an already consumed dial/key action; pass a filtered remainder when appropriate.
- If the alternate-mode flag is nonzero, leave stock behavior unchanged and do not paint BF+.

Stock init/resume rejects saved index>9 at `0x4d337305c` / `0x4d3372e00`. The owned parent resume wrapper supplies a valid temporary selection9, then restores current/previous10, scroll412 and highlight592 before the queued foreground draw. It restores during the draw if the queue completes synchronously, or after stock resume before a deferred draw. An intermediate unwind (`w2 & 255 != 0`) clears the return marker without restoring. Reopening Settings from outside still uses the original init and may reset saved index10 to0; returning directly from BF+ preserves it.

### Native scene ABI and concrete stock model

These facts are established from segment05 instructions, not assumed from symbol names:

- Stock three-row submenu entry `0x4d3384f40` pushes descriptor `0x4d3e892a8`: qwords `{0x4d33845a0, 0x4d3384760, 0x4d3384400, 0x4d3384580}`. Its left-key branch `0x4d3384b40..4b58` calls stock pop `0x4d3324250`; Menu/playback branches match the Settings handler's exit routes.
- Push `0x4d3324110..415c` validates descriptor and non-NULL init, copies **32 bytes** to pending descriptor `0x4d7301d40`, and sets pending depth=current+1. It returns0 on success, -1 for invalid descriptor. It does not enforce stack capacity; the wrapper enforces depth<11 and idle pending12.
- Transition engine `0x4d3323ca0` uses a 32-byte scene stack at `0x4d7301bc0`. Offset0 is init, +8 resume, +16 suspend, +24 exit. Push invokes suspend at `0x4d3323de0..3de8`. Pop invokes exit at `0x4d3323f38..3f48`, compares the target descriptor, and selects resume on equality at `0x4d3323f74..3f80`.
- Init/resume ABI is `u32(u64 next_scene[4], u64 handlers[2], u32 unwind)`. At `0x4d3323e74..3ea4`, the engine zeroes the output next-scene and handler pair, passes those pointers in x0/x1 and zero in w2, then invokes the callback. A zero return with no next scene ends initialization. Intermediate unwind passes w2=1 at `0x4d3323f18..3f24`. Suspend/exit take no meaningful arguments.
- The handler pair is input at+0 and update at+8, published at `0x4d3323ec0..3ec4`. A NULL update is explicitly accepted by the event loop at `0x4d3323b98..3ba8`. BF+ has no timer and no externally changing option source; its update pointer is NULL.
- Stock title renderer `0x4d3363ca0` reads title Y at+0, string pointer at+8 and back-arrow flag at+16. The owned title is24 bytes, Y52, textBF+, back1. `0x4d3363c60` paints its background. Stock submenu foreground `0x4d33844e0` demonstrates viewport clear, title, rows, then status `0x4d335d4b0(surface,0x2f,0,0)`; background `0x4d3384450` demonstrates fill `0x228080ff`, title background and row highlights.
- `menu_submenu_rows[2]` uses the established 32-byte row layout. Row0 is Y142, flags2/3, label Touch focus zoom, ON/OFF, font4. Version is Y232, flags0x12/0x13, Version/v1.0, font4. Stock special flag0x10 omits the editing chevron (`0x4d3363f74`) for the read-only row.

`menu_initialize(base)` also seeds the relocated child scene, child callback triple, title, row strings and private view state. The parent hook is the **only additional firmware pointer replacement**. All new runtime callbacks and data live in the retained resident allocation. No scene-stack descriptor is patched in place.

Counts are hardcoded in multiple places, not a single writable count field:

| Address | Stock instruction / role |
|---|---|
| `0x4d3372730` | `add x22,x19,#0x140`; full draw ten ×32 bytes |
| `0x4d3372ad4` | `cmp w21,#0xa`; row updater ten iterations |
| `0x4d3372e00` | `cmp w1,#9`; resume saved-index bound |
| `0x4d337305c` | `cmp w1,#9`; init saved-index bound |
| `0x4d3373298` | `cmp w0,#8`; positive dial can increment only through8→9 |
| `0x4d3373524` | `cmp w0,#8`; down key same bound |

Do not merely increase the updater count: it would read an eleventh label ID outside the existing ten-entry label array. The proposed wrappers avoid all these code patches.

### Removal

Keep menu enablement/installation state separate from feature `state.mode`: turning BF+ OFF must not remove its settings row or bypass the menu wrapper.

The parent requires idle live view before removal. Restore all14 menu pointers with the existing cache/TLB discipline and retain the allocation. Mode2 makes stale main draw/input/resume wrappers clamp current/previous to0..9 and a valid stock viewport before forwarding. Child draw/input callbacks become inert on removal; suspend/exit clears child activity so stale queued child drawing also becomes inert after normal return. Intermediate unwind clears the selection-return marker. No wrapper dereferences row10 after removal.

## Offline verification performed

`decoded-V104/agent-menu/verify-menu.py` passed:

- Original UTF-8 decoder returns B/F/+ with byte length1.
- Original row renderer builds text calls for BF+ in font5 and ON/OFF in font4, at expected coordinates; selected and unselected flags tested.
- Original row updater, with all normal-table pointers redirected to an eleven-row clone, updates the ten expected labels and preserves an eleven-row sentinel. Current index10 clears all ten old highlights.
- Original input handler refuses down from9, and accepts up from10→9 using the clone.
- Original full-render routine paints exactly ten original rows, preserves prepainted row10, and its actual memcpy copies row10 into visible pixel rows592..681 at scroll412. Rasterizers were stubbed with marker pixels for this check.

`tests/test_touch_menu.py` additionally builds the integrated payload (including launch.S) in an isolated temporary directory. It covers relocated scene descriptors and strings, native submenu selection/toggle/read-only version, mixed events, both draw layers, stock exits, parent selection restoration, scrollbar geometry, removal and stale callbacks. When the supplied decoded image is present, it executes the **original push, pop, transition engine and Settings resume** with the compiled resident callbacks: depth4→5, toggle, left/pop→4, exact handler-pair publication, current/previous10 and scroll412 survive return. Draw queue completion is simulated synchronously; separate wrapper tests cover deferred completion. Rasterizers and device services remain stubbed.

These offline checks do **not** prove final glyph appearance, camera queue timing, cache coherency, or physical-camera behavior of the new submenu. Parent handles hardware validation and installer integration separately.
