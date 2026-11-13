# BF+ v1.0

This is an original, reversible RAM extension for the analyzed Sigma BF 1.04
build. It does not produce a modified firmware update. Power cycling removes
the extension and resets its options; installation requires the
[MTP connection setup](ROOT-SHELL.md#2-put-the-camera-in-mtp-mode).

**BF+** is appended to Settings as a submenu. It contains **Touch Focus Zoom**
(OFF/ON), **MF Subject Detection** (OFF/ON, initially OFF), **Extra Aspect Ratios**
(OFF/ON, initially OFF), and **Version — 1.0**. Extra Aspect Ratios adds XPan
(65:24), 2.35:1 and 5:4 to the native aspect chooser. Disabling it restores the
native list and stored native selection. The reduced build was installed on
2026-11-13 with Touch Focus Zoom and MF Subject Detection ON and Extra Aspect
Ratios OFF. Native chooser interaction and saved-photo crops await validation.
Press center/right on an editable option to open the native compact selector.
Up/down or the dial changes the tentative selection;
center/right confirms and left cancels. Version is read-only. With Touch Focus Zoom
ON and a lens/adapter without electronic contacts attached, touching the center
button magnifies live view for as long as contact remains. Release requests the
stock scene exit. Pressing the center button exits the temporary magnification
and forwards the press to the normal UI. Existing magnification is not owned by
this feature. LCD menu input and automatic UI rotation are not included in the
replacement; native button/dial navigation, fonts and layout are retained.

With both options ON, center-button touch uses a valid stock eye/face detection
to choose the magnified area. It follows the primary target already
selected by native AF detection, including its eye/face choice. Without a usable
selected target it keeps the current zoom position.
The target is chosen once per touch and stays steady while held. Release
restores the previous zoom position. Focus remains manual. Detection alone
does not enter magnification. This targets lenses/adapters without electronic
contacts, matching Touch Focus Zoom's existing scope.

Native detector activation, eye/face centering and release restoration are
confirmed on camera. A native gray rectangle now identifies the chosen subject in
full live view using the native frame renderer. The user confirmed that the
final gray box matches AF and touch zoom/release works. Details and remaining checks are in
[MF-SUBJECT-DETECTION.md](MF-SUBJECT-DETECTION.md).

## Validation status

The current reduced build has 15,808 initialized bytes, a 21,440-byte resident
extent and no compositor scratch. All 39 pointer hooks and 34 code patches,
immutable resident code, permissions and settings verified after COMMIT; old
rotation and LCD menu-control sites verified stock. USB closed successfully.
The previous RAM extension was already absent at preflight, so that attempt
made zero writes; a separately recorded fresh installation followed a complete
stock audit. Every actual transfer was bounded to 4 KiB with the write cooldown.
The frozen source passed 249 distinct integrated tests, including execution of
the exact configured image, plus six installer audit/removal/journal tests.
These checks do not establish physical chooser behavior or saved-file crops.

The observations and sizes below describe earlier installed focus-feature
builds. The current reduced replacement retains these focus features and uses
the bounded segmented loader; it excludes rotation and LCD menu controls.

The earlier native-AF indicator build passed all 174 offline tests. Its image is
16,192 bytes, 192 bytes below the staging limit, with the first 256 launcher
bytes unchanged from the previous installation. Relevant source hashes were
checked before and after testing/building; installation checks the resulting
image digest against that validation record.

The detector activation build was installed with 21 pointer hooks and two
instruction regions verified. The user confirmed that touch magnification
centers on the eye/face and returns on release. A 60-second observation reached
27 attempts, using all three candidate records in the earlier selection logic,
and 11 misses. All 15
completed targeted holds captured in that observation restored the exact saved
position, including a user-changed baseline; replay/exit errors stayed zero.
The indicator adds one display-only snapshot hook (22 pointer
hooks and three instruction regions total). Its native producer/renderer tests
cover gray color, movement, loss, option disabling, and zoom/menu suppression.
Direct comparisons execute the original AF display and subject-center code: the
manual extension now selects and draws the same primary rectangle. It also uses
the native configured detection mode when enabling processing for manual lenses.

The first RAM prototype was installed on the user's BF 1.04 on 2026-11-12.
The user confirmed that its BF+ toggle worked and magnification followed touch
and release. Live logs recorded six entry/exit cycles with lens classification
zero, and three further touch/release cycles with the option OFF that stayed in
ordinary live view. The callback, page permissions, and all 19 hooks verified;
no replay or exit errors were recorded.

The v1.0 submenu opened and toggled correctly on hardware, with all 20 hooks,
callback restoration, and code-page permissions verified. The first submenu
build exposed missing lowercase glyphs in the stock label font. The native
font-switch control selects the matching regular font for all custom labels
and values, with title-case labels and uppercase ON/OFF values. A read-only capture of the native menu and a comparison using actual
camera glyph bitmaps established the matching typeface. The font and compact
selector changes are installed in the combined build: all 20 hooks, the
completion nonce, storage callback and restored page permissions verified.
Touch Focus Zoom was preserved On; MF Subject Detection initially started Off.
The user confirmed the final title-case typography and compact selector on
camera. Live observation recorded 14 touch/release zoom cycles with zero replay
or exit errors. Final RAM readback verified all six strings and font6 for every
submenu value. Both options were On after the user's test; subject targeting
recorded 14 attempts, all without a usable detection, and no position changes.

The subsequent uppercase ON/OFF correction passes all 55 menu tests, including
the native picker measurement/render paths. It changes only three string bytes
in the compiled image. The camera's two shared option strings were updated in
one verified 11-byte RAM span; executable code, current option settings, and
the original immutable removal image were retained. The installation record
tracks this text update separately. Menu labels remain in title case.

The user's open Shutter Blackout selector matched the analyzed scene descriptor
on the camera. BF+ reuses its native popup painters with uppercase ON/OFF choices and a
private descriptor and input handler. Its confirmation changes only the
extension's option; the stock Shutter Blackout getter and setter are not called.

Electronic-lens exclusion, the center-press replay path, and movie-mode behavior have offline
coverage but have not all been exercised on hardware. Release latency has not
been instrumented; the user confirmed the perceived behavior.

## Build and use

Requires Python 3.11+, PyUSB/libusb, Clang with AArch64 support, LLVM tools, and
lld. Capstone and Unicorn are needed for the offline tests.

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements-bfplus.txt
.venv/bin/python bfplus_cli.py build
.venv/bin/python -m unittest discover -s tests

# Read-only identity and current state:
.venv/bin/python bfplus_cli.py status

# Camera must be awake, idle in still shooting live view, and connected by MTP.
# Installs with Touch Focus Zoom OFF; the original update is read and hashed only.
.venv/bin/python bfplus_cli.py install --firmware /path/to/BF__V104.bin

# Or install with both BF+ options ON:
.venv/bin/python bfplus_cli.py install --firmware /path/to/BF__V104.bin --enable --subject-detection

# Observe physical state and decoded handler events (read-only):
.venv/bin/python bfplus_cli.py observe --seconds 60

# Development controls; Settings > BF+ > Touch Focus Zoom is the normal control:
.venv/bin/python bfplus_cli.py enable
.venv/bin/python bfplus_cli.py disable

# Return to still live view and release the center button before removal:
.venv/bin/python bfplus_cli.py remove
```

Only the analyzed package is accepted (SHA-256
`0c6cb624967c0d2254fa3e532ea25f389f09b007e9e31788df7e9682995e478b`).
Live function fingerprints, callback state, original pointers/instructions, and the
page-table descriptor must also match. Generated code, transaction cooldown,
and the installation record are kept in ignored `.touch-focus/`. Keep that
directory until removal; the saved original payload is used even if sources
change after installation.

## Transport and recovery

Each vendor RAM write also schedules the camera's normal calibration flash
save. The tool never targets the calibration block, but installation is **not
flash-free**. It submits one payload and one trigger, checks readback, enforces
at least ten seconds between writes, and never automatically repeats a failed
write. Do not run the older shell/display tools concurrently; they do not share
the new process lock or cooldown record.

A fresh random completion nonce is written after the installer operation and
the original storage callback return. The storage writer's result is checked.
Callback restoration alone is not treated
as proof of completion. A missing nonce or transport failure means the outcome
is uncertain: do not repeatedly retry. Power cycle to restore the stock state.

The resident code lives in an allocation obtained from the stock RTOS allocator,
separate from the PTP response buffer. Removal restores pointers, instructions and code-page
permissions. The allocation stays reserved until reboot because queued callbacks
may still reference it. No permanent firmware patch or automatic boot loader is
installed.

The v1.0 loader uses a fixed entry prefix that cleans the uploaded data and
invalidates instruction caches before entering the C installer at offset
`0x100`. This prefix remains identical across C-code updates. The first launch
uses the repository's established RAM execution method; a successful hardware
run verifies that particular attempt, not every possible cache history. The
original prototype's saved image is retained for its removal, and v1.0 uses a
separate staging location so it does not initially replace cached prototype
instructions.

## Implementation boundaries

- Only center Touch (key bit 0) starts magnification. Push and repeat are distinct.
- Lens classification must be zero (no electronic connection); electronic or
  transitional/error classifications cannot start the feature.
- Stock magnification uses the indefinite hold setting. Release is handled by
  the key callback, with a periodic callback as a fallback using raw contact.
- A temporary 1× setting is raised to 2×, then restored on exit. Existing larger
  magnification levels are retained.
- Center presses are copied to the stock UI queue without blocking. A full queue
  increments `replay_errors`; that press can be lost. The tool never waits for
  space from within the queue's own consumer.
- Offline emulation stubs stock services and skips privileged cache operations.
  It verifies the generated control flow and memory updates, not hardware cache
  coherence, real UI scheduling, or image rendering.

Input evidence is in [TOUCH-FOCUS-INPUT.md](TOUCH-FOCUS-INPUT.md). Menu analysis
is in [TOUCH-FOCUS-MENU-NOTES.md](TOUCH-FOCUS-MENU-NOTES.md). Extracted firmware,
disassembly, and vendor bytes remain local and are not included in the sources.
