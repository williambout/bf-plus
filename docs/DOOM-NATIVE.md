# Doom native ABI evidence — BF 1.04

The resident loader can read an optional engine/WAD package through the native
file-service task. [doom_storage.h](../bfplus/doom_storage.h) exposes read-only
open/read/close and uses `"J:\\DOOM.BFP"`. The firmware establishes this path
syntax; native access to the Mass Storage-copied root file is unverified.
See [DOOM.md](DOOM.md) for package usage and the integrated scene.

Evidence is local static analysis (Capstone 5.0.7) and offline execution
(Unicorn 2.1.4), following the reverse-engineer-anything skill. REA MCP was
unavailable; these are not REA Evidence records or hardware observations.
The ABI checks performed no camera or USB access. Target: `decoded-V104/rtos-alt.bin`,
BF 1.04 segment 05, 15,744,640 bytes, SHA-256:

```text
f747c1350f00526b9c68c65aaef44d6e7b644b0169992342e12f059c42e150dc
```

Code VA is `0x4d3000000 + file_offset`. Initialized data bytes
`[0xebdfb0,0xf03e70)` map at `0x4d7000000`. All addresses below are specific to
this image; API names describe the decoded entries.

## File interface

| Entry | Address | AArch64 ABI / result |
| --- | --- | --- |
| FS_Open | `0x4d313b9e0` | `u64(const char *path, u32 mode)`; mode 0 is read-only; 0 means failure |
| FS_Read | `0x4d313bb50` | `u32(u64 handle, void *buffer, u32 requested, u32 *actual)` |
| FS_Lseek | `0x4d313bc60` | `u32(u64 handle, s64 offset, u32 whence, u64 *position)`; 0 success, 1 failure; whence 0/1/2 = SET/CUR/END |
| FS_Close | `0x4d313baf0` | Handle in x0; treat return as void: it waits but does not reload the worker's close status |

Handles are opaque **64-bit values**. Public read status is 0 for success,
4 for EOF (including a short read), and 1 for other failures. `actual` is a
**four-byte output**, although the lower wrapper uses an eight-byte count.
The header returns bytes read, 0 at EOF, or -1 on failure; it rejects invalid
arguments and counts above `INT32_MAX`, and avoids native I/O for zero-length
reads. The package parser must enforce exact lengths after short reads.
Seek is verified but deliberately absent from the current header interface.

Public calls dispatch through `0x4d313d350` to worker `0x4d313d4d0` and wait
through `0x4d3141040` with timeout -1. The worker invokes the adapter at
`0x4d313d52c`, stores its result at `0x4d313d59c`, and wakes the caller through
`0x4d3141030`. The decoded chains are:

| Operation | Adapter → FS layer → lower wrapper → libc-file endpoint |
| --- | --- |
| Open | `0x4d313d650` → `0x4d313f790` → `0x4d3142450` → `0x4d352bb60` (`fopen`) |
| Read | `0x4d313d680` → `0x4d313f8c0` → `0x4d3142730` → `0x4d352bc20` (`fread`) |
| Seek | `0x4d313d710` → `0x4d313fd70` → `0x4d3143350` → `0x4d352bc40` (`fseek`), `0x4d352bb50` (`fgetpos`) |
| Close | `0x4d313d670` → `0x4d313f850` → `0x4d3142690` → `0x4d352bb20` (`fclose`) |

Open mode 0 constructs `"r"` at `0x4d31424a0..0x4d31424b0`. Public open
rejects NULL and paths longer than 527 bytes at `0x4d313b9ec..0x4d313ba00`,
then copies the path before enqueueing. Lower converter `0x4d31413d0`
rewrites the logical drive in place; use the public entry to protect a const
caller string. Lower wrappers serialize using `*(u32 *)0x4d729d14c` and a
5000-unit semaphore timeout. Lower EOF -501 becomes public status 4; lock
timeout -50 becomes status 1 with zero actual bytes.

The stock binary loader at `0x4d31a0040` independently corroborates the ABI:
mode-0 open at `0x4d31a0060`, Fstat at `0x4d31a0070` (entry
`0x4d313c150`, u64 size at output +24), read at `0x4d31a008c`, and close at
`0x4d31a0098`. Size-cap/error paths also close the file.

The stock path builder at `0x4d31a0570` tries `"I:\\"` at
`0x4d31a0598`, then constructs `"J:\\" + filename` and calls the loader at
`0x4d31a05dc..0x4d31a0604`. Prefix literals are at `0x4d396b010` and
`0x4d396b058`. Corroborating strings include `J:\DATA.bin` at `0x4d396af88`,
`J:\__C46FW.bin` at `0x4d396af98`, and `J:\SSD_TEST\000001.DNG` at
`0x4d35604f8`. This supports the selected `J:\DOOM.BFP` convention, not a
claim that this particular file exists or that J: is currently mounted.

First 16 bytes at each public entry, in file byte order:

```text
0x4d313b9e0  ff 43 09 d1 f3 53 00 a9 fe 0b 00 f9 e0 04 00 b4
0x4d313bb50  f3 7b bc a9 f3 03 03 aa e2 03 02 2a e4 63 00 91
0x4d313bc60  fe 0f 1c f8 43 04 00 b4 5f 04 00 71 a0 01 00 54
0x4d313baf0  fe 0f 1d f8 e4 b3 00 91 03 01 80 52 e2 63 00 91
```

## Island and frame scheduling

The integrated island is **`0x4d3320840` → `0x4d3317610`**, file offset
`0x320840`. Its original 16 bytes are one branch and 12 zero padding bytes:

```text
74 db ff 17 00 00 00 00 00 00 00 00 00 00 00 00
u64 little-endian: 0x0000000017ffdb74, 0x0000000000000000
```

This is a **setter**, not an unused getter. Its target loads the object pointer
through the literal at `0x4d3317628` (value `0x4d7301b98`), executes
`str w0,[x1,#0x320]` at `0x4d331761c`, then returns at `0x4d3317620`.
Direct native calls occur at `0x4d33904e4`, `0x4d3390558`, `0x4d33a6148`, and
`0x4d33a61e0`; unrelated calls must forward to the original target preserving
arguments, especially w0. No exact u64 literal reference was found in the
bounded image scan; indirect callers remain possible. The retired
`0x4d3320830` hook is left untouched.

| Evidence | Consequence |
| --- | --- |
| `0x4d3323ac0`: `e4 3f f4 97`, BL `0x4d3033a50`; return `0x4d3323ac4`: `1f 00 00 71`, CMP w0,0 | Only this UI receive caller is diverted. Arguments are queue ID in w0 (`[x19,#0xa0]`) and buffer in x1 (`sp+0x70`). |
| Blocking `0x4d3033a50` supplies w2=-1; timed `0x4d3033ab0(u32 queue,void *buffer,int timeout)` forwards w2; both reach `0x4d30017b0` | Use timeout 28 while Doom is active; preserve stock blocking receive otherwise. Normalized E_TMOUT is -50; preserve other results. |
| Timestamp `0x4d3033bb0(u64 *out)` calls `0x4d3001770`; status 0 means success | Combines high/low kernel words at stack +0x18/+0x1c. Original-wrapper emulation verifies the 64-bit output. |
| Delay `0x4d3033660(u32 delay)` adds 1 before syscall `0x4d3001690` | Input 28 reaches the kernel as 29, verified offline. This is not a measured 28 ms sleep or a demonstrated frame rate. |
| Synchronous draw `0x4d3322d90` enqueues at `0x4d3322dd0` through `0x4d31ac850`, then waits at `0x4d3322de4` through `0x4d3033810` | Queue frames from the UI task; calling this from the OSD renderer would self-deadlock. Lower enqueue also uses blocking `0x4d30339d0`, so bypassing the wait does not make worker selfqueue safe. |
| Third draw callback invoked at `0x4d31ad35c` or `0x4d31ad684` | Runs on the OSD worker, takes no arguments, return ignored, and precedes bank publication. It is not a safe post-publication frame scheduler. |

The integrated scene checks elapsed time around timed UI receives and runs the
engine on the native renderer with its own stack. Update callbacks are not
established as periodic without input. Native timer service `0x4d33257c0`
replaces stock timer state, so it is not used for this loop.

## Reproducible offline checks

[tests/test_doom_storage.py](../tests/test_doom_storage.py) passed **27 tests:
18 native ABI + 9 compiled-header checks**, with no skips:

```sh
.venv/bin/python -B -m unittest tests.test_doom_storage -v
```

The test requires the exact firmware above and Unicorn. Compiled checks also
require AArch64-capable clang (prefers `/opt/homebrew/opt/llvm/bin/clang`).
It compiles the actual header with `--target=aarch64-none-elf -O2
-ffreestanding -fno-builtin -fno-stack-protector -Wall -Wextra -Werror`, reads
ELF text/symbols from stdout, and rejects relocations. It writes no probe or
firmware build artifacts. Missing prerequisites produce explicit skips;
a firmware hash mismatch fails.

- **18 native:** four open checks (read-only mode/path-copy/drive translation,
  failure, NULL, 528-byte rejection); five read checks (exact, short EOF, EOF,
  other error, lock timeout), with four-byte count canaries; six seek checks
  (END, negative offset, SET, CUR, invalid whence, NULL output), with eight-byte
  position canaries; 64-bit close; delay 28→29; timestamp high/low word assembly.
- **9 compiled header:** read-only open; exact/short/EOF reads; native-error and
  lock-timeout mapping to -1; invalid/zero read guards; close; NULL close and
  NULL/empty open guards avoiding native calls.

The emulator runs original public entries, adapters, FS wrappers, and ordinary
memory/string routines. Dispatch is modeled synchronously with the real adapter;
storage endpoints, semaphores, task waiting, logging, and clock/delay syscalls
are mocked. A synthetic J: mount translates to `0:\`; the mock handle exceeds
32 bits. These checks verify ABI/control flow, not live storage or scheduling.

## Remaining limits

- A Mass Storage copy of `DOOM.BFP` to the camera root passed complete host
  readback. Confirm the mapping to J: and native file availability in shooting
  mode. MTP `SendObject` timed out in two physical attempts; use Mass Storage.
- Call FS only from a task allowed to block, never an ISR or the file worker
  itself. Serialize each handle and retain buffers until return. The 5000-unit
  semaphore timeout is not an overall operation deadline: worker waits can be
  indefinite.
- Real timing, renderer stack requirements, CPU load, allocation capacity,
  executable cache publication, storage concurrency, display/input behavior,
  and return to the camera still require hardware validation. The separate
  engine, package parser, allocation, and stack switch are integration work;
  these ABI tests do not validate them.
