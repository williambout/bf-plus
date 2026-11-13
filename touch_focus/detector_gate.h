/* A single detector-processing call uses the effective setting (which the
 * stock getter forces Off for no-contact lenses). Reuse the raw-setting
 * veneer as a long-branch island, preserving its other callers exactly.
 * Branch opcodes below are generated from addresses, not copied firmware. */
#define DETECTOR_CALL 0x4d326dcd4ULL
#define DETECTOR_ISLAND 0x4d3321270ULL
#define A64_BRANCH(from,to,link) ((u32)(((link)?0x94000000U:0x14000000U) | \
    (((to)-(from))>>2 & 0x3ffffffU)))
#define DETECTOR_CALL_OLD A64_BRANCH(DETECTOR_CALL,0x4d31559d0ULL,1)
#define DETECTOR_CALL_NEW A64_BRANCH(DETECTOR_CALL,DETECTOR_ISLAND,1)
#define DETECTOR_ISLAND_OLD ((u64)A64_BRANCH(DETECTOR_ISLAND,0x4d3318500ULL,0))
/* ldr x16, PC+8; br x16. The following qword is an owned pointer hook. */
#define DETECTOR_ISLAND_NEW 0xd61f020058000050ULL
struct DetectorGate { u32 calls, overrides, stock_mode, effective_mode; };
volatile struct DetectorGate detector_gate;

u32 detector_gate_wrapper(void) {
    uptr caller;
    __asm__ volatile("mov %0, x30" : "=r"(caller));
    if (caller!=DETECTOR_CALL+4)
        return ((u32 (*)(void))(uptr)0x4d3318500ULL)();
    u32 mode=((u32 (*)(void))(uptr)0x4d33211c0ULL)();
    detector_gate.calls++;
    detector_gate.stock_mode=mode;
    if (!mode && state.mode==1 && focus_target.enabled && lens()==0) {
        /* Respect the native AF detection mode. If stock detection was Off,
         * the explicit BF+ ON option enables native automatic mode1. */
        mode=((u32 (*)(void))(uptr)0x4d3318500ULL)();
        if (!mode) mode=1;
        detector_gate.overrides++;
    }
    detector_gate.effective_mode=mode;
    return mode;
}
