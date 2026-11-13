# BF+ settings insertion — V104 segment 05

Current source: **five-row BF+ submenu**, including Aspect Ratio and the new
**Auto Rotate UI** boolean, initially ON. The original three-row menu and
subject targeting have separate hardware observations below; these do not
validate the newer portrait/touch/segmented-loader changes. Current integration,
coverage and verification boundaries are in [UI-INTEGRATION.md](UI-INTEGRATION.md).
Historical test/image counts below identify earlier menu revisions only.

The new eleventh row in the main settings list opens a native child scene:

```
Settings:
BF+                                      >

BF+:
Touch Focus Zoom                         ON / OFF
MF Subject Detection                     ON / OFF
Aspect Ratio                             Native
Auto Rotate UI                           ON / OFF
Version                                  1.0

Touch Focus Zoom opens the native compact panel:
                                         OFF
                                         ON

Aspect Ratio opens the same native panel:
                                         Native
                                         XPan (65:24)
                                         2.35:1
                                         5:4
```

Center/right **press** opens BF+. Inside, up/down/dial selects one of five rows; center/right on an editable option opens its compact picker without changing the option. The three booleans have two choices, and Aspect Ratio has four. Picker navigation changes only the tentative highlight; center/right confirms and returns to the same BF+ row. Touch Focus Zoom uses resident `state.mode`; MF Subject Detection uses separate `focus_target.enabled`; Aspect Ratio reads `aspect_ratio.selected` and applies a changed selection through `aspect_select(value)`. Left cancels the picker, and left from BF+ returns to Settings with BF+ still selected. Menu/playback retains the stock exit handlers and cancels without committing. Version is read-only and displays exactly `1.0`, independently of `State.version` (the internal protocol version). Center-button touch and activation repeats do not open or confirm. All ten original settings rows remain present. Subject-targeting evidence and hardware validation are in [MF-SUBJECT-DETECTION.md](MF-SUBJECT-DETECTION.md).

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

The label is painted at X=48, width=916, height=90, font 5. The value uses the same box with right alignment and `value_font`. Row10 has Y=`952` (`0x3b8`), flags 2 or 3, label=`"BF+"`, **NULL value** for a submenu arrow, and value_font=4. Child rows are Y142, Y232, Y322, Y412 and Y502. All strings belong to the resident allocation; ASCII uses the existing renderer without new language IDs.

The BF+ boolean row values and compact picker share owned strings `"\x1b\x06" "OFF"` and `"\x1b\x06" "ON"`. The explicit control switches the native popup painter's initial font5 to font6 without displaying either control byte. All five submenu values use `value_font=6`; Version remains plain `1.0`. The ratio choices use the same font control and owned strings in both the row value and picker. The user requested uppercase ON/OFF after the title-case revision; row labels remain in title case. The popup still uses the original native layout, dim, highlight and committed-marker painters.

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

   Replace +0, +8, +24 and +32 in the owned copy with resident foreground/background wrappers. Background wrappers call stock first, then supply the portrait background only after a successful portrait foreground.
3. An input wrapper, two main draw wrappers, and native child scene/draw callbacks with owned title and five rows.
4. `menu_parent_scene[4]`, cloning the stock Settings scene except its resume callback; the wrapper restores selection10 after stock resume's index bound check.

The original menu insertion uses these 14 pointer replacements. Automatic rotation adds three update-handler slots listed after the table. Every slot is verified against its expected value before installation:

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

Orientation adds `0x4d3372678`, `0x4d3372f40`, and `0x4d33731b0`, each
replacing `0x4d3372c30` with `menu_parent_update_wrapper`. The wrapper calls
the native updater and queues a full redraw when camera orientation changes.
These are separate from the aspect/focus hooks in the combined payload.

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
- The handler pair is input at+0 and update at+8, published at `0x4d3323ec0..3ec4`. A NULL update is explicitly accepted by the event loop at `0x4d3323b98..3ba8`. The current BF+ update pointer is `menu_orientation_update`, which monitors orientation and requests a redraw only when it changes.
- Stock title renderer `0x4d3363ca0` reads title Y at+0, string pointer at+8 and back-arrow flag at+16. The owned title is24 bytes, Y52, textBF+, back1. `0x4d3363c60` paints its background. Stock submenu foreground `0x4d33844e0` demonstrates viewport clear, title, rows, then status `0x4d335d4b0(surface,0x2f,0,0)`; background `0x4d3384450` demonstrates fill `0x228080ff`, title background and row highlights.
- `menu_submenu_rows[5]` uses the established 32-byte row layout. Row0 is Y142, flags2/3, label Touch Focus Zoom, ON/OFF, value font6. Row1 is Y232, flags2/3, MF Subject Detection, ON/OFF, value font6. Row2 is Y322, flags2/3, Aspect Ratio and its selected choice, value font6. Row3 is Y412, flags2/3, Auto Rotate UI, ON/OFF, value font6. Row4 is Y502, flags0x12/0x13, Version/1.0, value font6. Each label starts with native control bytes `1b 06`, switching the stock painter's initial font5 to font6. Stock special flag0x10 omits the editing chevron (`0x4d3363f74`) for the read-only row.

`menu_initialize(base)` also seeds the relocated child scene, child callback triple, title, row strings and private view state. The parent resume hook adds one firmware pointer replacement to the original row/input insertion; the later portrait integration adds the three update pointers documented above. All new runtime callbacks and data live in the retained resident allocation. No scene-stack descriptor is patched in place.

### Owned compact option picker

The parent captured the actual Shutter Blackout panel in `.touch-focus/shutter-blackout-reference.json`: depth5 scene `{0x4d3388e10,0x4d3388ca0,0x4d3388b40,0x4d3388df0}`. It exactly matches the statically traced main-settings row4 candidate. `.touch-focus/shutter-blackout-picker.json` records Y412, count2, selected1, previous255, committed1, widest0, first-visible0, visible-count2, flags0, and label bytes `ef839d` / `ef839e`. `.touch-focus/native-off-on.png` is the parent's visual asset evidence. These are supplied observations, not hardware reads by this worker.

The reusable boundary is native measurement/layout/drawing with an **owned scene and input handler**. The stock input at `0x4d3388f10` is not reusable: it commits through `0x4d33212e0`, which writes a camera setting at `*(u64 *)0x4d7301b98 + 0x6c`. The implementation never calls that getter/setter pair, pushes stock scene `0x4d3e89370`, or changes stock picker descriptor `0x4d7043890`.

| Native call | Interface / use |
|---|---|
| `0x4d33646d0` | `u32(Picker *)`; returns widest label index, not width |
| `0x4d3364750` | `u32(surface, Picker *)`; background, highlight, committed marker |
| `0x4d3364970` | `u32(surface, Picker *)`; text and viewport |
| `0x4d332b110` | Initial background blend of `{0,52,1024,630}` with `0x00808085` |
| `0x4d3327240` | Initial foreground blend of the same viewport with8 |
| `0x4d335d380` | Initial background status decoration |
| `0x4d335d4b0` | Initial foreground status, `(surface,0x2f,0,0)` |

The mutable picker descriptor is48 bytes, aligned8:

| Offset | Type / meaning | BF+ value |
|---|---|---|
| +0 | u16 Y | 142, 232 or322, aligned with the selected option |
| +2 | u8 count | 2 for booleans; 4 for Aspect Ratio |
| +3 | u8 tentative selection | Entry snapshot of the selected option, then navigation |
| +4 | u8 previous | 255 on entry |
| +5 | u8 committed marker | Entry snapshot of the selected option; navigation leaves it intact |
| +6 | u8 widest label index | Native measurement result |
| +7 | u8 first visible | 0; native painters may modify this for scrolling |
| +8 | u8 visible count | 2 for booleans; 4 for Aspect Ratio |
| +9 | u8 flags | 0 |
| +10..15 | reserved | 0 |
| +16 | pointer to primary string pointers | `menu_picker_labels` for OFF/ON; `menu_picker_labels+2` for ratios |
| +24 | secondary strings | NULL |
| +32 | pointer to per-row **disabled** flags | Owned `{0,0,0,0}`; booleans use the first two |
| +40 | language-related data | NULL; non-NULL would invoke a native language setter |

The stock reference uses uppercase U+F0DD/U+F0DE sprites (English family10 glyphs214/215, widths99/77 and height58). BF+ uses owned uppercase strings in font6/family5: OFF94×60, ON74×60. The original painters measure those strings and produce a panel at X790,width234, with two90-pixel rows and a10×76 committed marker at X797,Y(row)+7. Conditional tests execute the original parsers and glyph path under all17 language settings, verifying identical uppercase values, font6 metrics, supported glyphs, and no rendered escape bytes or PUA lookup. These owned English labels do not require the resource resolver.

`menu_picker_scene[4]` uses the already-proven init/resume/suspend/exit ABI. Init/resume installs `menu_picker_input_wrapper` and `menu_orientation_update`, snapshots the selected option into tentative/current, sets panel Y142, Y232 or Y322, resets the label pointer/count/visible-count for that option, measures labels, and queues the initial callback triple at `menu_picker_callbacks+3`. Suspend/exit clears separate `menu_picker_active`; it cannot use the BF+ active flag because pushing the picker suspends BF+. The normal triple at `menu_picker_callbacks` redraws only the popup. Navigation never repeats the viewport dim operations. Pop calls `menu_submenu_resume`, retaining the selected row and repainting both BF+ layers with the committed values and Version1.0. A fresh `menu_submenu_enter` selects row0. A stale picker entry for Version clears activity and publishes NULL handlers.

The two owned child scenes share packed-input filtering: copy unaligned key/dial bytes, consume navigation/activation, retain NULL payloads and optional event fields, then let the stock Settings handler process the remainder. Menu/playback and left take precedence over confirmation; navigation takes precedence over simultaneous center/right. Check mode2 and pending12 again after forwarding. Confirm changes only the selected option: it assigns `state.mode` or `focus_target.enabled` for booleans, or calls `aspect_select(value)` for a valid changed ratio, then requests pop. The wrapper returns without another dial pass after commit/cancel. Repeated activation, touch-only input, pending transitions, wrong hierarchy, and removed/inactive callbacks cannot commit. The stock input's independent second dial pass after pop is deliberately not reproduced.

All picker data, scene pointers and two callback triples are seeded at resident addresses by the existing `menu_initialize(base)`. `menu_picker_labels[6]` contains OFF, ON and the four ratios; the menu never indexes the ratio choices with an invalid backend value. No additional firmware hooks, installer ABI changes, State fields, or fixed stock settings writes are required by this UI addition; the parent's crop backend has separate integration needs. The last verified build with the initial native backend and concurrent LCD additions uploads 15,872 bytes (`0x3e00`, including launcher) and reserves 21,056 bytes (`0x5240`) resident. The upload has 512 bytes below the unchanged `0x4000` cap; the resident extent remains below the separate `0x10000` cap. These figures belong to the snapshot below, before the planned JPEG/DNG tables and capture-idle gating. The earlier selection-stub build was13,696 upload /18,816 resident bytes.

### Aspect Ratio contract and native geometry

`menu.h` includes the parent-owned `aspect_ratio.h` after its include guard. The menu interface is `volatile struct AspectRatio aspect_ratio` with a `u32 selected`, plus `static void aspect_select(u32)`. Values are exactly 0 Native, 1 XPan (65:24), 2 2.35:1 and 3 5:4. The parent replaced the initial selection-only stub with native geometry and getter/setter/label wrappers; their crop behavior is outside this UI's tests. Menu initialization and painting read the resident selection without applying it. Invalid values display and snapshot Native while leaving backend state unchanged. Center/right calls the backend only when the tentative value is below4 and differs from the current selection. Cancel and stale/removed callbacks make no backend call. The UI fixture executes the owned backend and intercepts its stock refresh at `0x4d33a03a0`, recording the published selection without running device services. It does not require geometry initialization or assert crop dimensions.

The `void aspect_select` contract also permits rejection while capture is busy: leave `selected` unchanged. The picker still pops, and `menu_submenu_resume` reads that unchanged value for the row. It never copies the tentative picker value back over the backend's decision. The parent is adding capture-idle gating and owned JPEG/DNG tables; the menu does not depend on their internal layout.

The actual stock measurement and paint routines establish the four-choice layout. Choice widths are138,285,124,67 pixels, all height60 in font6/family5; the Aspect Ratio label is274×60. XPan is the widest choice, index1. The panel starts at X598,Y322, width426, with rows at Y322,412,502,592; its final extent is exactly Y682, within the stock viewport. The committed marker is10×76 at X605 and committed-row Y+7. For committed2/tentative3, the original painter keeps that marker at Y509 while moving the highlight. The 17-language parser checks verify the owned ratio strings retain their font6 measurements without a PUA lookup; they are English strings, not translated resources.

### Aspect Ratio UI verification handoff — 2026-11-12

The isolated menu suite passed63 tests in46.685 seconds with decoded segment05 present. It executed the real owned selection backend and stubbed only its stock refresh. Tests verify no refresh during navigation/cancel, one refresh after a changed confirmation with the final selection already published, and no second apply while the pop is pending. The original painters/parsers verify panel geometry and fonts. `git diff --check` passed for the three owned files.

Source SHA-256 values at the start of that test run:

| File | SHA-256 |
|---|---|
| `touch_focus/menu.h` | `1be9dc4d91598abf01e1dfb87b42ae56648fbf92e8de20f55e67885e2800c301` |
| `tests/test_touch_menu.py` | `562954e5cc315ce268b4183047004e75ac4f2fb3793164b2abf064f9345b09a2` |
| `touch_focus/aspect_ratio.h` | `c97cd4f505315d4d4e147fdd686ade6d28b622963408beb7f3595b5dd1751467` |
| `touch_focus/payload.c` | `a78337b52d1725e85afe4411205fc88c5db65676dd836be262cc1e8e44f39663` |
| `touch_focus/build.py` | `501fae95f47443e5a46fed71eb724225e5b8dfb44a9f8e255c5ac495cebddbd5` |
| `touch_focus/payload.ld` | `a265d40f58b672010ba5db8d9ccb59daee8478381a0730545d3f85f7d44cbce7` |

Another writer added LCD tap/drag support and bootstrap `aspect_initialize`; this worker preserved those changes. During the test run, `menu.h` changed to `fe48bc7bcbf928d8382b52d658aed845cb2e7c5762e212bddba7c5505cd14283`. All other hashed source files, including the tests, backend, builder, linker, launcher, detector/frame and guide sources, remained unchanged during the run. The 63-test result therefore does not establish the newer menu revision or future backend revisions. The parent owns final source freeze, full-suite validation and installation. This UI worker stops editing at handoff and has made no hardware writes or commits.

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

The parent requires idle live view before removal. Restore all14 menu pointers with the existing cache/TLB discipline and retain the allocation. Mode2 makes stale main draw/input/resume wrappers clamp current/previous to0..9 and a valid stock viewport before forwarding. Both child scenes' draw/input callbacks become inert on removal; their suspend/exit callbacks clear their own activity so queued draws also become inert after normal return. Removed init/resume publishes NULL handlers. Intermediate unwind clears the selection-return marker. No wrapper dereferences row10 after removal.

## Offline verification performed

`decoded-V104/agent-menu/verify-menu.py` passed:

- Original UTF-8 decoder returns B/F/+ with byte length1.
- Original row renderer builds text calls for BF+ in font5 and ON/OFF in font4, at expected coordinates; selected and unselected flags tested.
- Original row updater, with all normal-table pointers redirected to an eleven-row clone, updates the ten expected labels and preserves an eleven-row sentinel. Current index10 clears all ten old highlights.
- Original input handler refuses down from9, and accepts up from10→9 using the clone.
- Original full-render routine paints exactly ten original rows, preserves prepainted row10, and its actual memcpy copies row10 into visible pixel rows592..681 at scroll412. Rasterizers were stubbed with marker pixels for this check.

`tests/test_touch_menu.py` builds the integrated payload (including launch.S, the aspect header and passive guide files) in an isolated temporary directory. Its tests cover relocated scene descriptors/strings, the image limit, native submenu/read-only version, independent options, picker tentative navigation, press-only confirmation, cancellation, mixed packed events, initial dim versus partial redraw, stock exits, selection restoration, scrollbar geometry, removal and stale callbacks. Aspect coverage adds all16 old/new choice pairs with both confirmation keys, no apply during navigation/cancel, field isolation, switching the shared picker between four and two choices, invalid backend indices, read-only Version, and actual four-row panel geometry. Hooks explicitly reject fixed stock Shutter Blackout getter/setter calls, the stock picker entry, stock descriptor push, and the language setter. Builds preserve the parent's split upload/BSS layout and do not write shared build output.

When the supplied decoded image is present, the suite executes the **original push, pop, transition engine and Settings resume** with compiled resident callbacks through depth4→5→6: cancel returns to BF+ with ON, reopening and confirming OFF returns with OFF, and left returns to Settings at current/previous10 and scroll412. It also executes original stock input/key parsing for Menu and both playback routes on filtered simultaneous events, proving they cancel without a commit or row10 access. Original popup painters, text parsers and font metrics verify uppercase values and panel geometry; font control and glyph coverage are checked in all17 languages. Draw queue completion is simulated synchronously; separate wrapper tests cover deferred completion. Rasterizers and device services remain stubbed.

### Repeated-glyph cause and regression coverage

The parent/user reported `TTTTT m` and `VVVVVVV` while live RAM reads confirmed intact ASCII strings and row pointers. Original firmware execution establishes that this is missing font coverage:

- Row painter `0x4d3363df0` uses label font5. Font-height lookup `0x4d3325940` reads `0x4d3df71f0`: font5 is54 pixels, value font4 is52. Family lookup `0x4d332df40` returns4 and3 respectively. Executing the original title painter `0x4d3363ca0` establishes that its text descriptor uses font3 (41 pixels, family2); the nearby constant5 is alignment flags, not its font index.
- Glyph lookup `0x4d332df80(height, codepoint, style=0, flag=0)` dispatches height54 to `0x4d332d200` and height52 to `0x4d332d0d0`. ASCII tables are `0x4d35631f0` and `0x4d3562d70`, with12 bytes per codepoint starting at space. Flag0 selects the third signed32 column. Font5 returns `0xffffffff` for lowercase `o,u,c,h,f,s,z,e,r,i,n`, but supports `T` (59), `V` (61), and lowercase `m` (48). Font4 supports all characters in the original mixed-case labels.
- Glyph raster helper `0x4d320abf0` tests the lookup result at `0x4d320ac50..ac54` and returns on -1 without clearing the bitmap or updating dimensions. Text renderer `0x4d3328180` then reuses the previous bitmap at `0x402174800` and its dimensions. This explains the repeated initial T/V and the surviving final m. It is not evidence of corrupted strings or an asynchronous string lifetime problem.
- Initial clear `0x4d332ba70` only clears the full foreground rectangle; it does not initialize font/cache state. Stock resolved menu labels use single private-use UTF-8 tokens (for example label203 is U+F0CA) selecting whole-label sprites through `0x4d320acf0`. Parent runtime reads confirm this encoding. Their appearance does not establish ordinary lowercase ASCII coverage.

The labels are `"\x1b\x06" "Touch Focus Zoom"`, `"\x1b\x06" "MF Subject Detection"`, `"\x1b\x06" "Aspect Ratio"`, and `"\x1b\x06" "Version"`. The native ESC control selects font6 (60-pixel cell, family5), retaining the stock painter, alignment, and layout. BF+ remains plain text (main row font5, title font3). All submenu values use font6; OFF/ON and ratio choices also carry the same explicit font control so the popup keeps the matching type size. No firmware hook, callback ABI or internal protocol version changes are required for this typography change.

Font4 solved missing lowercase glyphs but the user reported that it looked too small. Its capitals occupy28 pixels and its lowercase x-height is about20, within a52-pixel cell. Font6 has36-pixel capitals and a25-pixel x-height in a60-pixel cell. In a90-pixel row, font6 capitals occupy Y27..62, matching the captured native English labels; font4 capitals occupy Y31..58. The parent compared actual stock `Information / Firmware`, font4, and font6 in `.touch-focus/stock-vs-fonts.png` and confirmed font6 matches the native size and regular style. This worker inspected that supplied image without accessing hardware. Font6's per-character advance for that phrase is488 versus the stock whole-label sprite's492; matching typography does not imply identical whole-string spacing.

Font6 uses the glyph lookup at `0x4d332d380`, ASCII index table `0x4d3563670`, and family5 descriptor table `0x4d3e09338` returned by `0x4d332cec0`. Its requested label characters all resolve. T is glyph52 (advance30, ink28×36, top/bottom12); V is glyph56 (advance32, ink30×36, top/bottom12). Stock English family10 descriptor table `0x4d3dfbbc8` contains whole-label sprites with58-pixel cells: index196 Information / Firmware has36-pixel ink height with top/bottom11, producing the same vertical placement. Font6 therefore matches the measured stock ink size and baseline while supplying lowercase glyphs.

- Text renderer `0x4d3328180` recognizes codepoint0x1b at `0x4d3328358..8360`. At `0x4d33285fc..8618`, it reads the next raw byte, calls font-height lookup `0x4d3325940`, stores the new height in the glyph context, and advances two bytes without emitting a glyph.
- Width measurement `0x4d3327e50` handles the same control at `0x4d3327f84..7fa0`. Height measurement `0x4d3328000` does so at `0x4d33280fc..8118`. Thus the stock native parser applies the switch consistently during drawing and measurement; no custom string parser or text descriptor is needed.

Earlier wrapper tests intercepted rasterizers and verified string pointers/content, so they could not detect unsupported glyphs. Conditional regressions in `tests/test_touch_menu.py` now execute the supplied segment05's **original row/title painters, text renderer, width/height parsers, glyph helper, font selection, glyph lookup and metrics**. They trace every glyph for the main BF+ row, submenu title, all four labels, OFF/ON, ratio choices and `1.0`, checking supported indices, effective font height, and exact visible characters. Title-case labels measure406/466/274/159 pixels wide at height60 in row order. The smaller font4 controls for Touch Focus Zoom, MF Subject Detection and Version retain widths316/364/123 at height52. Both boolean rows are tested in all four independent value combinations, using OFF94×60 or ON74×60; `1.0` is57×60 with glyph indices1/18/0 in family5. No ESC/font byte is rendered and no value uses the former uppercase PUA path. The historical negative control retains the original mixed-case font5 failure.

At the earlier three-row typography handoff, the menu suite passed55 tests. That isolated build was15,488 bytes (`0x3c80`), including launcher, leaving896 bytes below `0x4000`. Source hashes captured before that styling pass and after verification are recorded under `.touch-focus/value-size-review/`; target-feature logic was outside the typography change.

Parent verification after this worker's handoff: all128 tests passed on stable relevant sources. That exact combined image was installed with all20 hooks verified. The user confirmed the final display/selector check; live readback verified the title-case strings and value font6 on all three rows. Fourteen touch/release zoom cycles completed with zero replay/exit errors. Final verification is retained locally in `.touch-focus/title-case-final-verification.json`.

The user's later ON/OFF correction changed three bytes only; all code and symbol offsets matched that installed build. All55 menu tests passed with uppercase values and the wider native panel geometry stated above. The parent reported a single verified 11-byte data write that updated both shared strings on camera, preserving both enabled options. The immutable original removal image was retained, and `resident_text_updates` in the installation manifest records the override. Readback and hook checks are in `.touch-focus/uppercase-values-patch.json`. Full installs build uppercase values directly from source.

These tests stub memory helpers, language selection, and the three bitmap conversion leaves (`0x4d33278e0`, `0x4d3327c80`, `0x4d3327d90`) whose pixel assets reside outside segment05; they do not claim pixel fidelity. Other UI services remain stubbed. The conditional tests skip explicitly when `decoded-V104/rtos-alt.bin` is absent.

These offline checks establish glyph lookup coverage, but do **not** prove final rasterized appearance, camera queue timing, cache coherency, or physical-camera behavior of the corrected submenu. Parent handles hardware validation and installer integration separately.

## Subsequent subject detection and indicator build

The earlier 15,488-byte/20-hook figures above describe the typography build.
Before the Aspect Ratio addition, detector activation and the native gray indicator brought the complete
payload to 16,192 bytes, with 22 pointer hooks and three instruction regions.
That menu retained three rows, title-case labels, uppercase ON/OFF values,
font6 and compact selector. All 174 offline tests passed at that handoff, including the
native frame producer/renderer tests. See [MF-SUBJECT-DETECTION.md](MF-SUBJECT-DETECTION.md)
for detection and display behavior. The fixed launcher and State/log ABI remain
unchanged. The installer verifies uploads using read chunks of at most 4096
bytes; this does not add writes or bypass the save cooldown.

The parent reported installing the gray indicator and native AF target selection. The user
confirmed that the box matched AF and touch zoom/release worked. That update
retained the menu styling and both enabled options. The new Aspect Ratio UI does
not change their detector, frame or guide logic.
