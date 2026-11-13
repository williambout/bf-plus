# Native image-anchor and playback UI profiles

`touch_focus/ui_image_profiles.h` extends the root image-anchor adapter with
two aspect-corner scenes, the dedicated level menu, normal live AF and bounded
S2/overlay recipes with verified inherited bases,
and inventories verified UI-only playback painters.
It reuses `UIImageAnchors` and its capture, epoch, rebuild and publication
contract. It supplies a small value-only style snapshot; the parent owns its
transaction and publication. It adds no framebuffer, raster, locks, input
rewrite or native descriptor mutations. See [UI-IMAGE-ANCHORS.md](UI-IMAGE-ANCHORS.md) for the
root split and FIT_OVER contract. No camera or USB was used.

Evidence is BF 1.04 `decoded-V104/rtos-alt.bin`, SHA-256
`f747c1350f00526b9c68c65aaef44d6e7b644b0169992342e12f059c42e150dc`,
local `decoded-V104/analyze.py` disassembly and original-instruction Unicorn
tests. Code base is `0x4d3000000`; initialized RAM file range
`[0xebdfb0,0xf03e70)` maps at `0x4d7000000`. The companion test file is
`tests/test_ui_image_profiles.py`.

## Corner profiles and native full pairs

| Family | Initial/full FG | Regular FG | BG | Original input / update |
| --- | --- | --- | --- | --- |
| 3, corner A | `0x4d33b3ce0` | `0x4d33b3a30` | `0x4d33b38e0` | `0x4d33b3eb0 / 0x4d33b33f0` |
| 4, corner B | `0x4d33b5070` | `0x4d33b4820` | `0x4d33b4640` | `0x4d33b4cf0 / 0x4d33b4c40` |

Native initializers submit A at `0x4d33b3778` and B at `0x4d33b4b74`,
with `x1=NULL,w2=0`. Literal pairs are respectively
`0x4d33b37d0/37d8` and `0x4d33b4bd0/4bd8`. Their native third callback is
`0x4d332bae0`; the extension exports a zero third callback so orientation
acquisition does not replay a post callback. Do not call the scene initializer
or updater for an orientation change.

Both initial FG entries clear `(0,0,1024,682)` before widgets. The regular
FG callbacks are partial and are **not** rebuild substitutes. Each BG first
paints `(0,0,1024,608)` transparent and `(0,608,1024,74)` opaque black,
covering the complete canvas before its children. Tests execute these original
instructions, then execute the complete initial draw callbacks with actual
rectangle rasterization on both zero-filled and `0xa5`-filled surfaces. The
outputs agree for the exercised selector states. Font/status children are
explicit stubs in this acquisition test; it does not verify atlas rendering.

The extension lists initial pairs first, matching the parent's first-pair
normalization. Classification must recognize the initial FG as well as the
regular FG. Match the complete FG/BG pair before acquisition; never combine
A foreground with B background or infer current hierarchy from an old pair.

Four added direct BL hooks cover both wrappers:

| Call site | Target |
| --- | --- |
| `0x4d33b39c8` | `0x4d339f1e0` |
| `0x4d33b39e8` | `0x4d339f070` |
| `0x4d33b4710` | `0x4d339f1e0` |
| `0x4d33b4734` | `0x4d339f070` |

Each wrapper has ABI `uint32_t wrapper(void *surface)`. Their nested tail
branches remain untouched. All four callers discard the wrapper return;
tests inject `0xfeed` and the complete BG callbacks still return zero.
Deferral nevertheless preserves the exact value: corner wrapper returns0;
center wrapper returns the aspect getter except secondary state3 returns0.

Both BG functions unconditionally reach exactly one wrapper after their UI
children, including when their countdown fields are nonzero. The native
selector is `u32[0x4d73033f0]`, obtained via `0x4d33afed0()+0x30`:
value1 selects center wrapper `0x4d339f070`, all other values select corner
wrapper `0x4d339f1e0`. Physical paint reads it again every job/no-op and calls
exactly one original wrapper. There is no FG anchor in these two profiles.

`0x4d339f1e0` reads the aspect getter and calls
`0x4d335aef0(surface,aspect,1)`. This is a complete sixteen-stroke paint,
returns0 and does not require previous pixels. Tests execute its actual YUV
rectangle rasterizer and verify exact wrapper-versus-leaf pixel equality for
aspects0,1,2,6, with observed left/top bounds `(0,122)`, `(0,52)`, `(0,0)`,
`(170,0)`. The corners remain at the physical image bounds. They are not a
filled crop mask.

## Root adapter extension seams

Include `ui_image_profiles.h` **before** `ui_image_anchors.h`.
The five required seams are small and preserve the existing API:

1. Append `UI_IMAGE_ANCHORS_EXTRA_PAIRS` to `ui_anchor_pairs`, after the six
   root rows. The existing `family_for_draw()` and `select()` then recognize
   both corner families without separate state.
2. After complete pair validation in `full_pair()`, before the photo/cine
   ternary, use
   `if (ui_image_profiles_full_pair(family,draw)) return 1;`. Reject families
   other than1/2 before the root fallback. Families9/10 deliberately return0:
   their initial pair alone cannot certify a clean complete scene.
3. Inside `defer()`, **after** the canonical capture/surface/failure guard,
   use `ui_image_profiles_defer(a->family,a->plane,fn,native_result)` before
   the root target cases. Never invoke this helper as an unguarded global hook.
4. In `paint()`, after the clean-plane/epoch/once-per-job checks and setting
   the painted bit, return `ui_image_profiles_paint(...)` when
   `ui_image_profiles_is_split(a->family)`. This precedes root level/popup
   logic: corner scenes must not acquire the cine level or cine overlay gates.
5. Expand `UI_IMAGE_ANCHORS_EXTRA_BL_HOOKS(X)` at both installation and island
   dispatch. Recognized complete corner pairs override the older root-only
   `unsplit_draw()` inventory. Unknown mixed pairs still fail closed.

The parent has integrated these seams. The host test includes both actual
headers and verifies initial/regular classification, full-pair selection,
unclean-seed rejection, private-surface exclusion, per-plane certification,
once-per-job paint, no-op selector refresh, identity exit, epoch invalidation,
and reentry rejection. The profile header cannot independently authorize
paint: calling it outside the root guards violates its contract.

For the independent families, both split entry and exit require full canonical rebuilds. On entry,
clear both canonical planes and draw the family full pair under deferral.
On exit, rebuild the full pair with deferral disabled while the old hierarchy
is still current. Clear physical, paint anchors, then FIT_OVER the canonical
UI. Seeded pixels containing old anchors are never an acquisition shortcut.
The inherited9/10 identity rules below supersede this exit sequence for them.

## Dedicated level menu, profile 7

The parent-owned level extension is a normal stock menu: root input
`0x4d33736b0` calls `0x4d338b0c0`, which pushes descriptor `0x4d3e893f0`.
Its full pair is FG `0x4d338aa40`, BG `0x4d338a940`, with NULL/0 parameters.
Native initial submission is `0x4d338ac04`. Full clears are reached at
`0x4d338aaa8 → 0x4d332ba70` and `0x4d338a9bc → 0x4d332ba20`.

Two BL hooks defer FG `0x4d338ab0c → 0x4d3367b40` and BG
`0x4d338a9e0 → 0x4d3368760`. Both use mode5 and descriptor
`0x4d7043920`. Mode5 fixes y at322, regardless of descriptor y. BG is always
visible; FG is visible only when `u32[0x4d7043904]==1`. Each physical paint
copies the current 24 descriptor bytes, preserving angles and history.
FG returns0; BG returns the native orientation byte at `0x4d7035bec`, even
with an explicit descriptor. Never replay initializer `0x4d338ab50`, which
samples the sensor and changes descriptor/history state.

The parent's `test_ui_level_profile.py` has three passing tests, including
72 original mode5 executions comparing default/native and copied descriptor
pixels, full-clear calls and host visibility/current-descriptor behavior.
The extension contained five pairs and six BL hooks at the profile7 boundary;
profile8 expands that to seven pairs and twenty BL hooks.

## Normal live AF, profile 8

These are normal user paths, not service-only callbacks. Stock root descriptor
`0x4d3e89760` initializes through `0x4d338e070 → 0x4d338cf00`. When
`0x4d33252e0()` returns1, the dispatcher copies descriptor `0x4d3564de8`
through `0x4d33d2960`. Its initializer `0x4d33d16e0 → 0x4d33cfc60`
installs input `0x4d33d16f0` and update `0x4d33cddf0`. The firmware labels
include `uI_LV_S1_WaitAFDone`, `WaitAFInitDone` and `AFSelect_Sync`.

| Role | FG | BG |
| --- | --- | --- |
| Full acquisition | `0x4d33cd4b0` | `0x4d33cc230` |
| Regular partial | `0x4d33cf410` | `0x4d33cc450` |

The full pair is queued at `0x4d33cff98`, with a one-byte argument from
`0x4d3399670()`. FG ignores its parameters. BG **unconditionally copies
one byte from x1**, then never reads that copied value. NULL/0 is invalid.
`ui_image_profiles_rebuild_params(8,&length)` returns a resident immutable
zero byte and length1, suitable for both full callbacks. Other profiles return
NULL/0. The parent must use this helper for both split entry and exit. It
must not retain the native worker's job/stack argument. Post callback
`0x4d33cd220` is not replayed.

Both full callbacks clear the complete 1024×682 surface. Original-instruction
tests verify identical results from zero and dirty seeds and parameter bytes
0/255, while explicitly stubbing status/font children. The BG NULL/0 probe
faults at its required read. The full FG may expire the native timer at
`0x4d73037d0`; it is a full acquisition callback, not a per-frame pure leaf.
Never replay partial FG `0x4d33cf410` for acquisition: its branches include
AF synchronization, waits and state changes.

Fourteen added BL hooks cover all direct level and marker calls in this pair:

| Target | Call sites (all prefixed `0x4d`) |
| --- | --- |
| FG level `3367b40` | `33cd604`, `33cd674`, `33cd688`, `33cfad4`, `33cfae8`, `33cfb94`, `33cfba8`, `33cfbbc`, `33cfbd0` |
| BG level `3368760` | `33cc410`, `33cc59c` |
| BG center `339f070` | `33cc2e4` |
| FG marker `339f160` | `33cf8d0` |
| FG marker clear `339f0f0` | `33cf998` |

All eleven level sites pass x1=NULL,w2=0. The physical painter therefore
refreshes a 24-byte value copy from default descriptor `0x4d7035be8` each job,
and paints levels only when `0x4d3321530()==1`. BG center is unconditional;
its wrapper rechecks the current native selector. Profile8 handles its own
physical paint before root/cine popup gates, so cine flags do not hide AF UI.
A different hierarchy scene invalidates selection as usual.

Anchor order is deliberate: AF BG calls center before level, matching
`0x4d33cc2e4` before `0x4d33cc410`. All six photo/cine BG callbacks call their
level child (`0x4d3393be0` or `0x4d3390070`) before center, so the original
root adapter's level-then-center order remains correct.

FG marker paint is selected only in AF substate `u32[0x4d73037c4]==2`.
The native partial callback reaches the clear/paint pair for dirty mask
`0x120`; zero-dirty/no-op jobs retain that policy. Original-instruction probes
cover substates0..4 and masks0,0x20,0x100,0x120. The wrapper itself paints
only selector `u32[0x4d7043b70]==10`: sixteen aspect-bound FG strokes via
`0x4d335b340` and four central strokes via `0x4d335b790`. Actual RGB444 pixels
match those original leaves for aspects0,1,2,6. It returns0 for selectors0..18
and1 for larger unsigned selectors; clear wrapper `0x4d339f0f0` returns0.
Both native callers discard the result, but deferral preserves it exactly.
No marker tail branch is patched.

## Retained-base S2 and overlay, profiles 9 and 10

These are ordinary live-view states. Root state2 with `!0x4d32450d0()` chooses
S2 descriptor `0x4d3e8b9c8` through `0x4d338cfcc → 0x4d33d41a0`.
Overlay10 descriptor is `0x4d3e8a9e0`. These replace the root-dispatched
slot; they are not automatically descendants of the last root painter.
The parent must prove the old-base handoff and invalidate it on unknown
image-bearing transitions or command0. A previously seen callback is not
adequate provenance.

| Family | Initial FG / BG (NULL/0) | Actual partial callbacks |
| --- | --- | --- |
| 9, S2 | `0x4d33d3b50 / 0x4d33d3200` | FG `0x4d33d3bf0`, `0x4d33d2a10`; BG `0x4d33d3590`, `0x4d33d3650`, `0x4d33d3800`, `0x4d33d3970` |
| 10, overlay | `0x4d33a23b0 / 0x4d33a2120` | `0x4d33a2230 / 0x4d33a2170`, four-byte dirty mask |

S2 initial BG clears the entire1024×682 canvas. Its FG retains most of the
previous scene. Overlay10 initial FG clears top52 and bottom100; initial BG
clears only top52. Neither pair is a standalone full redraw.

`base_mask(family)` and `accepts_base(family,base)` allow only published,
proven base1/photo,2/cine or8/AF. Unknown base stays at native geometry.
`rebuild_step(family,base,plane,index,&step)` returns bounded steps:

| Family/plane | Ordered steps after one canonical reset |
| --- | --- |
| 9 FG | base full FG, S2 initial FG |
| 9 BG | S2 initial BG |
| 10 FG | base full FG, overlay initial FG |
| 10 BG | base full BG, overlay initial BG, extracted bottom gradient |

`UIImageProfileStep` contains `fn`, resident `params`, `length`, and the
step's `family`. Pass that family as the capture context, so AF/base anchors
are deferred according to their own ABI. AF uses the resident byte described
above; other native steps use NULL/0. The last overlay BG step is a local
ABI-compatible pure adapter: if `0x4d331eb10()!=5`, invoke
`0x4d332a0a0(surface,{0,582,1024,100},0x00808000,0x12)`. The native leaf
writes pixels and surface dirty bounds; it does not write native globals.

Never replay `0x4d33a2230` as a rebuild: even mask0x100 can consume
`0x4d73031f4` and call `0x4d331da90`. Likewise, do not replay S2 partials,
timers, random-state producers or level updater `0x4d33690d0`. Actual partial
jobs execute once after acquisition with their original arguments. Only an
actual callback exactly equal to the relevant initial step may be consumed
by that same acquisition. Initial UI constructors can update renderer caches
(for example `0x4d33602d0`); they are not described as globally write-free.

### S2 style snapshot and six alpha hooks

`UIImageProfileStyle` stores `producer`, `random_height`, `alpha`,
`level_mode`, `valid`, and `phase`, never native argument pointers. Stage a
copy before each actual S2 BG job using `style_begin()`. Observe the listed
alpha calls using `capture_alpha()` before deferral or original forwarding,
even in landscape. Save actual level mode through `style_level()`.
Publish only after the complete native frame succeeds. Do not alter this
snapshot during synthetic reconstruction. Scene changes discard it; rotation
and partial `0x4d33d3590` retain it. First entry can initialize producer3200
when acquisition consumes that exact native initial callback.

| Producer | Captured field | BG level mode |
| --- | --- | --- |
| `0x4d33d3200` | initially transparent, valid without alpha hooks | 0 |
| `0x4d33d3590` | retains previous field producer | actual0/1 |
| `0x4d33d3650` | alpha25, native random-height ramp to76, remaining rows76 | 3 |
| `0x4d33d3800` | whole-screen alpha76 or255 | 2 or1 |
| `0x4d33d3970` | top582 alpha0, bottom gradient remains UI | 0 |

The random ramp uses the **old** `0x4d73037f0` byte before the level painter
updates it. Capture the actual rectangle; deriving height afterward from that
byte is wrong. S2 consumes the BG level return to update that byte. Preserve
the real `u8[0x4d7035bec]` return when deferring it. Modes1/2/3 change opacity
and icon policy; they are not force-full flags. `level_mode_valid()` accepts
S2 FG0/BG0..3, overlay FG0/BG4, and the existing independent-family modes.

| Exact BL site(s) | Target and ABI |
| --- | --- |
| `0x4d33d36c8`, `0x4d33d3724`, `0x4d33d3854`, `0x4d33d38f8`, `0x4d33d3998` | `0x4d332a8c0(surface,u16 rect[4],u32 alpha)` |
| `0x4d33d36ec` | `0x4d332aba0(surface,u16 rect[4],u32 firstAlpha,u32 lastAlpha)` |

These six callers discard x0; the enclosing callbacks return0. The raster
leaves' own return values are unspecified. `defer_alpha()` supplies0 only
for these caller hooks under the parent's exact canonical-surface, family,
epoch and failure guards. Do not globally intercept either raster entry.
The bridge forwards all four argument registers. `0x4d33d38f8` passes -1;
capture masks alpha to8 bits exactly as native does.

The ramp leaf does **not clip**. With the tall level orientation, height is
548..560 and the200-row ramp overruns a682-row allocation. This is observed
in original instructions and guard bytes. `alpha_original()` is mandatory
also when a known S2 canonical call cannot be deferred, including missing-base
landscape. It keeps the original200-row fixed-point slope and rounding, groups
equal-alpha visible rows, and invokes original fill on bounded rectangles.
The short438..480-height ramp executes the original gradient once. No extra
framebuffer or replacement rasterizer is introduced.

### Portrait and identity presentation

Portrait9/10: clear physical, call
`paint_inherited(family,base,bg_mode,style,physical,plane)`, then FIT_OVER the
canonical UI. It paints captured S2 field, current center, and current level
once. Native level descriptor bytes are copied fresh. The sensor/update
predicate is not replayed; the level painter's normal renderer-cache writes
still happen once. S2 center requires both a producer other than3200 and
`u8[0x4d7303820]!=0`; partial3590 does not resurrect a center removed by3200.
Overlay10 uses mode4 and inherited center policy. New portrait UI occlusion
at fitted coordinates is intentional.

Raw0 S2 BG requires **identity copy of canonical colors followed by
`finish_identity_bg(9,base,bg_mode,style,physical)`**. Skip the ordinary
underlay/OVER operation for that plane. Native alpha overwrites retain UYVY
colors, including colored BG widgets. Neutral physical mask plus canonical
OVER would compute `A+C*(1-A)` and double opacity; erasing canonical alpha
instead would discard those widgets. The finish preserves native order:
alpha field, center when present, level or histogram, conditional glyph
`0x4d3362e30`, then the appropriate bottom gradient. It replays no random,
timer or sensor producer. FG and overlay10 continue using their normal
identity composite.

`paint_underlay(owner,base,style,physical,plane)` supplies ancestor mask/AF
marker only, without center/level, for a separately verified child policy.
`finish_identity_underlay(9,base,style,physical)` supplies the identity alpha
and post-mask glyph/gradient, with no parent center, level or histogram. A
child must execute its own verified BG paint afterward. These helpers do not
authorize arbitrary child replay or infer ancestor provenance.

### Inherited marker erasure

Painting the full AF marker after an overlay would resurrect erased corners.
For base8, physical FG marker paint is followed by the native zero fills
intersecting it, before the new level. Overlay10 masks top52 and bottom100;
the latter merges the five actual slot6..10 rectangles, identical for both
native layouts. S2 masks its fixed left/right top regions and the applicable
conditional status clears. The header uses original getter values and
`0x4d3354940(1,0x4d339ed90(),1)` for those conditions. Original helper
`0x4d33540c0` and all seven aspect tables validate the resulting erasure.

BG center is not always fixed at the middle: selector17 delegates to
`0x4d335b5f0`, reading user image XY through `0x4d331d2a0`. Overlay10 therefore
also erases center strokes in top52 and, when its gradient is active,
bottom100, using native `0x4d3328cc0` transparent color, before level4.
The canonical gradient then supplies its own fitted UI. Native edge-cross
tests exercise top, boundary, middle and bottom positions.

The extension now exports14 pair identities and37 exact BL hooks. The parent
separately owns profile11 and its hooks; it is not counted here.

## Acquisition call graph and descriptor lifetime

The test walks resolved control flow from the four root full painters, four
corner full painters, two AF full painters and four S2/overlay initial
painters (14 roots). It follows direct calls and
branches, bounded switch tables, 25 glyph getters, two sprite getters, the
two 11-entry icon painter tables, and five photo/cine state callbacks. No
resolved path reaches synchronous draw queue `0x4d3322d90`.

This is not a closed whole-program proof. Twelve unresolved indirect sites
remain in library formatting, locale, allocation and error paths:
`0x4d30067cc`, `0x4d300680c`, `0x4d30068cc`, `0x4d300dbcc`,
`0x4d300e054`, `0x4d301ceac`, `0x4d301d3c4`, `0x4d3021b60`,
`0x4d3021b9c`, `0x4d3022300`, `0x4d302251c`, `0x4d30225f0`.
The test rejects indirect sites outside that declared frontier. Cine's state table at `0x4d70439d8`
uses shipped initialized-RAM values; arbitrary runtime replacement is not
proved absent. Neither scene initializers nor post callbacks are audited as
safe redraw substitutes.

The stock draw worker passes global surface descriptors at `0x4d31ad2a4`
and `0x4d31ad30c`, not local descriptor copies. Only its parameters are on
the worker stack. An exhaustive proof that every child never retains a
surface alias is unavailable. The parent consequently keeps two persistent
32-byte canonical descriptors in UI state, copies local state into them
before native paint and back afterward, and uses that **same persistent
pointer** for anchor/row capture and the native callback. This addresses
descriptor lifetime without allocating another framebuffer.

## Playback controls: ordinary FIT, raw image gestures

`ui_image_profiles_ui_for_draw(fn,plane)` identifies the following bounded
UI-only inventory. It is separate from the split pair table: it does not
authorize a native redraw, sensor update or timer replay. A NULL native plane
callback means retain that plane, not replace its scene identity with zero.

| UI class | FG callbacks | BG callbacks |
| --- | --- | --- |
| 5, movie controls | `0x4d336cb50`, `0x4d336eaa0`, `0x4d336f570`, `0x4d336c330`, `0x4d336cc80`, `0x4d336cda0`, `0x4d336efd0`, `0x4d336e640` | `0x4d336c1b0`, `0x4d336c2c0`, `0x4d336c230`, `0x4d336e1f0` |
| 6, playback zoom overview | `0x4d32e3600` | `0x4d32e3b30` |

Movie initial submission is `0x4d336d0dc` (and `0x4d336f484`), selecting
`0x4d336cb50 / 0x4d336c1b0`. Timer/update `0x4d336f9a0` submits retained
partial callbacks at `0x4d336fb40`, including `0x4d336eaa0`, `0x4d336f570`,
`0x4d336c330`, `0x4d336cc80` and `0x4d336cda0`. **It is an updater, not a
draw callback.** Modal control submissions select `0x4d336efd0 / 0x4d336c2c0`
at `0x4d336c69c`, and `0x4d336e640 / 0x4d336e1f0` at `0x4d336c6f4`.

The movie progress painter `0x4d336f570` clears UI bands
`(0,624,1024,6)` and `(0,630,1024,52)`, then computes progress width from
`0x4d3055b30()` divided by duration `0x4d304da30()`. Native probes verify
widths0,256,1024 for 0%,25%,100%, and width0 beyond range. The dimensions
depend on playback time, not image position. Labels, status glyphs and the
progress band can rotate/fit together without an image-anchor split.

The playback zoom overview clears `(822,510,184,124)`, paints its outer
rectangle, an inset by2 on every side and the viewport rectangle from
`0x4d7300a80`. The original foreground instruction probe verifies all five
rectangles including the full canvas clear. This is a schematic widget,
not an image buffer copied into the OSD. Moving its complete frame and
viewport together is valid UI fitting. Keep the main playback image layer
and native image pan/zoom coordinates unchanged.

Movie tap input `0x4d336f7d0` reads LCD flags, not XY; its any-location
play/pause semantics remain native. Dial seek handlers remain dial commands.
Still-image pan routes through `0x4d336b810 → 0x4d3359af0 → 0x4d3359530`;
do not inverse-map the whole Event. Corner A/B tap UI paths use the already
classified common icon sink `0x4d3367530` at `0x4d33b3fdc` and
`0x4d33b4dd4`; their input packets also stay native. This is a bounded
call-path inventory, not exhaustive dynamic input coverage.

## Hierarchy drain and backing-copy boundary

The parent drains/restores before the BL at `0x4d3323a74` to hierarchy worker
`0x4d3323ca0` (LR=`0x4d3323a78`). The native pending predicate at
`0x4d3323c50` is:

```c
u32_at(0x4d703469c) != 12 || (int32_t)u32_at(0x4d70346a4) <= 11
```

Checking only the latter target word misses root/unwind requests.
`0x4d3324370` writes the former at `0x4d33243b8/43e8`, without writing
the latter. Original-instruction tests verify both words, including the
signed comparison. Restoration must complete before native suspend/leave
and initializer callbacks, not after the worker returns.

Static tracing establishes that this drain is early enough for all ten
normal child-open paths in root input `0x4d3373200`. Their openers tail-call
`0x4d3324110`, which copies a **32-byte scene descriptor**, then sets pending;
it does not copy pixels or invoke a painter. The backlight opener additionally
clamps/stores its picker y first. Menu-back
`0x4d337374c → 0x4d33731e0 → 0x4d338e1d0 / 0x4d336bdb0 → 0x4d3324180`
also only stages the transition. The worker's suspend call at
`0x4d3323de8` and new initializer call at `0x4d3323ea4` follow the drain.

All five direct root-request callers of `0x4d3324370`
(`0x4d332b89c`, `0x4d338c3dc`, `0x4d338c74c`, `0x4d338cb8c`,
`0x4d338e19c`) likewise perform no pixel capture. Their queued UI callback
execution at `0x4d3323bc8` returns to the pending check, then reaches the same
drain before leave/init callbacks. This is static call-path evidence.

The inspected private canvases are freshly painted backing, not snapshots:

- Root `0x4d33726d0` paints rows into `0x4d7042ec0`; memcpy at
  `0x4d3372790` copies private rows into callback canvas at y52, height630.
  Initializer clears private pixels at `0x4d3372e9c/0x4d33730f8`.
- Settings FG `0x4d337d180` copies only a 32-byte surface descriptor at
  `0x4d337d3b0`, replaces its pixels pointer with `0x402972800` and its
  height at descriptor+0x14 with3105, then paints private rows. Pixel copy
  `0x4d337d28c` reads private scroll offset and writes callback y142,height540.
- BG `0x4d337d4b0` does the same at `0x4d337d69c/0x4d337d6c4` with pixels
  `0x402f83000`; pixel copy is `0x4d337d5b8`. These painters are queued by
  child initialization `0x4d337e660 → 0x4d337e4c0 → 0x4d337e5d8`, after
  the hierarchy drain.

This verifies ordinary menu push/back/root-request transitions. Alternate or
debug actions `0x4d31c6060/0x4d31d3b20` remain separate scope. It does not
prove that every private canvas is freshly painted or every scene switch
passes through this worker.

Standard playback crosses tasks: `0x4d31a3800/0x4d31a38b0` enqueue mode3/2
through `0x4d330f410 → 0x4d3313110`. SysSts worker `0x4d3313ec0` dispatches
mode3 to `0x4d3312a10`, then `0x4d33245f0` queues UI callback
`0x4d336bd90`, which stages descriptor `0x4d3e880f8`. Mode2 uses
`0x4d3312d30 → 0x4d33244d0 → 0x4d338e0e0 → 0x4d338e19c`.
Both reach the existing UI hierarchy drain before new initialization.

Some shared values change before that drain. Mode3 clears
`u32[0x4d70345f8+12]`, which old root full painters read when choosing
status-widget variants `0x4d3366f40/0x4d33668b0`. Conditional display0/1/5
messages may also precede the UI queue; inspected OSD command7 retains the
existing buffers and does not replace/replay stored native painters. These
findings do not establish invalid descriptors, backing corruption or unsafe
old-scene lifetime. The restoration contract redraws **current native
values**, so exact reproduction of an earlier status-widget frame is not
required. No additional early enqueue hook/hold is justified by this evidence.

For future task-gated work, the UI_EVT task ID is `u32[0x4d730190c]`
(`0x4d7301890+0x7c`). Record `0x4d3575528` has enum0x6e and entry
`0x4d3323a00`; task creation stores into `0x4d7194d50[enum]` at
`0x4d3031460/1464`, and publication `0x4d303241c..2454` copies starting at
enum0x4f. `0x4d3033ce0(uint32_t *out)` writes current task ID and returns0;
its return value is not the ID. This audit does not add a task-ID hook.

## Validation and remaining scope

Run `.venv/bin/python -m unittest discover -s tests -p test_ui_image_profiles.py -v`.
Twenty tests pass. New coverage includes the bounded base/step/style contract,
14 original S2 mask/identity cases with every canvas byte compared on colored
seeds, original overflow versus safe guard bytes, native level return handling,
extracted gradient pixels/dirty bounds,84 conditional AF erasure cases,
seven overlay marker cases,14 dynamic crosshair edge cases, and original
overlay slot geometry for both layouts. The call-graph audit now covers14
roots. These supplement the earlier lifecycle, AF dispatch, native marker,
corner raster and dirty-seed tests.

Formatting/fonts/status/center/level boundaries are explicitly stubbed in the
named composition probes; actual alpha, gradient and rectangle rasterizers
run unchanged. Native center/marker pixels are exercised in their separate
tests. The composition tests do not claim full font-atlas or whole-firmware
pixel identity. FIT_OVER conversion, bank publication, base provenance and
hierarchy integration remain the parent's tests. No hardware visual validation
was performed.

Release overlay `0x4d33d4590/0x4d33d4a50`, descriptor `0x4d3e8b9e8`, is a
normal release-control child, not a diagnostic. It initializes with four bytes
of -1 and neither callback fully clears. FG consumes native flags and can
change timestamps, so this extension exports **no full replay recipe** for it.
The parent owns its separately proved retained-clean-parent acquisition and
three hooks. This header supplies only the ancestor underlay helpers.

Actual magnification is distinct: descriptor `0x4d3e8a9c0`, pair
`0x4d33a0cb0/0x4d33a1590`. A read-only audit closed35 UI functions and four
finite switches without a known image-anchor leaf. Its navigator is a small
UI schematic; its post `0x4d33a1010 → 0x4d322dfd0` targets the160×80
secondary status LCD (`SLCD_Task`), not main OSD. This extension does not
replay that post or add the magnified pair to its split registry. Unknown
callbacks are not classified as UI-only by default; native image-pan input
packets remain unchanged.
