/* Original, freestanding AArch64 code. Firmware addresses are for BF 1.04,
 * segment 05 only. No vendor instructions are copied into this payload. */
typedef unsigned char u8;
typedef unsigned short u16;
typedef unsigned int u32;
typedef unsigned long long u64;
typedef u64 uptr;
/* Freestanding aggregate copies may lower to memcpy even with -fno-builtin. */
void *memcpy(void *destination, const void *source, __SIZE_TYPE__ length) {
    volatile u8 *out=destination;
    const volatile u8 *in=source;
    for (__SIZE_TYPE__ i=0;i<length;i++) out[i]=in[i];
    return destination;
}
void *memset(void *destination, int value, __SIZE_TYPE__ length) {
    volatile u8 *out=destination;
    for (__SIZE_TYPE__ i=0;i<length;i++) out[i]=(u8)value;
    return destination;
}
#define Q(a) (*(volatile u64 *)(uptr)(a))
#define W(a) (*(volatile u32 *)(uptr)(a))
#define B(a) (*(volatile u8 *)(uptr)(a))
#define CALLBACK 0x4d729bd00ULL
#define ORIGINAL 0x4d31254f0ULL
#define LIVE_LITERAL 0x4d3398860ULL
#define MAG_LITERAL 0x4d33a1388ULL
#define LIVE_UPDATE_LITERAL 0x4d3398868ULL
#define MAG_UPDATE_LITERAL 0x4d33a1390ULL
#define LIVE_ORIGINAL 0x4d3398940ULL
#define MAG_ORIGINAL 0x4d33a1670ULL
#define LIVE_UPDATE_ORIGINAL 0x4d3396120ULL
#define MAG_UPDATE_ORIGINAL 0x4d33a1420ULL
#define CINE_LITERAL 0x4d3392b60ULL
#define CINE_UPDATE_LITERAL 0x4d3392b68ULL
#define CINE_ORIGINAL 0x4d3392c40ULL
#define CINE_UPDATE_ORIGINAL 0x4d338ef10ULL
#define CINE_SLOT 0x4d7303030ULL
#define LIVE_SLOT 0x4d7303098ULL
#define L2_SLOT 0x4d71484c8ULL
#define L2_RO 0x4d3200781ULL
#define DEPTH 0x4d70346a0ULL
#define PENDING 0x4d70346a4ULL
#define RAW_KEYS 0x4d72c2468ULL
#define MAGIC 0x314843554f544642ULL /* BFTOUCH1 */
#define RING_COUNT 128

struct __attribute__((packed)) Key { u16 changed, touch, press, repeat; u8 count, pad; };
struct Event { struct Key *key; void *dial, *lcd, *one, *five; };
struct Log {
    u32 seq, scene, depth, pending;
    struct Key key;
    u16 flags;
    u32 lens;
};
_Static_assert(sizeof(struct Log) == 32, "log ABI");
struct State {
    u64 magic;
    u32 version, mode;
    u64 nonce, owner;
    u32 active, held, saved_mag, forced_mag;
    u32 sequence, entry_depth;
    u32 replay_errors, exit_errors;
    struct Log log[RING_COUNT];
};
volatile struct State state __attribute__((section(".bss.state"), aligned(64)));
struct Control {
    u64 nonce, done, result, resident;
    u64 el, ctr, mair, tcr;
    u32 command, mode;
    u32 storage_rc, reserved;
};
volatile struct Control control __attribute__((section(".data.control"), aligned(64))) = {0};
extern u8 __start[] __attribute__((visibility("hidden")));
extern u8 __end[] __attribute__((visibility("hidden")));
extern u8 __image_end[] __attribute__((visibility("hidden")));
typedef u32 (*Handler)(struct Event *);
static u32 stock(struct Event *e, u64 fn) { return ((Handler)(uptr)fn)(e); }
static u32 lens(void) { return ((u32 (*)(void))(uptr)0x4d31d48c0ULL)(); }
static u32 mag_get(void) { return ((u32 (*)(void))(uptr)0x4d33224d0ULL)(); }
static void mag_set(u32 value) { ((void (*)(u32))(uptr)0x4d3322500ULL)(value); }
static u32 physical_touch(void) { return W(RAW_KEYS)&1; }

#include "focus_target.h"
#include "detector_gate.h"
#include "subject_frame.h"

static void clear_owned(void) {
    state.active=0;
    if (state.forced_mag) { mag_set(state.saved_mag); state.forced_mag=0; }
    target_restore();
}
static int leave_owned(void) {
    if (!state.active) return 0;
    if (W(DEPTH)!=state.entry_depth+1 || W(PENDING)!=12) {
        clear_owned();
        return 0;
    }
    int rc=((int (*)(void))(uptr)0x4d3324250ULL)();
    if (rc) { state.exit_errors++; return 0; }
    clear_owned();
    return 1;
}

/* Nonblocking copy to the stock UI queue. Pop is applied before next dequeue.
 * Forward an unhandled center press, or the remainder of a release bundle. */
static void replay_event(struct Event *e, int strip_center) {
    if (!e) return;
    u8 packet[64]={0};
    struct Key key;
    const void *parts[5]={e->key,e->dial,e->lcd,e->one,e->five};
    const u8 sizes[5]={10,4,20,1,5};
    if (e->key && strip_center) {
        key=*e->key;
        key.changed&=~1; key.press&=~1; key.repeat&=~1;
        parts[0]=(key.changed || key.repeat)?&key:0;
    }
    u32 length=21;
    for (u32 i=0;i<5;i++) if (parts[i]) {
        packet[16+i]=sizes[i];
        const u8 *src=parts[i];
        for (u32 j=0;j<sizes[i];j++) packet[length++]=src[j];
    }
    if (length==21) return;
    packet[2]=(u8)(length-16);
    int rc=((int (*)(u32,const void*,u32))(uptr)0x4d3033a00ULL)(W(0x4d7301650ULL),packet,length);
    if (rc<0) state.replay_errors++;
}

static void record(struct Event *e, u32 scene) {
    if (state.mode==2 || !e || !e->key) return;
    u32 seq=state.sequence+1;
    volatile struct Log *r=&state.log[(seq-1) & (RING_COUNT-1)];
    r->seq=0;
    r->scene=scene; r->depth=W(DEPTH); r->pending=W(PENDING);
    const u8 *src=(const u8 *)e->key;
    volatile u8 *dst=(volatile u8 *)&r->key;
    for (u32 i=0; i<sizeof(struct Key); i++) dst[i]=src[i];
    r->flags=(!!e->dial) | ((!!e->lcd)<<1) | ((!!e->one)<<2) | ((!!e->five)<<3);
    r->lens=lens();
    __asm__ volatile("dmb ishst" ::: "memory");
    r->seq=seq; state.sequence=seq;
}

static u32 live_common(struct Event *e, u64 original, u32 scene) {
    record(e,scene);
    if (state.active) clear_owned(); /* Stock scene transition already exited. */
    if (e && e->key) {
        u32 was=state.held, held=e->key->touch&1;
        state.held=held;
        if (state.mode==1 && held && !was && (e->key->changed&1) &&
            !e->key->press && !e->key->repeat && !e->dial && !e->lcd && !e->one && !e->five &&
            W(PENDING)==12 && W(DEPTH)>0 && W(DEPTH)<11 && lens()==0 &&
            (W(RAW_KEYS)&0x401)==1) {
            u32 mag=mag_get();
            u32 saved=((u32 (*)(void))(uptr)0x4d3319880ULL)();
            /* A stock recording restriction may force getter=1. Recheck after
             * setting so we never claim ownership of a nonmagnifying scene. */
            state.saved_mag=saved; state.forced_mag=0;
            if (mag<=1 && saved>1) return stock(e,original);
            if (mag<=1) { mag_set(2); state.forced_mag=1; }
            if (mag_get()<=1) { clear_owned(); return stock(e,original); }
            target_apply();
            state.entry_depth=W(DEPTH); state.active=1;
            if (((int (*)(u32,u32))(uptr)0x4d33a1e70ULL)(4,1)) {
                clear_owned();
                return stock(e,original);
            }
            return 0;
        }
    }
    return stock(e,original);
}
u32 live_wrapper(struct Event *e) { return live_common(e,LIVE_ORIGINAL,1); }
u32 cine_wrapper(struct Event *e) { return live_common(e,CINE_ORIGINAL,3); }
u32 mag_wrapper(struct Event *e) {
    record(e,2);
    if (state.active) {
        if (e && e->key) state.held=e->key->touch&1;
        if (!physical_touch() || state.mode!=1 || lens()!=0) {
            if (leave_owned()) { replay_event(e,1); return 0; }
        } else if (e && e->key && (e->key->changed & e->key->press & 1)) {
            if (leave_owned()) { replay_event(e,0); return 0; }
        }
    }
    u32 result=stock(e,MAG_ORIGINAL);
    if (state.active && W(PENDING)!=12) clear_owned();
    return result;
}
u32 live_update_wrapper(struct Event *e) {
    if (!physical_touch()) state.held=0;
    if (state.active) clear_owned();
    return stock(e,LIVE_UPDATE_ORIGINAL);
}
u32 cine_update_wrapper(struct Event *e) {
    if (!physical_touch()) state.held=0;
    if (state.active) clear_owned();
    return stock(e,CINE_UPDATE_ORIGINAL);
}
u32 mag_update_wrapper(struct Event *e) {
    if (state.active && (!physical_touch() || state.mode!=1 || lens()!=0)) {
        state.held=physical_touch();
        if (leave_owned()) return 0;
    }
    u32 result=stock(e,MAG_UPDATE_ORIGINAL);
    if (state.active && W(PENDING)!=12) clear_owned();
    return result;
}

static void clean_range(uptr start, uptr end, u64 ctr, int code) {
    uptr step=4ULL << ((ctr>>16)&15);
    for (uptr p=start & ~(step-1); p<end; p+=step)
        __asm__ volatile("dc cvac, %0" :: "r"(p) : "memory");
    __asm__ volatile("dsb ish" ::: "memory");
    if (code) {
        step=4ULL << (ctr&15);
        for (uptr p=start & ~(step-1); p<end; p+=step)
            __asm__ volatile("ic ivau, %0" :: "r"(p) : "memory");
        __asm__ volatile("dsb ish\n isb" ::: "memory");
    }
}
static void translation_at(uptr slot, u64 value) {
    Q(slot)=value;
    __asm__ volatile("dc cvac, %0\n dsb ish\n tlbi vmalle1is\n dsb ish\n isb"
                     :: "r"(slot) : "memory");
}
static u64 relocate(const void *symbol, uptr base) {
    return base + ((uptr)symbol-(uptr)__start);
}

#include "menu.h"
#include "loader_abi.h"
#define RESIDENT_SCRATCH_BYTES 0

static int idle_still_scene(void) {
    return W(DEPTH)==2 && W(PENDING)==12 && W(0x4d703469cULL)==12 &&
        Q(0x4d7301c00ULL)==0x4d3398930ULL &&
        Q(0x4d7301c08ULL)==0x4d33988b0ULL &&
        Q(0x4d7301c10ULL)==0x4d3393730ULL &&
        Q(0x4d7301c18ULL)==0x4d33936a0ULL;
}

#define PATCH_TARGETS(X) \
    X(live_wrapper,LIVE_ORIGINAL) \
    X(mag_wrapper,MAG_ORIGINAL) \
    X(live_update_wrapper,LIVE_UPDATE_ORIGINAL) \
    X(mag_update_wrapper,MAG_UPDATE_ORIGINAL) \
    X(cine_wrapper,CINE_ORIGINAL) \
    X(cine_update_wrapper,CINE_UPDATE_ORIGINAL) \
    X(menu_rows,MENU_STOCK_ROWS) \
    X(menu_callbacks,0x4d3564220ULL) \
    X(menu_input_wrapper,MENU_INPUT) \
    X(menu_parent_scene,0x4d3e88bc8ULL) \
    X(detector_gate_wrapper,0) \
    X(subject_frame_wrapper,0) \
    X(aspect_raw_wrapper,ASPECT_RAW_SLOT_OLD) \
    X(aspect_stock_set_wrapper,0) \
    X(aspect_label_wrapper,0) \
    X(aspect_main_wrapper,0) \
    X(aspect_half_wrapper,0) \
    X(aspect_small_wrapper,ASPECT_SMALL_SLOT_OLD) \
    X(aspect_meta_wrapper,0) \
    X(aspect_dng_wrapper,0) \
    X(aspect_release_wrapper,0) \
    X(aspect_reserve_wrapper,0) \
    X(aspect_view,ASPECT_VIEW_TABLE)
#define PATCH_ENUM(name,original) PATCH_##name,
enum { PATCH_TARGETS(PATCH_ENUM) PATCH_TARGET_COUNT };
#undef PATCH_ENUM
extern const int patch_targets[PATCH_TARGET_COUNT] __attribute__((visibility("hidden")));
/* Link-relative words avoid absolute resident pointers and repeated runtime
 * address construction. PREL32 relocations remain position independent. */
#define PATCH_WORD(name,original) ".long " #name " - .\n"
__asm__(".pushsection .rodata.patch_targets,\"a\"\n.balign 4\n"
        ".global patch_targets\n.hidden patch_targets\npatch_targets:\n"
        PATCH_TARGETS(PATCH_WORD) ".popsection\n");
#undef PATCH_WORD
static uptr patch_target(u32 index, uptr base) {
    const int *entry=&patch_targets[index];
    return relocate((const u8 *)entry+*entry,base);
}

struct Patch { u32 offset; u16 target, runtime; };
static __attribute__((minsize)) int patch_all(uptr base, int install, u64 ctr) {
    /* Shared targets keep repeated firmware slots compact without embedding
     * absolute resident pointers. Validate every slot before changing any. */
#define PATCH_ORIGINAL(name,original) original,
    static const u64 originals[]={ PATCH_TARGETS(PATCH_ORIGINAL) };
#undef PATCH_ORIGINAL
    static const uptr runtimes[]={0,LIVE_SLOT,LIVE_SLOT+8,CINE_SLOT,CINE_SLOT+8};
    static const struct Patch p[]={
        {(u32)(LIVE_LITERAL-0x4d3000000ULL),PATCH_live_wrapper,1},
        {(u32)(MAG_LITERAL-0x4d3000000ULL),PATCH_mag_wrapper,0},
        {(u32)(LIVE_UPDATE_LITERAL-0x4d3000000ULL),PATCH_live_update_wrapper,2},
        {(u32)(MAG_UPDATE_LITERAL-0x4d3000000ULL),PATCH_mag_update_wrapper,0},
        {(u32)(CINE_LITERAL-0x4d3000000ULL),PATCH_cine_wrapper,3},
        {(u32)(CINE_UPDATE_LITERAL-0x4d3000000ULL),PATCH_cine_update_wrapper,4},
        {(u32)(0x4d3372868ULL-0x4d3000000ULL),PATCH_menu_rows,0},
        {(u32)(0x4d3372980ULL-0x4d3000000ULL),PATCH_menu_rows,0},
        {(u32)(0x4d3372be8ULL-0x4d3000000ULL),PATCH_menu_rows,0},
        {(u32)(0x4d3372d50ULL-0x4d3000000ULL),PATCH_menu_rows,0},
        {(u32)(0x4d3372ef0ULL-0x4d3000000ULL),PATCH_menu_rows,0},
        {(u32)(0x4d3373160ULL-0x4d3000000ULL),PATCH_menu_rows,0},
        {(u32)(0x4d33738c8ULL-0x4d3000000ULL),PATCH_menu_rows,0},
        {(u32)(0x4d3372d60ULL-0x4d3000000ULL),PATCH_menu_callbacks,0},
        {(u32)(0x4d3372f00ULL-0x4d3000000ULL),PATCH_menu_callbacks,0},
        {(u32)(0x4d3373170ULL-0x4d3000000ULL),PATCH_menu_callbacks,0},
        {(u32)(0x4d33738e0ULL-0x4d3000000ULL),PATCH_menu_callbacks,0},
        {(u32)(0x4d3372f38ULL-0x4d3000000ULL),PATCH_menu_input_wrapper,0},
        {(u32)(0x4d33731a8ULL-0x4d3000000ULL),PATCH_menu_input_wrapper,0},
        {(u32)(0x4d33731d0ULL-0x4d3000000ULL),PATCH_menu_parent_scene,0},
        {(u32)(DETECTOR_ISLAND+8-0x4d3000000ULL),PATCH_detector_gate_wrapper,0},
        {(u32)(SUBJECT_FRAME_ISLAND+8-0x4d3000000ULL),PATCH_subject_frame_wrapper,0},
        {(u32)(ASPECT_RAW+8-0x4d3000000ULL),PATCH_aspect_raw_wrapper,0},
        {(u32)(ASPECT_SET_ISLAND+8-0x4d3000000ULL),PATCH_aspect_stock_set_wrapper,0},
        {(u32)(ASPECT_LABEL_ISLAND+8-0x4d3000000ULL),PATCH_aspect_label_wrapper,0},
        {(u32)(ASPECT_MAIN_WRAPPER+8-0x4d3000000ULL),PATCH_aspect_main_wrapper,0},
        {(u32)(ASPECT_HALF_WRAPPER+8-0x4d3000000ULL),PATCH_aspect_half_wrapper,0},
        {(u32)(ASPECT_SMALL_WRAPPER+8-0x4d3000000ULL),PATCH_aspect_small_wrapper,0},
        {(u32)(ASPECT_META_ISLAND+8-0x4d3000000ULL),PATCH_aspect_meta_wrapper,0},
        {(u32)(ASPECT_DNG_ISLAND+8-0x4d3000000ULL),PATCH_aspect_dng_wrapper,0},
        {(u32)(ASPECT_RELEASE_ISLAND+8-0x4d3000000ULL),PATCH_aspect_release_wrapper,0},
        {(u32)(ASPECT_RESERVE_ISLAND+8-0x4d3000000ULL),PATCH_aspect_reserve_wrapper,0},
        {(u32)(0x4d3269718ULL-0x4d3000000ULL),PATCH_aspect_view,0},
        {(u32)(0x4d3269738ULL-0x4d3000000ULL),PATCH_aspect_view,0},
        {(u32)(0x4d3269768ULL-0x4d3000000ULL),PATCH_aspect_view,0},
        {(u32)(0x4d32697c8ULL-0x4d3000000ULL),PATCH_aspect_view,0},
        {(u32)(0x4d32697f8ULL-0x4d3000000ULL),PATCH_aspect_view,0},
        {(u32)(0x4d3269828ULL-0x4d3000000ULL),PATCH_aspect_view,0},
        {(u32)(0x4d3269878ULL-0x4d3000000ULL),PATCH_aspect_view,0},
    };
    const u32 patch_count=sizeof(p)/sizeof(p[0]);
    static const struct { uptr address; u64 original; } islands[]={
        {DETECTOR_ISLAND,DETECTOR_ISLAND_OLD},
        {SUBJECT_FRAME_ISLAND,SUBJECT_FRAME_OLD},
        {ASPECT_RAW,ASPECT_RAW_OLD},
        {ASPECT_SET_ISLAND,ASPECT_SET_OLD},
        {ASPECT_LABEL_ISLAND,ASPECT_LABEL_OLD},
        {ASPECT_MAIN_WRAPPER,ASPECT_MAIN_OLD},
        {ASPECT_HALF_WRAPPER,ASPECT_HALF_OLD},
        {ASPECT_SMALL_WRAPPER,ASPECT_SMALL_OLD},
        {ASPECT_META_ISLAND,ASPECT_META_OLD},
        {ASPECT_DNG_ISLAND,ASPECT_DNG_OLD},
        {ASPECT_RELEASE_ISLAND,ASPECT_RELEASE_OLD},
        {ASPECT_RESERVE_ISLAND,ASPECT_RESERVE_OLD},
    };
    static const struct { uptr address; u32 original,replacement; } calls[]={
        {DETECTOR_CALL,DETECTOR_CALL_OLD,DETECTOR_CALL_NEW},
        {ASPECT_LABEL_CALL,ASPECT_LABEL_CALL_OLD,ASPECT_LABEL_CALL_NEW},
        {ASPECT_META_CALL,ASPECT_META_CALL_OLD,ASPECT_META_CALL_NEW},
        {ASPECT_DNG_CALL,ASPECT_DNG_CALL_OLD,ASPECT_DNG_CALL_NEW},
        {ASPECT_RELEASE_CALL,ASPECT_RELEASE_CALL_OLD,ASPECT_RELEASE_CALL_NEW},
        {ASPECT_RESERVE_CALL,ASPECT_RESERVE_CALL_OLD,ASPECT_RESERVE_CALL_NEW},
#define ASPECT_STEP_PATCH(address) \
        {address,A64_BRANCH(address,0x4d33993e0ULL,1),A64_BRANCH(address,ASPECT_SET_ISLAND,1)},
        ASPECT_NATIVE_STEP_CALLS(ASPECT_STEP_PATCH)
#undef ASPECT_STEP_PATCH
#define ASPECT_NATIVE_LABEL_PATCH(address) \
        {address,A64_BRANCH(address,0x4d33724b0ULL,1),A64_BRANCH(address,ASPECT_LABEL_ISLAND,1)},
        ASPECT_NATIVE_LABEL_CALLS(ASPECT_NATIVE_LABEL_PATCH)
#undef ASPECT_NATIVE_LABEL_PATCH
#define ASPECT_SUBLCD_PATCH(address) \
        {address,A64_BRANCH(address,0x4d332dce0ULL,1),A64_BRANCH(address,ASPECT_LABEL_ISLAND,1)},
        ASPECT_NATIVE_SUBLCD_CALLS(ASPECT_SUBLCD_PATCH)
#undef ASPECT_SUBLCD_PATCH
    };
    const u32 island_count=sizeof(islands)/sizeof(islands[0]);
    const u32 call_count=sizeof(calls)/sizeof(calls[0]);
    u64 daif;
    int result=0;
    __asm__ volatile("mrs %0, daif\n msr daifset, #15" : "=r"(daif) :: "memory");
    if (Q(L2_SLOT)!=L2_RO || !idle_still_scene()) goto done;
    for (u32 i=0;i<patch_count;i++)
        if (Q(0x4d3000000ULL+p[i].offset)!=(install?originals[p[i].target]:patch_target(p[i].target,base))) goto done;
    for (u32 i=0;i<island_count;i++)
        if (Q(islands[i].address)!=(install?islands[i].original:DETECTOR_ISLAND_NEW)) goto done;
    for (u32 i=0;i<call_count;i++)
        if (W(calls[i].address)!=(install?calls[i].original:calls[i].replacement)) goto done;
    for (u32 i=0;i<7;i++)
        if (W(aspect_snapshot_sites[i])!=(install?0x2a0003e2U:0x12001c02U)) goto done;
    translation_at(L2_SLOT,L2_RO & ~0x80ULL);
    /* Budget arrays must see only the native low byte before any getter can
     * emit a tagged still snapshot. Restoration happens after admission seals. */
    if (install) for (u32 i=0;i<7;i++) {
        W(aspect_snapshot_sites[i])=0x12001c02U;
        clean_range(aspect_snapshot_sites[i],aspect_snapshot_sites[i]+4,ctr,1);
    }
    if (!install) {
        for (u32 i=0;i<call_count;i++) {
            W(calls[i].address)=calls[i].original;
            clean_range(calls[i].address,calls[i].address+4,ctr,1);
        }
        for (u32 i=0;i<island_count;i++) {
            Q(islands[i].address)=islands[i].original;
        }
    }
    for (u32 i=0;i<patch_count;i++) {
        uptr address=0x4d3000000ULL+p[i].offset;
        Q(address)=install?patch_target(p[i].target,base):originals[p[i].target];
        clean_range(address,address+8,ctr,0);
    }
    /* On removal the pointer slots for raw/small become instructions again;
     * publish the entire 16-byte region after restoring both halves. */
    for (u32 i=0;i<island_count;i++) {
        if (install) Q(islands[i].address)=DETECTOR_ISLAND_NEW;
        clean_range(islands[i].address,islands[i].address+16,ctr,1);
    }
    if (install) for (u32 i=0;i<call_count;i++) {
        W(calls[i].address)=calls[i].replacement;
        clean_range(calls[i].address,calls[i].address+4,ctr,1);
    }
    if (!install) for (u32 i=0;i<7;i++) {
        W(aspect_snapshot_sites[i])=0x2a0003e2U;
        clean_range(aspect_snapshot_sites[i],aspect_snapshot_sites[i]+4,ctr,1);
    }
    translation_at(L2_SLOT,L2_RO);
    for (u32 i=0;i<patch_count;i++) {
        uptr runtime=runtimes[p[i].runtime];
        u64 before=originals[p[i].target], after=patch_target(p[i].target,base);
        if (runtime && Q(runtime)==(install?before:after)) Q(runtime)=install?after:before;
    }
    result=1;
done:
    __asm__ volatile("dsb ish\n msr daif, %0\n isb" :: "r"(daif) : "memory");
    return result;
}

/* Called only after the loader has verified the complete initialized image,
 * zeroed its BSS, and published the complete resident instruction range. */
static u32 initialize_resident(uptr base, uptr owner, u64 nonce, u32 mode, u64 ctr) {
    volatile struct State *s=(volatile struct State *)(uptr)relocate((void *)&state,base);
    s->magic=MAGIC; s->version=1;
    s->owner=owner; s->nonce=nonce; s->mode=mode;
    __asm__(".global __scratch_size\n.set __scratch_size, %c0" :: "i"(RESIDENT_SCRATCH_BYTES));
    menu_initialize(base);
    aspect_initialize(base);
    clean_range(base,base+(uptr)__end-(uptr)__start,ctr,1);
    return patch_all(base,1,ctr) ? 0 : 6;
}

u32 resident_entry(u32 operation, const struct LoaderControl *request, u64 ctr) {
    uptr base=(uptr)__start;
    if (!request || request->magic!=LOADER_CONTROL_MAGIC ||
        request->abi_version!=LOADER_ABI_VERSION || request->struct_size!=sizeof(*request) ||
        request->resident!=base || request->image_size!=(uptr)__image_end-base ||
        request->memory_size!=(uptr)__end-base || request->scratch_size!=RESIDENT_SCRATCH_BYTES ||
        !request->identity_nonce || request->mode>1 || Q(L2_SLOT)!=L2_RO || !idle_still_scene()) return 11;
    if (operation==LOADER_INSTALL_ENTRY) {
        if (state.magic) return 8;
        return initialize_resident(base,request->owner,request->identity_nonce,request->mode,ctr);
    }
    if (operation!=LOADER_REMOVE_ENTRY || state.magic!=MAGIC || state.version!=1 ||
        state.nonce!=request->identity_nonce || state.owner!=request->owner) return 8;
    if (state.active) return 9;
    if (!aspect_seal(base)) return 12;
    u32 result=patch_all(base,0,ctr) ? 0 : 6;
    if (!result) {
        state.mode=2;
        if (aspect_ratio.selected) ((void (*)(void))(uptr)0x4d33a03a0ULL)();
    } else __atomic_fetch_and(&aspect_ratio.capture,~ASPECT_SEALED,__ATOMIC_RELEASE);
    return result;
}

/* Storage callback: restore callback first, preserve its arguments, execute one
 * operation, call the real storage writer, and publish a fresh nonce LAST. */
__attribute__((section(".text.entry"), minsize))
u32 bootstrap(u32 block, u32 count, void *buffer) {
    Q(CALLBACK)=ORIGINAL;
    __asm__ volatile("dsb ish" ::: "memory");
    u64 el,ctr,mair=0,tcr=0;
    __asm__ volatile("mrs %0, CurrentEL\n mrs %1, ctr_el0" : "=r"(el),"=r"(ctr));
    control.el=el; control.ctr=ctr;
    control.result=1;
    if (el!=4) goto finish;
    __asm__ volatile("mrs %0, mair_el1\n mrs %1, tcr_el1" : "=r"(mair),"=r"(tcr));
    control.mair=mair; control.tcr=tcr;
    if (Q(L2_SLOT)!=L2_RO) { control.result=2; goto finish; }
    if (!idle_still_scene()) { control.result=11; goto finish; }
    if (control.command==0) {
        if (Q(LIVE_LITERAL)!=LIVE_ORIGINAL || Q(MAG_LITERAL)!=MAG_ORIGINAL ||
            Q(LIVE_UPDATE_LITERAL)!=LIVE_UPDATE_ORIGINAL || Q(MAG_UPDATE_LITERAL)!=MAG_UPDATE_ORIGINAL ||
            Q(CINE_LITERAL)!=CINE_ORIGINAL || Q(CINE_UPDATE_LITERAL)!=CINE_UPDATE_ORIGINAL) {
            control.result=3; goto finish;
        }
        uptr allocated=0;
        uptr size=(uptr)__end-(uptr)__start;
        u32 ok=((u32 (*)(u64,u64,u32,u32,uptr*,int))(uptr)0x4d330c850ULL)(
            size+4095+RESIDENT_SCRATCH_BYTES,0x400000000ULL,0,0,&allocated,100);
        if (!(ok&255) || !allocated) { control.result=4; goto finish; }
        uptr base=(allocated+4095)&~4095ULL;
        if (base<0x400d20c00ULL || base>0x4fff00000ULL || base+size+RESIDENT_SCRATCH_BYTES>0x500000000ULL) {
            control.result=5; goto finish;
        }
        volatile u8 *dest=(volatile u8 *)base;
        uptr image_size=(uptr)__image_end-(uptr)__start;
        for (uptr i=0;i<image_size;i++) dest[i]=__start[i];
        for (uptr i=image_size;i<size;i++) dest[i]=0;
        control.resident=base;
        control.result=initialize_resident(base,allocated,control.nonce,control.mode,ctr);
    } else if (control.command==1) {
        uptr base=control.resident;
        if (base<0x400d20c00ULL || base>0x4fff00000ULL || (base&4095)) {
            control.result=7; goto finish;
        }
        volatile struct State *s=(volatile struct State *)(uptr)relocate((void *)&state,base);
        u64 live=relocate((void *)live_wrapper,base), mag=relocate((void *)mag_wrapper,base);
        if (s->magic!=MAGIC || s->version!=1 || Q(LIVE_LITERAL)!=live || Q(MAG_LITERAL)!=mag) {
            control.result=8; goto finish;
        }
        if (s->active) { control.result=9; goto finish; }
        if (!aspect_seal(base)) { control.result=12; goto finish; }
        control.result=patch_all(base,0,ctr)?0:6;
        volatile struct AspectRatio *a=(void *)(uptr)relocate((const void *)&aspect_ratio,base);
        if (!control.result) {
            s->mode=2;
            if (a->selected) ((void (*)(void))(uptr)0x4d33a03a0ULL)();
        } else __atomic_fetch_and(&a->capture,~ASPECT_SEALED,__ATOMIC_RELEASE);
        /* A queued scene may still retain a wrapper. Allocation stays owned
         * until reboot; disabled wrappers safely forward to the stock code. */
    } else {
        control.result=10;
    }
finish:;
    u32 rc=((u32 (*)(u32,u32,void*))(uptr)ORIGINAL)(block,count,buffer);
    control.storage_rc=rc;
    __asm__ volatile("dsb ish" ::: "memory");
    control.done=control.nonce;
    clean_range((uptr)&control,(uptr)&control+sizeof(control),ctr,0);
    return rc;
}
