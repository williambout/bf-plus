# BF+ package interface

The segmented RAM loader and `bfplus_cli.py` implement this contract using
the `bfplus-segmented-v1` manifest and loader ABI 1. The implementation is tested
offline; it is not a flashable firmware format or a claim of camera installation.
See [SEGMENTED-LOADER.md](SEGMENTED-LOADER.md) for the binary ABI, host API,
archived artifacts, phase recording and exact removal path. Firmware packaging
remains a separate investigation.

## Artifact boundary

Separate the small transport bootstrap from the resident extension. Future
firmware packaging needs the resident code, its initialization contract and
memory requirements; it does not require embedding the USB storage-callback
entry point. The two binaries can be built together but should have independent
identities and symbol maps.

The versioned package descriptor has these semantics. The C ABI is defined in
`bfplus/loader_abi.h`; the CLI records its native receipt in `loader_record`.

| Item | Required meaning |
| --- | --- |
| Format/loader ABI version | Distinguish segmented packages from existing single-image installations |
| Target identity | Original package SHA-256, analyzed RTOS SHA-256, and expected native fingerprints/hook bytes |
| Bootstrap | Immutable bytes and SHA-256, entry/control offsets, symbol offsets; initialized size at most `0x4000` |
| Resident image | Immutable initialized bytes and SHA-256; may exceed one transfer; contains no extracted vendor code |
| Resident layout | Initialized extent, BSS start/end, full resident extent, alignment, extra scratch extent/alignment |
| Resident entry contract | Symbol offsets and ABI for initialization, installation/removal and state inspection; document readiness requirements |
| Hook manifest | Expected original pointers/instructions and affected ranges, sufficient to validate and reverse the exact installed version |
| Features | Exact included feature set and its validation status; unfinished Focus Guide must remain identified as incomplete |

Keep symbol offsets relative to their owning image. Do not confuse bootstrap
offsets, resident offsets, staging addresses and allocated runtime addresses.
Record an explicit resident size bound; the existing `0x10000` bound is not
automatically enlarged by allowing multiple transfers. Retain relocation and
section validation, including the compiler model's addressing constraints.

The standalone loader is 2,944 bytes. Resident image/memory extents come from
each build's symbols, with a 64 KiB maximum. The reduced native-menu build has
`__scratch_size=0`. Archived portrait/global-UI builds used `0x4a9800`
(4,888,576 bytes); removal still uses their saved extent. The guarded
allocation also includes a 256-byte prefix and up to 4,095 alignment bytes.
These extents are checked for overflow, overlap and supported RAM range.

## Installation protocol properties

The host helpers expose prepare, load, commit and remove phases. Each command
uses the small immutable loader artifact; resident chunks never overwrite the
loader or its separate control block.

1. Prepare a guarded allocation and identify it with a fresh installation
   nonce. Confirm callback restoration, writer result and completion before
   treating the returned address as usable. No resident UI hooks are published.
2. Upload initialized bytes in bounded transfers into that known allocation.
   Actual segmented READ and WRITE payloads are at most `0x1000` (4 KiB).
   The transport/staging hard cap remains `0x4000`; larger loader artifacts
   are staged with multiple cooldown-protected subwrites, then verified in
   full before triggering. Every subread must have exact length. These bounds
   avoid the observed 16 KiB transfer corruption/framing boundary; the precise
   native cause is still under investigation.
   Preserve the shared lock, persisted cooldown, exact readback and prohibition
   on automatic retries after uncertain writes. Each write can schedule a
   calibration flash save; batching is not permission to bypass the cooldown.
3. Verify all initialized bytes and their complete identity before commit.
   Host readback/hash verification and installer-side state/extent checks must
   be explicit. A host hash is not an implemented on-camera hash check.
   Reject missing, overlapping, stale or out-of-range portions. Keep the
   incomplete resident image unreferenced by hooks and callbacks.
4. Zero the declared BSS, initialize required state/scratch, and publish caches
   for the complete executable resident range. The fixed bootstrap launcher's
   16 KiB cache-maintenance range does not cover a larger resident image.
   Recheck the target's idle/readiness state and original hook values before
   publication. Installation success requires the exact expected hooks,
   restored permissions/callback, successful writer result and fresh nonce.
5. Removal uses the immutable package corresponding to the actual installation.
   Restore its exact original hooks and permissions. Do not free memory while
   queued callbacks may still reference it; retaining it until reboot is the
   current established strategy. For global UI builds, the CLI first verifies
   the saved identity/code/guard and aspect pending/jobs state, sets the exported
   UI `removing` field, and waits for landscape, ready input, and no active frame.
   It does not change the user's Auto Rotate UI option. The resident rechecks
   that drain condition before sealing aspect work and removing hooks.

The CLI archives `loader-<sha256>.bin` and `resident-<sha256>.bin` without
overwriting existing files. `installation.json` includes both symbol maps,
layout and immutable ELF section ranges, original package/RTOS hashes, native
fingerprints, exact pointer/code hook tables, and feature metadata. Artifacts
are synced before the manifest; every command/chunk/drain intent is atomically
recorded and synced before its write. Installed code comparisons exclude
mutable initialized data and BSS. Legacy manifests retain their archived image
and original single-image removal path; no current build is used to remove one.

Native aspect call-site tables are read from the same restricted
`ASPECT_NATIVE_STEP_CALLS`, `ASPECT_NATIVE_LABEL_CALLS` and
`ASPECT_NATIVE_SUBLCD_CALLS` macros in `bfplus/aspect_ratio.h` that the
resident compiler uses. Parsing rejects malformed syntax and duplicate sites;
installation rechecks the header before any write. New builds contain no
global UI compositor, rotation adapters or LCD menu-input hooks.
The resulting exact tuples are stored in each installation manifest. Removal
and status use those saved tuples, including the installed version's aspect
hooks; later source edits do not redefine the saved installation.

The installer must distinguish prepared/loading/committed/removed states and
uncertain completion. A host interruption or stale on-disk manifest must not
cause writes to an allocation from a previous boot. Do not automatically resume
an uncertain installation based only on a saved address. Preserve the ability
to inspect state and recover by power cycling without executing partial code.

Transport bootstrap staging must remain isolated from response buffers,
resident chunks, control data and any executing code. A larger resident image
does not justify enlarging the staging window or lifting the transport cap.

## Compatibility and verification

Existing installed images and manifests are immutable compatibility inputs.
Retain their status/removal path and original saved bytes even if the new source
uses another ABI. Never regenerate an old remover from current sources. Keep
the existing small-image path during migration where practical; the essential
guarantee is that an already-installed version remains identifiable/removable.
The CLI now requires both expected L2 descriptors even for legacy removal;
offline compatibility tests preserve the archived executor path and verify a
second-descriptor mismatch causes no dispatch, write or manifest change. This
legacy rejection path is covered offline; both descriptor values were checked
on hardware during the 2026-11-13 reduced-build installation. Host idle checks also
require the native node-replacement and depth-request fields to be idle, since
node replacement can be pending without a depth change.

Offline verification should cover images on both sides of the 16 KiB boundary,
multiple chunks and a short final chunk, full-image readback corruption,
allocation/alignment/extent failures, BSS initialization, complete cache-range
publication, failure before commit with original hooks intact, stale nonces,
interrupted loading, exact removal, and legacy-manifest compatibility. Stubbed
cache operations do not establish hardware coherency. Native chooser behavior
and saved-photo crop metadata need their own camera validation.

Firmware integration remains a separate entry contract after RTOS services
are ready. It must not invoke the USB bootstrap with invented storage-callback
arguments. The two system-image/update paths and flash recovery are still
unresolved, as documented in [CUSTOM-FIRMWARE.md](CUSTOM-FIRMWARE.md).
