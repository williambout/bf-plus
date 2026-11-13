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

Copy `DOOM.BFP` to the root of the camera's internal storage, or use normal
MTP mode and the dedicated uploader:

```sh
.venv/bin/python bfplus_doom.py upload .touch-focus/doom/DOOM.BFP
```

The uploader creates a new file through standard MTP and verifies a complete
readback. USB writes are bounded to 4 KiB within a single PTP data container.
A durable receipt records creation, the returned object handle, and verification
or uncertain completion beside the local package. It preserves any existing `DOOM.BFP`, never deletes photos, and
never uses the vendor RAM-write command to transfer game data. An unsuccessful
transfer is not automatically retried. To replace a package, remove the old
file manually first. Restart the camera before loading a larger replacement
after a game has already allocated memory.

Then install the current BF+ build using the [normal instructions](../README.md#install-from-source).
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
