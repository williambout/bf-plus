The V104 firmware exposes separate rear-button **Touch** and **Push** states.
Center is key **index 0**, therefore **bit 0 / mask `0x0001`** in the UI key
fields. Touch is the input to use for magnification that lasts only while the
finger remains on the center button. Pressure release alone must not end it.

These findings come from static analysis and isolated Unicorn execution of V104
key predicates. This investigation did not access the camera. Addresses use
RTOS base `0x4d3000000`, corresponding to offset `0x15020` in the decoded
`05_1002.bin`. Runtime observation remains separate. “Touch” names the firmware
channel; the electrical sensing technology was not independently established.

The center identity has direct diagnostic evidence. Renderer `0x4d337e990`
constructs labels `U,D,L,R,C` at `0x4d337ea1c–0x4d337ea2c` and pairs them with
indices `4,3,1,2,0` from the table at `0x4d35643c0`. It reads and displays the
corresponding sensor channels at `0x4d337ea5c–0x4d337ea98`.

For read-only hardware observation, use the first little-endian `u32` at
**`0x4d72c2468`**, the published 16-byte input snapshot:

| Center state | Raw word mask | UI key payload |
| --- | --- | --- |
| Touch | `0x00000001` | `u16(key + 2) & 0x0001` |
| Push | `0x00000400` | `u16(key + 4) & 0x0001` |
| Repeat | `0x00100000` | `u16(key + 6) & 0x0001` |

Observe `word & 0x401` to ignore other keys and repeat. The expected isolated
sequence is `0 → 1 → 0x401 → 1 → 0`: untouched, touched, pressed while touching,
pressure released while still touching, then finger removed. These are
code-derived expectations, not recorded camera measurements.

| Writable state address | Purpose |
| --- | --- |
| `0x4d72c2468` | Published raw input snapshot; preferred polling source. |
| `0x4d72c2458` | Driver's working input state before publication. |
| `0x4d70346b0` | Previous filtered UI input state; less suitable for observing physical contact. |
| `0x4d72c247c` | Sampled rear-key bits before debounce, produced by `0x4d3240670`. |
| `0x4d72c25b0` | Seven `u16` sensor readings; center is element 0, read by `0x4d3245780`. |

Getter `0x4d3240b80` copies all 16 published bytes under a mutex. The key task
calls it at `0x4d32405cc`, then passes the copy to UI translator `0x4d3324870`.
The producer locks the same mutex at `0x4d32413f8–0x4d3241408`. It either copies
the whole working snapshot at `0x4d3241a9c–0x4d3241aa8`, or publishes selected
fields at `0x4d3241418–0x4d3241458`. Both publication paths preserve center Touch,
Push and repeat bits. Snapshot `+4` is the selected rear-push index; `7` is the
no-selected-push sentinel, initialized by `0x4d3240b30`.

The argument to live handler `0x4d3398940` or magnification handler
`0x4d33a1670` is a container of five pointers, constructed by `0x4d3323280`:

| Container offset | Payload | Serialized size |
| --- | --- | --- |
| `+0x00` | Rear keys | 10 bytes |
| `+0x08` | Dial | 4 bytes |
| `+0x10` | LCD touch | 20 bytes |
| `+0x18` | One-byte event | 1 byte |
| `+0x20` | Other event | 5 bytes |

Each pointer can independently be null. A null key pointer means **no key
update**, not release. The container and payload pointers are transient, and
serialized payloads can be unaligned. Do not retain them after handler return.

| Key offset | Type | Meaning |
| --- | --- | --- |
| `+0` | `u16` | Changed keys: union of Touch and Push changes. |
| `+2` | `u16` | Current Touch states. |
| `+4` | `u16` | Current Push states. |
| `+6` | `u16` | Repeat flags. |
| `+8` | `u8` | Repeat count used for acceleration; copied from raw snapshot `+0xc`. |
| `+9` | `u8` | Serialized padding; no semantic use established here. |

Producer `0x4d332491c–0x4d3324954` splits the packed raw word into three groups
of ten bits. Touch occupies bits 0–9, Push bits 10–19, and repeat bits 20–29.
For current word `R` and previous word `P`, the changed field is
`((R ^ P) | ((R ^ P) >> 10)) & 0x3ff`.

Before splitting, `0x4d33248cc–0x4d3324904` can retain only the selected rear
push key, together with the separate keys at indices 7–9. Pushing another rear
button can therefore mask center Touch in the UI payload while the published
raw snapshot still reports center contact. Use the published raw word, or
capture it at translator entry before this filter, if simultaneous-button
contact must be distinguished.

Key helper second arguments are **indices**, so pass `0` for center:

| Function | Relevant behavior |
| --- | --- |
| `0x4d3323320(key, i)` | Tests repeat bit `i`. |
| `0x4d3323330(key, i)` | Tests changed AND Push for bit `i`. |
| `0x4d3323360(key, i)` | Tests changed AND Push, or repeat. |
| `0x4d3323390(key, i, period)` | Push predicate with timed repeat handling. |
| `0x4d3323480(key, i)` | Tests changed AND Touch. |
| `0x4d3323510(key, i, 0)` | Tests changed AND NOT Touch: Touch release. |
| `0x4d3323510(key, i, 1)` | Tests changed AND NOT Push: pressure release. |

Because changed combines both kinds of transition, the Touch predicate also
returns true when pressure starts or ends during continuous contact. It is not
a unique Touch rising edge. Similarly, the pressure-release predicate can be
true on initial Touch because Push is absent. Keep previous contact/pressure
state, or an ownership guard, when exact transitions matter.

Five isolated Unicorn cases confirmed the firmware predicates: initial touch,
push during touch, pressure release with touch retained, finger removal, and
push repeat. Pressure release with contact retained does not report Touch
release. These checks execute the original predicate instructions against
constructed input; they do not observe driver timing or hardware behavior.

`0x4d33235c0` is a separate **LCD touch** predicate. It reads a mask at LCD
payload `+0x10`; live-handler call site `0x4d3398bb8` supplies the container's
LCD pointer. It must not be used on the 10-byte rear-key payload.

For the intended manual, no-contact-lens feature, wrap both live and
magnification handlers and share contact/ownership state across the scene
change. Enter once when the runtime eligibility checks permit it, then exit
only magnification owned by that touch when contact ends. Lens eligibility and
the zoom operations are outside this input analysis. The stock magnification
handler still recognizes center pressure through `0x4d3323330(key, 0)` at
`0x4d33a1cbc–0x4d33a1ccc`; explicitly consume or preserve that action. A local
forwarded key copy can suppress center changed/repeat bits while preserving
unrelated input. Avoid changing the shared key predicates globally.

For preserving a center press by popping and replaying it, static control flow
establishes the scene-change ordering. A successful `0x4d3324250()` copies the
previous scene descriptor into `0x4d7301d40` and writes the target depth to
`0x4d70346a4`. It returns `-1` when the requested preceding depth is at or below
zero. After the current handler and any completion callback return, the event
loop calls `0x4d3323c50` at `0x4d3323aac`. A pending scene change sends execution
to `0x4d3323ca0`, which runs exit/resume processing and replaces the dispatch
handler pair at `0x4d3323ec0–0x4d3323ec4`. Only then does the loop dequeue at
`0x4d3323ac0`.

Thus a successful pop is applied before the **next dequeue**. A replay is not
necessarily next in the queue: earlier queued events may themselves change
scene. Clear custom ownership before returning from the pop path, and prevent
the replay's already-held Touch state from reopening magnification.

`0x4d3323660(key, dial, lcd, one, five, completion_callback)` copies the supplied
payloads into a queued record before returning. Its sixth argument is a
**completion callback, not a timeout**; pass zero when no completion is needed.
The callback runs with the handler result in `w0`.

The serializer uses send wrapper `0x4d30339d0`, which passes `w3=-1` to RTOS
send `0x4d3001950`. Sibling `0x4d3033a00` passes `w3=0`, consistent with a
nonblocking send. For an enqueue from the UI consumer itself, the nonblocking
form avoids waiting for space in that consumer's own queue. Check its return
value. The queue ID is the `u32` at `0x4d7301650`.

A key-only replay has a 16-byte header followed by five payload-length bytes
and the 10-byte key payload, for 31 bytes total. Header fields are type `0` at
`+0`, body length `15` at `+2`, and a null completion pointer at `+8`; reserved
header space can be zero. The five lengths are `10,0,0,0,0`. A center-press
payload uses changed, Touch and Push masks `1`, with repeat/count/padding zero.
Replay delivery and queue-failure behavior still require runtime validation.
