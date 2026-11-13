# Native image anchors and a bounded live-view split

The main image, hardware AF/face frames, and the verified composition grid
are separate from the CPU OSD. **The CPU OSD still contains image-coordinate
crosshairs, aspect-bound corners, and the electronic level.** Fitting the
entire mixed OSD moves those graphics away from the image.

`bfplus/ui_image_anchors.h` implements a bounded split for the photo and
cine **root live-view** callback families. It defers their native level and
center-marker painting, draws those anchors once on a cleared physical
surface, then lets the parent composite fitted UI over them. No third raster
buffer is required. This deliberately permits the rotated UI to occlude
anchors in its new positions. It does not promise the stock ordering between
an anchor and every background gradient in portrait.

Landscape bypasses the split and retains native ordering. Both entering and
leaving the split require a complete canonical rebuild. The header alone
does not install hooks, allocate buffers, select scene policy, publish banks,
or transform input. The parent owns those operations. No camera was used.

## Evidence identity and limits

Firmware: `decoded-V104/rtos-alt.bin`, SHA-256
`f747c1350f00526b9c68c65aaef44d6e7b644b0169992342e12f059c42e150dc`.
Code base is `0x4d3000000`. Initialized RAM bytes at file
`[0xebdfb0,0xf03e70)` belong at `0x4d7000000`; BSS cannot be read as a file
offset. Addresses below are full native virtual addresses.

Evidence comes from `decoded-V104/analyze.py`/Capstone, the existing
`.touch-focus/global-ui-rotation/render/` disassembly, and original-instruction
Unicorn execution in `tests/test_ui_image_anchors.py`. There was no hardware
I/O, installation, or observation of a running camera. Static call inventories
cover aligned direct B/BL instructions in the decoded code region; they do not
prove absence of computed calls or unclassified image-bearing scenes.

## Parent integration contract

The module's public API is in `bfplus/ui_image_anchors.h`. Use its
`UI_IMAGE_ANCHORS_BL_HOOKS(X)` table: **14 direct BL sites**, eight for level
painters and six for the center wrapper. There is no tail-B patch. The six
root callers of `0x4d339f070` discard its return; `defer()` nevertheless
preserves its value. The wrapper's internal tail B remains native.

The display worker must serialize the module. It takes no gate and holds no
lock across a native function. It expects the exact persistent canonical
surface descriptor actually passed to the callback, not a separate equal-valued
descriptor. The parent keeps one 32-byte descriptor per plane in UI state;
private backing surfaces are not captured. See the descriptor-lifetime audit
in [UI-IMAGE-PROFILES.md](UI-IMAGE-PROFILES.md).

1. At each job, call `select(state, last_actual_fg, last_actual_bg, epoch, raw)`
   **once**, before either plane. For a no-op use the verified current scene's
   pair. Unknown pairs and raw values other than 1/3 disable the split. A
   different pair or epoch revokes the clean-canonical certificate.
2. On first enable, a new pair/epoch, or re-entry after landscape, get the
   **family initial** pair with `bootstrap()` or `full_pair(fg,bg,out[3])`.
   Call `start_rebuild()`. Reset both canonical planes to transparent; do not
   seed them from a bank that contains native anchors.
3. Invoke each initial draw once, with `params=NULL,len=0`, bracketed by
   `begin(state, actual_canonical, background, epoch)` and `end(state, ok)`.
   At a listed native call, `defer(...)==1` supplies the original result and
   suppresses that invocation's drawing. Otherwise call the native target
   normally. A set `failed` flag invalidates the transaction.
4. After each reset/full draw succeeds, report
   `rebuilt(state,epoch,1<<background,ok)`. It is valid to paint FG while the
   worker is still preparing BG; **neither input geometry nor the completed
   frame may be published until both planes are ready and native bank
   selection succeeds**. `commit_rebuild(...,ok)` can certify a staged pair.
5. For each physical plane, call the parent's `global_orientation_clear`,
   then `paint(state,physical,background,epoch)`, then present canonical UI
   using `GLOBAL_ORIENTATION_FIT_OVER`. The parent owns RGB444/alpha4 and
   UYVY/alpha8 composition and destination chroma-pair repacking. Each plane
   may be painted only once per selected job.
6. Subsequent native partial jobs use ordinary capture brackets without a
   reset. No-ops need no native draw callback. `paint()` rechecks level
   visibility and root overlay flags every job; it refreshes a default
   level descriptor from native data. An explicit descriptor is copied as
   24 bytes and never retained by pointer.
7. **On exit**, retain the previous actual root pair long enough to call
   `full_pair()` independently of the now-disabled state. Reset both
   canonical planes and execute that full pair with deferral disabled.
   This restores native anchors before an identity no-op, an unsupported
   image scene, or a popup/backing capture inherits the underlay. Disabling
   the split without this rebuild leaves missing anchors. Entering it from
   native pixels without the opposite rebuild leaves rotated duplicates.

`full_pair()` selects these two initial pairs, regardless of which matching
regular callback caused the transition:

| Root family | Full foreground | Full background | Native evidence |
| --- | --- | --- | --- |
| Photo | `0x4d3394c90` | `0x4d33970b0` | Initial selection at `0x4d3394fb8..0x4d3394fcc`; submission at `0x4d3394f48` uses NULL/0 |
| Cine | `0x4d3391dc0` | `0x4d3390ad0` | Initializer literals `0x4d338eea8/0x4d338eeb0`; NULL/0 submissions `0x4d338ed40`, `0x4d33921ac`, `0x4d33922b4` |

Unicorn executes the four entry paths through their first drawing operation:
all construct a `0,0,1024,682` clear before their UI children. Photo foreground
uses `0x4d3325ca0` at `0x4d3394d0c`; photo background uses `0x4d3328cc0` at
`0x4d33970f0`. Cine uses full-clear helpers `0x4d332ba70` at `0x4d3391e38`
and `0x4d332ba20` at `0x4d3390afc`. **The regular callbacks are classifiers,
not the module's promised full redraw.**

Recognized actual pairs are:

| Foreground | Background | Family |
| --- | --- | --- |
| `0x4d3394c90` | `0x4d33970b0` | Photo |
| `0x4d33944d0` | `0x4d3393e00` | Photo |
| `0x4d33946c0` | `0x4d3397240` | Photo |
| `0x4d3391dc0` | `0x4d3390ad0` | Cine |
| `0x4d3390770` | `0x4d3390d20` | Cine |
| `0x4d3391b40` | `0x4d3391550` | Cine |

### Hierarchy and transition boundary

The getter proves a callback pair, **not that it is still the active scene**.
The parent must schedule a requested redraw only while native transition
state `u32[0x4d70346a4]` is idle 12, snapshot depth
`u32[0x4d70346a0]` plus its scene epoch, and reject publication if scene/depth
changes. Retaining a root pair after a popup becomes foreground does not
authorize replaying it. Do not queue another synchronous native draw from a
renderer callback; use the current worker transaction or the UI task's
existing redraw queue.

The native initializers also perform state/hardware work. The adapter exports
**draw callbacks only**; do not replay the initializer, input, update, or post
callback. Before a popup copies the native underlay, restore the mixed native
canonical pair as above. If the parent cannot intercept before that copy,
that transition remains a blocker: disable portrait splitting for that path
until its backing-copy lifecycle is handled. A later bank copy cannot recover
anchors absent from an earlier private snapshot.

## Native painter ABIs and full-paint evidence

| Painter/wrapper | Argument registers | Behavior and return |
| --- | --- | --- |
| `0x4d3367b40` | x0 surface, x1 descriptor or NULL, w2 mode | Foreground electronic level; mode0 returns 0 |
| `0x4d3368760` | Same | Background electronic level; mode0 returns `u8[0x4d7035bec]` |
| `0x4d339f070` | x0 surface | Current center-marker selection; returns aspect getter result except secondary state3 returns 0 |
| `0x4d335b5f0` | x0 surface | Image-position crosshair; returns 0 |
| `0x4d335b6f0` | x0 surface | Fixed center glyph; returns 0 |
| `0x4d339f1e0` | x0 surface | Queries aspect via `0x4d3320850`, tail-calls corner painter with style1; outside the root adapter |
| `0x4d335aef0` | x0 surface, w1 aspect, w2 style | Background aspect-bound corner strokes; outside the root adapter |
| `0x4d339f160` | x0 surface | Actual foreground marker painter, not an update predicate; outside the root adapter |

The level's 24-byte data at `0x4d7035be8` contains u16 x/y at 0/2,
orientation byte at 4, signed Q16.16 roll/current-history words at 8/12,
and pitch/current-history words at 16/20. Calibration getters are
`0x4d3322250/0x4d3322270`. Sensor sampling/update is a separate routine:
`0x4d33690d0 → 0x4d31e35b0`; **the adapter never calls it**.

Mode0 is the stock root mode, not an invented force-full flag. Both painters
clear the prior-orientation footprint, evaluate the current angles, emit
current glyphs/strokes, and update native hysteresis/orientation bytes
`0x4d730255e..0x4d7302561`. Native foreground and background order is retained.
No native state or descriptor is patched. On a freshly cleared physical
plane the old-footprint clear is harmless; fitted UI is composited afterwards.

The test executes the original painter and its libm for two painters, nine
roll/pitch/orientation combinations, and two initial history states. It
compares **every emitted primitive**, return, and changed history byte between
NULL/default and a copied descriptor. This is 36 comparisons / 72 painter
executions. Glyph rasterizers and calibration getters are explicit test stubs;
this verifies painter geometry and selection, not native atlas decoding.

The default descriptor refresh also lets a no-op present draw the current
anchor without replaying the native sensor updater. `0x4d3321530()==1` gates
the level. A photo root overlay (`u8[0x4d7303048]!=0`) omits its anchor
underlay. Cine root overlay flags at `0x4d7302fd3/2fd6/2fd7/2fda/2fdd/2fdf`
are treated the same way. Omission while an overlay is open is intentional;
it is not a claim to reproduce every native popup opacity choice.

### Center wrapper

`0x4d339f070` reads `u32[0x4d7043b70]`: state `0x11` calls crosshair
`0x4d335b5f0`; state `0xe` calls glyph `0x4d335b6f0`. Independently,
`u32[0x4d7043b74]==3` tail-calls the center glyph. The adapter calls the
original wrapper on the physical plane once per BG job, so native visibility
and the original tail call are retained.

The crosshair obtains physical image coordinates through `0x4d331d2a0`
at `0x4d335b610`, then emits four YUV rectangles through `0x4d3328cc0`:
`(x-18,y-4,36,8)`, `(x-4,y-18,8,36)`,
`(x-16,y-2,32,4)`, `(x-2,y-16,4,32)`.
Unicorn executes the actual rectangle rasterizer and verifies fresh-surface
pixel parity at `(512,341)` and `(300,200)`. The fixed glyph wrapper uses point
`(504,333)`, glyph index `0x12`; its exact visual meaning was not inferred
from the index alone.

## Hardware/image separation

| Element | Native chain | Evidence / policy |
| --- | --- | --- |
| Main live/playback image | `0x4d321df00 → 0x4d30806c0/0x4d3080910/0x4d3080e80` | Image layer1; leave image DMA and existing image orientation alone |
| Face/rectangle frames | `0x4d335c260 → 0x4d320bef0 → 0x4d3082920` | `IM_DISP_Set_Face_Frame`, MMIO frame registers; leave physical |
| AF frames | `0x4d335c270 → 0x4d320bb10 → 0x4d3082ca0` | `IM_DISP_Set_Af_Frame`; leave physical |
| Composition grid | `0x4d339d390 → 0x4d31ac970 → worker → 0x4d321b6d0/0x4d321ba40 → 0x4d3082430` | Hardware grid, outside CPU pixel callbacks; leave physical |

`0x4d3082430` is named `IM_DISP_Set_Grid` by literal
`0x4d3082730 → 0x4d3587ea0`. It programs base `0x16480000`, channel stride
`0x4000`, offsets `0x1600/1604/1608/160c/1610/1614/1618/1630`; enable is
`0x4d3082890`. `0x4d31ac970` submits command3 with four bytes. The grid UI
wrapper obtains native grid settings and the current aspect before submission.
Builders `0x4d321c0a0/0x4d321c370` also use this hardware grid; their exact
guide semantics remain unclassified. No CPU grid painter was established by
this bounded trace, which is not proof that every grid variant is hardware.

Foreground OSD uses layer4, RGB444+alpha4; background OSD uses layer8,
YUV422 plus alpha8. These formats and independent image/AF setup are recorded
in the prior `GLOBAL-UI-ROTATION-NOTES.md` and render disassemblies.

## Known image scenes outside the root adapter

`ui_image_anchors_unsplit_draw()` inventories the following callbacks so the
parent can keep them at native geometry. This list is not a pure-UI allowlist
for everything else.

| Callback category | Foreground / background | Anchor evidence |
| --- | --- | --- |
| Dedicated level screen | `0x4d338aa40 / 0x4d338a940` | Level calls at `0x4d338ab0c / 0x4d338a9e0` |
| Additional level overlay | `0x4d33a2230 / 0x4d33a2170` | Level calls at `0x4d33a22d4 / 0x4d33a2200` |
| Aspect/corner scene A | `0x4d33b3a30 / 0x4d33b38e0` | BG calls `0x4d339f1e0` at `0x4d33b39c8` or center wrapper at `0x4d33b39e8` |
| Aspect/corner scene B | `0x4d33b4820 / 0x4d33b4640` | BG calls `0x4d339f1e0` at `0x4d33b4710` or center wrapper at `0x4d33b4734` |
| Extended mixed scene | `0x4d33cd4b0 / 0x4d33cc230` | FG level, BG level+center |
| Extended partial mixed scene | `0x4d33cf410 / 0x4d33cc450` | FG level+aspect/center markers, BG level |
| Other mixed variants | FG `0x4d33d3bf0`, `0x4d33d4590`; BG `0x4d33d3200`, `0x4d33d3590`, `0x4d33d3650`, `0x4d33d3800`, `0x4d33d3970`, `0x4d33d4a50` | Direct native level and/or center-wrapper calls |

The two aspect/corner backgrounds branch on
`u32[0x4d33afed0()+0x30]` (`0x4d73033f0`): value1 uses the center wrapper;
otherwise they use `0x4d339f1e0`. This is an exact future split boundary.
The latter queries the current aspect and draws through `0x4d335aef0`.
`0x4d3269770` derives bounds from dimensions at `0x4d3cabc60`:
left `(1024-width)/2`, top `(682-height)/2`, with symmetric right/bottom.
Original-instruction probes produced left/top `(0,122)`, `(0,52)`, `(0,0)`,
and `(170,0)` for aspect indices 0,1,2,6. The resulting 16 corner strokes
must remain at those image bounds. They are **not a filled crop mask**.

`0x4d339f160` is a real FG painter. For state10 it calls
`0x4d335b340` (16 aspect-bound corner rectangles) and `0x4d335b790`
(four central-cross rectangles), and returns0. For other states0..18 it
does not paint and returns0; for states>18 it returns1 through the center
leaf's nonpainting return. It is not an updater that can be left drawing
inside fitted canonical UI. The only direct caller is `0x4d33cf8d0`, inside
the excluded `0x4d33cf410` callback, and that caller discards the return.
Its clearing companion `0x4d339f0f0` is called at `0x4d33cf998` in the same
excluded callback. Full direct-branch/literal scans found no other callers
or literal pointers to these wrappers. Computed aliases remain unproved.

Enabling these families needs their own native full-pair acquisition and
visibility policy. Merely adding their leaf to the hook table is insufficient.

## Masks, gradients, zoom overview and playback

No aspect-dependent **filled crop-mask** painter was positively identified.
The verified corner strokes cannot stand in for one. Main image setup has
its own output sizing/positioning, but that alone does not prove every crop
shade or mask is outside the OSD. This remains a bounded inventory gap.

There are definite CPU background masks/gradients:

- `0x4d332ba20(surface,color_or_NULL,len)` fills the whole BG canvas; NULL
  selects transparent `0x00808000`. `0x4d332baa0` fills opaque black.
- `0x4d332a0a0(surface,rect,color,end_alpha)` **replaces** YUV color and
  writes a row-varying alpha; it does not read/alpha-blend existing pixels.
  Descriptor-style helper `0x4d335c720`, style1, calls it at `0x4d335c754`.
- Photo BG `0x4d33970b0` calls the center wrapper at `0x4d3397144`, then
  may write a `(0,582,1024,100)` gradient at `0x4d33971cc` when
  `u32[0x4d730305c]==1`. Another root site is `0x4d3397454`.

These explain why unconditional post-UI anchor blitting is wrong. The agreed
`clear → anchors → FIT_OVER UI` policy instead lets fitted masks/labels occlude
physical anchors in their new UI coordinates. On popup scene changes the
root adapter resets/omits anchors, with the canonical restoration contract
above. Simply copying dirty-row bounds to a separate anchor plane would not
reproduce native rectangular clears, gradient replacement or backing copies.

The zoom overview is a **schematic viewport widget**, not a proven miniature
image buffer:

| Path | Concrete paint boundary | Findings |
| --- | --- | --- |
| Playback | FG `0x4d32e3600`, guide region `0x4d32e3618..0x4d32e3690`; BG `0x4d32e3b30`, region `0x4d32e3b4c..0x4d32e3b8c` | Clears `(822,510,184,124)`, draws outer/inset frame and viewport; no image pointer/copy in these regions |
| Live magnification | `0x4d33a0ab0`, called at `0x4d33a0d44` inside FG `0x4d33a0cb0` | Aspect outline at `0x4d33a0be8 → 0x4d3325f10`; viewport derives from image getter `0x4d331d2a0` at `0x4d33a0bf4` |

Playback producer `0x4d32e6a60` stores outer/viewport rectangles at
`0x4d7300a80+0/+8` and zoom step at+16, then submits that FG/BG pair at
`0x4d32e6c18`. Post callback `0x4d32e08f0` updates the sub-LCD indicator;
do not replay it for an OSD orientation request. The FG/BG callbacks also
clear the full OSD and paint ordinary status UI, so they cannot be suppressed
as whole functions to remove just the guide.

Moving the entire schematic frame+viewport together is different from moving
a crosshair off a real image coordinate. This trace establishes no need to
pin that widget to a specific physical main-image pixel. It does not establish
absence of a separately rendered miniature elsewhere. Playback/magnification
full-scene split profiles remain outside this header.

## Input domains

Keep native mixed-scene Event packets raw. Only classified UI hit sinks get
the inverse UI transform. The header contains no input transformation.

| Sink | Native evidence | Policy |
| --- | --- | --- |
| Common UI icon tests | `0x4d3367530 → 0x4d33235e0` | Map the private UI hit-test packet |
| Live physical focus | `0x4d3398bec/0x4d3398c80 → 0x4d339fb50`; drag `0x4d3398c90 → 0x4d339fbd0 → 0x4d331d5d0` | Keep raw |
| Post-icon live/cine fallthrough | XY loads `0x4d3398e4c/0x4d3398e50` and `0x4d3393188/0x4d339318c → 0x4d339fb50/0x4d339f620` | Keep raw; these bypass a generic rectangle UI sink |
| AF-area editor | Input `0x4d33af690`; tap XY `0x4d33af894/0x4d33af898 → 0x4d339faf0 → 0x4d331d5d0` at `0x4d33af8d4`; drag current XY `0x4d33af800/0x4d33af808 → 0x4d33afb90` subtracts23 per axis | Keep raw despite being an editor scene |
| Playback image pan/zoom | `0x4d336b810 → 0x4d3359af0 → 0x4d3359530 → 0x4d32f5710` | Keep raw image gesture ownership |
| Movie tap play/pause | `0x4d336f7d0`, LCD Event+16 read at `0x4d336f7dc`, flags1 at `0x4d336f7ec` | No XY loads in the traced handler; not a seek-bar hit box |
| Movie seek | `0x4d336f2a0`, `0x4d336cba0 → 0x4d32f5960` | Signed dial commands, not LCD coordinates |

Movie progress painter `0x4d336f570` computes width from playback time over
duration; that does not establish touch scrubbing. The bounded input search
covered 79 flag-helper callers and paired-halfword reads in
`0x4d3330000..0x4d33d0000`; it found no additional proven UI-coordinate sink
in these traced live/playback routes. This is not exhaustive dynamic coverage.

## Verification and remaining work

Run:

```sh
.venv/bin/python -m unittest discover -s tests -p test_ui_image_anchors.py -v
```

Seven tests passed. They cover routing/returns, descriptor lifetimes,
visibility and no-ops, private-surface rejection, unknown mode/reentry failure,
identity/epoch reacquisition, firmware BL target bytes, original level painter
and libm emissions, original center-wrapper decisions, initial full clears,
actual crosshair raster pixels, and the excluded FG marker wrapper/leaf return
paths. The parent must separately verify FIT_OVER pixels, native queue/bank
transactions, active-hierarchy checks, and restoration before popup backing
capture. These tests do not claim hardware visual validation or completion of
all image-bearing scenes.

The bounded deliverables are `bfplus/ui_image_anchors.h`,
`tests/test_ui_image_anchors.py`, and this document. Row, compact-picker,
payload, build, global compositor and parent integration files were not edited
by this assignment.
