# Custom firmware investigation — BF 1.04

Investigation date: 2026-11-12 (America/Los_Angeles).

**The update container is reproducible. A bootable custom firmware has not been
produced or installed.** This investigation uses local firmware files and
isolated analysis. It does not contact the camera, issue vendor commands, or
write flash.

The supplied `BF__V104.bin` is 233,729,536 bytes, SHA-256
`0c6cb624967c0d2254fa3e532ea25f389f09b007e9e31788df7e9682995e478b`.
The main analyzed RTOS is segment 05's payload at segment offset `0x15020`,
15,744,640 bytes, mapped at `0x4d3000000`, SHA-256
`f747c1350f00526b9c68c65aaef44d6e7b644b0169992342e12f059c42e150dc`.
Findings are specific to these bytes.

## Container reconstruction: verified offline

`tools/check_bf_roundtrip.py` verifies the package without writing a firmware
image. It validates table bounds and encrypted-segment checksums, compares the
header-seeded keystream with the independent known-plaintext prefix, decrypts
every segment, and re-encodes it. It regenerates the table's checksum fields
and preserves all other header, gap, and trailing bytes.

The full package passed:

- All 17 decoded segments match the existing independently decoded files by
  length and SHA-256.
- All re-encoded segment bytes equal their originals.
- The reconstructed package SHA-256 equals the original above.
- All 1,534 bytes of padding outside the initial `0x300`-byte header region
  and segment payloads are preserved.
- Seven synthetic tests pass, covering independent scalar stream generation,
  zero-seed handling, segment stream resets, nonzero padding, truncation,
  overlap, bad indices/trailers, damaged ciphertext, wrong seeds, and reference
  mismatches. A corrected checksum on modified synthetic data also passes,
  explicitly demonstrating that this checker is not an authenticity test.

Reproduce with Python 3.11+:

```sh
.venv/bin/python -m unittest discover -s tests -p 'test_bf_roundtrip.py' -v
.venv/bin/python tools/check_bf_roundtrip.py /path/to/BF__V104.bin \
  --decoded-dir decoded-V104 --report /path/to/new-report.json
```

The report path must be new and its parent directory must exist. The checker
has no image-output or flashing command. Its successful no-change roundtrip
does **not** establish that a modified package will install or boot. The
encoding details remain in [FIRMWARE-DECRYPTION.md](FIRMWARE-DECRYPTION.md).

## Updater acceptance: bounded native-code evidence

The original RTOS segment-processing code was executed in Unicorn beginning
at `0x4d31a0a58` and stopping at the next-iteration boundary `0x4d31a0cf8`,
or the checksum error branch `0x4d31a1420`. Each run used one original-size
segment, its descriptor and a synthetic stack. Only small memory copies and
cache maintenance were stubbed; the checksum and stream-decoding instructions
executed from the supplied firmware. No flash writer was executed.

| Input | Segment 0 (122 bytes) | Segment 5 / RTOS system image (46,607,616 bytes) |
| --- | --- | --- |
| Original ciphertext and checksum | Iteration accepted | Iteration accepted; decoded hash matches |
| One changed ciphertext byte, old checksum | Rejected | Rejected |
| Same changed byte, recomputed checksum | Iteration accepted | Iteration accepted; decoded hash matches intended modification |

The segment-5 change was at segment offset `0x15120`, inside the RTOS payload.
These tests establish that this particular processing loop accepts altered
RTOS contents with the corrected one-byte checksum. They do not establish
full-package acceptance, installation success, executable correctness, or
the absence of authentication in earlier/later layers.

There is a material dispatch gap: this RTOS's updater registers kind `0x0002`
for its main writer, while kind `0x1002` (segment 5, the basis for the existing
BF+ addresses) only sets a flag. The main writer is called at
`0x4d31a0e10`, through `0x4d31a67a0` to `0x4d31a5cd0`. It processes
`MILBEAUT` records and invokes the eMMC block-write wrapper `0x4d3135960`,
whose indirect backend was not resolved. Acceptance of the segment-5 parser
iteration therefore does not show that the changed segment would be installed.
Resolve the two updater/system-image paths before choosing which bytes to patch.

The traced writer can update partition records and boot-region data as well as
payloads. It is not established as an atomic transaction with rollback. Several
error/write-return paths need further review before any live experiment.

The ordinary update UI also has a version gate. Executing the original
comparison at `0x4d337c088..0x4d337c108` with supplied decoded header fields gave:

| Candidate | Version enforcement | Gate result |
| --- | --- | --- |
| 1.04, matching stock package | Enabled | Blocked |
| 1.03 | Enabled | Blocked |
| 1.05 | Enabled | Allowed |
| 1.04 | Disabled in supplied header state | Allowed |

This is a UI comparator result, not a successful update. A custom release
needs deliberate version and reinstall behavior; an unchanged 1.04 version
with the stock patch/build and enforcement state will not pass this UI gate.
The comparison includes major, minor, patch and build, so increasing the
displayed minor number is not the only possible version-policy design.

## System images and startup

Segments 2 and 5 each contain six sequential `MILBEAUT` records with a
16-byte header. Both contain the same 86,016-byte first-stage payload,
10,113,056-byte ARM64 Linux image, compressed root filesystem, device tree,
and final 303,120-byte payload. Static class-4 handling and register-like data
identify that final payload as likely DDR training/register-program data;
it is not an established place to put custom code. Their RTOS payloads differ.
This does not prove that the camera has recoverable A/B slots or automatically
falls back.

The main analyzed image is segment 5. Its RTOS begins at `0x15020`. The root
filesystem's gzip stream is 20,333,401 bytes in a 20,333,424-byte record; it
decompresses to a 52,157,952-byte `newc` CPIO archive with 1,014 entries. The
gzip CRC and uncompressed size match. Its contents include `/sbin/finit` and
the startup script `/etc/init.d/rc.local`.

The device-tree boot arguments select `rdinit=/sbin/finit`. An isolated run of
the original `finit` startup code reaches `execv("/etc/init.d/rc.local", ...)`
with process and filesystem services stubbed. That script enumerates
`/etc/init.d/S??*`. This is a concrete Linux startup integration path, stronger
evidence than merely finding a script name in an archive. It still does not
show a modified filesystem booting on camera.

The bootloader routine at `0x0820c534` and the RTOS Linux-loader path beginning
at `0x4d3314410` were also exercised with synthetic storage descriptors and
intercepted storage calls. They consume descriptor sizes, sector locations
and destination addresses. Hardware storage, the earlier ROM boot chain and
the actual flash partition table were not exercised.

Rebuilding a larger root filesystem must account for more than gzip and CPIO.
The static boot argument specifies the gzip length, while static
`linux,initrd-start`/`linux,initrd-end` properties describe a smaller span. Which
values the running kernel ultimately receives, including any fixups, remains
unresolved. Those fields must not be blindly regenerated from assumptions.

## BF+ integration constraints

The existing payload is designed for installation into an already-running
RTOS. `bootstrap()` restores the storage callback, checks the exception level,
page-table state and idle still-view scene, allocates resident memory, copies
and initializes BF+, and patches validated pointers/instructions. It then
calls the original storage writer and publishes a completion nonce. Calling
that entry point at boot with invented storage arguments is inappropriate.

A firmware integration needs a separate initializer, with the common BF+
allocation/initialization/hook logic separated from USB transport and the
storage-writer callback. It must run after the allocator, native services and
UI are ready, initialize BSS, publish code to caches, and retain exact-build
checks and a way to skip BF+ when troubleshooting.

The current upload path has a `0x4000` (16 KiB) initialized-image limit in the
linker, host loader and fixed cache-maintenance launcher. That is a property
of this USB staging design, not an established firmware-container limit.
Simply raising one constant would leave the other constraints unresolved.
The integrated aspect/portrait build fits exactly 16,384 initialized bytes,
with a 22,720-byte resident image including BSS. The local payload length,
linker symbols and SHA-256 were checked against the integration task's report:
`9c1e3ea44c0328b82b49c208a3cd43afb2edc3efaff7b5c43b5dc8918ce7a2e7`.
That task reports all 280 offline tests passed; this packaging investigation
did not rerun those tests or establish hardware behavior.

Portrait rendering also requires 1,396,736 bytes of scratch space beyond
`__end`. The current allocator requests `22,720 + 4,095 + 1,396,736 = 1,423,551`
bytes, including alignment allowance. A boot initializer must preserve that
allocation and BSS zeroing contract; 22,720 bytes alone is insufficient.
Sensor orientation polarity remains unverified on hardware, and stock child
screens/live-view overlays are not integrated into the portrait behavior.

Focus Guide remains incomplete and must not be described as a working feature
in a firmware release. Its core tests do not establish on-camera measurements
or rendering. Packaging should use an explicit feature manifest distinguishing
verified features from unfinished components.

Any further RAM-loader work must retain the installed image and manifest,
shared transport lock, cooldown and readback/completion checks. Vendor RAM
writes can trigger calibration flash saves even when the payload itself is
RAM-only. No such operations were used in this investigation.

## Recommended next implementation

The most direct design to investigate is a BF+ initializer in the existing
RTOS system image, invoked at a verified point after native services are
ready. It can reuse the extension's original code without making Linux
responsible for cross-core RTOS execution. The alternative is an initramfs
startup service, but that still requires a Linux-to-RTOS loading/execution
mechanism; finding `rc.local` does not supply that mechanism.

The next offline milestone should be a deterministic, exact-build patch recipe
for a minimal initializer, with expected-original-byte checks, a complete diff
manifest, consistent inner lengths and outer checksums, and emulated execution
through initialization and the unmodified continuation. Keep the bootloader,
Linux kernel and unrelated assets unchanged for that experiment. This is a
design recommendation, not a generated or boot-tested artifact.

Before any camera installation, resolve the active-image selection, complete
writer/boot validation path, and a usable recovery route. The existing USB root
shell depends on a running RTOS and MTP stack, so it is not established as a
recovery mechanism for an image that fails early in boot. Two packaged system
images alone are not evidence of rollback protection.

| Investigation question | Result |
| --- | --- |
| Can we reconstruct the supplied container exactly? | Verified for all 17 segments and the whole file |
| Does the segment loop reject every modified RTOS image? | No: corrected-checksum mutation passed the isolated native loop |
| Is same-version installation automatically available? | No: the ordinary enforced UI version comparator blocks stock 1.04 |
| Is there an identifiable startup path? | Linux init path identified and exercised in isolation; BF+ RTOS hook not selected |
| Is the complete modified-image boot chain validated? | No; earlier ROM/hardware and full writer behavior remain unresolved |
| Is recovery from a failed custom image established? | No |
| Does this create working firmware containing every tweak? | No; boot integration is unimplemented and Focus Guide is incomplete |

## Local evidence

Research artifacts are under ignored `.touch-focus/custom-firmware/`:

- `container-roundtrip.json`: all segment identities and exact roundtrip result.
- `packaging-source-identity.json`: hashes of the integration source examined;
  no claim that the current combined extension was built or validated here.
- `integrated-payload-identity.json`: the later verified local payload size,
  digest and resident extent, with the integration task's reported test status.
- `updater/REPORT.md`: bounded native updater analysis and isolated emulation.
- `boot/REPORT.md`: system-image, bootloader, root filesystem and startup analysis.

These are ordinary local Python/Capstone/Unicorn observations, not REA Evidence
records or live camera observations. The existing REA diagnostic reports a
missing Codex registration; this investigation used the available local
analysis tools without changing client configuration. Firmware bytes,
disassembly and extracted vendor scripts stay in ignored local storage.
