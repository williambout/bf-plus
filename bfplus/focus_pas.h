/* Scoped BF 1.04 diagnostic adapter for the no-contact PAS table fallback.
 * Not linked or enabled by the normal build. This does not enable the stock
 * phase producer or establish optical calibration. See docs/FOCUS-GUIDE.md.
 * Requires payload u8/u16/u32/u64/uptr types and lens(). */
#ifndef BF_FOCUS_PAS_H
#define BF_FOCUS_PAS_H

#define FOCUS_PAS_ISLAND 0x4d3321190ULL
#define FOCUS_PAS_PROFILE_GETTER 0x4d33184c0ULL
#define FOCUS_PAS_LEFT_CALL 0x4d32ca044ULL
#define FOCUS_PAS_RIGHT_CALL 0x4d32ca054ULL
#define FOCUS_PAS_LEFT_TABLE 0x41a0d1c94ULL
#define FOCUS_PAS_RIGHT_TABLE 0x41a0d1e94ULL

struct FocusPasDiagnostic { u32 enabled, fills, rejected, last_lens; };
volatile struct FocusPasDiagnostic focus_pas __attribute__((section(".data.focus_pas"))) = {0};

/* The island normally forwards the public Lens+ profile getter. Preserve
 * that behavior for every caller except the two exact memset return sites.
 * Both table destinations must match their corresponding call site; the
 * adapter never follows an arbitrary destination in its halfword-fill path. */
static u64 focus_pas_explicit(uptr caller, u64 arg0, u64 arg1, u64 arg2) {
    if (caller!=FOCUS_PAS_LEFT_CALL+4 && caller!=FOCUS_PAS_RIGHT_CALL+4)
        return ((u64 (*)(u64,u64))(uptr)FOCUS_PAS_PROFILE_GETTER)(arg0,arg1);
    uptr expected=caller==FOCUS_PAS_LEFT_CALL+4 ? FOCUS_PAS_LEFT_TABLE : FOCUS_PAS_RIGHT_TABLE;
    u32 kind=lens();
    focus_pas.last_lens=kind;
    if (focus_pas.enabled==1 && kind==0 && arg0==expected && arg1==0x1000 && arg2==0x200) {
        /* The real initializer's reference fill at 0x4d32c5b6c writes these
         * same 256 halfwords. Stock no-contact memset instead fills zero bytes.
         * Run only at the native initialization boundary, before SPT setup. */
        volatile u16 *table=(volatile u16 *)expected;
        for (u32 i=0;i<256;i++) table[i]=0x1000;
        focus_pas.fills++;
        return arg0;
    }
    focus_pas.rejected++;
    return ((u64 (*)(u64,u64,u64))(uptr)0x4d3008200ULL)(arg0,arg1,arg2);
}
#ifndef FOCUS_PAS_EXTERNAL_ROUTER
u64 focus_pas_wrapper(u64 arg0, u64 arg1, u64 arg2) {
    return focus_pas_explicit((uptr)__builtin_return_address(0),arg0,arg1,arg2);
}
#endif
#endif
