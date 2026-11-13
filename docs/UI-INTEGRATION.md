# BF+ automatic UI rotation and touch integration

> Historical experiment: the user requested removal of automatic UI rotation
> and LCD menu controls. These adapters are unlinked from the current replacement
> build. The installed image is retained until the reduced native-aspect build
> completes verification and replacement.

**BF+ → Auto Rotate UI → ON/OFF** controls automatic portrait rotation.
It starts ON when the RAM extension is installed. OFF requests a paired
landscape redraw; touch remains enabled. Like the other resident options,
this setting resets when the camera reboots.

The option applies to the shared foreground/background OSD worker, including
stock menus, live-view labels and playback controls. Settings, BF+ and BF+
pickers use a readable 682×1024 layout with full-size native text. Other stock
OSD content is rotated and fitted proportionally into portrait, keeping the
whole original layout visible at approximately two-thirds size. This is not
individual portrait reflow for every stock screen.

Camera image DMA, native AF/face rectangles, tap-to-focus coordinates and
playback image panning retain their native image-space behavior. The root
photo/cine level and center markers, and two verified corner-marker families,
are painted in physical image coordinates beneath the fitted UI. Entering or
leaving this split rebuilds both canonical planes using the verified initial
painters. See [UI-IMAGE-ANCHORS.md](UI-IMAGE-ANCHORS.md) and
[UI-IMAGE-PROFILES.md](UI-IMAGE-PROFILES.md) for the native evidence.

The normal AF and S2 screens, their additional live-view overlay, the dedicated
level screen and the retained live-view popup have separate image-overlay
policies. S2 dimming stays aligned with the image; its current level style is
retained across orientation changes. The popup retains its verified parent
canvas and runs its native initializer once. Rotation does not replay the
popup's state-changing paint callback.

Inherited live-view content requires a verified full parent and a native
hierarchy handoff. Installing while an inherited screen is already active
cannot establish that history; returning to a full live-view screen permits
acquisition. Unknown image-bearing callbacks invalidate publication until a
known full screen or native clear restores it. Offline coverage of the normal
inventory is being validated; physical whole-camera coverage is not yet proven.

## Touch behavior

- Main Settings: drag to scroll; tap to select/open. Portrait shows seven rows.
- BF+ and its pickers: tap an editable row/option, or the portrait Back label.
  Version remains read-only. Lists that fit on screen do not scroll.
- Eight verified stock compact-picker families and six stock row-list
  families: drag for discrete row navigation; tap to select and invoke the
  native center action. Native disabled/read-only rules remain authoritative.
- The mixed Settings information list and the variable-length saved-entry list
  use their native scrolling viewports. Taps on readable information select it;
  action rows invoke the native confirmation flow. Their adapters are described
  in [NATIVE-TOUCH-SETTINGS-LIST.md](NATIVE-TOUCH-SETTINGS-LIST.md) and
  [NATIVE-TOUCH-PRIVATE-LIST.md](NATIVE-TOUCH-PRIVATE-LIST.md).
- Existing native rectangular UI hit tests follow the displayed fit. A tap
  in portrait margins does not activate an off-screen control.
- A drag release does not select an item. Physical buttons/dial take priority;
  changing scene or orientation cancels an active gesture.

The exact family maps and unadapted editors/dialogs are recorded in
[NATIVE-TOUCH-MENUS.md](NATIVE-TOUCH-MENUS.md) and
[NATIVE-TOUCH-ROWS.md](NATIVE-TOUCH-ROWS.md). There is no claim that arbitrary
numeric/date-time editors, service menus or every playback gesture gained
new touch actions. Their native controls remain available.

## Display and input transaction

`touch_focus/ui.h` intercepts all four verified native draw callback sites.
Actual draw jobs update retained, unrotated canonical planes. Acquiring an
image-overlay split can reconstruct UI from bounded render callbacks; native
input, initializer, update and post callbacks are not replayed for rotation.
They receive persistent per-plane surface descriptors, matching the native
worker's descriptor lifetime. A separate local copy validates each callback's
geometry before presentation.
The compositor presents those pixels into the worker's physical banks. It
never re-seeds canonical data from an already rotated/downscaled bank.
Foreground RGB444/alpha and background UYVY422/separate alpha are handled
independently; YUV chroma is repacked in destination horizontal pairs.

Portrait places physical image overlays beneath the fitted UI, so moved labels
can occlude different image pixels. S2 landscape restoration instead copies
the canonical colors before applying its original alpha-mask order. Native
alpha writes preserve background glyph colors; blending two alpha masks would
incorrectly increase opacity. The bounded mask pass also clips a native ramp
that can extend beyond the 682-row canvas while preserving its original slope
and visible pixels.

The worker dequeue hook starts a transaction. Publication occurs after the
native cache work, third draw callback, bank programming and bank-index flips,
at the existing `0x4d31ad3f4 → 0x4d321d770` call. This is a software completion
boundary, not a verified vblank fence. A change in orientation or layout
requires both planes before input becomes ready. Ordinary single-plane updates
retain the established mapping. Failed planes invalidate touch geometry.

Command 0 permits fresh canonical seeding only after native plane clearing.
Command 7 reconfigures banks without clearing them, so canonical pixels remain
retained. Scene transitions invalidate targets even when the same handler is
entered again. Initial/regular callbacks of a known list share a scene identity.
Stock initializers can paint before the hierarchy publishes its new depth;
row capture records that pending depth and accepts input only after it commits.

Both native transition requests are checked: the target depth and the separate
root-replacement request. Before the hierarchy changes, the UI task submits a
synchronous landscape restoration and waits for native display completion.
The switch proceeds only after successful restoration. A failed restoration
gets at most two additional idle-time attempts; it cannot silently publish
touch coordinates or continue the hierarchy over a failed display. Scene
epoch, depth and both request values must also agree at frame completion.

An inherited screen also records the native root descriptor and the owner of
hierarchy slot 2. Saved slot bytes alone are insufficient because the native
worker leaves popped slots intact. A pop to the root, or replacement with the
same exact root descriptor, can hand a verified base to the two known partial
live-view owners during one worker invocation. Ownership commits only after
native depth publication. A known popup push preserves clean canonical pixels
through the outgoing AF suspend paint and the popup initializer; unrelated
callbacks and native clears revoke that permission.

The UI receive call uses the native timed receive adapter with timeout 100.
On native `E_TMOUT`, it checks orientation in the UI task and resumes waiting.
Real input messages and other errors keep their native behavior. This allows
rotation while a scene has a NULL update callback and no input is arriving.
Actual clock units, sensor latency and redraw performance need hardware checks.

Only classified UI sinks receive inverse coordinates. The original Event and
LCD packet are forwarded unchanged. Native menu adapters transform a private
copy for synthesized selection, and the three native rectangle hit-test calls
use a private inverse-mapped packet. This avoids moving tap-to-focus or image
panning into the menu coordinate system.

## Memory, installation and removal

The compositor uses **4,888,576 bytes (`0x4a9800`) of scratch**, separate from
the initialized image and resident BSS: 1,396,736 for full-size portrait menu
rendering and 3,491,840 for the two canonical OSD planes.

The resident image exceeds a single transfer. The separate
[segmented loader](SEGMENTED-LOADER.md) uses **4 KiB reads and writes** within
the fixed **16 KiB staging cap**, a **64 KiB resident extent limit**, immutable install
artifacts and exact hook checks. Scratch is allocated, not uploaded.
The code touches two verified code-page descriptors; both must match expected
read-only values before any hook changes.

Before removal the host sets the resident removal flag and waits for a paired
landscape frame. The resident refuses removal unless that flag, displayed
orientation, ready flag and idle frame state agree. Crop admission is then
sealed and all exact installed hooks restored. Memory remains allocated until
reboot because queued native callbacks can still reference it. Existing saved
legacy installations retain their immutable remover path.

## Validation boundary

Offline tests compile the actual
freestanding, relocated AArch64 payload and run it under Unicorn, with native
firmware paths where the user's decoded image is available. Tests cover
pixels/guards, native text, packet production, selection, reentrant draw
queues, exact hooks, transaction ordering and segmented-loader failure paths.
RTOS scheduling, hardware cache coherence and actual display scanout are not
established by emulation.

The raw sensor's portrait classification is established; physical polarity is
still provisional (raw 1 clockwise, raw 3 counterclockwise). Verify both ways
of holding the camera, frame latency, available allocation and mixed image/UI
screens before treating this as camera-validated whole-interface behavior.
The combined image was installed on BF 1.04 on 2026-11-13 after a user-confirmed
power cycle. The host verified complete image readback, a fresh COMMIT receipt,
all 57 pointer hooks and 132 code patches, immutable installed code, and restored
code-page permissions. Touch Focus, MF Subject Detection and Auto Rotate UI
were enabled; the live Focus Guide/PAS pipeline was excluded. USB was closed
after verification. This establishes deployment, not visual/touch usability:
the user check of both portrait directions, list scrolling, tapping and the
BF+ switch is still pending.
