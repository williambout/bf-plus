# BF+ Extra Aspect Ratios

The reduced BF+ 1.0 build was installed and read back successfully on
2026-11-13 (resident image SHA-256 `675135be85a6fc9c404e86d23797e3868c1503c9766f3eb6ae38cefec2a8d248`).
Touch Focus Zoom and MF Subject Detection are ON; Extra Aspect Ratios starts
OFF. Retired touchscreen/rotation hooks were checked against their stock bytes.
The exact configured image passed 73 offline checks; the frozen core passed
207. Installation evidence is in
`.touch-focus/native-stock-install-20261113T080842Z/`.

Physical selector and saved-photo validation are pending. The implementation
and offline checks below do not yet establish that the camera's JPEG engine accepts every new shape,
that playback renders each crop correctly, or that a particular RAW editor
honors the crop metadata.

Settings → BF+ → Extra Aspect Ratios uses the native compact OFF/ON selector
and defaults to OFF. ON appends **65:24 (XPan), 2.35:1, and 5:4** to the
camera's native aspect choices: 21:9, 16:9, 3:2, A Size, 4:3, 6x7, and 1:1.
Choose the ratio with the camera's normal aspect control. The main display,
native editor, navigation arrows, and small status display reflect the extra
choices. Native 6x7 and the added 5:4 remain separate choices.

OFF restores the seven native choices and, when a custom ratio is selected,
returns to the most recently stored native ratio. Photos already queued keep
their captured crop. BF+ retains its 1.0 version label, title-case labels,
stock font, and uppercase ON/OFF values. Touchscreen menu and automatic UI
rotation changes are excluded from this build; center-button Touch Focus Zoom
and MF Subject Detection remain available. Focus Guide is deferred.

The selected ratio affects still-photo framing and saved JPEGs. DNG files keep
the complete native RAW pixel data and carry the corresponding framing in the
standard DefaultUserCrop tag. This permits a compatible editor to restore the
area outside the crop. The setting is resident in RAM and resets on reboot.

| Selection | Full-frame JPEG | APS-C JPEG |
| --- | --- | --- |
| XPan (65:24) | 5980 × 2208 | 3770 × 1392 |
| 2.35:1 | 6016 × 2560 | 3760 × 1600 |
| 5:4 | 4980 × 3984 | 3180 × 2544 |

These are the exact rectangles propagated through the native encoder
descriptor builder in emulation, not dimensions measured from camera files.
All starts are aligned to the JPEG engine's 16-byte address requirement, and
every rectangle lies inside an existing native buffer. Strides, allocations,
RAW storage geometry, and resizer tables remain native. Alignment causes a
small departure from perfect horizontal centering.

The half-size and 1920-class embedded previews use the same normalized image
region, with rounding for their pixel dimensions and source alignment. The
fixed 160 × 120 thumbnail retains its native content mapping. Logical live-view
geometry is centered and rounded to even pixels; its framing can differ from
the saved crop by a few logical pixels. Camera playback/face-coordinate
assumptions and editor rounding still need verification with real files.

## Capture consistency

Crop descriptors are initialized once and remain immutable. A photo records
the choice when its still settings snapshot is made, so switching to another
ratio or turning Extra Aspect Ratios OFF cannot change an earlier queued
photo's JPEG or DNG crop.

Only seven audited still-snapshot return addresses receive a validity-tagged
32-bit aspect word. At those sites, the argument to the native budget lookup
is masked to its low byte. The common metadata builder records the private
choice and returns a normal native index before the original metadata store.
Every later native array therefore receives an index in the existing domain.
Movie/type-2 requests, readiness queries, settings-copy round trips, and the
effective getter's forced-native paths remain untagged.

The private choice lives in a 192-entry sidecar indexed by the native image
database ID. JPEG selector bridges use the metadata already held in x20; the
DNG copy bridge uses x27. Each bridge checks its exact native caller and falls
back to the original behavior for unrelated calls. Release clears the choice
before the ID is returned to the native free queue. Reserve also clears the
choice after a successful dequeue, before unlocking or publishing the new ID.
This covers alternate producers and ID reuse after a native pool reset.
Untagged and foreign metadata use Native behavior; no custom choice is guessed
from a native enum.

An atomic control word couples selection, admission sealing, and the count of
tagged snapshots not yet materialized. Removal seals admission and refuses to
restore hooks while such a snapshot or a live custom photo remains. Metadata
publication precedes pending-count retirement. The allocation remains owned
until reboot, including after hooks are removed, so an already-entered wrapper
does not lose its code or tables. A capture failure that strands a tagged
request conservatively prevents removal; do not force-clear its accounting.
A native pool reset can likewise leave an unused stale sidecar entry that
blocks removal until that ID is reused or the camera restarts.

## Verification

`tests/test_native_aspect.py` executes all six original navigation sequences
with the patched step calls. It covers all ten choices, boundaries, zero-step
normalization, the original arrow instructions, all three main/editor label
calls, forced-native modes, and a mode transition between stepping and commit.
Only these UI step/commit pairs carry private positions 7–9. Native settings
and ordinary geometry/table consumers retain indices 0–6. The small display
uses its original white numeric glyphs and native centered sequence renderer;
tests check the draw coordinates and bounds before the hardware blitter.
Turning OFF with a queued custom photo is exercised through the native encoder
descriptor builder. No touchscreen/rotation hooks are needed by these tests.

`tests/test_aspect_ratio.py` executes the actual compiled adapters and the
supplied BF 1.04 JPEG descriptor builder, DNG crop copy, effective getter,
JPEG EXIF dimension stores, producer/budget sequences, metadata store, and
image-ID reserve/release paths. RTOS,
display services, and the hardware encoder are intercepted. Coverage includes
the six exact crops, preview bounds/alignment, independent queued choices,
native reuse, reserve success/failure and ID bounds, caller scoping,
saved-setting preservation, and removal refusal.
The seven budget sites are exercised across three formats, two sensor sizes,
and all three private choices.

`bfplus_camera_files.py` reads standard MTP object lists, information, and selected
JPEG/DNG objects through the existing exclusive transport lock. Its variable
length responses remain bounded and retain the base transport's transaction
and framing checks. It never captures, deletes, changes settings, or writes
camera RAM. `tests/test_camera_files.py` covers its bounds and metadata parsers.
The reader also checks JPEG EXIF pixel dimensions against the actual frame.

Before declaring the feature verified, use a fresh object-list baseline, take
RAW+JPEG photos at each ratio and Native, read back those new objects, inspect
the JPEG dimensions and DNG crop tags, and decode the JPEGs. Check framing,
playback, ordinary native ratios, and touch-focus hold/release on the camera.
The original BF__V104.bin remains unchanged; this is a reversible RAM feature,
not a flashable firmware package.
