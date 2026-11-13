# BF104 inherited image UI lifecycle

This is an offline, bounded audit of profiles9/10/11. It adds no production
hooks or replay recipe. The native regression is
[`tests/test_ui_inherited_lifecycle.py`](../tests/test_ui_inherited_lifecycle.py).
It executes original instructions from operator-supplied
`decoded-V104/rtos-alt.bin`, base `0x4d3000000`, SHA-256
`f747c1350f00526b9c68c65aaef44d6e7b644b0169992342e12f059c42e150dc`.
All shortened addresses below have prefix `0x4d`.

**Profiles9 and10 replace slot2. Profile11 pushes a child above slot2.**
A saved full-family recipe is provenance, not a live ancestor requirement:
after replacement, the old full descriptor is no longer in the live stack.
The retained-canonical proposal for11 avoids replaying its control-bearing
foreground callback, but must also preserve the parent physical-anchor
underlay and the native order of erasure.

## Descriptors and hierarchy ABI

Each descriptor is32 bytes: `{init, resume, suspend, exit}` as four pointers.

| Scene | Descriptor | init | resume | suspend | exit |
| --- | --- | --- | --- | --- | --- |
| Live root slot1 | `3e89760` | `338e070` | `338cfe0` | `338cef0` | `338e060` |
| Photo1 slot2 | `35646f0` | `3398930` | `33988b0` | `3393730` | `33936a0` |
| Cine2 slot2 | `3564608` | `3392c30` | `3392bb0` | `338ebd0` | `338eb40` |
| AF8 slot2 | `3564de8` | `33d16e0` | `33d1640` | `33cd6a0` | `33cd820` |
| S2 profile9 | `3e8b9c8` | `33d3f60` | `33d3340` | `33d29d0` | `33d3a70` |
| Overlay10 | `3e8a9e0` | `33a2680` | `33a2560` | `33a1f90` | `33a2660` |
| Countdown11 | `3e8b9e8` | `33d4b10` | `33d48d0` | `33d4240` | `33d4af0` |

Stack slot `i` is `7301bc0+32*i`; live depth is u32`70346a0`.
Root/base index is u32`7034698`. Root replacement request u32`703469c`
and ordinary pending target u32`70346a4` are idle at12. Pending descriptor
storage is `7301d40`. `3323c50` reports pending if rootrequest!=12 or
signed target<=11. Depth alone cannot validate a transition.

`3324110` copies a push descriptor and sets target=depth+1. `3324180`
finds an exact32-byte ancestor descriptor and stages its index. `3324370`
copies a replacement descriptor and stores its root index from w1, leaving
ordinary target unchanged. None of these immediately changes the live slots.

## Exact9/10 replacement chains

`338cf00` reads state through `33252e0` (u32`7301d60`). State2 tests the
low byte of `32450d0()`:

- false: `338cfcc → 33d41a0` copies profile9 into the root's next-scene output;
- true: `338cf48 → 33a2770` copies profile10 into that output.

These are descriptor copies, not `3324110` child pushes. Root initialization
`338e070` and resume0 `338cfe0` call the dispatcher. The native worker then
copies the emitted next-scene descriptor into slot2 and calls its initializer.

The fixture exercises old full1/2/8 × new9/10 × both requests, twelve cases:

| Request executed | Before worker `(rootrequest,target,depth)` | At new slot2 init | After worker |
| --- | --- | --- | --- |
| `338e1d0 → 3324180(root)` | `(12,1,2)` | `(12,1,2)` | `(12,12,2)` |
| `3324370(root,1)` | `(1,12,2)` | `(12,12,2)` | `(12,12,2)` |

In every case oldslot2.exit runs before newslot2.init, and newslot2 already
contains9/10 when init starts. The replacement path can exit/re-enter the
same root descriptor; equality of root bytes does not prove uninterrupted
lifetime. `3323db4` resets rootrequest before initialization. **Both requests
can be idle while the worker still owns the transition.**

Relevant worker writes/calls:

- `3323e28/e2c` or `3323fac/fb0`: install the descriptor before calling init;
- `3323ea4`: call init/resume with x0 next-scene output, x1 handlers, w2=0;
- `3323eb0`: publish depth; `3323ebc`: reset target12;
- `3323ec4`: publish input/update handler pointers.

A bounded one-worker handoff can therefore recognize either `(12,1)` with
unchanged root prefix, or `(1,12)` with the exact pending live-root descriptor,
provided a valid old base existed before invalidation. Accept only actual
newslot2 descriptor9/10; bind its ownership and new slot snapshots only after
successful drawing and worker completion. This does not authorize a generic
unknown root replacement or acquisition from arbitrary existing slot bytes.
Snapshot the complete32-byte descriptor; request flags alone are insufficient.

### AF outgoing full repaint

Actual AF exit `33cd820` first polls event0x10. If that fails and AF is active,
it waits event0x20 and may queue a full draw at `33cd8e4` between failed waits:

```
{ FG=33cd4b0, BG=33cc230, post=33cd220 }, x1=&one_byte, w2=1
```

The fixture supplies wait results−50,−50,0 and getter`3399670=0x5a`, producing
one exact full draw before slot replacement. Old AF still occupies slot2;
depth remains2 and the pending request remains `(12,1)` or `(1,12)`.
The post callback is part of the actual outgoing native job, not a callback
to replay during reconstruction. The handoff must survive this authorized
outgoing job and keep its canonical capture free of anchors.

The first event0x10 success path skips the wait/repaint. The test proves the
repaint is possible, not that every shutter transition performs it.

## Profile11 entry, ownership and exit

`33d4c80 → 3324110(3e8b9e8)` is an unconditional descriptor push. At depth2
it stages `(rootrequest,target,depth)=(12,3,2)`. The worker calls the current
slot2.suspend, installs11 in slot3 and runs its real initializer while global
depth is still2/target3. It then publishes depth3/target12. Native tests do this
from full1/2/8 and from9/10, checking that slot2 remains byte-for-byte intact.
Thus a full-only guard would deliberately exclude mechanically valid9/10
parents; a live full ancestor is not required by the push machinery.

Profile9 suspend `33d29d0` clears event bits0xc00 and stops its timer.
Profile10 suspend `33a1f90` stops its timer. Neither queues paint in the
executed original paths. **AF suspend `33cd6a0` can repaint too:** when AF is
active, a failed event0x20 wait queues the same full AF job at `33cd738`.
The fixture executes actual suspend followed by actual11 init, capturing AF
full first and11 second, both while depth2/target3. A direct AF→11 clean
handoff must cover this interval, not merely the pre-worker drain.

On pop11, its exit stops the timer and the worker invokes the live9/10
parent's resume with w2=0. The dead pre-replacement AF ancestor is not resumed.
Slot3 memory still contains11 after live depth returns2: never treat memory
above depth as a live child. The fixture intercepts parent resume at its entry;
the parent recipe/reacquisition is integration scope.

### What normal release reachability proves

There is a normal countdown route: `3242fa0` stores the requested nonzero
delay, branches to `3243150 → 3324580`, which queues `33d4c80` through
`33237b0`, then waits event0x200 through `3324fc0`. Initial11 sets that bit
after its synchronous initial draw.

The inspected release branch in `3243be0` sets state2 at `3243e08`, then waits
event0x80 and event4 before dispatching the release-action table at `3ca8f40`.
The table functions `3243520/3244090/3243750/32449c0` call `3242fa0`.
However **event0x80 is not proof that9/10 has initialized**: `33cfe00`, inside
AF initialization, produces that bit. This audit does not model intertask
ordering or prove the frequency of9/10→11 in a complete shutter sequence.
The unconditional push and actual worker prove that those parents are legal;
the production guard should validate the observed parent, not infer one from
the release event alone.

## Initial draw, hook ABIs and parameter lifetime

Init`33d4b10` and resume0`33d48d0` install input`33d4810` and update`33d4290`.
Each constructs the same exact draw pair:

```
{ FG=33d4590, BG=33d4a50, post=0 }, params=&u32(0xffffffff), length=4
```

Queue calls are `33d4bd8` and `33d49a8`. The mask is at initializer SP+0x24
inside a0x40-byte frame, while the24-byte pair starts SP+0x28. Resume(w2!=0)
returns without drawing. Neither painter establishes a full transparent canvas;
`0xffffffff` means all dirty bits, not a standalone full-scene image.

`3322d90` clears completion bit1, calls `31ac850` with completion callback
`3322d60`, and waits bit1 before returning. `31ac850` copies the24-byte pair
at `31ac884..890` and copies the parameter bytes at `31ac89c` into an outgoing
stack message. For11 the message is44 bytes: callback at+0, command1 at+8,
payload length28 at+10, pair at+16, and four mask bytes at+40. The fixture
intercepts the OS send`30339d0`, verifies the copied bytes, then verifies that
overwriting the original mask does not change the message payload.

**No initializer pointer or worker message pointer may be retained after its
call/job lifetime.** A deferred recipe would need owned mask storage. The
retained-canonical design needs neither pointer once the native initial job
has executed. The OS queue implementation/scheduling is an explicit fixture
boundary; the original copy and wait instructions execute.

| Call site | Target and exact arguments | Gate | Return use |
| --- | --- | --- | --- |
| `33d46d8` | `3367b40(surface,NULL,0)` | FG bit8 and `3321530()==1` | discarded |
| `33d4ac4` | `339f070(surface)` | BG bit5 | discarded |
| `33d4ab8` | `3368760(surface,NULL,4)` | BG bit8 and `3321530()==1` | discarded |

The third argument to the level leaf is its **mode**, not the outer draw's
parameter length. The wrapper has only x0 as an argument; do not interpret
residual x1/x2 as its API. NULL level descriptor selects `7035be8`; an owned
24-byte snapshot can be passed when the parent needs stable geometry.

Native11 FG is not safe to replay: fullmask calls timestamp setter`3399590`
through `33d47dc`, and flag`u8[7303833]` independently invokes control updater
`331da90` at `33d47c4`. A mask0 probe still invokes that updater when the flag
is set. Normal initializers clear that flag before their first draw, but the
timestamp change still occurs. The regression observes one timestamp setter
for fullmask and proves the mask0 updater behavior; it does not suppress
native side effects. Rotation-only jobs should reuse the retained pixels.

## Physical anchor order and inherited pixels

**BG execution order is center, optional UI backgrounds, then level4.**
Fullmask branches from `33d4a68` to center at `33d4ac4`, returns to the bit6
path, calls `335ffb0` if`3321610()==1`, calls `335f730` if`33215a0()==1`, and
finally reaches level4 at `33d4ab8`. Sorting call addresses would reverse the
center/level relationship. A20-case native branch probe checks mask/gates,
exact arguments and discarded returns.

Level4 is not a non-erasing overlay. It calls BG rectangle primitive`3328cc0`
at `3368a34` with color`0x00808000` (neutral YUV, zero alpha) before the level's
current strokes. At center512,341 the prior footprint is:

| Previous orientation byte | Rectangle `(x,y,w,h)` |
| --- | --- |
| 0 | `(206,257,612,168)` |
| 1 | `(428,135,168,412)` |

The same primitive for parent level modes1/2/3 writes `0x008080ff`,
`0x0080804d`, or `0x0080801a`. Child mode4 therefore erases that prior opaque
or dimmed level footprint, including a center marker drawn immediately before
it where they overlap. It does not clear the whole BG; parent styling outside
the overwritten footprint survives. Original level probes check both previous
orientations and all five modes0..4 with zero roll/pitch and calibration0.

FG level0 also clears its prior footprint to0 via `3367c3c → 3325ca0` before
current strokes. With an inherited AF marker (selector10), native`339f160`
emits16 aspect-corner rectangles followed by four center-cross rectangles.
At full1024×682 image bounds, the native primitive trace proves all16 corners
lie outside the level-clear rectangle and all four center strokes lie inside.
Thus **marker before child level** matches native erasure; marker after level
would restore a cross native level cleared. Dropping the inherited marker
altogether loses surviving corners. If the level is off, there is no such
clear. This fixture's corner conclusion uses the stated aspect/center, not
every possible image bound or calibration.

For a new physical plane, the parent must preserve/reconstruct the established
parent anchor/style underlay first, apply the11 center/level changes in native
order, then composite the retained clean canonical UI. That is a composition
contract, not permission to replay parent state-machine or full11 callbacks.
Inherited9 styling is owned by the separate profile audit. Current sensor
values and hysteresis history versus exact old-frame pixels remain the
parent's chosen redraw policy; these probes establish native operations and
their ordering, not a fresh-plane pixel-equivalence proof for every history.

## Retained-canonical acceptance bounds

The proposed implementation is supported under these explicit conditions:

1. Before the worker, exact pending descriptor11, a proven push from depth2
   to3, unchanged root/slot2 snapshots, and valid parent owner1/2/8/9/10.
2. Drain to identity OVER while retaining canonical storage with anchors
   excluded. Keep deferral through any outgoing AF suspend repaint. Never
   seed this storage from a physical plane that already contains anchors.
3. Run the native11 initial pair once with its actual copied four-byte mask,
   capturing both canonical planes while deferring the three proven calls.
4. Bind11 only after successful publication and worker completion. Rotation,
   no-ops and disable-to-identity reuse this canonical image; no synthetic
   fullmask replay. Known command7 may retag only a still-valid certificate;
   command0, unknown scene, failed job, or mismatched hierarchy revokes it.
5. Return to the actual live parent through native resume/reacquisition. Any
   later canonical clear cannot be repaired by treating11 as a full painter.

The fixture tests the native premises. Parent/Bohr production tests own the
certificate, cancellation, command0/7, OVER pixel composition, retries and
successful publication checks.

## Final11 BG pass after the inherited identity underlay

The later profile9 alpha-mask finding changes the raw0 composition order:
an alpha-only parent operation can replace child glyph alpha while retaining
its color. The agreed final pass is therefore **one entire native11 BG call
on the physical surface after copying canonical and finishing the parent
identity underlay**, with no separate child center/level paint. This is an
ordinary renderer with bounded rendering effects, not a literally pure
function. It does not authorize replay of11 FG.

ABI, as an integration recipe only (no header is added here):

```c
static const uint32_t child_bg_mask = UINT32_MAX;
((uint32_t (*)(void *, const void *, uint32_t))0x4d33d4a50ULL)
    (physical_background, &child_bg_mask, 4);
```

Require the established11 certificate and parent-owner guard. In canonical
capture, keep the three11 anchor calls deferred. In this final physical call,
use the native center and level calls, once, in their original order. The
physical descriptor must pass the parent's normal destination validation.
Discard the callback return0. Do not call init, resume, update, post, or FG to
produce this final pass. This BG-specific exception replaces any earlier
blanket prohibition on a synthetic fullmask BG draw; the retained-canonical
and no-FG-replay requirements still apply.

### Widget dependency audit

`335ffb0` and `335f730` construct only caller-local widget/string descriptors.
Their inspected dependencies fall into these groups:

| Dependency | Observed role/effects |
| --- | --- |
| `3321610/33215a0/3321790`, through `330f3f0`, `3315350`, `3318940/8980/89c0/8a00/8bc0` | Read UI/settings selectors; final getters load current settings fields. |
| `31d4a10/31d4a30/31d48c0/31d5080/31d52c0/31d55c0` | Read lens/status snapshots and flags, not lens commands. |
| `31d6180` | Query flag via`3033890`; if valid, lock/unlock via`3033950/3033970` around the current snapshot index and memcpy128 bytes to caller storage; otherwise clear that caller buffer. |
| `335fb00/335fe50`, `33724b0`, `30088a0` | Build display strings using table pointers and immediate sprintf to the caller's local string. |
| `3372230` | Format-token ring: writes three-byte slots at`73025d0`, advances cursor`73025f0` modulo10. |
| `3327e50 → 320abf0/320acf0` | Measure display text; clear/rasterize shared font scratch at`0x402174800`, return width/height into caller-local outputs. |
| `335c820 → 332d4e0` | Compute widget width from glyph metrics and current local style. |
| `335c720 → 335c310` | Paint background widget plates/glyphs through existing graphics primitives. |

No lifecycle/queue/timer/start-stop action, `331da90`, `3399590`, or clock
query`3033bb0` was found in these inspected widget/control dependencies.
The flags/semaphore operations in the lens getter are query/snapshot
synchronization, not state-transition requests. The regression executes both
branches of that getter with those OS services intercepted and verifies
the copied/cleared128-byte result and query→lock→unlock order.

The text token does not escape its formatting call: for the focal-length
widget, `335f874 → 3372230` returns a token pointer, `335f884` puts it in x3,
and `335f898 → 30088a0` copies it into the widget's SP+0x5c string.
The distance formatter similarly passes token pointers immediately to
`30088a0`; when it constructs a format string first, that string is local too.
The widget subsequently passes its local string descriptor to synchronous
`3327e50` and then paints through `335c720`. There is no queued callback,
global pointer store or returned retained token in these widget bodies.
Do not export or retain any of their local/token pointers from a hook.

Four native widget fixtures cover both distance-format selectors and
focusmode0/2, executing the original BG body, widget bodies, distance
formatter branches, token maker and plate layout. Their native RAM-write
trace is confined to the token ring/cursor at the declared formatter, text
metric and final-raster boundaries. They verify token arguments are live at
the immediate formatter call and destination strings are on the active stack.
The fixture substitutes sprintf output and metrics; it is not exhaustive
font/locale or floating-point formatting validation.

Together with the existing level trace, the allowed effects are surface/pixel
writes, stack temporaries, bounded token/font scratch, ordinary level history
`730255f..7302561`, and snapshot-query synchronization. The call belongs on
the native serialized rendering path, where shared formatting/font scratch is
already used. The audit does not establish reentrancy on another task or
authorize calling it while the native renderer is concurrently using that
scratch.

## Reproduction and limitations

Run:

```sh
.venv/bin/python -m unittest discover -s tests -p test_ui_inherited_lifecycle.py -v
```

Fourteen tests pass, with parameterized native transition and renderer cases.

The fixture maps firmware and globals in Unicorn, seeds initialized data from
the same supplied image, and refuses execution outside listed native ranges
or named service stubs. It never opens USB/PTP, a device, or the network.

Declared boundaries: libc copy/set/compare are Python equivalents; RTOS flag,
queue and timer services are stubs; root environmental selectors are fixed;
full scene exits and9/10 init endpoints are intercepted in the replacement
matrix. AF exit/suspend and11 init/resume execute in their dedicated probes.
Parent suspend endpoints are intercepted in the broad push matrix, with real
9/10 and AF suspend tested separately. Graphics tests record native primitive
emission, stubbing final rasterizers, glyphs, calibration and aspect bounds
where stated. They do not observe native task races, hardware scheduling,
frame-bank publication, atlas output or physical camera appearance.
