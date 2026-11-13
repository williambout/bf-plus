/* BF 1.04 detector snapshot and native magnification coordinates.
 * See docs/MF-SUBJECT-DETECTION.md for field provenance and limitations. */
#define DETECTOR_STATE 0x4d72f40d8ULL
struct DetectionRect { u8 valid, selected; u16 x, y, width, height; };
_Static_assert(sizeof(struct DetectionRect)==10, "detector rectangle ABI");
/* Separate from State: keep the installed touch/log ABI unchanged. */
struct FocusTarget {
    u32 enabled, moved, source, attempts;
    u16 saved[2], point[2];
    u32 misses, unstable;
};
/* The host sets enabled in the upload before bootstrap; keep it initialized. */
volatile struct FocusTarget focus_target __attribute__((section(".data.focus_target"))) = {0};
_Static_assert(sizeof(struct FocusTarget)==32, "target status ABI");

static int target_valid(const struct DetectionRect *r) {
    return r->valid==1 && r->width && r->height &&
        (u32)r->x+r->width<=1023 && (u32)r->y+r->height<=681;
}
static u32 target_tracking(void) {
    /* The producer can substitute a tracking rectangle into record zero. */
    return (B(DETECTOR_STATE+1)&8) && W(DETECTOR_STATE+0x40)==2;
}
static void target_restore(void) {
    if (!focus_target.moved) return;
    u16 point[2]={focus_target.saved[0],focus_target.saved[1]};
    ((void (*)(const u16 *))(uptr)0x4d3319b30ULL)(point);
    focus_target.moved=0;
}
/* Return 0 for no subject, 1 for the native AF target, 4 for instability. */
static __attribute__((minsize)) u32 target_snapshot(struct DetectionRect *out) {
    struct DetectionRect a[4], b[4];
    typedef void (*Snapshot)(void *);
    Snapshot snapshot=(Snapshot)(uptr)0x4d3270e50ULL;
    u32 tracking=target_tracking();
    snapshot(a);
    __asm__ volatile("dmb ish" ::: "memory");
    snapshot(b);
    /* Bounded consistency check; no spinning in the UI consumer. There is
     * no generation/timestamp in this stock snapshot (not a freshness test). */
    if (tracking!=target_tracking()) return 4;
    for (u32 i=0;i<sizeof(a);i++)
        if (((u8 *)a)[i]!=((u8 *)b)[i]) return 4;
    /* Stock AF display and subject-centered zoom use record zero. The
     * detector has already selected its target; do not rerank candidates. */
    if (tracking || !target_valid(&a[0])) return 0;
    *out=a[0];
    return 1;
}
static void target_apply(void) {
    focus_target.source=0;
    if (!focus_target.enabled) return;
    focus_target.attempts++;
    struct DetectionRect rect;
    u32 source=target_snapshot(&rect);
    if (source==4) { focus_target.unstable++; return; }
    if (!source) { focus_target.misses++; return; }
    u16 point[2];
    ((void (*)(u16 *))(uptr)0x4d3319b00ULL)(point);
    focus_target.saved[0]=point[0]; focus_target.saved[1]=point[1];
    focus_target.moved=1;
    const struct DetectionRect *r=&rect;
    ((void (*)(u16,u16))(uptr)0x4d331d040ULL)(
        (u16)(r->x+r->width/2),(u16)(r->y+r->height/2));
    ((void (*)(u16 *))(uptr)0x4d3319b00ULL)(point);
    focus_target.point[0]=point[0]; focus_target.point[1]=point[1];
    focus_target.source=source;
}
