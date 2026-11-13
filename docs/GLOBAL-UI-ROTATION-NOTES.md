# Global UI portrait investigation — BF 1.04

> Historical experiment: the user requested removal of automatic UI rotation
> and LCD menu controls. These adapters are unlinked from the current replacement
> build. The installed image is retained until the reduced native-aspect build
> completes verification and replacement.

2026-11-12. **Recommendation: extend at the OSD draw transaction, with a
persistent landscape backing canvas and explicit input domains.** Use
proportional rotate-and-fit as the compatibility renderer for stock scenes;
retain native-sized portrait reflow where a scene's layout is understood.
There is no established native switch that turns every scene into a
682×1024 layout. The hook boundaries below are evidenced; the proposed
compositor is **not implemented or hardware-tested**.

This investigation wrote only this document and
`.touch-focus/global-ui-rotation/`. No shared C/header changes, USB access,
camera operation, firmware installation, or host MMIO access occurred.
The existing BF+ **Auto Rotate UI** setting is the intended common policy
control; adding that control does not by itself extend rotation coverage.

## Evidence identity and boundaries

- Artifact: `decoded-V104/rtos-alt.bin`, 15,744,640 bytes; SHA-256
  `f747c1350f00526b9c68c65aaef44d6e7b644b0169992342e12f059c42e150dc`.
- Code VA = file offset + `0x4d3000000`. Initialized data at file offsets
  `[0xebdfb0,0xf03e70)` is copied to `0x4d7000000`; BSS addresses are not
  interchangeable with offsets into the file. The native-layout evidence
  includes startup-copy instructions.
- Evidence is local Capstone original-byte disassembly, literal decoding,
  and explicitly bounded Unicorn experiments. These are **not REA Evidence
  IDs**. The reverse-engineer-anything workflow was used with delegated,
  disjoint layout and input investigations. No REA MCP tools were available;
  the existing `.touch-focus/rea-doctor.json` reports missing registration.
  No registration or provider setup was changed.
- Raw listings, identities and experiment results are in
  [the analysis directory](../.touch-focus/global-ui-rotation/). Each `.asm`
  includes original bytes, VA, file offset and artifact hash. Linear listings
  include literal pools: a decoded instruction in a pool is not executable
  evidence. Direct-branch searches do not cover constructed/indirect calls.

## Native layout: what is and is not established

The Settings row painter `0x4d3363df0` embeds landscape geometry, including
1024-wide rows, 90-pixel row height and 916-pixel text width. Settings background
literal `0x4d33726c0` contains `{0,52,1024,630}`. Settings also uses its own
backing surface (`0x4d7042ec0`) and scroll state (`0x4d7042ee0`). The scene
descriptor inspected by the scene manager is four callback pointers, not a
width/height/orientation descriptor. Changing only a surface pitch or swapping
the panel dimensions therefore cannot reflow these scenes safely.

`0x4d30854f0`, identified as `IM_DISP_Set_OSD_Reverse_Display`, accepts layer
4 or 8 and copies a raw control word into the corresponding register. It does
not decode an angle. The single direct caller found, `0x4d321dc54`, passes a
pointer to a zero word set at `0x4d321dc50`. Neither a value of 1 nor a bit
pattern for 90° is established. **Do not try guessed reverse-register bits.**

The separate `0x4d32f8de0` image-rotation wrapper has real quarter-turn cases,
including orientation 6/8 to RSZ modes 1/3. It builds an image-plane descriptor
and reaches `0x4d30b63a0` (`IM_RSZ_Core_Ctrl`). This establishes an image
rotation facility, not compatibility with an RGB444+alpha4 OSD surface, its
alpha plane, or a scene layout. It is not a drop-in UI rotation hook.

The bounded direct-reference search found two callers of sensor getter
`0x4d31e36b0`, both metadata paths; it did not establish a native scene
orientation consumer. Raw 1/3 identify portrait. Their physical clockwise
polarity remains provisional, as described in [UI-ORIENTATION.md](UI-ORIENTATION.md).
Preserve the native getter's mutex/cache protocol; poll it in task context.

Evidence: `native-layout/menu-row.asm`, `osd-reverse.asm`,
`image-rotation-wrapper.asm`, `image-rotation-hardware.asm`,
`scene-manager.asm`, `entry-xrefs.json` and the native-layout report.

## General OSD boundary and original hook words

The worker starts at `0x4d31acad0`. Draw messages are type 1 and contain three
callback pointers followed by a copied parameter payload. Callback ABI:
`x0 = surface`, `x1 = payload`, `w2 = payload length`. The third callback is
separate and must retain its original behavior.

**There are two foreground/background pairs**, selected by the signed byte at
`0x4d72aa7f0` (loaded through literal `0x4d31ad860`). A nonzero value takes the
first pair and programs output channels 0 and 1; zero takes the second pair
and programs the selected channel. This establishes branch behavior, not the
physical connector names of those channels.

| Role | Instruction VA | Original bytes (little endian) | Observed contract / use |
| --- | --- | --- | --- |
| Foreground, nonzero mode | `0x4d31ad2a4` | `80 00 3f d6` | `blr x4`; clean at `0x4d31ad2c0` |
| Background, nonzero mode | `0x4d31ad30c` | `60 00 3f d6` | `blr x3`; color/alpha cleans at `0x4d31ad328`, `0x4d31ad350` |
| Foreground, zero mode | `0x4d31ad5cc` | `80 00 3f d6` | `blr x4`; clean at `0x4d31ad5e8` |
| Background, zero mode | `0x4d31ad634` | `60 00 3f d6` | `blr x3`; color/alpha cleans at `0x4d31ad650`, `0x4d31ad678` |
| Draw submission | `0x4d31ac850` | `fd 7b bd a9` | Entry `stp x29,x30,[sp,#-0x30]!`; copies callback triple at `+0x34..+0x40` and payload at `+0x48` |
| Received-message dispatch | `0x4d31accf8` | `f7 33 41 79` | `ldrh w23,[sp,#0x98]`; command type before dispatch |
| Common command completion | `0x4d31acbb0` | `e1 4b 40 f9` | `ldr x1,[sp,#0x90]`; optional completion callback follows |

These are **candidate interception boundaries, not tested patches**. No branch
island address or writable code cave is assumed. Any implementation must
verify the complete displaced instruction window and branch reach, preserve
the AArch64 ABI, retain original callback pointers, and restore exact bytes.
The four BLR sites are the narrowest demonstrated draw coverage; intercepting
submission requires handling the original copied message format/lifetime.

`0x4d3322d90` is a synchronous UI draw wrapper calling `0x4d31ac850` at
`0x4d3322dd0`. There are **659 direct B/BL candidates** to the former and
**59 to the latter**, including calls bypassing the former. Thus patching
only the UI wrapper is weaker coverage than the worker or lower submission
funnel. Counts are whole-image aligned instruction-word matches, not a
complete call graph or proof of 659 distinct scenes.

Evidence: `render/displayworker{,-head,-tail}.asm`, `draw-submission.asm`,
`ui-draw-queue.asm`, `worker-references.json`, `submission-references.json`.

### Surfaces and bank lifetime

| Surface | Native format | Standard geometry |
| --- | --- | --- |
| Foreground | 16-bit RGB444, alpha in low nibble | 1024×682, byte pitch 2048 |
| Background | YUV422, shared chroma per horizontal pixel pair, separate 8-bit alpha | color pitch 2048, alpha pitch 1024, alpha offset `0x155000` |

Both descriptors are 32 bytes: dirty start/end at `+0/+2`, pixels at `+8`,
color/alpha pitches and height at `+16/+18/+20`, alpha offset at `+24`.
The worker descriptor pair is at `0x4d72aa7a0`; the bank pointer table at
`0x4d396b870` contains `{0x4022c9800,0x40241e800,0x402573800,0x402773000}`.
Those values are evidence about the supplied build, not proposed allocations.

At `0x4d31acbbc..0x4d31accdc`, the worker compares current/back bank indices
and copies dirty rows with `0x4d31ac520`, including the background alpha
plane. This is a **retained, partial-redraw canvas**. Post-rotating a native
bank in place would feed already-rotated pixels into later native painting
and blending. Rotating it back after downscaling cannot restore lost pixels.

Instead, keep one canonical, unrotated 1024×682 backing surface per OSD layer.
Call the stock callback once with a descriptor pointing to that backing
surface, then resample the complete canonical layer into the real worker bank.
Restore/retain the physical descriptor and mark physical dirty rows `[0,682)`.
The stock cache work and bank programming must see the physical destination.
Never read the transformed bank back as the canonical source.

The minimum canonical pixel storage is **3,491,840 bytes (`0x354800`, about
3.33 MiB)**: 2 bytes/pixel foreground plus 2+1 bytes/pixel background. This
excludes alignment, guards, any native cached surfaces, and optional additional
buffers. Do not reuse the resident payload tail or assume that much memory is
available. Direct inverse sampling avoids a second portrait-sized intermediate.

This design assumes callbacks respect their supplied surface or use compatible
unrotated caches. The literal search found the worker surface address only in
its worker pool and the exact bank-table pointer in two worker/setup pools;
that is useful evidence, **not proof against constructed aliases or DMA**.
Callback aliases, native scene backing surfaces and hardware blits still need
focused audit before claiming coverage of every scene.

## Camera imagery and overlays

The OSD bank calls explicitly use layers **4 and 8**. Main image setup takes
a different path (`0x4d321df00` to `0x4d30806c0`, `0x4d3080910`,
`0x4d3080e80`; associated start/stop uses layer 1). Therefore rotating these
two CPU-drawn OSD surfaces does not itself rotate live or playback image DMA.
Keep live/playback imagery and existing native image-orientation behavior.

There are also separate hardware overlay paths:

| Overlay | Observed chain | Separation evidence |
| --- | --- | --- |
| Face/rectangle frames | `0x4d335c260 → 0x4d320bef0`; call at `0x4d320c0a0 → 0x4d3082920` | Diagnostic names `IM_DISP_Set_Face_Frame`; writes frame coordinate/style registers at base `0x16480000`, channel stride `0x4000`, offsets `0x1800..0x1b14` |
| AF frames | `0x4d335c270 → 0x4d320bb10`; call at `0x4d320bc90 → 0x4d3082ca0` | Diagnostic names `IM_DISP_Set_Af_Frame`; writes frame registers at offsets `0x1a00..0x1b20` |

These functions program descriptor/register data, rather than the two OSD
pixel buffers. Leave these image-anchored rectangles in physical image
coordinates when the image remains unchanged. Their firmware instructions
were only inspected; none of these APIs was called on a camera.

This does **not** classify every overlay. Grids, crop masks, level indicators,
histograms, zoom guides, playback selection and image-bearing submenus need
an inventory: anything image-anchored that is baked into OSD cannot be freely
rotate-and-fit with the labels. It needs a separate pass or explicit geometry
handling. Conversely, rotating all final scanout layers would also rotate
camera imagery and these frames, defeating UI-only behavior.

Evidence: `render/frame-ui-submit.asm`, `hardware-frame-submit{,-tail}.asm`,
`frame-api.asm`, `hardware-frame-api.asm`, `literals.json`,
`main-image-layer.asm`.

## Rotate-and-fit and input domains

For stock scenes, retain original canvas coordinates `(a,b)` in 1024×682.
For the upright portrait viewport `(u,v)` in 682×1024, use uniform scale
`s = 682/1024 = 0.666015625`, with `u = s*a`,
`v = v0+s*b`, `v0 = (1024-s*682)/2 = 284.888671875`.
This preserves the entire landscape UI, with its text at about **two-thirds
size** and substantial empty space above/below. It is a compatibility fallback,
not portrait reflow. Reflow remains preferable for readable lists.

Using the existing provisional polarity, physical `(x,y)` maps to upright
portrait as raw 1: `(u,v)=(y,1023-x)`, raw 3: `(u,v)=(681-y,x)`.
For **stock fitted UI hit tests**, then compute
`a=u/s`, `b=(v-v0)/s`; reject coordinates outside the fitted UI. The exact
integer pixel-center, rounding and edge convention must be shared by painter
and hit testing. If using a 682×454 raster rectangle centered at v=285,
use its actual horizontal/vertical scales for both directions, rather than
silently retaining the continuous formula. Do not clamp empty-space taps onto
the first/last control.

The existing `orientation_touch()` returns **682×1024 reflow coordinates**.
It is not the inverse of fitting the original 1024×682 UI. Reusing it for
native stock hit boxes is wrong even if all three coordinate pairs rotate.

Background sampling must decode/resample/repack **destination horizontal
YUV422 pairs** and preserve per-pixel alpha. Transposing packed 16-bit YUV
words swaps chroma relationships incorrectly. Handle pair boundaries and
transparent neighbors explicitly; preserve RGB444+alpha4 on foreground.

| Input boundary | Original instruction | Correct scope |
| --- | --- | --- |
| Global type-0 decoder call | `0x4d3323b20`: `d8 fd ff 97`, `bl 0x4d3323280` | Common packed-event entry; not itself a safe blanket transform |
| Current scene handler dispatch | `0x4d33232f8`: `60 00 3f d6`, `blr x3` | `x0` points to five-pointer Event, LCD pointer at `+16`; useful routing/context hook |
| Common icon hit tester | `0x4d3367530` | Verified stock UI consumer; invokes rectangle helper `0x4d33235e0`; bounded scan finds 33 direct callers |
| Live icon use | `0x4d3398e3c → 0x4d3367530` | Candidate UI-domain mapping at the hit-test sink |
| Live image focus bounds | `0x4d3398bec`, `0x4d3398c80 → 0x4d339fb50` | Preserve raw physical tap/current coordinates |
| Live image drag | `0x4d3398c90 → 0x4d339fbd0 → 0x4d331d5d0/0x4d331d840` | Preserve image-space targeting/movement |
| Playback gesture route | `0x4d336b810 → 0x4d3359af0 → 0x4d3359530` | Mixes UI icon tests and image pan/zoom (`0x4d32f5710`); needs split ownership |

For pure UI scenes, copy the Event and its LCD packet and inverse-map the
packet once. For mixed live/playback scenes, retain raw scene input and map
only classified UI sinks, with UI hit priority and a gesture owner. The common
icon tester is useful coverage, not proof that all controls use it. Do not
transform a packet globally and then feed the result to focus/pan/replay.

Native LCD direction bits are up/down/left/right `0x10/0x20/0x40/0x80`;
diagonals combine them. Rotate these as vectors as well as tap, drag origin
and current coordinates. Drag begin/update/end are `0x100/0x200/0x400`, tap
is `1`. These are not a universal press/release protocol: stationary contact
has no begin packet, and short drag release can also carry a tap. Drop
activation on a canceled gesture without swallowing independent key/dial
payloads. Existing focus replay queues LCD data again, so retain raw replay
data or explicitly track its coordinate domain to prevent double mapping.

Evidence: `input/verified-hooks.json`, `event-decoder.asm`, `event-loop.asm`,
`stock-icon-hit-test.asm`, `live-input.asm`, `live-image-coordinates.asm`,
`image-gesture-router.asm`, `native-input-experiments.json` and input report.

## Implementation sequence and gates

1. **One policy and explicit render modes.** Reuse BF+ Auto Rotate UI;
   distinguish landscape identity, stock fitted UI and owned portrait reflow.
   Already-reflowed Settings/BF+/picker output must bypass global fit, and its
   input must bypass native-fit inversion. Do not add another compact-picker
   touch worker. On mode/scene changes, rebuild canonical pixels from a known
   unrotated scene; do not derive them from a scaled displayed frame.
2. **Own complete transactions.** Intercept both worker branches, preserve
   third/command-completion callbacks and initialize/reset canonical surfaces
   with native lifecycle changes. Commands 0/7 reconfigure display surfaces or
   banks outside normal draw callbacks; four BLR hooks alone do not cover
   lifecycle. Foreground-only/background-only jobs are legitimate. Orientation
   changes must schedule a paired re-presentation even if neither scene data
   nor one of the layers changed. Never call the synchronous draw wrapper
   recursively from the display worker.
3. **Publish one transform per completed frame.** Latch policy, raw orientation,
   scene generation and renderer mode for the complete job. Publish the input
   epoch after both layers are ready and native bank programming completes,
   not after foreground alone. `0x4d31acbb0` is a demonstrated software
   completion boundary; actual scanout/vblank timing remains unverified.
   Keep input on the previous epoch or cancel/hold it during transition.
   Cancel active UI gestures across epochs. Disable/failure restores both
   layers and their input mapping together.
4. **Implement UI-only input ownership.** Start with pure native menu scenes;
   explicitly classify live, movie, magnified and playback controls versus
   image coordinates. Handle replay, mixed key/dial/LCD bundles, directional
   gestures, null LCD and invalid/outside coordinates. An opaque full menu
   cannot use a transparent background fallback intended for liveview.
5. **Extend reflow by component family.** Native list/title/value/picker
   painters have reusable structure, but text, glyphs, blits and hit boxes all
   need the same geometry contract. Rotating only rectangle primitives cannot
   rotate text or safely change every stock layout. Keep full-canvas fit for
   unported UI after its image/input-domain audit.
6. **Validate before enabling global coverage.** Offline original-callback
   rendering with guards, partial updates, alpha blending, two banks, both
   output modes, initialization/reset, toggles and portrait reversals; UI/image
   touch ownership and replay; then separately authorized camera checks for
   polarity, latency, available memory, frame time and all target scene
   families. This investigation does not establish a safe on-device patch.

## Verification and coverage ledger

`render/verify_worker.py` executed original code from `0x4d31ad230` to
`0x4d31acbb0` under Unicorn. **10 cases passed**: mode 0/1, with paired,
foreground-only, background-only, third-only and absent callbacks. It checks
callback sites/ABI, payload length, surface bank addresses, cache-call order
and one-channel/two-channel bank-selection arguments. Callbacks, cache/MMIO
APIs and final wait were stubbed. It does not validate native pixels or timing.
Full results: `render/worker-emulation.json`.

| Question | Status | Bounded conclusion |
| --- | --- | --- |
| Common native draw layer? | Answered | OSD worker has four callback sites; lower submission has callers bypassing the synchronous UI wrapper |
| Native automatic portrait/reflow switch? | Not established | Fixed native list geometry; inspected reverse and image-rotation APIs do not supply a scene-wide portrait contract |
| Image/overlay separation? | Partly answered | OSD 4/8, main image path, face/AF registers are distinct; remaining overlays/image-bearing menus are unaudited |
| Global coordinate dispatcher? | Answered, with constraints | Common decoder found; mixed image/UI consumers make blanket remapping incorrect |
| Every stock submenu/live/playback works? | Unverified | Architectural coverage opportunity, not an exhaustive scene test or completed implementation |
| Automatic polling, redraw and scanout coherence? | Partly answered | Transaction boundaries known; universal redraw integration, timing and runtime concurrency still require implementation/validation |

The next implementable increment is the canonical OSD compositor plus its
transaction/epoch contract, accompanied by pure-menu input mapping. It must
not be presented as completed whole-camera portrait until mixed scene input,
image-anchored OSD content and lifecycle coverage are resolved.
