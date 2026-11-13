# Bounded stock list touch coverage — V104

> Historical experiment: the user requested removal of automatic UI rotation
> and LCD menu controls. These adapters are unlinked from the current replacement
> build. The installed image is retained until the reduced native-aspect build
> completes verification and replacement.

Audit date: 2026-11-12. **The initial audit found complete compact-picker
coverage and one additional fixed two-row family compatible with the existing
ordinary-row adapter.** Other list gaps required their own viewport or
selector contracts. Automatic portrait rendering alone did not establish
touch coverage for them.

**Integration update, 2026-11-12:** the parent reports six ordinary families,
eight compact families and two private-list adapters integrated. This includes
ordinary family 5 (`uiOpUSBSto`, input `0x4d3352220`), the variable private list
at `0x4d3386a00`, and the mixed Settings list built by `0x4d337d180`. The
private-list production transaction fixture also passed offline, as reported
by the parent. Current contracts are in
[NATIVE-TOUCH-PRIVATE-LIST.md](NATIVE-TOUCH-PRIVATE-LIST.md) and
[NATIVE-TOUCH-SETTINGS-LIST.md](NATIVE-TOUCH-SETTINGS-LIST.md).

The tables and recommendations below preserve the **pre-integration audit**;
their “unmapped” and future-work wording for those three additions is
historical. This update does not establish coverage of alternate/service
Settings or other surfaces outside the audited scope. Date/time field-editor
controls remain native and are not ordinary list families. AF/S2 profile work
remains with the parent; no installation or hardware validation is claimed.

This audit owns only this document and
[`tests/test_touch_menu_inventory.py`](../tests/test_touch_menu_inventory.py).
No shared header, integration code or existing test was edited. The parent
owns image-anchor transactions; mixed image-profile analysis is separate.
All work was offline. No USB/device connection, PTP command, firmware write,
network fetch or REA configuration change occurred.

## Artifact and method

The operator artifact is `decoded-V104/rtos-alt.bin`, 15,744,640 bytes,
base `0x4d3000000`, SHA-256
`f747c1350f00526b9c68c65aaef44d6e7b644b0169992342e12f059c42e150dc`.
Local Capstone 5.0.7 and Unicorn 2.1.4 supplied the evidence; the REA MCP was
unavailable. The evidence labels below are local, not REA-issued IDs.

The inventory scans **every aligned 32-bit word in this file**, sign-extends
the immediate of AArch64 `B`/`BL`, and selects exact painter targets. It finds:

| Target | Direct calls | Tail branches | Aligned 64-bit raw pointer references |
| --- | ---: | ---: | ---: |
| Ordinary row foreground `0x4d3363df0` | 37 | 0 | 0 |
| Compact picker foreground `0x4d3364970` | 12 | 0 | 0 |
| Compact picker background `0x4d3364750` | 12 | 0 | 0 |

Matching call sites were classified by their surrounding native code. The
full site sets are retained in the new fixture, which compares them against
a fresh whole-file scan. This bounds the completeness claim to these native
painters and this image. Computed/indirect calls, other painters and external
scene code are not excluded by this search.

Initialized RAM is not read at its runtime address in the file. Boot code
`0x4d3000fa8..0x4d3000fcc`, with literals at `0x4d3001138/1140/1148`, copies
`0x45ec0` bytes from `0x4d3ebdfb0` to `0x4d7000000`. Thus the relevant file
offset is `0xebdfb0 + runtime_address - 0x4d7000000`. The fixture installs this
actual data image before running original instructions. BSS and external
status services are explicitly initialized or intercepted in the fixture.

## Compact inventory: no missing mapped family

All 12 foreground callers are present in `UI_COMPACT_SCENES`, and each
resolves to one of the eight inputs in `NATIVE_TOUCH_MENU_FAMILIES`. Their
descriptor literals match that input's 48-byte picker descriptor.

| Existing family | Input | Foreground callback(s) | Direct call(s) to `0x4d3364970` |
| --- | --- | --- | --- |
| 0 | `0x4d3375730` | `0x4d3374df0`, `0x4d3375450` | `0x4d3374e14`, `0x4d337548c` |
| 1 | `0x4d3379ea0` | `0x4d3379d80` | `0x4d3379dbc` |
| 2 | `0x4d33807e0` | `0x4d3380140` | `0x4d338017c` |
| 3 | `0x4d33809f0` | `0x4d33801b0` | `0x4d33801ec` |
| 4 | `0x4d3381c80` | `0x4d3381600`, `0x4d3381640` | `0x4d338161c`, `0x4d3381674` |
| 5 | `0x4d3381e70` | `0x4d33816a0`, `0x4d33816d0` | `0x4d33816ac`, `0x4d33816fc` |
| 6 | `0x4d3387f80` | `0x4d3387cb0` | `0x4d3387cfc` |
| 7 | `0x4d3388f10` | `0x4d3388bf0`, `0x4d3388c20` | `0x4d3388bfc`, `0x4d3388c4c` |

Family 1's seven modes are already represented by its mode-dependent counts;
they are not seven missing families. There is no evidence here for adding
another compact entry. The existing tests separately exercise native input
and conversion semantics. This audit adds the missing *inventory equality*
check, rather than only checking that the known map entries exist.

## Ordinary row inventory: every direct site accounted for

The following partitions all 37 sites, without treating painter reuse as an
input ABI. “Covered” refers to the source adapters present at audit time,
not physical camera validation.

| Family / owner | Sites | Status and generic-map decision |
| --- | --- | --- |
| `uiOpUSBSto`, foreground `0x4d3351e80` / `0x4d3351ec0` | `0x4d3351e98`, `0x4d3351ea4`, `0x4d3351f20`, `0x4d3351f2c` | **Unmapped fixed two-row list. Compatible candidate**, detailed below. |
| Other date/time scene, foreground `0x4d3370190` | `0x4d337028c`, `0x4d33702a8`, `0x4d33702c0` | Three ordinary rows share selection with a date/time editor and a separate control. Not a three-row family. |
| Normal and alternate Settings root, foreground `0x4d33726d0` | `0x4d3372740`, `0x4d3372844`, `0x4d337285c` | Normal root covered by `menu.h`; **alternate root not adapted**. Shared private backing, ten rows and u8 selector prohibit a `NativeTouchRowFamily` entry. |
| Existing row family 0 | `0x4d337527c`, `0x4d3375288`, `0x4d3375294`, `0x4d33759d4`, `0x4d33759e0`, `0x4d33759ec` | Covered, three rows. |
| Settings date/time scene | `0x4d3376e50`, `0x4d3376e5c`, `0x4d3376e68`, `0x4d3376e74` | Four ordinary rows plus a date/time editor. Not a four-row family. |
| Mixed Settings child, painter `0x4d337d180` | `0x4d337d37c`, `0x4d337d390`, `0x4d337d454` | Existing documented gap. Private viewport and heterogeneous selector; no map-only extension. |
| Existing row family 2, language parent | `0x4d337fa9c`, `0x4d337faa8` | Covered, two rows. |
| Existing row family 1, Sound | `0x4d3380ff0`, `0x4d3380ffc` | Covered, two explicitly supported transient stack rows. |
| Existing row family 3 | `0x4d3384520`, `0x4d3384530`, `0x4d3384540` | Covered, three rows. Its children do not inherit coverage. |
| Variable-length private list, painter `0x4d3385d10` | `0x4d3385e54`, `0x4d3385ef4`, `0x4d3385f8c` | **Concrete unadapted list**, reached from existing row family 3 row 1. Not compatible with the current map. |
| Existing row family 4 | `0x4d3389f38`, `0x4d3389f44`, `0x4d3389fdc`, `0x4d3389fe8` | Covered, two rows. |

Of the 37 sites, 17 belong to the five existing row families, four to the
new compatible candidate, three to the shared root painter, seven to the
two date/time scenes, and six to the two private child lists. There are no
unclassified sites left in this bounded inventory.

## Bounded patch recommendation: one new ordinary row family

Append the following entry to `NATIVE_TOUCH_ROW_FAMILIES` when the parent
chooses to integrate it. This is a recommendation, not a shared-header edit:

```c
 X(5,0x4d3352220ULL,0x4d7302508ULL,0x4d7035760ULL,2,0x4d3351e80ULL,0x4d3351ec0ULL)
```

The fields are input, u32 selector, stable row base, row count, regular
foreground and initial foreground. Increase the array bound and both family
lookup loop bounds from five to six, preferably deriving the loop count from
the array. Keep the existing three-row snapshot capacity and all validation.
All four row-painter call sites are **already** in `UI_ROW_CALLS`; no new
instruction hook is needed. The current `ui_input` dispatch uses `ntr_family`,
and scene identity uses `native_touch_rows_handler_for_draw`, so extending
that table supplies the existing dispatch/capture path. This is not a
compact-picker entry and requires no compact input-literal replacements.

The native diagnostic string `uiOpUSBSto_Initialize` at `0x4d3e86938` identifies
the family; untranslated option meanings are not guessed. Its scene descriptor
at `0x4d3e86950` points to init `0x4d3352160`, resume `0x4d3352130`, suspend
`0x4d3351a40` and exit `0x4d3351a60`. Init/resume call `0x4d3351f60`.

| ABI evidence | Exact observation |
| --- | --- |
| Input ownership | Literal `0x4d3352100 = 0x4d3352220`; `0x4d3352038..2048` publishes it to the native handler table. |
| Initial/regular identity | `0x4d3352110` and `0x4d3351ae8` contain initial `0x4d3351ec0`; `0x4d3352568` contains regular `0x4d3351e80`. Native dial queues `(0x4d3351e80,0x4d3351b00,0)`. |
| Row storage/geometry | Two 32-byte boot rows at `0x4d7035760` and `0x4d7035780`, Y502/Y592, initial flags 2, value font 4. Both fit completely in native 1024×682 coordinates. |
| Surface contract | Both foreground forms preserve the caller's surface and pass it unchanged to both row calls. There is no private viewport between these rows and the supplied surface. Initial header drawing is separate. |
| Selector | Literal `0x4d3352550 = 0x4d7302508`; native loads/stores are u32. Positive signed first dial channel selects 1; negative selects 0; endpoints clamp. No magnitude-dependent skip. |
| Selection flags | `0x4d335229c..22dc` and `0x4d3352364..239c` update row bit 0 and the selector before queueing the redraw. |
| Center semantics | Native center test at `0x4d33523e0..23f0`; row 0 reaches `0x4d33442f0(9)` through `0x4d3352418..241c`, subject to the native status byte at `0x4d7302500`. Row 1 reaches `0x4d33537c0(1)` at `0x4d33524ec`. The adapter must retain these calls, not copy their behavior. |
| Disabled state | Original initializer sets row 0 flags to 0/1 when unavailable, or 2/3 when both status services permit it (`0x4d3351ff8..2034`, `0x4d33520a0..20b4`). Existing capture and live-row `(flags & 0x12) == 2` checks preserve this gate. |
| Original event | Input reads key, dial and fifth side channel; it ignores LCD. The fifth part can request a transition at `0x4d335222c..223c`. It must be forwarded exactly once, never copied into synthetic dial/center events. |

The temporary fixture executes these native initializer, input, key-test and
foreground instructions with the proposed family in the **existing generic
adapter**. It does not replace selection with a mock. Both directions and
signed extreme dial values are tested. Tap selection triggers the real native
queue call, which synchronously executes the native regular foreground and
publishes a new capture before center. The fixture checks disabled/readonly
rows, physical priority, drag releases, outside taps, pending transitions,
unaligned caller packets and no adapter writes to native RAM.

This supports including the family in the existing ABI, subject to the same
parent display-publication/lifecycle contract as the current five families.
The fixture intercepts status getters, native actions, header/raster services
and scheduling. It does **not** validate device/storage action results, live
status races, camera scheduling, cache coherence or production portrait
publication. Parent integration should run its normal transaction checks.

## Concrete gaps that cannot be fixed by adding map rows

### Alternate/service Settings root

This is a real ten-row list, not a numeric editor. The renderer switches
between `0x4d7042c18` and `0x4d7042d58` using byte `0x4d73025f4` at
`0x4d33726dc..2704`; its full loop spans `0x140` bytes at a 32-byte stride.
Both use private surface `0x4d7042ec0`. Copy at `0x4d3372790` maps the
scroll offset `0x4d7042ee0` into screen Y52. Alternate initialized row Ys
are 52,142,...,862. Input selector `0x4d73025f6` is **u8**, observed at
`0x4d3373294` and `0x4d33732b4`, not the row adapter's u32.

`menu_input_wrapper` explicitly delegates when `MENU_ALTERNATE` is nonzero;
the parent draw wrapper similarly delegates. Therefore touch support for the
normal root does not cover this mode. Do not add this input to the ordinary
row map: the wrong selector width, ten-row capacity, private surface and
offscreen Ys each violate that adapter's contract. A future change belongs
in the root adapter with mode-specific table/count/activation proof. Reusing
normal-mode BF+ index 10 or normal-mode child dispatch is not justified.

### Variable-length child list at input `0x4d3386a00`

Existing row family 3 row 1 calls `0x4d3386f90`, which pushes descriptor
`0x4d3e892e8`. It reaches native input `0x4d3386a00` via literals
`0x4d3386450/65a0`, initial foreground `0x4d33865d0` via
`0x4d3386468/65b8`, and regular foreground `0x4d33861b0` via
`0x4d3386f78`. This child is a list even though some labels contain formatted
dates; it is distinct from the multi-field date/time editors below.

Its row builder `0x4d3385d10` reuses a single **stack** row at `sp+0x68`.
It paints a first entry at local Y56 and later entries at local Y236 followed
by 90-pixel increments. The loop count comes from `0x4d31a4b10`'s output,
and selector `0x4d7302ec0` is u32. The `%s%s(%d/10)` string at
`0x4d3e89308` is supporting context, not a substitute for the loop evidence.

Crucially, row painter calls use private surface `0x4d7043708` (literal
`0x4d3385ff8`). The regular callback copies from that backing with offset
`0x4d70436e0` to destination Y142 at `0x4d33861f4..6228`, for height540.
Thus visible row Y is `142 + local_y - offset`, with clipping, not raw row Y.
The separate first-row/group spacing and dynamic count also defeat Sound's
special `rows == NULL` mapping, which accepts only Y142/Y232 and two indices.

No generic map entry is safe. A future adapter must capture transient rows
by native selection index, retain viewport/clipping metadata, account for
disabled entries and delegate native movement/activation. This audit does
not implement or audit image-anchor compositing for this scene.

### Existing mixed Settings child

Normal root row 0 still reaches the documented private-backed heterogeneous
list (`0x4d337db20`, row builder `0x4d337d180`). Direct ordinary-row calls
at `0x4d337d37c/390/454` do not cover its whole selection space. For example,
`0x4d337d2fc..d320` and `0x4d337d344..d368` instead build 16-byte-stride
entries for painter `0x4d3365d00`; ordinary entries use `0x4d3363df0` on
the private surface. This independently corroborates the existing exclusion.
It needs its own selector/viewport adapter, not more ordinary family entries.

## Editors and documentation reconciliation

Do not count these as ordinary list gaps merely because they contain rows:

- Foreground `0x4d3370190` calls date/time painter `0x4d33643e0` at
  `0x4d33701d8`, three ordinary rows, and separate control painter
  `0x4d3364070` at `0x4d337026c`. Its input is `0x4d33708a0`, with byte
  selection at `0x4d7035c20+0xd8` and field-editing state at `+0x44`.
  `0x4d3370430` navigates the wider selection space. It is not a contiguous
  three-row u32 selector.
- Settings date/time foreground calls `0x4d33643e0` at `0x4d3376e40`
  before its four row calls. Its existing compact children are covered;
  the mixed parent is not thereby an ordinary row family.
- Root entries `0x4d33843e0` and `0x4d338b0c0`, numeric/sliders, modal button
  groups, grids and other custom painters are outside this row/compact
  inventory. Absence here is not proof of either list semantics or coverage.

The “Explicit coverage gaps” table in `NATIVE-TOUCH-MENUS.md` describes that
header in isolation. Read together with `NATIVE-TOUCH-ROWS.md`, its root rows
1,2,3,8,9 already have parent row adapters. They should not be reported as
five new missing ordinary families. Root row 9's variable child list remains
a real nested gap. The older “other direct callers” category can now be
replaced by the explicit 37-site partition above. Existing documents were
left unchanged to preserve ownership.

## Regression fixture and evidence ledger

Run only the new fixture:

```sh
.venv/bin/python -m unittest discover -s tests -p test_touch_menu_inventory.py -v
```

**11 tests passed.** Compilation uses freestanding AArch64/PIC flags and a
temporary directory; the compiled candidate runs at a relocated address.
If the production header still has five families, only the temporary copy
gets the proposed sixth row and three count adjustments. If it already
contains the candidate input, the fixture uses that header directly. No
shared file or production payload is patched or built. A missing local
firmware causes an explicit skip; a wrong hash fails.

| Local evidence | Observation | Regression method / limitation |
| --- | --- | --- |
| UTC-01 | Exact supplied image and boot initialized-data map. | Hash gate and `test_candidate_boot_rows_and_callback_literals`; no inference from BSS file offsets. |
| UTC-02 | All 37 direct row sites classified; existing observation hooks include them. | `test_row_inventory_and_installed_observation_sites_are_exhaustive`; does not prove indirect-call completeness. |
| UTC-03 | All 12 compact foreground sites map to the eight existing descriptors; background set also fixed. | `test_compact_inventory_is_covered_by_existing_eight_input_families`; native behavior remains covered by the existing suite. |
| UTC-04 | Proposed USB-storage family meets direct-surface geometry, selector, dial and center ABI. | Eight `ProposedTouchFamilyTests`; original instructions run with explicit service/scheduler intercepts, including the fifth-part transition path. |
| UTC-05 | Alternate root and variable child list are actual remaining list gaps, incompatible with current map fields. | Static instructions/literals and boot rows cited above; no new production adapter or camera observation. |
| UTC-06 | Both date/time scenes and mixed Settings child cannot be promoted from row-call count. | Static call/selector/surface evidence cited above; intentionally no family-map recommendation. |

Within this boundary, the actionable map delta is **one fixed two-row
family**, with no compact delta. That does not make “all camera menus
scroll/tap-select” complete: the named private lists and alternate root
remain separate work, as do surfaces using other widget families.
