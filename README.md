# BF+

Manual-focus controls, extra aspect ratios, and Doom for the **SIGMA BF**.

BF+ 1.0 adds a native-style **Settings → BF+** submenu to firmware **1.04**.
Touch the center button to check focus, center magnification on a detected
subject, or enable additional ratios in the camera’s normal aspect selector.

BF+ loads into RAM over USB. Power cycling removes the extension and resets
its options; it does not replace the installed firmware.

## Features

### Touch Focus Zoom

Lightly touch the center button to magnify live view. Keep your finger on it
while focusing, then lift it to return to the full view. No button press is
needed.

Designed for a fully manual lens or adapter **without electronic contacts**
in still-photo mode. Focus stays manual. Turn the feature ON or OFF in BF+.

### MF Subject Detection

Use the camera’s native eye/face detection with a manual lens. A gray frame
marks the selected subject. With Touch Focus Zoom also ON, touching center
magnifies the detected eye or face.

The target is chosen at the start of each touch and stays steady while held.
Release restores the previous zoom position. If no usable subject is detected,
magnification uses the current zoom position.

### Extra Aspect Ratios

Set **Extra Aspect Ratios → ON** to append these choices to the native
aspect-ratio selector, after 1:1:

| Ratio | Format |
| --- | --- |
| **65:24** | XPan |
| **2.35:1** | Cinema widescreen |
| **5:4** | Classic photographic format |

The option defaults to **OFF**. Turning it OFF restores the seven stock
choices and returns from a custom crop to the stored native ratio.

Cropped JPEG output and DNG crop metadata are implemented and tested offline;
RAW pixels remain intact. **Native selector interaction and real saved-photo
crops still need camera validation.** See [aspect-ratio details](docs/ASPECT-RATIOS.md).

### Doom

Launch the original Doom engine from **Settings → BF+ → Doom**. Use the camera
buttons to move and fire, and press Playback to return to BF+. The game runs
locally with a separately installed game package; the original shareware first
episode is supported. This initial port is silent, with no saved games.

Offline engine, package, and camera-scene checks pass; physical camera validation is pending.
See [Doom setup and controls](docs/DOOM.md).

## On-camera menu

```text
Settings → BF+
  Touch Focus Zoom      OFF / ON
  MF Subject Detection  OFF / ON
  Extra Aspect Ratios   OFF / ON
  Doom                  Launch
  Version               1.0
```

BF+ uses the camera’s native fonts, layout, and compact ON/OFF selector.
Navigate with the buttons or dial; center/right confirms and left cancels
an option change. Version is read-only.

## Current status

The focus-feature confirmations below apply to fully manual lenses or adapters
without electronic contacts.

| Area | Validation |
| --- | --- |
| Touch-to-zoom and release with manual lenses | Confirmed on camera |
| Subject detection, target frame, and zoom-position restoration with manual lenses | Confirmed on camera |
| Extra aspect ratios | Offline navigation/crop checks pass; physical selector and saved-file checks pending |

The full local offline suite passed **466 tests**, with two additional upload-streaming checks passing afterward. Hardware observations and
remaining checks are recorded in the [feature guide](docs/TOUCH-FOCUS.md).

The active build uses native landscape rendering and button/dial navigation.
Focus Guide, touchscreen menu controls, and automatic UI rotation are research
prototypes and are not included in the active build.

## Install from source

You need:

- A **SIGMA BF running firmware 1.04** and the original `BF__V104.bin` package.
- A USB data cable and the camera connected in **normal MTP mode**.
- macOS or Linux, **Python 3.11+**, and libusb.
- Clang with AArch64 support, LLVM tools, and lld.

```sh
git clone https://github.com/williambout/bf-plus.git
cd bf-plus
python3 -m venv .venv
.venv/bin/pip install -r requirements-bfplus.txt
.venv/bin/python bfplus_cli.py build
```

Follow the [USB/MTP setup instructions](docs/ROOT-SHELL.md#2-put-the-camera-in-mtp-mode).
Return the camera to idle still-photo live view and leave the buttons untouched
during installation. Check the current state first:

```sh
.venv/bin/python bfplus_cli.py status
```

For a camera with no BF+ installation currently loaded:

```sh
.venv/bin/python bfplus_cli.py install \
  --firmware /path/to/BF__V104.bin \
  --enable --subject-detection
```

This starts **Touch Focus Zoom** and **MF Subject Detection** ON, with
**Extra Aspect Ratios** OFF. Adjust them in **Settings → BF+**. The original
firmware package is read only to verify its identity.

To remove a loaded build, return to still-photo live view, release the center
button, and run:

```sh
.venv/bin/python bfplus_cli.py remove
```

Keep the generated `.touch-focus/` directory until removal: it records the
exact installed build. Remove an existing build before installing a different
one. Power cycling also removes BF+.

> Installation is experimental and specific to the analyzed 1.04 firmware.
> The USB write command also triggers calibration flash saves. The loader
> enforces cooldowns and readback checks; do not bypass them or retry an
> uncertain installation. See [transport and recovery](docs/TOUCH-FOCUS.md#transport-and-recovery).

## Development

Run the offline suite:

```sh
.venv/bin/python -m unittest discover -s tests
```

Firmware-dependent tests require a local decoded copy of the supported image;
see the [firmware analysis guide](docs/FIRMWARE-DECRYPTION.md). The repository
contains original code and documentation, with no Sigma firmware or extracted
binaries. Firmware files, generated builds, and local camera records stay ignored.

| Path | Purpose |
| --- | --- |
| [`bfplus/`](bfplus/) | Resident feature code, menus, and build tools |
| [`bfplus_cli.py`](bfplus_cli.py) | Build, status, install, and removal CLI |
| [`bfplus_loader.py`](bfplus_loader.py) | Verified, bounded RAM loading |
| [`bfplus_ptp.py`](bfplus_ptp.py) | Shared USB transport, locking, and write cooldowns |
| [`bfplus_camera_files.py`](bfplus_camera_files.py) | Read-only JPEG/DNG download and metadata inspection |
| [`bfplus_doom.py`](bfplus_doom.py) | Doom packaging, validation, and standard MTP upload |
| [`tests/`](tests/) | Host, emulation, menu, game, and crop checks |

The earlier Python command and import names remain compatibility aliases.
Existing `.touch-focus/` installation records and transport locks continue to
be used by both names.

## Documentation and origins

- [BF+ feature and installation guide](docs/TOUCH-FOCUS.md)
- [MF Subject Detection](docs/MF-SUBJECT-DETECTION.md)
- [Extra Aspect Ratios](docs/ASPECT-RATIOS.md)
- [Doom setup and controls](docs/DOOM.md)
- [Segmented RAM loader](docs/SEGMENTED-LOADER.md)
- [USB/MTP and root-shell tools](docs/ROOT-SHELL.md)
- [Custom firmware research](docs/CUSTOM-FIRMWARE.md) — boot integration remains unimplemented.

BF+ is a fork of [wjhrdy/sigma-bf-root-shell](https://github.com/wjhrdy/sigma-bf-root-shell).
The original USB root-shell and firmware-analysis tools remain available for
diagnostics and development.
