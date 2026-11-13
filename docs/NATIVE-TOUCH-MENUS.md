# Native compact-picker touch adapter — BF 1.04

`touch_focus/native_touch_menus.h` adds bounded tap selection and drag
navigation to **eight verified compact-picker input families**. It does not
implement touch for every stock menu, install hooks, rotate the UI, or change
the shared payload/build. Those are parent integration tasks. No camera,
USB, PTP, flash, or hardware access was performed for this work.

The adapter calls original native input functions. A tap sends enough signed
one-step dial events to select its visible row, then one synchronous center
press. Native code retains setting conversion, redraw submission and scene
transitions. Dragging changes the tentative selection only. Stock painters
scroll their own visible window to follow that selection; this is discrete
90-pixel row navigation, not inertial or pixel-smooth scrolling.

## Parent integration contract

Include the header after the payload's `u8`, `u16`, `u32`, `u64`, `uptr`,
`struct Key`, and `struct Event` definitions. It has no `menu.h`, `state`,
allocator, or orientation-module dependency. Its separately named
`NativeTouchPicker` matches the existing 48-byte `MenuPicker` ABI.

```c
/* Parent owns the enable/removal predicate. Define before inclusion. */
#define NATIVE_TOUCH_MENU_ENABLED() (state.mode != 2)
#include "native_touch_menus.h"

/* Select only a verified family installed for the current scene. */
u32 native_touch_menu_input(struct Event *event, u32 family);
void native_touch_menu_reset(void);
/* Equivalent family-specific callbacks, each accepting struct Event *. */
/* native_touch_menu_0 ... native_touch_menu_7 */
```

`native_touch_menu_families[8]` provides `input`, `descriptor`, `hooks[2]`
and maximum `limit`. `NATIVE_TOUCH_MENU_FAMILIES(X)` expands
`X(id,input,descriptor,init_literal,resume_literal,limit)` for a parent-owned
installation/relocation table. A zero second literal means absent. The table
contains absolute **firmware addresses only**, not resident function pointers.
The generated callbacks and runtime state use position-independent code.

Installation must validate the firmware identity and each hook's expected
original input pointer, integrate relocated wrapper addresses, and retain the
parent's normal uninstall/cache/scene ownership rules. This header neither
patches those literals nor rewrites the live scene handler slot. Installing
while a picker is already open requires parent lifecycle handling; replacing
its initializer literal alone does not change its already-published callback.

The event's LCD payload must already use canonical **1024 × 682 native
coordinates**. Whole-camera portrait integration must inverse-transform all
three coordinate pairs (+0/+2, +4/+6, +8/+10) using the last displayed frame's
orientation, then call this adapter with the resulting event. Do not inverse-
transform twice, or apply the independent BF+ full-screen portrait layout to
these compact native picker descriptors. Coordinate transformation and UI
rotation are not provided or tested by this module.

Call `native_touch_menu_reset()` on scene entry/exit, orientation change,
disable/removal and any same-family scene re-entry. It cancels active drag
ownership while blocking an interrupted drag's stray tap. A fresh BEGIN or
END clears that block. The adapter also detects family/depth/mode/label/count
changes. Those guards cannot detect a complete scene exit and re-entry at the
same depth with the same descriptor between two callbacks: lifecycle resets
remain required. A disabled predicate delegates physical input unchanged and
stops touch synthesis. NULL events or unknown family IDs are safe no-ops;
unknown IDs cannot be forwarded because they have no original callback.

## Hook and setting map

All addresses below are full 64-bit addresses for V104 segment 05.
Fourteen expected-value pointer replacements cover eight inputs.

| Family | Original input | Native descriptor | Input pointer literals | Native confirm behavior |
| --- | --- | --- | --- | --- |
| 0 | `0x4d3375730` | `0x4d7042f50` | `0x4d3374fd8`, `0x4d3375628` | Boolean conversion, setter `0x4d3322560`, then pop |
| 1 | `0x4d3379ea0` | `0x4d7302890` | `0x4d3379c78` | Mode-specific conversion/setter, then pop |
| 2 | `0x4d33807e0` | `0x4d70435b8` | `0x4d3380398`, `0x4d33807a8` | Selected index to `0x4d33217a0`, then pop |
| 3 | `0x4d33809f0` | `0x4d7043588` | `0x4d33805d8` | Language index to `0x4d3321f80`, then pop |
| 4 | `0x4d3381c80` | `0x4d7043618` | `0x4d3381830`, `0x4d3381b30` | Selected index to `0x4d33212c0`, then pop |
| 5 | `0x4d3381e70` | `0x4d70435e8` | `0x4d33819e0`, `0x4d3381c50` | Selected index to `0x4d33212a0`, then pop |
| 6 | `0x4d3387f80` | `0x4d7043728` | `0x4d3387e10`, `0x4d3387f50` | Calls `0x4d3387bf0`; pushes child `0x4d3e89318`; **does not pop** |
| 7 | `0x4d3388f10` | `0x4d7043890` | `0x4d3388d88`, `0x4d3388ee8` | Shutter Blackout index to `0x4d33212e0`, then pop |

Family 1 reads its mode as a u32 at `0x4d730288c`:

| Mode | Entry count | Native setter | Conversion |
| --- | --- | --- | --- |
| 0 | 32 (six visible) | `0x4d3321f40` | Signed 16-bit table at `0x4d3e88e90`, from −600 to 780 |
| 1, 4 | 2 | `0x4d3321f60` | Index != 0 |
| 2, 5 | 3 | `0x4d3321f20` | Index |
| 3, 6 | 2 | `0x4d3321f00` | Index |

These conversions execute in native instructions; the adapter does not copy
or reimplement the setting table. Family 3 has 17 entries. Other families
require exactly two. Unknown modes or mismatched counts disable touch
synthesis while preserving original-event forwarding.

## Gesture, packet and descriptor rules

The LCD payload is 20 bytes and may be unaligned. Its tap XY is at +0/+2,
drag origin at +4/+6, current XY at +8/+10 and u16 flags at +16.
`1` is a completed stationary tap without a preceding BEGIN. `0x100`,
`0x200`, `0x400` identify drag begin/update/end. Native releases may combine
END with tap (`0x401`) or direction (`0x410`). **Every END suppresses
activation and clears drag state before the next independent tap.**
Pinch/cancellation bits `0x7000` also terminate ownership. Unknown packets
never synthesize confirmation. A coalesced BEGIN+UPDATE is applied once.

Each non-NULL caller event is forwarded once with all five original nullable
part pointers and bytes unchanged, including `one` and `five`. All eight
verified native picker inputs ignore the LCD part. Synthetic dial events have
only a four-byte signed dial payload, and synthetic confirms have only a
ten-byte key (`changed=1`, `press=1`, `touch=repeat=count=pad=0`). They are
stack-resident and delivered synchronously, never queued as pointers.
Nonzero physical key fields or either dial channel take priority over LCD;
NULL LCD updates preserve an active gesture.

Touch begins only inside the visible popup. Its horizontal extent matches
the native background painter, using primary font 5 and secondary font 4:

- Primary only, or secondary measured width zero: `(primary + 141) & ~1`.
- Nonzero secondary width: `(primary + secondary + 191) & ~1`.

The right edge is X1024; row height is 90; the descriptor's native Y and
`first_visible` select the actual row. Screen and viewport bounds are checked,
including partly visible bottom rows. Widths exceeding 1024 are rejected.
Outside taps do nothing; this adapter does not invent a cancel/pop action.

No adapter instruction writes the native descriptor. In particular it never
changes count, selected, committed, first-visible, disabled flags, language
data, or native pointers. Native input changes its own tentative highlight;
native painters change their own window. The disabled byte at +32's table
is tested before selection and again before confirmation. Nonzero means
disabled, so a disabled tap does not select, commit, or pop. Navigation may
pass over a disabled row just as the original dial does. This is separate
from the main Settings row flags: the native parent activation check
`(flags & 0x12) == 2` at `0x4d3373674..3684` remains the parent's responsibility.
No readonly row is made editable by this module. Picker +9 bit0 is a native
indicator flag, not the parent row's readonly bit; it is preserved, and
unknown picker flag bits reject touch synthesis.

There are at most 31 synthetic dial calls and one confirm per packet.
Selection must advance by exactly one each time; lack of progress, unexpected
progress, changed labels/mode/count, pending transition or changed depth
aborts confirmation. The code never applies a second explicit pop: family 6
must retain its native child transition. A pending transition blocks repeat
LCD confirmation. Parent lifecycle validation still matters for stale events.

## Explicit coverage gaps

This is a bounded compact-picker family adapter, **not “all stock menus.”**
Opening a Settings row with touch does not prove touch support inside that
child. The normal Settings dispatch at `0x4d3373648..38bc` reaches these
ten entry points; the table records this module's boundary, using stable row
indices rather than guessing untranslated label meanings.

| Normal Settings row | Child entry | Coverage in this header |
| --- | --- | --- |
| 0 | `0x4d337db20` | Child list/editor not adapted |
| 1 | `0x4d338a6e0` | Child list/editor not adapted |
| 2 | `0x4d3375da0` | Parent submenu not adapted; compact family callbacks alone are covered |
| 3 | `0x4d33814a0` | Parent submenu not adapted; compact family callbacks alone are covered |
| 4 | `0x4d3389130` | Family 7 compact picker covered |
| 5 | `0x4d33843e0` | Child list/editor not adapted |
| 6 | `0x4d338b0c0` | Child list/editor not adapted |
| 7 | `0x4d3379700` | Parent submenu/editor not adapted; family 1 compact picker covered |
| 8 | `0x4d3380000` | Parent submenu not adapted; families 2/3 compact pickers covered |
| 9 | `0x4d3384f40` | Three-row child submenu not adapted |

Further boundaries:

- The main Settings row list (`0x4d3373200`), BF+ submenu and BF+ owned
  pickers belong to `menu.h`; this module does not replace them.
- Alternate/service Settings uses table `0x4d7042d58` and flag
  `0x4d73025f4`; it is not covered by this adapter.
- Other row lists, multi-field date/time or numeric editors, grids,
  adjustment screens, confirmation/progress dialogs, and the child reached
  by family 6 need their own verified geometry, events and state semantics.
  Do not reinterpret them as this 48-byte picker type.
- Playback menus, live-view/cine/magnification overlays and capture controls
  are outside the inspected compact-picker boundary. No exhaustive scene
  inventory or touch coverage claim is made for those surfaces.
- Whole-camera rotation, compositor behavior, physical sensor direction,
  scratch allocation and transformed hit testing belong to the parent.
  This module only consumes canonical landscape coordinates.

## Evidence and offline validation

Local artifact: `decoded-V104/rtos-alt.bin`, base `0x4d3000000`, SHA-256
`f747c1350f00526b9c68c65aaef44d6e7b644b0169992342e12f059c42e150dc`.
Static inspection used the supplied `decoded-V104/analyze.py`/Capstone.
REA skill workflow was used; REA MCP tools were unavailable and the read-only
doctor reported missing/drifted registration. No registration repair or
analysis engine installation was performed. The ledger below uses local
evidence IDs, not REA server-issued IDs.

| Local evidence ID | Observation | Scope/limit |
| --- | --- | --- |
| NTM-01 | All 14 literal values equal the eight native input addresses | Exact supplied image; test reads original bytes |
| NTM-02 | Native input signed dial moves one row regardless of magnitude | Executed every input in Unicorn; setting services are intercepted |
| NTM-03 | Native center commit and all seven family-1 conversions | Original key tests and input instructions execute; setter calls/arguments are recorded |
| NTM-04 | Family 6 confirm stores its request and pushes child `0x4d3e89318` | Executes `0x4d3387bf0`; scene push service is intercepted |
| NTM-05 | Width rounding and native first-visible adjustment | Original background `0x4d3364750..4960` executes; font metrics and raster calls are intercepted |
| NTM-06 | Native 40px/200px drags release as `0x401`/`0x410`; next stationary tap is `1` | Executes producers `0x4d3246250`, `0x4d3246340`, `0x4d32464b0`; mutex/memory services intercepted |
| NTM-07 | Adapter preserves packets and never writes descriptors | Unicorn memory-write hooks reject writes from compiled adapter code |

Run only the isolated fixture:

```sh
.venv/bin/python -m unittest tests.test_native_touch_menus -v
```

**33 tests pass** with the local V104 image. Coverage includes all native
families, every mode-0 conversion, first-visible/language end rows, disabled
targets, original-producer releases, null/mixed/unaligned packets, physical
priority, viewport/width bounds, maximum 31-step selection, lost ownership,
mid-navigation changes/transitions, malformed metadata and pending/disabled
callbacks. Compilation uses the payload's freestanding AArch64/PIC flags,
checks allowed relative relocations, and runs from a relocated address.
Without the supplied firmware, the suite explicitly skips; it never fetches
firmware or opens hardware.

The isolated fixture is 2,196 initialized bytes / 2,248 resident bytes with
the available `-Oz` compiler, including fixture support and metadata. This is
an integration size estimate, **not a production payload budget result**.
It writes build artifacts only into a temporary directory and does not depend
on the shared builder passing its 16 KiB staging cap. Parent must verify its
final source snapshot, upload limit, installation/removal and orientation
pipeline after integration.

Unicorn establishes these instruction and event contracts, not actual camera
render scheduling, physical gesture timing, font rendering, cache coherence,
settings persistence, or whole-camera UI behavior. No hardware validation is
claimed.
