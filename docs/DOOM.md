# Doom on BF+

**Settings → BF+ → Doom** launches the original Doom engine on the camera.
The engine runs locally; a computer is needed only to prepare and install it.
This port uses [PureDOOM](https://github.com/Daivuk/PureDOOM), with an optional
game package stored separately from the small BF+ RAM extension.

The initial build is silent and does not save games or settings. The game data
is read only. The camera port has offline checks; physical display, controls,
performance, storage visibility, and return to photography still need camera
validation.

## Controls

| Camera control | Doom action |
| --- | --- |
| Up / Down | Walk forward / backward; navigate game menus |
| Left / Right | Turn; adjust game menu choices |
| Press Center | Fire; confirm a game menu choice |
| Lightly Touch Center | Use/open a door |
| Turn Dial | Select a weapon |
| Menu | Open/close Doom's menu |
| Playback | Exit to BF+ |

Touch Focus Zoom stays a shooting feature. While Doom is open, its controls
belong to the game. Playback exits even when the game package cannot load.
The original 320×200 image is displayed at its intended 4:3 aspect ratio.

## Prepare the game

Use the original **Doom shareware Episode 1** (`DOOM1.WAD`), a Doom/Doom II
IWAD you own, or compatible Freedoom data. Commercial game data is not included
in this repository. The local build requires the same LLVM tools as BF+.

```sh
.venv/bin/python -m bfplus.doom_engine.build_module
.venv/bin/python bfplus_doom.py package \
  --module .touch-focus/doom-engine/build/bfdoom.elf \
  --wad /path/to/DOOM1.WAD \
  --output .touch-focus/doom/DOOM.BFP
.venv/bin/python bfplus_doom.py check .touch-focus/doom/DOOM.BFP
```

Connect the camera using **Access Camera → Mass Storage**. Copy `DOOM.BFP`
to the root of its mounted storage, alongside `DCIM`, then eject the volume.
The 5,294,260-byte Doom shareware package was copied this way on BF 1.04 and
its complete readback matched the source SHA-256. The native game's access
to that file still needs on-camera validation.

Use Mass Storage for the game file. The experimental `upload` command uses
standard MTP, but both tested transfers timed out in `SendObject`, including
the version with bounded 4 KiB USB writes. Successful `SendObjectInfo` does
not establish that the camera accepts the file data. Transfers stop on failure;
they are never automatically retried or resumed. A receipt beside the local
package records the object handle and uncertain outcome when available.

To replace a package, remove the old `DOOM.BFP` manually first. Restart the
camera before loading a larger replacement after a game has allocated memory.

Reconnect in MTP mode and install the current BF+ build using the
[normal instructions](../README.md#install-from-source).
An older resident build must be removed before its replacement is installed.
Open **Settings → BF+ → Doom**. Select New Game in Doom's menu and press Center.
Power cycling removes BF+ from RAM; the game package remains on storage.

## Implementation and checks

The small resident contains the native child scene, bounded read-only file
loader, controls, and RGB444+A4 renderer. A single audited UI-receive call uses
timed receives while the game is active. All other receive behavior and the
borrowed setter's original callers retain their stock paths. A UI timeout
queues a frame through the normal synchronous display worker, preserving its
cache maintenance and bank switching. Doom never queues a draw from inside
the renderer.

The separate AArch64 PIE engine has no firmware addresses or libc imports.
The package includes a complete IWAD, a bounded module, and sorted relative
data relocations. Header bounds, exact file lengths, CRC32, relocation ranges,
and IWAD structure are checked before execution. CRC32 detects corruption;
it is not a signature. Only use packages built from trusted source.

Native API evidence is in [DOOM-NATIVE.md](DOOM-NATIVE.md).

The game uses a 24 MiB heap and a separate 256 KiB stack. The loader retains
its allocation until reboot so stale callbacks cannot reference freed memory.
Scene generations reject old draws after exit or suspension. A missing or
invalid package displays a native message and leaves Playback available.
Ordinary BF+ use does not allocate the game heap.

Source and license details for the GPL engine are in
[`bfplus/doom_engine/`](../bfplus/doom_engine/). Game packages and local WADs
belong under the ignored `.touch-focus/` directory, not in source control.

Offline tests cover package corruption/range rejection, actual engine frames
and controls, reset/error handling, native surface bounds, menu entry/exit,
stale callbacks, UI receive routing, and stack restoration. They do not
establish physical camera performance or display behavior.
