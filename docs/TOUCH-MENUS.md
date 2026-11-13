# LCD touch menus (BF 1.04)

> Historical experiment: the user requested removal of automatic UI rotation
> and LCD menu controls. These adapters are unlinked from the current replacement
> build. The installed image is retained until the reduced native-aspect build
> completes verification and replacement.

The source adds automatic portrait rotation, controlled by **BF+ → Auto Rotate
UI → ON/OFF**, and LCD touch input to the main Settings list, BF+, BF+ pickers
and the verified stock families in [UI-INTEGRATION.md](UI-INTEGRATION.md). This is separate from the rear center
button's capacitive Touch state used for momentary magnification.

- Drag vertically in Settings to scroll its eleven rows, including BF+.
  Scrolling follows finger displacement and stops at either end. Portrait
  shows seven complete rows and advances its viewport in row steps.
- Tap a Settings or BF+ row to select it and open its existing action.
  Native Settings activation retains the stock disabled/read-only checks.
- Tap an option in a BF+ picker to apply it and return.
- Tap the BF+ back arrow, or outside its picker, to go back/cancel.
- Version stays read-only. Lists that fit on screen do not scroll.
- Buttons/dial take priority over simultaneous LCD input. A drag cannot
  commit an option on release; horizontal drags and pinches do not scroll.
- Holding the camera vertically requests a portrait redraw. Both portrait
  directions share a 682×1024 layout with full-size native text. BF+ pickers
  become full-screen lists; returning to landscape restores their compact form.
- Tap the visible **Back** label in portrait to return. Touch coordinates use
  the last successfully drawn orientation; rotating during a drag cancels it.

These changes passed offline tests and were **installed on BF 1.04 on
2026-11-13**. Image, hook and settings checks passed; physical rotation and
touch usability checks remain pending. The shared worker also fits stock OSD layouts into portrait;
full-size reflow is specific to the owned menus. See
[UI-INTEGRATION.md](UI-INTEGRATION.md) for the transaction/loader architecture,
stock touch coverage and remaining checks. Unsupported owned text dimensions
fall back to the fitted native canvas with matching touch coordinates.

Auto Rotate UI starts ON. OFF restores landscape while retaining touch.
The separate segmented loader uses 4 KiB reads/writes within its 16 KiB staging cap;
resident and scratch extents are independent. Allocations stay owned until
reboot because queued callbacks may retain resident pointers.

## Firmware evidence

Addresses are for the locally supplied V104 segment05 image at `0x4d3000000`.
No vendor binary or disassembled instructions are included in this repository.

The 20-byte LCD payload is the independently nullable third pointer in the
UI event. Its packed fields are:

| Offset | Meaning |
| --- | --- |
| `+0`, `+2` | Tap X/Y, unsigned 16-bit |
| `+4`, `+6` | Drag origin X/Y, unsigned 16-bit |
| `+8`, `+10` | Current drag X/Y, unsigned 16-bit |
| `+16` | Gesture bitmask, unsigned 16-bit |

`0x4d33235c0` reads the gesture mask. Producers `0x4d3246c20`,
`0x4d3246ce0`, and `0x4d3246da0` emit begin/update/end bits
`0x100`, `0x200`, and `0x400`. `0x4d32466d0` classifies completed taps
(bit `1`) and directional gestures. The native tap tolerance is 100 pixels;
menu scrolling uses a 16-pixel movement tolerance to prevent a short scroll
from also selecting a row. A stationary tap has no drag-begin event.

The actual producer sequence is covered by conditional emulator tests:
contact `0x4d3246250`, movement `0x4d3246340`, release `0x4d32464b0`.
A 40-pixel drag produces begin `0x100`, then release/tap `0x401`;
a 200-pixel upward drag produces begin `0x100`, then release/direction
`0x410`. Neither opens a row, and a subsequent stationary tap does.
Mutex and memory services are stubbed; producer instructions execute from
the user's local decoded firmware. This does not establish driver timing
on physical hardware.

Picker hit boxes use the same native font-width parser as the painter,
including its even-pixel rounding: `1024 - ((width + 141) & ~1)`.
Tests compare the hit area against rectangles emitted by the original
picker renderer for both boolean pickers and the aspect picker.

## Validation

```sh
.venv/bin/python -m unittest tests.test_touch_menu_lcd tests.test_touch_menu tests.test_touch_orientation tests.test_orientation -q
.venv/bin/python -m unittest discover -s tests -q
```

The tests compile and execute the relocated AArch64 wrappers. They cover
scroll limits, partial-row hit testing, optional event preservation, native
activation, tap/drag separation, coalesced packets, cancellation, read-only
rows, and native picker geometry. Integration tests also cover orientation
updates, both directions, redraw publication, transformed scrolling and taps,
rotation during a gesture, picker transitions, fallback and disabled callbacks.
Native-firmware tests skip explicitly when
`decoded-V104/rtos-alt.bin` is absent. No test opens USB.
