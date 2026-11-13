# Standalone segmented RAM loader, ABI v1

This implements the RAM-loading portion of
[BFPLUS-PACKAGE-INTERFACE.md](BFPLUS-PACKAGE-INTERFACE.md). It separates the
small storage-callback bootstrap from the resident image and supports multiple
bounded transfers without increasing the resident's 64 KiB limit. The
`bfplus_cli.py` CLI now uses it for new installations and preserves legacy
status/removal. Offline tests cover loader and transport failure paths. A fresh
4 KiB-transfer installation was completed on BF 1.04 on 2026-11-13, including
full readback, COMMIT, installed-code/hook/settings checks and USB closure.
Physical UI and saved-photo validation are tracked separately.

The standalone loader is **2,944 bytes** with the local LLVM toolchain. Its
linked first 256 bytes match the existing `launch.S` linked against an entry
at `+0x100`. `launch=0`, `bootstrap=0x100`, and the separate `loader_control`
currently starts at `0xa80`; consumers must use the returned symbol map.
The immutable artifact contains a zeroed control block. The host changes only
that block when staging a command, leaving the launcher and code identical.

## Files and build boundary

- `bfplus/loader_abi.h`: versioned control, guard, operation and result ABI.
- `bfplus/loader.c`, `loader.ld`: standalone bootstrap; no resident UI hooks.
- `bfplus/loader_build.py`: isolated loader compiler/linker and layout checks.
- `bfplus_loader.py`: host protocol helpers with caller-supplied verification.
- `tests/test_segmented_loader.py`: compiled AArch64 and host/emulator tests.
- `bfplus_cli.py`, `tests/test_touch_cli.py`: CLI, durable package manifest,
  immutable artifact storage, UI drain, and legacy compatibility.

Build or test entirely offline:

```sh
.venv/bin/python -m bfplus.loader_build
.venv/bin/python -m unittest tests.test_segmented_loader -v
```

`loader_build.build()` returns `(blob, symbols)` using temporary output. An
explicit `build(directory)` or CLI `--out DIRECTORY` retains `loader.bin`,
`loader.elf`, objects, and `loader.json`. The shared `.touch-focus/build`
directory is rejected. The production `build.py` is neither imported nor run.
The builder uses tiny-model AArch64 PIC, validates relocation kinds and every
allocated section, rejects undefined runtime helpers/BSS, and enforces the
fixed entry, control placement and `0x4000` upload bound.

## Resident entry contract

The shared declaration is:

```c
uint32_t resident_entry(uint32_t operation,
                        const struct LoaderControl *control,
                        uint64_t ctr);
```

Operation 0 installs; operation 1 removes. Return zero for success. Before
publishing hooks, the resident must validate its own compiled image/memory/
scratch extents, base, ABI, mode, installation nonce, expected originals,
idle scene and L2 descriptor. It initializes state/menu/aspect and cleans that
initialized state before its atomic `patch_all` publication. Loader cache work
before entry does not publish writes that the resident subsequently performs.
On removal, validate resident identity/owner and active state, restore the exact
installed hook set and permissions, and leave queued wrappers safe. Nonzero
entry returns must leave hooks unchanged; the loader cannot roll back unknown
resident code. The resident entry must not call the USB storage writer.

The entry receives a temporary **stack snapshot** of `LoaderControl`; do not
retain its pointer. `identity_nonce` is stable for this allocation, while
`request_nonce` is fresh for each command. The allocation fields are:

| Field | Meaning |
| --- | --- |
| `owner` | Original allocator result; retained until reboot |
| `resident` | 4 KiB-aligned image base |
| `guard` | `resident - 256` |
| `image_size` | Exact initialized byte count, including initialized data |
| `memory_size` | Resident image plus zero-initialized tail |
| `scratch_size` | Extra storage beginning at `resident + memory_size` |
| `entry_offset` | Offset of the exported entry within initialized bytes |
| `image_crc32` | Standard reflected CRC32 of immutable initialized bytes |
| `image_sha256` | Host SHA-256 identity, stored/bound but not computed by device |

The loader enforces `4 <= image_size <= memory_size <= 0x10000`, memory and
scratch multiples of 64, mode 0 or 1, and an instruction-aligned entry with all
four bytes inside the image. Scratch can be zero through **16 MiB**. The
earlier `0x155000` portrait requirement and current **`0x4a9800`** combined
requirement both fit. Pass the resident build's `__scratch_size` value; do not
infer it from image length. The loader zeroes `[image_size,memory_size)` only;
scratch initialization belongs to the resident/renderer.

## Guard and command state machine

Both `LoaderControl` and `LoaderGuard` are 256 bytes, little-endian, ABI version
1. The C header is authoritative. Control completion `done` is at byte 24;
SHA-256 identity is at byte 160; `transport_buffer` and `allocation_size` are
at bytes 192 and 200. Reserved fields must remain zero.

| Command | Value | Required guard phase | Success phase |
| --- | ---: | --- | --- |
| PREPARE | 1 | No supplied allocation; control phase EMPTY | PREPARING (1) |
| COMMIT | 2 | PREPARING (1) | COMMITTED (3) |
| REMOVE | 3 | COMMITTED (3) | REMOVED (5) |

COMMITTING (2) and REMOVING (4) are published before attempting the entry.
The resident observes that in-flight phase in its control snapshot. CRC,
post-CRC gate, or resident-entry failures mark the guard FAILED (6). Invalid
ABI, extents, nonce, identity or phase are rejected before that transition.
The host has additional `preparing`, `prepared`, `loading`, `verified`,
`committing`, `committed`, `removing`, `removed`, and `uncertain` manifest phases.

PREPARE allocates:

```text
allocation_size = 256 + 4095 + memory_size + scratch_size
resident = align_up(owner + 256, 4096)
guard = resident - 256
```

Every later operation revalidates this arithmetic and all guard identity
fields: nonce, owner/base, extents, entry, mode, CRC and SHA bytes. The full
allocation must fit `0x400d20c00..0x500000000` without wrapping, and must not
overlap the executing/readback buffer or the known RTOS code/static-data range
`0x4d3000000..0x4d7400000`. The allocator is `0x4d330c850`; it receives the
computed size, region `0x400000000`, zeros, output pointer and timeout 100.
Invalid allocator results are never dereferenced or freed.

The guard prefix is outside resident transfers. PREPARE writes only the guard
and completion, leaving resident bytes unreferenced by UI hooks. A fresh random
64-bit host nonce identifies the allocation; COMMIT/REMOVE use distinct new
command nonces, and the guard rejects reuse of its last request/identity nonce.
There is no guard write API or disk-based loading-resume API in the host helper.

COMMIT computes CRC32 over **every initialized byte** before executing it,
zeros BSS, performs `dc cvac` and `ic ivau` across the **whole resident extent**,
and rechecks idle/L2 before calling the resident entry. This is separate from
the launcher's 16 KiB staging cache publication. REMOVE calls the same
`resident + entry_offset` stored in the guard. It neither uploads a newly built
remover, zeroes resident state, nor frees the allocation. Initialized resident
data may change after installation, so removal does not recompute the original
whole-image CRC. Exact installed state/code/hook validation belongs to the
resident and the parent's removal preflight.

CRC and guard checks detect corruption and stale/mismatched state; they are not
a signature or protection against a hostile host that already has arbitrary
RAM-write access. SHA-256 is computed and checked on the host, not on camera.

## Native execution gates and completion

The bootstrap restores `ORIGINAL=0x4d31254f0` at `CALLBACK=0x4d729bd00` first,
then reads control. It requires CurrentEL=4 (EL1),
`[0x4d71484c8] == 0x4d3200781`, depth 2, pending 12, and the four existing
idle-still scene pointers at `0x4d7301c00`. It never changes L2 permissions.
The resident's publication/removal path owns any necessary temporary change
and exact restoration. The host checks both L2 descriptors, including
`[0x4d71484c0] == 0x4d3000781`, before and after commands. Host and resident
also require node replacement state `[0x4d703469c] == 12`: a native root/node
replacement can be pending even while the requested depth at `0x4d70346a4`
remains 12. This additional node gate is not implemented in the standalone
loader; it is enforced by the CLI idle callback and resident entry.

The storage callback's original block/count/buffer arguments are preserved.
After the operation, the real writer runs exactly once. Its return value is
stored in `storage_rc` and returned to the caller. Outputs are published before
`done=request_nonce`, which is written last. A restored callback alone is not
completion. A nonzero writer result can coexist with a successful resident
installation: the host records **uncertain**, retains the actual receipt, and
does not retry or automatically remove it.

Loader result codes are defined in `enum LoaderResult`: 0 success; 1 ABI;
2 EL; 3 L2; 4 idle; 5 extents; 6 allocation; 7 range; 8 guard identity;
9 phase; 10 CRC; 11 resident entry; 12 command; 13 nonce. `entry_result` keeps
the resident's exact nonzero return. Errors do not authorize retrying an
uncertain operation; failed/incomplete allocations remain retained.

## Host API and integration

`bfplus_loader` imports neither `bfplus_cli` nor USB libraries. It accepts
an already-open `bfplus_ptp.PTP` context. All writes go through its existing
`write()` method, preserving the workspace process lock and durable cooldown.
The helpers hold that same context's `_io_lock` across each operation (across
the whole sequence for `execute`). Actual segmented READ and WRITE payloads
are limited to **`0x1000` (4 KiB)** each. The immutable loader/staging hard cap
remains **`0x4000` (16 KiB)** and the resident memory cap remains **64 KiB**.
Larger loaders are staged in contiguous 4 KiB subwrites, each through the same
cooldown-enforcing `p.write()`. Complete staged-byte readback must succeed
before the callback trigger. Resident chunks, complete-image verification and
CLI installed-code/status reads also use the 4 KiB transaction limit. Every
subread must return exactly the requested length; a short/oversized read or
transport exception stops immediately.
There are no write retries, new transport sessions, direct `_exchange` calls,
cooldown deletion, endpoint resets, or automatic uncertain recovery. Read-only
polling waits for asynchronous readback/completion within a bounded timeout.

The loader stages at `read_buffer + 0xc000` inside the observed `0x10080` read
buffer allocation; READ data containers occupy at most `0x100c` bytes,
including the 12-byte PTP header. The C
loader verifies that its own runtime address and `[0x4d72c2230]` agree with the
supplied transport buffer. Allocation guards exclude the entire transport
buffer, including code/control. A different response buffer during loading is
rejected. Each vendor RAM write can still schedule a calibration flash save;
segmentation does not bypass the established cooldown.

The 4 KiB limits follow a failed 16 KiB resident transfer. Readback reported
the expected image's last four chunk bytes as a PTP transaction ID, and a later
session encountered the old response. After USB reconnect, bounded read-only
inspection found native hooks, a completed PREPARE control and matching
PREPARING guard. Resident bytes `0..0x3ff3` matched; the last 12 bytes had become
the header of a READ command (`size=20`, `kind=1`, `operation=0x900b`, `tid=2691`).
That RAM corruption requires bounding writes as well as reads. The lower-level
buffer/framing mechanism remains unproved. Offline tests enforce both limits;
this change alone is not evidence of a successful hardware installation.

The subsequent fresh hardware attempt used 14 resident writes (13 × 4 KiB and
320 bytes), plus the 2,944-byte PREPARE/COMMIT loader and 8-byte callback writes.
Every write used the existing cooldown. Complete readback matched the 53,568-byte
MF-on image before COMMIT, and installed-code/hook checks passed afterward.
The committed image SHA-256 is
`853fcaf3aec66b1181cba4e1076b20a4218a3d7d41534e95d9b3b9bac34325e3`.
The prior uncertain receipt was preserved; its partial allocation was never
resumed or passed to REMOVE.

There is no PREPARING-abort/free command. Keep a failed allocation unreferenced
until a physical power cycle; do not invoke REMOVE on partial resident code,
resume an old `Prepared`, or relabel an uncertain receipt as removed/committed.
Preserve the original receipt and diagnostic evidence. After recovery, the sole
installer must verify native hooks, callback, both L2 descriptors and idle state
before recording a separate new attempt with a fresh PREPARE nonce/allocation.
USB reconnect clears neither the old allocation nor the uncertain manifest.

Construct the immutable inputs and supply parent verification callbacks:

```python
from bfplus_loader import LoaderArtifact, ResidentImage, Checks, execute, remove
from bfplus.loader_build import build as build_loader

loader_bytes, loader_symbols = build_loader()  # temporary offline build
loader = LoaderArtifact(loader_bytes, loader_symbols)
resident = ResidentImage(
    resident_bytes,
    memory_size=resident_symbols['__end'] - resident_symbols['__start'],
    entry_offset=resident_symbols['resident_entry'] - resident_symbols['__start'],
    scratch_size=resident_symbols['__scratch_size'],
    expected_sha256=expected_resident_sha256,
)
checks = Checks(check_callback, require_idle_still, package_preflight)

# p is the caller's existing opened PTP context. These calls are NOT run here.
record = execute(p, loader, resident, checks=checks,
                 on_phase=save_segmented_phase, mode=initial_mode)
base = record['control']['resident']
# Later, supply the exact archived artifacts and committed record:
removed = remove(p, loader, resident, record, checks=checks,
                 on_phase=save_segmented_phase)
```

The callbacks have these signatures and obligations:

| Callback | Contract |
| --- | --- |
| `check_callback(p)` | Raise unless the storage callback is the expected original |
| `idle(p)` | Raise unless installation/removal is allowed in the current scene |
| `preflight(p, command, record)` | Verify target/package fingerprints and the appropriate original or exact installed hooks/state/code; return current read-buffer address |
| `on_phase(record)` | Synchronously persist a copied JSON-compatible record durably before returning; raise on failure |

`preflight` runs **before and after** commands. Post-command phases are
`prepared`, `committed`, and `removed`; verify originals for prepared/removed,
and the exact expected installed state for committed. It also runs before
loading with command COMMIT and phase `loading`. In that case the nested
control is the last PREPARE receipt, not a new COMMIT request. The command
argument and host phase identify which checks to perform. Hook/target checks
are mandatory parent responsibilities; a no-op callback is not sufficient.
Postcondition failures are uncertain outcomes and never trigger a retry.

The individual helpers are:

```python
session = prepare(p, loader, resident, checks=checks, on_phase=save, mode=0)
load(p, session, checks=checks, on_phase=save)
record = commit(p, session, checks=checks, on_phase=save)
```

`prepare` returns a `Prepared` object bound to the current transport object and
lock-file lifetime. `load` accepts it only once, writes contiguous chunks from
offset zero with no overlap/gaps, verifies each exact chunk, then compares the
full image and its SHA/CRC. `commit` requires the verified state and repeats
complete readback immediately before its command. Any interrupted loading or
commit invalidates the live session. Do not construct a `Prepared` object from
a saved manifest or manually alter its fields. An old address/nonce on disk
does not authorize new uploads after a reconnect or reboot.

The returned format is `bfplus-segmented-v1`; its `control` dictionary contains
the allocation, identities, extents and native receipt. Loader/resident SHA-256
identities are also recorded at top level. Parent manifests must additionally
archive the exact immutable binaries/symbol maps, original target identity,
hook manifest, and feature metadata from the package contract. These helpers
do not write files or invent those package-level facts. A storage or completion
failure records `uncertain`, even if the guard may already be COMMITTED.
Read-only inspection/power cycling is the established recovery boundary.

Keep the existing legacy installer/status/removal path. `remove` rejects
legacy-format records, uncertain records, and mismatched artifact identities
without uploading a replacement. It accepts a saved committed segmented
record only after guard and parent installed-state checks. Never regenerate an
old package's remover or symbols from current sources.
The CLI's current preflight requires both expected L2 descriptors even for
legacy removal. The legacy compatibility test checks that correct descriptors
preserve the archived executor path and that a second-descriptor mismatch
causes no dispatch, camera write or manifest change. This added gate remains
hardware-unverified.

## CLI package and removal integration

`bfplus_cli.py build` builds both artifacts offline and prints resident
layout, symbols and the loader identity. New `install` operations verify the
original firmware package and native fingerprints, then use segmented
`execute()` with the shared PTP transport. The legacy `execute()` function
retains its `0x4000` cap and is used only for archived legacy removal.

The CLI archives exact content-addressed `loader-<sha256>.bin` and
`resident-<sha256>.bin` files in `.touch-focus/`. It rejects a conflicting existing
file. Neither artifact is regenerated during removal. The loader archive's
control block remains zero; per-command modifications exist only in staged RAM
copies. `installation.json` records:

- `format=bfplus-segmented-v1`, `abi_version=1`, and the current host `phase`;
- resident `image`, `image_sha256`, `symbols`, and `layout`;
- `loader.image`, `loader.sha256`, and `loader.symbols`;
- `target` package/RTOS hashes, unchanged native fingerprints and both L2 values;
- exact `patches` and `code_patches`, plus installed feature metadata;
- `loader_record`, the complete helper receipt, with installation `nonce` and
  resident/base fields mirrored at top level for status compatibility.

`layout.immutable_ranges` and `executable_ranges` come from the exact linked
ELF, validated against the initialized image. Status/removal compare the saved
immutable resident sections in reads of at most `0x4000`, and validate the saved
hook map, resident magic/version/nonce and allocator owner. Mutable `.data`
and BSS are not compared to their original image bytes. Guard validation runs
before removal or a segmented mode write. UI code hooks are obtained from
`UI_CALLS`/`UI_ROW_CALLS` in `ui_hooks.h`,
`UI_IMAGE_ANCHORS_BL_HOOKS` in `ui_image_anchors.h`, and
`UI_IMAGE_ANCHORS_EXTRA_BL_HOOKS` in `ui_image_profiles.h`, then frozen in the
manifest. The anchor macros supply 14 root and four profile calls and accept
only literal `(source, target)` pairs: original
`BL source,target` becomes `BL source,UI_ISLAND`. The parser rejects malformed
syntax and duplicate sites. It reads no other C expressions or includes.
Installation rechecks all three header maps against the imported snapshot before
any write, and the isolated menu fixture copies all three exact headers.

Read-only `status` includes `auto_rotate_ui` when the saved image has the
complete published UI ABI. Its `enabled` value reads the BF+ option at
`menu_orientation + 20`; `displayed_raw`, `input_ready`, `frame_mask`, and
`removing` use the saved `ui` symbol and exported offsets. All fields must lie
inside the saved resident BSS. `displayed_orientation` is `landscape` for raw
0, `portrait` for raw 1/3, and `unknown` otherwise; the raw value preserves
direction information without claiming physical sensor polarity. The option
can remain enabled while removal forces the display to landscape. Legacy or
incomplete ABIs omit this object instead of guessing offsets. Status performs
no camera or manifest writes; snapshots may change while UI work is pending.

Artifact writes and directory entries are synced before proceeding. Manifest
updates use a synced temporary file, atomic replacement, and directory sync.
The phase callback persists each command/chunk intent before submission and
records its fresh result afterward. An incomplete/uncertain manifest cannot
resume loading or authorize another install. Read-only status reports that
phase even when all hooks are still original. Confirmed reboot and deliberate
archival of an unresolved local record are manual recovery actions; the CLI
does not infer a new boot from an address or delete cooldown state.

`prepare_remove(p, manifest)` checks the active center-button state and saved
aspect pending/job state before any drain write. If the archived symbols have
`ui`, it requires four exported offsets relative to that structure:
`__ui_removing_offset`, `__ui_displayed_offset`, `__ui_ready_offset`, and
`__ui_frame_offset`. Each must identify a distinct aligned word inside BSS.
It records `draining`, writes `removing=1` once through the shared cooldown,
then polls for `(removing, displayed, ready, frame) == (1, 0, 1, 0)` twice.
The user-facing Auto Rotate UI option is preserved. Successful drain records
`drained`, followed by the loader's `removing`/`removed` phases. The resident
also checks this condition before aspect sealing and hook restoration.

A drain timeout or uncertain transport/loader outcome records `uncertain` and
sends no cleanup write. The host conservatively leaves `removing` set, which
holds landscape while the installed wrappers remain available. It does not
automatically clear the flag or retry removal. Older images without `ui` skip
this handshake; an image with `ui` but no archived drain ABI requires reboot
instead of an unsafe guessed offset. Allocations remain retained after removal.

## Offline verification and limits

**22 tests pass.** They build only the loader plus a separate original resident
fixture; the fixture is linked/relocated and executed, not replaced with a
Python success stub. Coverage includes:

- Linked byte-identical launcher prefix, fixed bootstrap/control placement,
  tiny PIC relocation/section rules, and execution at two staging addresses.
- Images below/at/above the single-transfer cap, a short final chunk, maximum
  64 KiB resident, and declared `0x4a9800` scratch.
- Allocator failure, overflow, alignment/extents, protected transport/firmware
  overlap, stale identity/request nonces, wrong phases, and malformed guards.
- No entry/UI hook publication during PREPARE or failed CRC; BSS zeroing and
  complete data/instruction cache-line coverage before the resident entry.
- EL/L2/idle rejection, and L2/idle changes during CRC caught before entry.
- Exact existing-entry removal after initialized resident data changes,
  preserved BSS/state during removal, retained allocation, and replay rejection.
- Host chunk ordering/caps, complete-image corruption checks, interrupted
  writes, stale completion, shared-lock/cooldown delegation, durable-intent
  failure, postcondition failure, and a writer error after actual commit.
- Legacy/wrong-artifact rejection and preservation of the uncertain receipt.

The emulator intercepts privileged cache operations and the allocator/storage
services. Cache-line address/order checks do **not** prove hardware coherency,
allocator availability, flash-save behavior, timing, or boot-session identity.
The transport mock checks delegation and locking; the real PTP transport's
cooldown/process-lock behavior has separate existing tests.

**31 CLI tests pass**, using temporary archives, an isolated loader build and
a protocol/state test double. They cover durable phases, multi-chunk resident
uploads, immutable loader/resident preservation, exact archived removal, code
and guard corruption, writer/postcondition uncertainty, legacy removal without
building, bounded ELF-derived code verification, header/native UI hook parity
including all 14 root and four profile calls and frozen three-header parsing,
aspect pending/job rejection, UI drain success/timeout/invalid offsets, and
read-only orientation status for off, both portrait directions, draining and
legacy images. Native node replacement pending blocks install/removal before
any write; legacy removal preserves its archived executor path and rejects a
bad second L2 descriptor without writes or manifest changes.
The local firmware parity test is skipped when decoded firmware is absent.
These tests do not run the production builder or touch shared build output.
The combined loader/CLI/transport run passes **94 tests** (22 + 31 + 41).
Two separate original-firmware tests in `tests/test_ui_hierarchy.py` bring the
targeted total to **96 passing tests**. They establish the native node/depth
distinction and that the hierarchy return is ignored while the native receive
timeout path retries pending transitions; integrated UI retry/drain behavior is
covered by the UI owner's separate suite.
An additional isolated snapshot of the integrated production sources passed
emulated installation and exported-entry removal with all **57 pointer hooks
and 95 code hooks**, including the 14 root and four profile BLs, compared against
the host manifest. That snapshot had 37,120 initialized bytes, 43,712 resident
bytes and `0x4a9800` scratch; these are observed build values, not new caps.
The check used temporary build output and did not execute on the camera.
Production resident/UI integration has its own separate suite. No device
execution, USB writes, flash changes, or production installation are claimed.
