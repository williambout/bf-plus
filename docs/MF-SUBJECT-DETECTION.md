# Manual focus subject detection

BF+ has an independent **MF Subject Detection** ON/OFF entry. With both this
option and **Touch Focus Zoom** ON, touching and holding the center button
magnifies the detected eye or face. Release returns to full view and restores
the previous zoom position. Nikon's Manual Focus Subject Detection is the
product reference. Detection alone never enters magnification; focus stays
manual and no autofocus command is issued.

The gray indicator uses the camera's native frame renderer to mark the primary
target selected by native AF detection. The firmware decides which eye/face to
select; BF+ does not rank auxiliary candidates. The box follows that target in
full live view and is suppressed during magnification and child menus. It uses
the same gray style and thin outline as native AF detection. The final gray
version is confirmed on camera: the user reported that it matches AF and that
touch zoom/release works.

The feature applies to lenses/adapters without electronic contacts. Both
options are held in RAM and reset on reboot. Installation defaults to OFF;
`--enable --subject-detection` starts both ON. The BF+ rows use native selectors
and fonts; returning from a picker preserves the selected row.

## Selection and lifetime

1. Read the native 40-byte detection snapshot twice. Reject changed snapshots
   without retrying in the consumer. This checks consistency, not freshness:
   the native data has no exposed timestamp or generation.
2. Use record zero, the primary subject chosen by native AF detection and
   consumed by the stock AF display and subject-centered zoom. A valid rectangle
   has flag 1, positive dimensions, and edges within x=0..1023, y=0..681. Auxiliary
   candidate records do not replace an absent primary target.
3. Exclude the dedicated tracker record and the producer's tracking takeover
   of the primary rectangle. With no usable detection, show no custom target
   and keep the ordinary zoom position.
4. At an eligible touch edge, establish magnification, save the old position,
   and center on the chosen rectangle using the stock clamping setter.
5. Keep that target fixed for the hold. Restore the exact old position on
   release, center press, a stock scene transition, or failed zoom entry.

The display and touch gesture share the selection routine. They sample at
different times, so a moving subject can change between the last drawn box
and the touch edge. Drawing never changes zoom ownership or gesture counters.

## Detector activation and display hooks

The stock effective detection-setting getter (`0x4d33211c0`) returns zero for
no-contact lenses. The neural buffers still update, but the detector consumer
at `0x4d326dcd4` skips candidate processing when that getter returns zero.
The extension redirects only this call through the raw-setting veneer at
`0x4d3321270`. When the effective mode is zero, both BF+ options are ON, and
lens classification is zero, it reads the native configured detection mode.
Modes 1..3 are preserved; if native detection was OFF, the explicit BF+ ON
option enables mode 1, which processes both native candidate groups. Ordinary callers of the raw-setting veneer and
all other effective-setting callers retain stock behavior. No AF setting is
persistently changed.

The display wrapper uses the snapshot veneer at `0x4d331ce50`. Only the native
frame producer's call (return address `0x4d31a74e0`) can receive an override.
When eligible and a subject is valid, the returned 20-byte display copy gets
the primary rectangle and native style 15 (gray `0x888888`, two-pixel stroke). Its local timestamp
is set to the maximum value to supersede AF status samples in that producer.
The underlying stock frame, timestamp and AF data are untouched. The stock
producer detects changes, and the stock renderer draws/clears its own frame
layer. Other snapshot callers receive the exact original data.

There are 22 pointer hooks and three instruction regions: the two branch
islands and the detector call. Original branch encodings are reconstructed
from addresses, not copied from vendor code. Installation prevalidates every
region before mutation and publishes instruction changes to caches. Removal
uses the saved immutable image and restores exact original pointers and
instructions. The State/log ABI and fixed 256-byte launcher remain unchanged.

`status` reports subject enablement, last source/position, ownership, attempts,
misses, inconsistent snapshots, and detector call/override counters. Older
saved installations remain supported. The current build is 16,192 bytes,
192 bytes below the protected staging limit; future changes must retain that bound.

## Firmware evidence

All addresses refer only to BF 1.04 segment05. Analysis uses the supplied local
`decoded-V104/rtos-alt.bin` with Capstone and Unicorn, plus read-only camera
observations. This is not REA runtime evidence. No extracted firmware
instructions or assets are included in tracked source files.

| Address | Observed interface / role |
| --- | --- |
| `0x4d3270e50` → `0x4d326ccd0` | Copies 40 bytes from `0x4d72f4168` |
| `0x4d326c4c0` | Produces four 10-byte detection/tracking rectangles |
| `0x4d326dcd4` | Effective-setting call that gates candidate processing |
| `0x4d3274b60` | Native candidate processing |
| `0x4d3319b00` / `0x4d3319b30` | Read / exactly restore `u16 point[2]` zoom center |
| `0x4d331d040` | Absolute center with native magnification/aspect clamping |
| `0x4d3398ed0..0x4d3398f20` | Stock still-view subject-centered zoom path |
| `0x4d3393300..0x4d3393350` | Equivalent movie-view path |
| `0x4d331ce50` → `0x4d3319b60` | 20-byte frame-state copy and separate timestamp |
| `0x4d31a7470` / `0x4d31a7240` | Native frame producer / renderer |
| `0x4d335b860` | Native rectangle painter and style/color lookup |

Each detection record is `{u8 valid, u8 selected, u16 x, y, width, height}`.
Record zero is the native selected target (`result+0xc` indexes the
array at `+0x1b8`). Records one/two come from `result+0x200/+0x208`, with
validity at `+0x1e8/+0x1ec`. A selected candidate at `+0x218`, gated by
`+0x214`, replaces one record and sets its selection byte to 1; `+0x210`
chooses the auxiliary record. Those candidate markers are not used to rerank
the primary target. The primary record's second byte is unused.

Record three is the separate tracker from `tracker+0x30`. That target can
also replace record zero when bit3 at `0x4d72f40d9` and mode2 at
`0x4d72f4118` are set. Both tracker paths are excluded. Offline tests execute
the original producer to verify these layouts and coordinate conversion.

## Validation

All 174 offline tests pass. Coverage includes targeting, tracking exclusion,
inconsistent/invalid snapshots, native clamping, entry failure, restoration,
menu interactions, activation caller isolation, exact installation/removal,
and rejected mismatched instructions. The frame tests execute the supplied
firmware's real producer and renderer through the relocated wrapper: native
primary target, gray stroke, movement, loss, option/lens/scene gating, AF status
precedence and unaffected unrelated callers. Direct comparison tests execute
the unmodified native AF display and original subject-center block using the
same detections, verifying identical rectangle drawing and zoom coordinates.
Auxiliary candidates cannot displace the native primary, even with marker 1.

On 2026-11-12, the initial 180-second manual-lens test produced no valid
face/eye records despite changing tracker data. With a visible face, a later
read-only baseline found neural confidence scores above the native threshold
while output rectangles remained empty. After the activation build was
installed, a valid face record appeared immediately.

The subsequent 60-second gesture observation reached 27 targeting attempts
and 11 misses. It used the earlier candidate-ranking implementation, with
records zero, one and two all observed as chosen targets. All 15
completed targeted holds captured by the observer restored the exact saved
point, including the user's newly chosen `(690,314)` baseline. The final
targeted hold was still active at the observation boundary. There were no
replay/exit errors or inconsistent target snapshots. Sampling is sequential
and not atomic. The user confirmed: **“Yes — centers and returns.”**

Local ignored evidence includes `mf-activation-baseline.json`,
`mf-activation-live.jsonl`, `mf-activation-gesture.jsonl` and
`mf-activation-gesture-analysis.json` under `.touch-focus/`.

Remaining hardware checks: electronic-lens exclusion, center-press replay,
and movie-mode behavior. Offline tests do not establish
physical display timing, cache coherence, or movie behavior. The snapshot
consistency check is not a freshness guarantee.

The earlier green-indicator build was installed with all 22 pointer hooks and three
instruction regions verified. Live frame-state readback shows native style 6
following the same detection rectangles, clearing on loss and during touch
magnification, and returning on release. The user confirmed **“Yes — box follows, clears, and zoom works.”**
They then requested gray indicators and the same detection logic as AF. The
revised build follows the native primary selection instead of ranking candidate
records, and uses native gray style 15. Evidence from the green version: `.touch-focus/green-frame-live.jsonl`.

An earlier 16,384-byte candidate encountered a PTP transaction-ID mismatch
while verifying its upload, before its activation trigger. The prior build
had already been removed cleanly. A read-only reconnect also found a stale
response, so the camera was power-cycled. A fresh read-only status then proved
stock hooks and idle live view. That validated green replacement used 16,320 bytes
and at most 4096 bytes per readback chunk; installation then completed with a
fresh nonce, successful storage callback result and restored page permissions.
The precise cause of the original protocol mismatch is not established.

The final native-selection/gray build was installed at `0x4475bf000`, with all
22 pointer hooks and three instruction regions verified. Its 16,192-byte image
matches the validated source/build, apart from the expected initial ON flag.
The user confirmed **“Yes — matches AF and zoom works.”** Final status and
frame readback are retained in `.touch-focus/native-af-frame-final-verification.json`.
