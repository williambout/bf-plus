/* Original BF+ aspect controls for BF 1.04. All crop rectangles stay inside
 * native buffers. RAW pixels are preserved; DefaultUserCrop carries framing. */
#ifndef BF_ASPECT_RATIO_H
#define BF_ASPECT_RATIO_H
#define ASPECT_VIEW_TABLE 0x4d3cabc60ULL
#define ASPECT_MAIN_TABLE 0x4d3daa870ULL
#define ASPECT_HALF_TABLE 0x4d3daa720ULL
#define ASPECT_SMALL_TABLE 0x4d3daa6c8ULL
#define ASPECT_DNG_TABLE 0x4d3cab100ULL
#define ASPECT_MAIN_WRAPPER 0x4d3288b60ULL
#define ASPECT_HALF_WRAPPER 0x4d3288b70ULL
#define ASPECT_SMALL_WRAPPER 0x4d3288b80ULL
#define ASPECT_META_ISLAND 0x4d33208c0ULL
#define ASPECT_DNG_ISLAND 0x4d33208d0ULL
#define ASPECT_RELEASE_ISLAND 0x4d33208e0ULL
#define ASPECT_RESERVE_ISLAND 0x4d33208f0ULL
#define ASPECT_META_CALL 0x4d32fd9dcULL
#define ASPECT_DNG_CALL 0x4d32621bcULL
#define ASPECT_RELEASE_CALL 0x4d3268fecULL
#define ASPECT_RESERVE_CALL 0x4d3268ea8ULL
#define ASPECT_TAG 0xbf000000U
#define ASPECT_SEALED 4U
#define ASPECT_PENDING_UNIT 256U
#define ASPECT_META_BASE 0x400000000ULL
#define ASPECT_JOBS 192U
#define ASPECT_RAW 0x4d3317670ULL
#define ASPECT_SET_ISLAND 0x4d33208a0ULL
#define ASPECT_LABEL_ISLAND 0x4d33208b0ULL
#define ASPECT_LABEL_CALL 0x4d335693cULL
/* Only these native aspect-editor calls receive private UI indices. The
 * ordinary camera property and every image pipeline still receive 0..6. */
#define ASPECT_NATIVE_STEP_CALLS(X) \
    X(0x4d3394c10ULL) X(0x4d33a3200ULL) X(0x4d33a3644ULL) \
    X(0x4d33a3fb0ULL) X(0x4d33a403cULL) X(0x4d33a41a0ULL)
#define ASPECT_NATIVE_LABEL_CALLS(X) X(0x4d33a2aa0ULL) X(0x4d33a3700ULL)
#define ASPECT_NATIVE_SUBLCD_CALLS(X) X(0x4d336a134ULL)
#define ASPECT_NATIVE_ARROW_RETURN 0x4d33a366cULL
#define A64_LDR_UIMM(rt,rn,offset,wide) (((wide)?0xf9400000U:0xb9400000U) | \
    (((offset)/((wide)?8U:4U))<<10) | ((rn)<<5) | (rt))
/* Reconstruct the two primitive loads and their literal-pool load from the
 * ISA operands. The source and target page of ADRP x0 are identical. */
#define ASPECT_RAW_OLD (0x90000000ULL | ((u64)A64_LDR_UIMM(0,0,0x688,1)<<32))
#define ASPECT_RAW_SLOT_OLD ((u64)A64_LDR_UIMM(0,0,0,1) | \
    ((u64)A64_LDR_UIMM(0,0,0x18,0)<<32))
#define ASPECT_SET_OLD ((u64)A64_BRANCH(ASPECT_SET_ISLAND,0x4d3317690ULL,0))
#define ASPECT_LABEL_OLD ((u64)A64_BRANCH(ASPECT_LABEL_ISLAND,0x4d33176b0ULL,0))
#define ASPECT_LABEL_CALL_OLD A64_BRANCH(ASPECT_LABEL_CALL,0x4d33724b0ULL,1)
#define ASPECT_LABEL_CALL_NEW A64_BRANCH(ASPECT_LABEL_CALL,ASPECT_LABEL_ISLAND,1)

#define ASPECT_SMALL_OLD (0x2a0103e0ULL | (0xaa0203e1ULL<<32))
#define ASPECT_SMALL_SLOT_OLD (0xaa0303e2ULL | \
    ((u64)A64_BRANCH(ASPECT_SMALL_WRAPPER+12,0x4d3295f60ULL,0)<<32))

/* capture atomically couples choice (bits0..1), removal seal (bit2), and
 * snapshots not yet materialized (bits8..31). UI selected remains unencoded. */
#define ASPECT_MAIN_OLD ((u64)A64_BRANCH(ASPECT_MAIN_WRAPPER,0x4d3295ec0ULL,0))
#define ASPECT_HALF_OLD ((u64)A64_BRANCH(ASPECT_HALF_WRAPPER,0x4d3295f10ULL,0))
#define ASPECT_META_OLD ((u64)A64_BRANCH(ASPECT_META_ISLAND,0x4d33176d0ULL,0))
#define ASPECT_DNG_OLD ((u64)A64_BRANCH(ASPECT_DNG_ISLAND,0x4d33176f0ULL,0))
#define ASPECT_RELEASE_OLD ((u64)A64_BRANCH(ASPECT_RELEASE_ISLAND,0x4d3317860ULL,0))
#define ASPECT_RESERVE_OLD ((u64)A64_BRANCH(ASPECT_RESERVE_ISLAND,0x4d33179c0ULL,0))
#define ASPECT_META_CALL_OLD A64_LDR_UIMM(0,21,0x10,0)
#define ASPECT_META_CALL_NEW A64_BRANCH(ASPECT_META_CALL,ASPECT_META_ISLAND,1)
#define ASPECT_DNG_CALL_OLD A64_BRANCH(ASPECT_DNG_CALL,0x4d3007fc0ULL,1)
#define ASPECT_DNG_CALL_NEW A64_BRANCH(ASPECT_DNG_CALL,ASPECT_DNG_ISLAND,1)
#define ASPECT_RELEASE_CALL_OLD A64_BRANCH(ASPECT_RELEASE_CALL,0x4d30339d0ULL,1)
#define ASPECT_RELEASE_CALL_NEW A64_BRANCH(ASPECT_RELEASE_CALL,ASPECT_RELEASE_ISLAND,1)
#define ASPECT_RESERVE_CALL_OLD A64_BRANCH(ASPECT_RESERVE_CALL,0x4d3033ab0ULL,1)
#define ASPECT_RESERVE_CALL_NEW A64_BRANCH(ASPECT_RESERVE_CALL,ASPECT_RESERVE_ISLAND,1)

struct AspectRatio { u32 selected, view_size, rejected, capture; };
volatile struct AspectRatio aspect_ratio;
/* Separate setting keeps the existing capture-state ABI unchanged. */
volatile u32 aspect_extra_enabled;
struct AspectSize { u16 width, height; };
_Static_assert(sizeof(struct AspectSize)==4, "native aspect size ABI");
volatile struct AspectSize aspect_view[7];
static const char aspect_xpan_label[]="65:24";
static const char aspect_cinema_label[]="2.35:1";
static const char aspect_photo_label[]="5:4";
/* Stock sub-LCD white numerals, colon and decimal point. The native sequence
 * renderer measures/centers these 26-pixel glyphs just like other status text. */
static const u32 aspect_sublcd_labels[3][7]={
    {30,26,53,14,22,0,0}, {14,57,18,26,53,10,0}, {26,53,22,0,0,0,0}
};
static u64 relocate(const void *symbol, uptr base);

static u32 aspect_effective(void) {
    u32 selected=__atomic_load_n(&aspect_ratio.capture,__ATOMIC_ACQUIRE)&3;
    return state.mode!=2 && selected<=3 ? selected : 0;
}
static u32 aspect_native_index(u32 selected) { return selected==3 ? 5 : 0; }
struct AspectCrop { u32 x,y; u16 width,height; };
_Static_assert(sizeof(struct AspectCrop)==12, "native crop ABI");
volatile struct AspectCrop aspect_half[3][2], aspect_small[3][2];
volatile u32 aspect_dng[3][2][8];
volatile u8 aspect_jobs[ASPECT_JOBS];
/* Exact pixel ratios, with 16-byte aligned starts in the native planes. */
static const struct AspectCrop aspect_main[3][2]={
    {{80,186,5980,2208},{96,128,3770,1392}},
    {{64,10,6016,2560},{96,24,3760,1600}},
    {{64,14,4980,3984},{64,8,3180,2544}}
};
static void aspect_copy(volatile void *out, uptr in, u32 size) {
    volatile u8 *dst=out;
    for (u32 i=0;i<size;i++) dst[i]=B(in+i);
}
static void aspect_preview(volatile struct AspectCrop *out,
                           const struct AspectCrop *native,
                           const struct AspectCrop *main,
                           const struct AspectCrop *crop) {
    u32 width=(u32)native->width*crop->width/main->width & ~1U;
    u32 height=(u32)native->height*crop->height/main->height & ~1U;
    u32 x=native->x+((crop->x-main->x)*native->width+main->width/2)/main->width;
    u32 y=native->y+((crop->y-main->y)*native->height+main->height/2)/main->height;
    x=(x+8)&~15U;
    u32 max_x=(native->x+native->width-width)&~15U;
    if (x>max_x) x=max_x;
    if (y+height>native->y+native->height) y=native->y+native->height-height;
    out->x=x; out->y=y; out->width=(u16)width; out->height=(u16)height;
}
static void aspect_geometry(u32 selected, u32 size) {
    aspect_copy(aspect_view,ASPECT_VIEW_TABLE,sizeof(aspect_view));
    if (selected) {
        const struct AspectCrop *crop=&aspect_main[selected-1][size];
        const struct AspectCrop *full=(const struct AspectCrop *)(uptr)ASPECT_MAIN_TABLE+size*7+2;
        volatile struct AspectSize *view=&aspect_view[aspect_native_index(selected)];
        /* Round to the nearest even logical pixel. Native view geometry is
         * centered, so aligned JPEG starts can differ by at most a few pixels. */
        view->width=(u16)(((u32)aspect_view[2].width*crop->width+full->width)/(2*full->width)*2);
        view->height=(u16)(((u32)aspect_view[2].height*crop->height+full->height)/(2*full->height)*2);
    }
    aspect_ratio.view_size=size;
}
static u32 aspect_size(void) { return ((u32 (*)(void))(uptr)0x4d33226f0ULL)()==1; }
static u32 aspect_job_id(uptr metadata) {
    uptr offset=metadata-ASPECT_META_BASE;
    return !(offset&4095) && offset<ASPECT_JOBS*4096 ? (u32)(offset>>12) : ASPECT_JOBS;
}
static u32 aspect_job(uptr metadata) {
    u32 id=aspect_job_id(metadata);
    if (id>=ASPECT_JOBS) return 0;
    u32 selected=__atomic_load_n(&aspect_jobs[id],__ATOMIC_ACQUIRE);
    return selected && selected<4 && W(metadata+0x74)==aspect_native_index(selected) ? selected : 0;
}
/* Only native JPEG descriptor-builder callers supply x20 as metadata. Each
 * wrapper retains the native buffer descriptor and replaces only its crop. */
__attribute__((used,noinline))
u64 aspect_jpeg_common(u32 size,u32 index,uptr *buffer,uptr *crop,
                      uptr metadata,u32 kind,uptr caller) {
    u64 result;
    if (kind==2)
        result=((u64 (*)(u32,uptr*,uptr*))(uptr)0x4d3295f60ULL)(index,buffer,crop);
    else result=((u64 (*)(u32,u32,uptr*,uptr*))(uptr)(kind ? 0x4d3295f10ULL : 0x4d3295ec0ULL))(
        size,index,buffer,crop);
    static const uptr callers[]={0x4d3300158ULL,0x4d33001b4ULL,0x4d330020cULL};
    if (size<2 && caller==callers[kind]) {
        u32 selected=aspect_job(metadata);
        if (selected && index==aspect_native_index(selected)) {
            if (!kind) *crop=(uptr)&aspect_main[selected-1][size];
            else if (kind==1) *crop=(uptr)&aspect_half[selected-1][size];
            else *crop=(uptr)&aspect_small[selected-1][size];
        }
    }
    return result;
}
#define ASPECT_JPEG_BRIDGE(name,number) \
    __attribute__((naked)) void name(void) { __asm__ volatile( \
        "mov x4,x20\n mov w5,#" #number "\n mov x6,x30\n b aspect_jpeg_common"); }
ASPECT_JPEG_BRIDGE(aspect_main_wrapper,0)
ASPECT_JPEG_BRIDGE(aspect_half_wrapper,1)
ASPECT_JPEG_BRIDGE(aspect_small_wrapper,2)

__attribute__((used,noinline))
u32 aspect_meta_common(u32 encoded,uptr metadata,uptr caller,uptr snapshot) {
    if (caller!=ASPECT_META_CALL+4) {
        ((void (*)(u32))(uptr)0x4d33176d0ULL)(encoded);
        return encoded;
    }
    encoded=W(snapshot+0x10);
    u32 selected=(encoded>>8)&3, native=encoded;
    u32 tagged=selected && encoded==(ASPECT_TAG|(selected<<8)|aspect_native_index(selected));
    if (tagged) native=aspect_native_index(selected);
    else selected=0;
    u32 id=aspect_job_id(metadata);
    if (id<ASPECT_JOBS) __atomic_store_n(&aspect_jobs[id],(u8)selected,__ATOMIC_RELEASE);
    else if (tagged) { aspect_ratio.rejected++; return native; }
    if (tagged) {
        u32 old=__atomic_load_n(&aspect_ratio.capture,__ATOMIC_RELAXED);
        while (old>=ASPECT_PENDING_UNIT && !__atomic_compare_exchange_n(
            &aspect_ratio.capture,&old,old-ASPECT_PENDING_UNIT,0,__ATOMIC_RELEASE,__ATOMIC_RELAXED)) {}
    }
    return native;
}
__attribute__((naked)) void aspect_meta_wrapper(void) {
    __asm__ volatile("mov x1,x19\n mov x2,x30\n mov x3,x21\n b aspect_meta_common");
}
__attribute__((used,noinline))
uptr aspect_dng_common(uptr out,uptr in,u64 length,uptr metadata,uptr caller) {
    if (caller!=ASPECT_DNG_CALL+4)
        return ((uptr (*)(uptr,uptr,u64))(uptr)0x4d33176f0ULL)(out,in,length);
    u32 selected=aspect_job(metadata), size=W(metadata+0x58);
    if (selected && size<2 && length==32 &&
        in==ASPECT_DNG_TABLE+aspect_native_index(selected)*64+size*32)
        in=(uptr)&aspect_dng[selected-1][size];
    return ((uptr (*)(uptr,uptr,u64))(uptr)0x4d3007fc0ULL)(out,in,length);
}
__attribute__((naked)) void aspect_dng_wrapper(void) {
    __asm__ volatile("mov x3,x27\n mov x4,x30\n b aspect_dng_common");
}
u64 aspect_release_wrapper(u32 queue,uptr pointer,u32 length) {
    uptr caller; __asm__ volatile("mov %0,x30" : "=r"(caller));
    if (caller!=ASPECT_RELEASE_CALL+4)
        return ((u64 (*)(u32,uptr,u32))(uptr)0x4d3317860ULL)(queue,pointer,length);
    if (length==2) {
        u32 id=B(pointer)|((u32)B(pointer+1)<<8);
        if (id<ASPECT_JOBS) __atomic_store_n(&aspect_jobs[id],0,__ATOMIC_RELEASE);
    }
    return ((u64 (*)(u32,uptr,u32))(uptr)0x4d30339d0ULL)(queue,pointer,length);
}
u64 aspect_reserve_wrapper(u32 queue,uptr pointer,u32 timeout) {
    uptr caller; __asm__ volatile("mov %0,x30" : "=r"(caller));
    if (caller!=ASPECT_RESERVE_CALL+4)
        return ((u64 (*)(u32,uptr,u32))(uptr)0x4d33179c0ULL)(queue,pointer,timeout);
    /* Receive clobbers x1. C preserves this original destination across the
     * call. Success is TWO bytes received; w2 is a timeout, not a byte count. */
    u64 result=((u64 (*)(u32,uptr,u32))(uptr)0x4d3033ab0ULL)(queue,pointer,timeout);
    if ((u32)result==2) {
        u32 id=B(pointer)|((u32)B(pointer+1)<<8);
        if (id<ASPECT_JOBS) __atomic_store_n(&aspect_jobs[id],0,__ATOMIC_RELEASE);
    }
    return result;
}
/* Caller seals before restoring any hook. A successful seal excludes every
 * later tagged snapshot; already-tagged snapshots and live jobs deny removal.
 * No native queues/tasks are blocked. Failure unseals without changing choice. */
static int aspect_seal(uptr base) {
    volatile struct AspectRatio *a=(void *)(uptr)relocate((const void *)&aspect_ratio,base);
    volatile u8 *jobs=(void *)(uptr)relocate((const void *)aspect_jobs,base);
    u32 busy=__atomic_fetch_or(&a->capture,ASPECT_SEALED,__ATOMIC_ACQ_REL)>=ASPECT_PENDING_UNIT;
    for (u32 i=0;i<ASPECT_JOBS;i++) busy|=__atomic_load_n(&jobs[i],__ATOMIC_ACQUIRE);
    if (busy) __atomic_fetch_and(&a->capture,~ASPECT_SEALED,__ATOMIC_RELEASE);
    return !busy;
}
__attribute__((used,noinline)) static void aspect_select(u32 value) {
    if (value>3 || state.mode==2 || (value && !aspect_extra_enabled) ||
        value==aspect_ratio.selected) return;
    u32 old=__atomic_load_n(&aspect_ratio.capture,__ATOMIC_RELAXED);
    do { if (old&ASPECT_SEALED) return; }
    while (!__atomic_compare_exchange_n(&aspect_ratio.capture,&old,(old&~3U)|value,
                                        0,__ATOMIC_RELEASE,__ATOMIC_RELAXED));
    aspect_geometry(value,aspect_size());
    aspect_ratio.selected=value;
    ((void (*)(void))(uptr)0x4d33a03a0ULL)();
}
__attribute__((used,noinline)) static void aspect_extra_select(u32 enabled) {
    if (enabled>1 || state.mode==2 || enabled==aspect_extra_enabled) return;
    if (!enabled) {
        aspect_select(0);
        if (aspect_ratio.selected) return; /* A removal seal owns the state. */
    }
    aspect_extra_enabled=enabled;
}
static int aspect_native_available(void) {
    return aspect_extra_enabled && state.mode!=2 &&
        ((u32 (*)(void))(uptr)0x4d3319c60ULL)()!=1 &&
        ((u32 (*)(void))(uptr)0x4d330f3f0ULL)()!=0x10 &&
        ((u32 (*)(void))(uptr)0x4d3315350ULL)()!=5;
}
static int aspect_native_step_site(uptr caller) {
#define ASPECT_STEP_RETURN(address) address+4,
    static const uptr sites[]={ ASPECT_NATIVE_STEP_CALLS(ASPECT_STEP_RETURN) };
#undef ASPECT_STEP_RETURN
    for (u32 i=0;i<sizeof(sites)/sizeof(sites[0]);i++)
        if (caller==sites[i]) return 1;
    return 0;
}
static int aspect_native_set_site(uptr caller) {
    static const uptr sites[]={0x4d3394c24ULL,0x4d33a320cULL,0x4d33a3650ULL,
        0x4d33a3fbcULL,0x4d33a4048ULL,0x4d33a41acULL};
    for (u32 i=0;i<sizeof(sites)/sizeof(sites[0]);i++)
        if (caller==sites[i]) return 1;
    return 0;
}
__attribute__((used,noinline))
u32 aspect_snapshot_value(void) {
    u32 old=__atomic_load_n(&aspect_ratio.capture,__ATOMIC_RELAXED), selected;
    do {
        selected=old&3;
        if (!selected || (old&ASPECT_SEALED) || old>=0xffffff00U)
            return W(Q(0x4d7301b98ULL)+0x18);
    } while (!__atomic_compare_exchange_n(&aspect_ratio.capture,&old,old+ASPECT_PENDING_UNIT,
                                          0,__ATOMIC_ACQ_REL,__ATOMIC_RELAXED));
    return ASPECT_TAG|(selected<<8)|aspect_native_index(selected);
}
/* These seven still snapshot sites also mask their budget argument to the
 * low byte. Type2/movie setup and readiness-only reads MUST remain untagged. */
static const uptr aspect_snapshot_sites[]={
    0x4d324358cULL,0x4d3243ac4ULL,0x4d3244174ULL,0x4d3244280ULL,
    0x4d324447cULL,0x4d3244820ULL,0x4d3244b50ULL
};
static int aspect_is_snapshot(uptr caller) {
    for (u32 i=0;i<7;i++) if (caller==aspect_snapshot_sites[i]) return 1;
    return 0;
}
u32 aspect_raw_wrapper(void) {
    uptr caller;
    __asm__ volatile("mov %0, x30" : "=r"(caller));
    if (state.mode!=2 && aspect_is_snapshot(caller)) return aspect_snapshot_value();
    u32 selected=aspect_effective();
    /* This one getter result is used only for left/right arrow availability.
     * Preserve the stock three-way arrow test without exposing an extended
     * index to any native table or image geometry consumer. */
    if (caller==ASPECT_NATIVE_ARROW_RETURN && aspect_native_available()) {
        u32 position=selected ? 6+selected : W(Q(0x4d7301b98ULL)+0x18);
        return position==0 ? 0 : position>=9 ? 6 : 1;
    }
    /* The bulk setting-copy routine reads and writes the same property.
     * Its round-trip must preserve the real stored setting. */
    if (selected && caller!=0x4d331f5d4ULL && caller!=0x4d324344cULL) {
        u32 size=aspect_size();
        if (size!=aspect_ratio.view_size) aspect_geometry(selected,size);
        return aspect_native_index(selected);
    }
    return W(Q(0x4d7301b98ULL)+0x18);
}
u32 aspect_stock_set_wrapper(u32 value,u32 step,u32 maximum,u32 minimum,u32 wrap) {
    uptr caller;
    __asm__ volatile("mov %0, x30" : "=r"(caller));
    u32 selected=aspect_effective();
    if (aspect_native_step_site(caller)) {
        if (aspect_native_available() && value<=6) {
            value=selected ? 6+selected : value;
            maximum=9;
        }
        return ((u32 (*)(u32,u32,u32,u32,u32))(uptr)0x4d33993e0ULL)
            (value,step,maximum,minimum,wrap);
    }
    if (value>=7 && value<=9 && aspect_native_set_site(caller)) {
        /* A mode transition between step and commit must not publish a
         * private UI index into the native setting. */
        if (aspect_native_available()) aspect_select(value-6);
        return 0;
    }
    /* Opening the stock chooser normalizes the current enum with step zero.
     * Opening alone must neither commit the private crop nor erase it. */
    if (selected && caller==0x4d33a3650ULL && value==aspect_native_index(selected)) return 0;
    __atomic_fetch_and(&aspect_ratio.capture,~3U,__ATOMIC_RELEASE);
    aspect_ratio.selected=0;
    aspect_geometry(0,0);
    ((void (*)(u32))(uptr)0x4d3317690ULL)(value);
    return 0;
}
uptr aspect_label_wrapper(uptr argument,u32 flags,u32 glyph) {
    uptr caller;
    __asm__ volatile("mov %0, x30" : "=r"(caller));
    u32 selected=aspect_effective();
    if (caller==0x4d336a138ULL) {
        if (aspect_native_available() && ((glyph==0xd0 && (selected==1 || selected==2)) ||
                                         (glyph==0xd3 && selected==3)))
            return ((uptr (*)(uptr,u32,const u32*,u32))(uptr)0x4d332dd30ULL)
                (argument,flags,aspect_sublcd_labels[selected-1],0);
        return ((uptr (*)(uptr,u32,u32))(uptr)0x4d332dce0ULL)(argument,flags,glyph);
    }
    if (caller!=ASPECT_LABEL_CALL+4 && caller!=0x4d33a2aa4ULL &&
        caller!=0x4d33a3704ULL)
        return ((u32 (*)(void))(uptr)0x4d33176b0ULL)();
    u32 id=(u32)argument;
    if (id==0x100 && (selected==1 || selected==2))
        return (uptr)(selected==1 ? aspect_xpan_label : aspect_cinema_label);
    if (id==0x103 && selected==3) return (uptr)aspect_photo_label;
    return ((uptr (*)(u32))(uptr)0x4d33724b0ULL)(id);
}
static void aspect_initialize(uptr base) {
    aspect_copy((void *)(uptr)relocate((const void *)aspect_view,base),ASPECT_VIEW_TABLE,sizeof(aspect_view));
    for (u32 selected=1;selected<4;selected++) for (u32 size=0;size<2;size++) {
        u32 index=aspect_native_index(selected), row=size*7+index;
        const struct AspectCrop *crop=&aspect_main[selected-1][size];
        const struct AspectCrop *main=(const struct AspectCrop *)(uptr)ASPECT_MAIN_TABLE+row;
        volatile struct AspectCrop *half=(void *)(uptr)relocate((const void *)&aspect_half[selected-1][size],base);
        volatile struct AspectCrop *small=(void *)(uptr)relocate((const void *)&aspect_small[selected-1][size],base);
        aspect_preview(half,(const struct AspectCrop *)(uptr)ASPECT_HALF_TABLE+row,main,crop);
        aspect_preview(small,(const struct AspectCrop *)(uptr)ASPECT_SMALL_TABLE+index,main,crop);
        volatile u32 *dng=(void *)(uptr)relocate((const void *)aspect_dng[selected-1][size],base);
        aspect_copy(dng,ASPECT_DNG_TABLE+index*64+size*32,32);
        dng[0]+=crop->y-main->y; dng[2]+=crop->x-main->x;
        dng[4]=dng[0]+crop->height-1; dng[6]=dng[2]+crop->width-1;
    }
}
#endif
