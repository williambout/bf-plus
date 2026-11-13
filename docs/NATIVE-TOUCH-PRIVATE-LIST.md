# Native private user-settings list touch — V104

`touch_focus/native_touch_private_list.h` adapts **only** stock input
`0x4d3386a00`: the variable-length child reached from ordinary row family 3,
row 1, via `0x4d3386f90` and scene descriptor `0x4d3e892e8`.
This closes the specific private-list gap identified in
[UI-TOUCH-COVERAGE.md](UI-TOUCH-COVERAGE.md). That earlier inventory remains
the record of the pre-adapter audit. Alternate/service Settings and the
other mixed Settings child have separate owners and are not adapted here.

A tap selects the captured native index using signed one-step native dial
events, then sends native center once. Dragging navigates selections and
lets the native handler move its own viewport. This is discrete navigation,
not inertial/pixel scrolling. The adapter never writes native selectors,
row descriptors, scroll offsets, user settings or scene state.

## Parent integration contract

Include after `u8/u16/u32/u64/uptr`, `struct Key`, `struct Event`, and the
freestanding `memcpy` used by the payload. There is no `menu.h` dependency.

```c
#define NATIVE_TOUCH_PRIVATE_LIST_ENABLED() (state.mode != 2)
#define NATIVE_TOUCH_PRIVATE_LIST_TRANSFORM(out,source) ui_map_packet(out,source)
#include "native_touch_private_list.h"

u64 native_touch_private_list_handler_for_draw(u64 callback);
u32 native_touch_private_list_begin(u64 original_input,
                                   const void *actual_canonical_surface,
                                   u32 epoch);
void native_touch_private_list_observe(u32 token,
                                     const void *actual_surface,
                                     const void *row);
u32 native_touch_private_list_end(u32 token,u32 displayed_ok);
u32 native_touch_private_list_input(struct Event *original_event,
                                   u64 original_input,u32 epoch);
void native_touch_private_list_reset(void);
void native_touch_private_list_reorient(u32 epoch);
```

The exported `NPL_INPUT` constant is `0x4d3386a00`. The foreground identity
function returns it for **initial `0x4d33865d0` and regular `0x4d33861b0`**,
and zero for all other callbacks, including background painters and the
private row builder itself.

1. Bracket only these known foreground callbacks. Pass the actual canonical
   surface received by the native foreground. Keep the returned nonzero
   token with its owning draw/frame invocation, independently of the ordinary
   row adapter's token. A zero token means no capture/end for that invocation.
2. At existing `UI_ROW_CALLS`, call `observe(token,x0,x1)` before the original
   ordinary row painter. The three relevant sites are `0x4d3385e54`,
   `0x4d3385ef4`, `0x4d3385f8c`; all already occur in that 37-site table.
   No new instruction hook is required. Keep executing the original painter.
3. End each owned token exactly once after the parent decides whether this
   coherent foreground was successfully published in the same epoch. Pass
   zero for failed, superseded, partial or otherwise unaccepted frames.
   A reset invalidates a capture; it does not release another draw's gate.
4. Route the original input/event to `input(event,NPL_INPUT,epoch)`. The
   original handler executes once before touch synthesis, and caller bytes
   and all five nullable part pointers remain unchanged. Unknown handlers
   are forwarded without synthesis after invalidating this adapter.
5. Reset on scene entry/exit/re-entry, disable and removal. For an orientation
   change in the same scene use `reorient(new_epoch)`: it cancels the gesture
   and retags only a still-valid published snapshot. During active capture it
   invalidates that capture instead of stealing the gate.

The transform macro writes a **private 20-byte copy**, invoked only after
the original event reaches the stock handler. It must inverse-map tap,
origin and current coordinate pairs into native 1024×682 coordinates using
the displayed frame. Its return value is ignored; failed mapping should put
all coordinate pairs outside bounds, e.g. `0xffff`. Never transform the
event sent to the original native input. The default macro copies unchanged.

Capture permits initial rendering before the hierarchy publishes its new
depth: a pending value below12 is the expected final depth. Input still
requires pending12 at that exact depth. Frame publication and same-handler
scene re-entry detection remain parent responsibilities.

## Native geometry and ABI proof

Artifact: `decoded-V104/rtos-alt.bin`, base `0x4d3000000`, SHA-256
`f747c1350f00526b9c68c65aaef44d6e7b644b0169992342e12f059c42e150dc`.
Local Capstone and Unicorn supplied the evidence. No REA-issued evidence ID,
camera observation, USB connection, storage I/O or network access is claimed.

| Native fact | Evidence |
| --- | --- |
| Scene ownership | Descriptor `0x4d3e892e8` contains init `0x4d33864a0`, resume `0x4d3386330`, suspend `0x4d3385b90`, exit `0x4d3386490`. Input literals `0x4d3386450/65a0` contain `0x4d3386a00`. |
| Foregrounds | Initial literals `0x4d3386468/65b8` contain `0x4d33865d0`; regular literal `0x4d3386f78` contains `0x4d33861b0`. Regular update queues `(0x4d33861b0,0x4d3386020,0)`. |
| Complete rebuilding | Regular foreground unconditionally calls `0x4d3385d10` at `0x4d33861f0`; initial does so at `0x4d3386668`. Both rebuild every row. The regular parameter byte changes the **background** path; foreground does not become a partial row repaint. |
| Transient rows | Builder `0x4d3385d10` reuses one 32-byte row at `sp+0x68`. It writes Y at +0 and flags at +2 before each painter call. No row pointer may outlive observation. |
| Native index 0 | Local Y56, 90-pixel row height. Its enable flag depends on native metadata's first-entry availability. |
| Native indices 1..count | Local Y`236 + 90*(index-1)`. The 180-pixel first-index spacing includes a section heading; it must not be flattened into 90-pixel positions. |
| Empty list | Count zero still paints a disabled placeholder at local Y236. It may carry the selected bit but must never be activated. The first entry can independently remain enabled. |
| Private surface | Row calls use descriptor `0x4d7043708`, not the foreground's canonical surface. Boot data gives buffer `0x402cc6800`, stride2048 and height1136. Capture validates stride/height and a stable nonzero buffer. |
| Viewport | Regular copy at `0x4d3386228`, initial at `0x4d33866a0`: source `private_buffer + offset*2048`, destination `canvas_buffer + 142*2048`, size `540*2048`. Offset is u32 at `0x4d70436e0`. |
| Selection | u32 index `0x4d7302ec0`, native highlight Y `0x4d70436d8`. Capture requires `highlight = 142 + local_row_y(index) - offset` and highlight within142..592. |
| Dial | `0x4d3386ab4` reads the first signed16 dial field. Positive moves one index toward count; negative moves one toward the first enabled entry. Magnitude is ignored. The native code owns the extra180-pixel first step and viewport edge adjustments. |
| Center | Key test `0x4d3386d84` reaches `0x4d3386dac`. It rechecks count/first availability, then calls `0x4d33881a0(index,highlight_y)` at `0x4d3386dd8`. That helper stores index at `0x4d7302f20`, positions the existing compact popup and tail-calls push with descriptor `0x4d3e89340`. No explicit pop or direct setting write is added. |

Displayed row Y is **`142 + local_y - offset`**, clipped to `[142,682)`.
Hit testing requires X in `[0,1024)` and Y in that viewport, then the actual
row's 90-pixel span. It rejects heading gaps and completely hidden rows, while
allowing the visible portion of a clipped row. At offset11 the first row is
Y187..277, the next is Y367..457, and native index4 is partly visible at
Y637..682. At offset596 the top visible row is index5, not index0.

For count0..3 the offset ceiling is11; above that it is `90*count - 304`,
up to596 for ten stored entries. These bounds follow the content extent and
540-pixel copy. Native movement can preserve different top padding when the
first row is reached; the adapter uses the published viewport, not an assumed
top-of-list layout.

## Metadata, publication and concurrency

Native getter `0x4d31a4b10` reads the cached pointer at `0x4d72aa518`, count
at cached+`0x7c`, and first-entry availability at cached+`0x81`. Its lazy
loading path assigns buffer `0x405118d00` at `0x4d31a4b58..4b7c`.
The adapter only reads that recognized, already-initialized cache. A null or
different cache pointer disables capture; it never invokes the getter's
storage-loading path while holding a lock.

Capture copies all130 metadata bytes through offset`0x81`, including record
data and ordering links. Native record formatting at `0x4d31a4c60` follows
those links, so count alone cannot identify a displayed entry. Every capture,
input refresh and pre-center check compares the copied bytes. A same-count
replacement/reorder, changed count or changed first-entry availability aborts
activation. Counts above10 are unsupported and fail closed. The original
native handler still receives its event.

Publication requires every expected row index exactly accounted for, no
conflicting observations, flags consistent with metadata, one selected bit
matching the native selector, stable viewport/metadata/private surface, and
successful parent publication. A count-zero placeholder is included for
geometry validation but stays disabled. Unknown flags, including readonly
flags the native builder does not emit, invalidate the frame.

No partial-row retention is necessary because both verified foregrounds
always rebuild all rows. A partial capture or foreign surface fails closed.
The initial/resume functions also prebuild private pixels outside their
queued foreground; those calls do not authorize a capture on their own.

The capture gate is nonblocking and is never held across native input calls.
Input snapshots under the gate, releases it, then invokes native dial. A
synchronous native redraw can capture a new generation and scroll offset.
Refresh accepts that new viewport only when epoch, depth and full entry
metadata still match. It requires exactly one index of progress per dial
step, at most ten dial calls per input packet, and aborts on no progress or
unexpected movement. Reentrant input forwards once but invalidates the outer
synthesis. Nested/contending captures invalidate without waiting. A stale
end cannot release another token's gate.

The complete native u32 return value is preserved, either from the original
event or the final native center. Synthetic events carry only a signed dial
payload or a center key (`changed=1,press=1`), never caller side channels.
Physical key/dial input takes priority. END/release/cancel packets clear
gesture ownership without confirmation; an interrupted drag cannot activate
from its trailing tap bit.

These checks rely on the parent's usual serialization of native input and
scene publication. They do not establish RTOS scheduling, atomic mutation
of native settings by other workers, cache coherence or physical display
behavior. Metadata is checked repeatedly, but this is not a new lock around
native storage operations.

## Offline regression fixture

```sh
.venv/bin/python -m unittest discover -s tests -p test_native_touch_private_list.py -v
```

**19 tests passed**, and all11 preserved inventory tests passed against the
parent's integrated six-family ordinary row map (30 combined).

The fixture compiles only this new header with freestanding AArch64/PIC flags,
checks relocation types, and executes it at a relocated address. It installs
the actual boot initialized-data image and executes original native input,
cached getter, initial/resume functions, foreground/stack-row builder,
viewport-copy argument construction, key tests and popup-request helper.
Text/date/raster services, the final scene push and the scheduler are explicit
intercepts. The queue substitute synchronously executes the original queued
foreground, exercising reentry without claiming the real RTOS scheduler ran.

Coverage includes all counts0..10 and both availability states; initial and
regular complete row builds; original init/resume and first touch; a full
native scroll sweep with endpoint clamps; first-row spacing; heading gaps;
clipped bottom and scrolled top rows; disabled first/empty placeholder;
single-step native selection and center popup index; full u32 return;
original packet preservation and private inverse transform; drag release;
same-count metadata replacement and mid-navigation mutation; incomplete,
failed, stale or conflicting capture; reentrant input; orientation retag and
initial depth publication.

The current isolated fixture is **3,976 initialized / 4,384 resident bytes**,
including fixture helpers. This is not the integrated payload size. It uses
a temporary directory, skips when the local firmware is absent, and rejects
the wrong firmware hash. It performs no firmware download or hardware I/O.
Parent integration owns the production build and transaction tests.
