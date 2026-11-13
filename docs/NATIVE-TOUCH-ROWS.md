# Native ordinary row-list touch — BF V104

`touch_focus/native_touch_rows.h` adds touch selection and discrete drag
navigation to **six verified stock row-list families**. A tap selects using
native signed dial events and activates using native center. It never writes
native selectors, row descriptors or setting values. The compact eight-family
adapter and the normal Settings root remain separately owned.

This is a bounded extension, not a claim that all stock menus accept touch.
Date/time, mixed private-backed lists, editors and several dialogs remain
outside this adapter. The inventory below records those gaps. Whole-camera
rotation, hook installation and the global input bridge belong to the parent.
No hardware, USB, PTP or flash access was performed.

## Parent API

Include after `u8`, `u16`, `u32`, `u64`, `uptr`, `struct Key`, `struct Event`
and the freestanding `memcpy` implementation already provided by payload.c.
The header has no shared `menu.h` or renderer dependency.

```c
#define NATIVE_TOUCH_ROWS_ENABLED() (state.mode != 2)
#define NATIVE_TOUCH_ROWS_TRANSFORM(out,source) ui_map_packet(out,source)
#include "native_touch_rows.h"

u64 native_touch_rows_handler_for_draw(u64 original_foreground);
u32 native_touch_rows_begin(u64 original_input,
                            const void *actual_canonical_surface,
                            u32 scene_epoch);
void native_touch_rows_observe(u32 token, const void *actual_surface,
                              const void *row_descriptor);
u32 native_touch_rows_end(u32 token, u32 displayed_ok);
u32 native_touch_rows_input(struct Event *original_event,
                            u64 original_input, u32 scene_epoch);
void native_touch_rows_reset(void);
void native_touch_rows_reorient(u32 new_scene_epoch);
```

`handler_for_draw()` returns the original input for either verified initial
or regular foreground callback, or zero for everything else. This permits
capture on the first displayed frame, before any input event. Do not infer
ownership from the hardware active-input pair on another worker's stack.
`native_touch_row_families` and `NATIVE_TOUCH_ROW_FAMILIES(X)` export the
map. The macro expands `X(id,input,selector,rows,count,foreground,initial)`;
`rows == 0` identifies Sound's stack descriptors.

The parent integration sequence is:

1. Identify a **foreground** callback with `handler_for_draw`. Use the returned
   original handler as the scene identity, so an initial-to-regular redraw
   within that family keeps the same epoch. Never bracket background draws.
2. Enter `begin(handler, actualSurface, epoch)` from the shim that receives the
   **actual canonical surface passed to the native callback**. A surface copy
   inside `global_draw_canonical` can have a different address from its caller's
   descriptor. Register that copy, not the outer physical surface.
3. Preserve the nonzero token in that invocation's draw context. At the direct
   BL row-painter hooks, call `observe(token, x0, x1)` before executing the
   original `0x4d3363df0`. Do not expose one mutable token across nested draws.
   A zero token means render normally without observe/end for that invocation.
4. Call `end(token, displayed_ok)` exactly once, including failed/aborted draws.
   Pass one only for a complete successful canonical foreground accepted as
   the current display in the same epoch. If publication can fail or the
   frame can be superseded after the callback, retain the token until that
   decision is known. Otherwise pass zero. The owning end always releases the
   capture gate, even when its snapshot was invalidated. Wrong/stale tokens
   cannot release another invocation's gate.
5. At global input dispatch, pass the original Event and original input handler
   to `input`. It forwards that Event exactly once and returns the native
   result, or the result of the synthetic center when it activates. Unknown
   handlers are forwarded without synthesis. A null Event or handler returns
   zero and resets the adapter.

Increment the parent's scene epoch **and call `reset()`** on a display scene
change, disable/removal or same-handler scene re-entry.
This includes unknown/new scenes for which no capture begins. The epoch is
passed by value to input; `reset()` provides immediate invalidation when a
scene changes during a native callback. Do not reset on a legitimate redraw
of the same known family. A lifecycle reset is necessary even when native
stack depth and handler happen to stay the same.

For an orientation-only change, call `reorient(new_epoch)` instead. It cancels
gesture ownership via the atomic abort counter and retags an intact published
canonical snapshot under the capture gate. Thus repeated rotation-only no-op
draws retain row targets without requiring a physical dial/redraw first. It
does not create geometry or revive an invalid snapshot. If capture is active,
or native depth/pending/enable state disagrees, it fails closed and the next
complete native foreground capture must reestablish targets. Do not use
reorient for an actual scene change.

The transform macro defaults to copying all 20 LCD bytes. A custom macro must
fill all 20 output bytes and leave its source untouched. It is invoked only
for the adapter's private geometry copy **after** the original Event has
reached the native handler. It must map tap, origin and current XY pairs to
canonical 1024×682 coordinates using the displayed orientation. Its return
value is ignored, matching the compact adapter contract; failed mapping must
produce out-of-range coordinates, such as `0xffff`, to suppress synthesis.
Do not pre-transform the Event supplied to `input`, or transform twice.
Physical input and null LCD packets bypass the transform entirely.

## Verified family and callback map

All addresses are full V104 addresses. Root indices refer to normal Settings,
not untranslated label guesses.

| Family | Normal Settings root row | Original input | u32 native selector | Stable row table | Rows | Regular foreground | Initial foreground |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 2 | `0x4d3375a50` | `0x4d7302640` | `0x4d7042ee8` | 3 | `0x4d3375230` | `0x4d3375930` |
| 1 | 3, Sound | `0x4d3381270` | `0x4d7302e54` | Stack, copied immediately | 2 | `0x4d3380f30` | `0x4d3381020` |
| 2 | 8, language parent | `0x4d337fde0` | `0x4d7302be0` | `0x4d7043450` | 2 | `0x4d337f960` | `0x4d337f960` |
| 3 | 9 | `0x4d3384930` | `0x4d7043650` | `0x4d7043678` | 3 | `0x4d33844e0` | `0x4d33844e0` |
| 4 | 1 | `0x4d338a3f0` | `0x4d7302f48` | `0x4d70438c0` | 2 | `0x4d3389f20` | `0x4d3389f60` |
| 5 | USB storage chooser | `0x4d3352220` | `0x4d7302508` | `0x4d7035760` | 2 | `0x4d3351e80` | `0x4d3351ec0` |

The sixth family uses the existing four observed row calls at
`0x4d3351e98/1ea4/1f20/1f2c`. Its native selector, initializer, input and
synchronous redraw are exercised by `tests/test_touch_menu_inventory.py`.
Native status gates and device actions remain authoritative. The full bounded
inventory is in [UI-TOUCH-COVERAGE.md](UI-TOUCH-COVERAGE.md).

Regular callback triples occur at `0x4d3564250`, `0x4d3564480`,
`0x4d3564420`, `0x4d35644b0`, `0x4d35644f8`, respectively. Initial
foreground pointers are present at `0x4d3374f08`, `0x4d3381160`,
`0x4d337fbc8`, `0x4d3384748`, `0x4d338a1c8`. Their native initialization
paths publish the input pointers at `0x4d3374ef0`, `0x4d3381148`,
`0x4d337fba8`, `0x4d3384730`, `0x4d338a1b0`. These original image literals
are checked by the test suite. The same callback identities also appear in
resume initialization paths; they do not create additional families.

Native center retains these actions:

| Family | Native actions for row 0 / row 1 / row 2 |
| --- | --- |
| 0 | Push descriptor `0x4d3e88dd0` / `0x4d3376390` / `0x4d3376980` |
| 1 | `0x4d3382090(index)` for both rows |
| 2 | `0x4d3380d70(index)` for both rows |
| 3 | `0x4d3388b20` / `0x4d3386f90` / `0x4d3385b70` |
| 4 | `0x4d337b350` / `0x4d3389b10` |

These calls execute in original native input instructions. The adapter adds
no explicit pop or setting conversion. Child action execution and setting
persistence are outside the offline tests; their call targets/arguments are
recorded at the boundary.

## Capture and synchronous redraw rules

The row descriptor is 32 bytes: u16 Y at +0, u8 flags at +2, label/value
pointers at +8/+16 and value font at +24. Bit 0 marks selection; bit 1 enables
activation; bit `0x10` marks readonly/special treatment. Native painter
`0x4d3363df0` clears X0..1024 at the descriptor's Y with height 90. The label
rectangle is X48, width916, height90. Hit targets use the complete native row.

Capture accepts only the exact canonical surface registered by begin. Stable
families require an aligned descriptor address within their own row table.
Sound maps its native stack-built rows by the verified Y142/Y232 positions;
it copies Y and flags immediately and never retains a descriptor pointer.
A publishable frame contains every expected row, ascending nonoverlapping
90-pixel geometry wholly within Y52..682, and exactly one selected flag
matching the live native u32 selector. Partial, conflicting, malformed,
failed or superseded captures do not publish hit targets.

The initial foreground can run before the hierarchy worker publishes the
new depth or clears pending: `0x4d3323ea4` calls the initializer, while
`0x4d3323eb0` stores depth and `0x4d3323ebc` stores idle12 afterwards. Begin
therefore permits a pending target depth below12 and retains that expected
depth with the initial geometry. End accepts either the unchanged transition
or its completed expected depth. **Input still requires pending12 and the
exact expected final depth**; no touch synthesis occurs during transition.
If the initializer creates further hierarchy levels or another scene appears,
the depth/handler/epoch checks reject that capture. A real hierarchy-worker
test verifies Sound's first frame and first tap without a preliminary event.

**Native queue `0x4d3322d90` may synchronously wait for the renderer.** No native
input, setting getter or center callback is called while holding the capture
gate. Input takes a small local snapshot under that gate, releases it, calls
the native handler, then obtains and validates a new snapshot. A redraw may
change the capture generation, canonical surface pointer and selection flags.
Family, parent epoch, native depth and every captured row Y must remain the
same before touch can continue. The most recent captured and live flags are
checked again before center. This permits legitimate synchronous redraws and
rejects changed geometry or another scene.

A separate nonblocking dispatch guard prevents recursively synthesizing touch
when native input is reentered; it does not block drawing. Reentered original
input is still forwarded once and cancels the outer synthesis. Capture
contention, invalid snapshots, lifecycle resets and failed selector progress
abort touch without waiting. Only the input owner modifies gesture state;
draw/reset communicate invalidation atomically. There are no cross-worker
spins waiting for a draw to finish and no lock held over a synchronous queue.

The parent still owns display/scene ordering and must serialize native input
as it normally does. These guards protect the adapter's state; they do not
make arbitrary concurrent native callbacks safe or establish camera cache
coherence. The owning draw invocation must eventually call end, even on its
failure path; a reset invalidates its token generation but does not steal its
lock while it might still be observing rows.

## Input behavior

The original five nullable Event parts and their pointed-to bytes remain
unchanged. Any nonzero physical key field or either signed dial channel wins
over touch. Synthetic dial events contain only `{s16 +/-1, s16 0}`; center
contains only a ten-byte key with `changed=1, press=1`. Both are delivered
synchronously from the stack.

All five native inputs move one row for either sign of the first s16 dial,
regardless of magnitude, and synchronously update their separate selector.
The adapter requires exactly one expected step per call and emits at most
`row_count-1` steps (two) plus one center. It never treats painted selected
flags as the live selector: language only refreshes those flags when painting.

A tap must hit a captured row and satisfy `(flags & 0x12) == 2`, both in the
capture and in stable native row memory. These checks repeat after selection.
Family 0 also rechecks the native master getter `0x4d3322550`, because native
dial gates rows 1/2 with it while native center omits that check. Disabled or
readonly taps do not navigate or activate. Drag navigation retains native
dial behavior and may highlight a disabled row without activating it.

LCD packets are 20 bytes, including unaligned input. Tap XY is +0/+2, origin
+4/+6, current +8/+10 and flags u16 at +16. Stationary tap `1` needs no BEGIN.
Begin `0x100` and update `0x200` move one row per 90 vertical pixels; these
short lists fit on screen, so this is selection navigation rather than a
scrollable viewport. Horizontal/offscreen gestures and begins outside rows
are ignored. Idle/null-LCD events preserve a valid drag.

END `0x400`, short drag release `0x401`, up `0x410`, down `0x420`, left
`0x440` and right `0x480` clear ownership without confirming. Cancellation/
pinch bits `0x7000` also clear ownership. A subsequent independent stationary
tap can activate. Unknown flags do not synthesize confirmation. An interrupted
drag remains blocked until an end or a new gesture, preventing its trailing
tap bit from activating a row.

## Why this is not a generic row registry

Scanning aligned AArch64 BL instructions in the exact supplied image finds
**37 direct calls** to `0x4d3363df0`. Hooking all those sites for observation
is compatible with this API, but is not proof that each caller is an ordinary
selectable list. Only the foreground map above authorizes capture and input.

| Excluded family | Evidence and reason |
| --- | --- |
| Date/time mixed scene | `0x4d3376e50`, `0x4d3376e5c`, `0x4d3376e68`, `0x4d3376e74` paint four ordinary rows, but the same scene contains the separate `0x4d33643e0` date/time editor. Selection space is not ordinary row order. |
| Mixed Settings child | `0x4d337d180` paints ordinary rows via `0x4d337d37c`, `0x4d337d390`, `0x4d337d454` into private surface `0x4d7043220`, then copies a viewport. Raw descriptor Y is not canonical screen Y. Other row types and separators share the selector space. |
| Sound | Row descriptors exist on the foreground stack (`0x4d3380f30`); addressed here only with its explicit two-row family and immediate copying. A pointer registry would retain dead stack memory. |
| Language parent | Native input updates `0x4d7302be0`; `0x4d337f960` changes selected flags later during painting. A generic selected-flag-only navigator would use stale state. |
| Other direct callers | Playback/modal/root and specialized scenes also use this painter; their input and selection contracts are not established by painter reuse. |

Normal Settings root coverage, including the separately implemented compact
adapter, is:

| Root row | Child entry | Coverage / remaining work |
| --- | --- | --- |
| 0 | `0x4d337db20` | Mixed/private-backed list not covered; needs viewport offset, heterogeneous selector and row-type proof. |
| 1 | `0x4d338a6e0` | Row family 4 covered; nested custom screens need separate adapters. |
| 2 | `0x4d3375da0` | Row family 0 covered; existing compact picker covered separately; nested sliders remain custom. |
| 3 | `0x4d33814a0` | Sound row family 1 covered; compact children covered separately. |
| 4 | `0x4d3389130` | Existing compact family 7. |
| 5 | `0x4d33843e0` | Adjustment/editor with no ordinary row painter found in the inspected scene; not covered. |
| 6 | `0x4d338b0c0` | No ordinary row painter found in the inspected scene; not covered. |
| 7 | `0x4d3379700` | Mixed date/time editor not covered; existing compact family 1 only. |
| 8 | `0x4d3380000` | Language parent row family 2 covered; compact families 2/3 separately covered. |
| 9 | `0x4d3384f40` | Row family 3 covered; nested dialogs/editors not automatically covered. |

The normal Settings root is parent-owned. Alternate/service Settings,
confirmation/progress dialogs, numeric editors, grids, playback, capture
controls and live-view overlays have no general touch coverage claim here.
Whole-UI portrait rotation can apply globally without proving touch semantics
for these remaining surfaces. Next bounded work should establish each mixed
scene's own selector-to-visible-geometry contract rather than adding a blind
row-count fallback.

## Offline evidence and verification

Artifact: `decoded-V104/rtos-alt.bin`, base `0x4d3000000`, SHA-256
`f747c1350f00526b9c68c65aaef44d6e7b644b0169992342e12f059c42e150dc`.
Analysis follows the reverse-engineer-anything skill with local
`decoded-V104/analyze.py`/Capstone and Unicorn. REA MCP was unavailable;
no configuration or analysis-engine installation was needed. The evidence
IDs here are local labels, not REA-issued identifiers.

| Evidence | Observation | Boundary |
| --- | --- | --- |
| NTR-01 | Native init literals and update triples map the five inputs to both foreground forms. | Exact image byte checks plus original foreground execution. Background callbacks return no mapping. |
| NTR-02 | All five signed dial paths update their selector synchronously by one. | Original input/key-test instructions execute; queue service is intercepted. |
| NTR-03 | Tap selects each reachable row and delegates native center to the expected child action. | Native handlers execute; downstream actions/settings services are intercepted. |
| NTR-04 | Original painter uses X0, native Y, width1024, height90; Sound builds transient stack rows; language changes flags during paint. | Original row-painter and foreground instructions execute. Raster/text/getter services are intercepted; stable row RAM is seeded with representative initialized state. |
| NTR-05 | Dial queue can reenter actual foreground drawing with begin/observe/end, publish a changed generation/surface, return, then confirm correctly. | A synchronous test scheduler replaces the queue service and executes the real queued foreground. This tests reentry ordering, not the RTOS scheduler implementation. |
| NTR-06 | Real touch producer emits `0x410/420/440/480` directions and `0x401` short release, then stationary `1`. | Executes `0x4d3246250`, `0x4d3246340`, `0x4d32464b0`; memory/mutex services intercepted. |
| NTR-07 | Adapter never writes firmware/native RAM; original caller bytes remain unchanged; transform acts only on a private copy. | Unicorn write hooks reject adapter writes to firmware RAM; default/custom-transform compiled fixtures validate packet identity. |
| NTR-08 | Generic registry is unsafe for mixed/backing-copy/date-time scenes. | Static instruction inspection bounded to the stock root inventory and the 37 direct row-painter calls; no exhaustive scene analysis claimed. |
| NTR-09 | Initial draw runs at old depth/pending target, then native hierarchy publication makes that captured frame eligible for input. | Original `0x4d3323ca0` hierarchy worker and Sound initializer `0x4d33811d0` execute with synchronous real foreground reentry; other initialization services are intercepted. |

Run:

```sh
.venv/bin/python -m unittest discover -s tests -p test_native_touch_rows.py -v
```

**41 tests pass** with the supplied image. The fixture compiles only this header with payload-style freestanding
AArch64/PIC flags, verifies relative relocation kinds and runs at a relocated
address. It builds in a temporary directory, independently of the shared
payload builder or staging-size limit. It imports only reusable offline
helpers from the frozen compact test file. Without local firmware it skips;
it does not download firmware or access a device.

The suite covers both foreground forms, every family/row, synchronous redraw
and recursive-input reentry, physical priority, exact packet preservation,
custom transform, disabled/readonly state, native master gating, stack-row
lifetime, stale selected flags, partial/wrong-canvas/malformed captures,
wrong/stale tokens, contention, lifecycle resets, direction releases, bounds,
selector progress and the absence of adapter writes to native state.

The default isolated fixture is 3,900 initialized / 4,056 resident bytes with
the available `-Oz` compiler, including test-only queue/transform probe support
and metadata. This is a module integration estimate, not a final production
payload-size result. Rotation retagging, interrupted captures and native
hierarchy initialization are included in the tested boundary.

Unicorn results do not prove physical touch timing, actual RTOS scheduling,
cache maintenance, final payload fit, install/uninstall behavior, camera
rendering or whole-camera portrait operation. Parent integration and final
source/build verification remain separate from these isolated module tests.
