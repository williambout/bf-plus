/* BF 1.04 compact picker foreground identity, include after uptr is defined.
 * ui_compact_scene(callback) returns the matching ORIGINAL input handler as
 * a stable scene key, or 0 for an unknown callback. No state or native calls.
 *
 * Evidence: rtos-alt.bin SHA256
 * f747c1350f00526b9c68c65aaef44d6e7b644b0169992342e12f059c42e150dc.
 * Each entry calls 0x4d3364970 with its family's picker descriptor in x1.
 * The original entry/regular draw pointer literals and those descriptor loads
 * are checked in tests/test_ui_transactions.py. This identifies callbacks;
 * it does not distinguish same-family scene re-entry (parent lifecycle hook).
 */
#ifndef BF_UI_COMPACT_SCENES_H
#define BF_UI_COMPACT_SCENES_H

/* X(foreground, original_input); initial and regular share one identity. */
#define UI_COMPACT_SCENES(X) \
 X(0x4d3374df0ULL,0x4d3375730ULL) \
 X(0x4d3375450ULL,0x4d3375730ULL) \
 X(0x4d3379d80ULL,0x4d3379ea0ULL) \
 X(0x4d3380140ULL,0x4d33807e0ULL) \
 X(0x4d33801b0ULL,0x4d33809f0ULL) \
 X(0x4d3381600ULL,0x4d3381c80ULL) \
 X(0x4d3381640ULL,0x4d3381c80ULL) \
 X(0x4d33816a0ULL,0x4d3381e70ULL) \
 X(0x4d33816d0ULL,0x4d3381e70ULL) \
 X(0x4d3387cb0ULL,0x4d3387f80ULL) \
 X(0x4d3388bf0ULL,0x4d3388f10ULL) \
 X(0x4d3388c20ULL,0x4d3388f10ULL)

static uptr ui_compact_scene(uptr callback) {
#define UI_COMPACT_MATCH(draw,input) if (callback==(uptr)(draw)) return (uptr)(input);
    UI_COMPACT_SCENES(UI_COMPACT_MATCH)
#undef UI_COMPACT_MATCH
    return 0;
}
#endif
