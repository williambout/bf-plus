# Engine provenance

The vendored PureDOOM source is pinned to
[`Daivuk/PureDOOM@355cfbd16fac119718879239336ee2ea408886bd`](https://github.com/Daivuk/PureDOOM/tree/355cfbd16fac119718879239336ee2ea408886bd).
`vendor/PureDOOM.h`, `vendor/LICENSE.PureDOOM`, and
`vendor/PureDOOM-README.md` are unmodified upstream files.

PureDOOM.h SHA-256:
`ec16ce721436bf3fa4c338320afedd56a93c0b563a94ebf283718503c71ca780`.
License file SHA-256:
`8177f97513213526df2cf6184d8ff986c675afb514d4e68a404010521b880643`.
The upstream repository LICENSE is GPLv2. Its header and README also retain
id Software's older Doom Source Code License notices; these are preserved
verbatim rather than silently rewritten. The adapter carries GPL-2.0-or-later
SPDX notices. Engine-source licensing does not grant rights to commercial WADs.

Evaluated doomgeneric at `e257a09527062bfb986b6e5e0780839b6cbd5b71`.
PureDOOM was selected because it already supplies allocation, memory-file,
timer, input, and framebuffer callbacks without required system headers.
doomgeneric would require replacing additional libc/platform interfaces.
This was source-only development; no REA or firmware calls were needed.

`prepare_engine.py` checks the original source checksum and makes these
explicit adaptations into an ignored build directory:

- Replace the sole floating-point fixed division with checked integer division.
- Place three const objects in writable engine state so the complete state
  can be snapshotted and restored, including function-local statics.
- Disable save/load and quicksave/quickload actions because no writable
  filesystem is exposed to the engine.

Freedoom test data is optional, redistributable, and entirely under
`.touch-focus/doom-engine/freedoom-0.13.0/`. `fetch_test_wad.py` contains the
pinned release URL and SHA-256 checks for the archive and both IWADs; it also
extracts COPYING and credits. Builds and tests never download anything.

Classic Doom shareware 1.9 was downloaded at the user’s request from
`https://www.gamers.org/pub/idgames/idstuff/doom/doom19s.zip`, extracted from
its split installer, and kept locally at
`.touch-focus/doom-shareware/doom1.wad` (4,196,020 bytes; SHA-256
`1d7d43be501e67d927e415e0b8f3e29c3bf33075e859721816f652a526cac771`).
No WAD, generated engine header, executable, or test output belongs in the
tracked source tree.
