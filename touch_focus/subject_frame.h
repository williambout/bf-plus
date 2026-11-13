/* Display-only copy of the native focus-frame state. Other callers receive
 * the original data. The native producer/renderer owns redraw and clearing. */
#define SUBJECT_FRAME_ISLAND 0x4d331ce50ULL
#define SUBJECT_FRAME_OLD ((u64)A64_BRANCH(SUBJECT_FRAME_ISLAND,0x4d3319b60ULL,0))
struct SubjectFrame { u32 visible, style, eyes; u16 rect[4]; };
_Static_assert(sizeof(struct SubjectFrame)==20, "native frame snapshot ABI");
__attribute__((minsize)) void subject_frame_wrapper(struct SubjectFrame *frame, u64 *stamp) {
    uptr caller;
    __asm__ volatile("mov %0, x30" : "=r"(caller));
    ((void (*)(void *,u64 *))(uptr)0x4d3319b60ULL)(frame,stamp);
    if (caller!=0x4d31a74e0ULL || state.mode!=1 || !focus_target.enabled ||
        state.active || W(DEPTH)!=2 || W(PENDING)!=12 || lens()!=0) return;
    struct DetectionRect rect;
    u32 source=target_snapshot(&rect);
    if (!source || source==4) return;
    frame->visible=1;
    frame->style=15; /* Native gray detection rectangle, RGB 0x888888. */
    frame->eyes=0;
    frame->rect[0]=rect.x; frame->rect[1]=rect.y;
    frame->rect[2]=rect.width; frame->rect[3]=rect.height;
    /* This display-only selection supersedes any older AF status sample.
     * The underlying stock frame/timestamp and AF state remain untouched. */
    *stamp=~0ULL;
}
