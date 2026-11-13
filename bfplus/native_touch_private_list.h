/* V104 user-settings list 3386a00 ONLY. Private rows are built on the stack
 * and copied through a viewport. Parent owns frame publication and epochs.
 * See docs/NATIVE-TOUCH-PRIVATE-LIST.md. No native state is written here. */
#ifndef BF_NATIVE_TOUCH_PRIVATE_LIST_H
#define BF_NATIVE_TOUCH_PRIVATE_LIST_H
#ifndef NATIVE_TOUCH_PRIVATE_LIST_ENABLED
#define NATIVE_TOUCH_PRIVATE_LIST_ENABLED() 1
#endif
#ifndef NATIVE_TOUCH_PRIVATE_LIST_TRANSFORM
#define NATIVE_TOUCH_PRIVATE_LIST_TRANSFORM(out,source) \
    do { for (u32 npl_i=0;npl_i<20;npl_i++) (out)[npl_i]=((const u8 *)(source))[npl_i]; } while (0)
#endif

#define NPL_INPUT 0x4d3386a00ULL
#define NPL_PRIVATE 0x4d7043708ULL
#define NPL_WORD(a) (*(volatile u32 *)(uptr)(a))
#define NPL_DEPTH NPL_WORD(0x4d70346a0ULL)
#define NPL_PENDING NPL_WORD(0x4d70346a4ULL)
#define NPL_SELECTED NPL_WORD(0x4d7302ec0ULL)
#define NPL_OFFSET NPL_WORD(0x4d70436e0ULL)
#define NPL_HIGHLIGHT NPL_WORD(0x4d70436d8ULL)

struct NplView {
    const void *canvas;
    u64 buffer;
    u32 token,epoch,depth,entry_depth,pending,selected,offset;
    u32 count,rows,seen,bad,valid;
    u8 metadata[130],flags[11];
};
static struct NplView npl_view;
static u32 npl_gate,npl_dispatch,npl_generation,npl_capture,npl_aborted;
static struct {
    u32 active,blocked,epoch,depth,aborted;
    u8 metadata[130];
    int x,y,selected;
} npl_gesture;

static u16 npl_read16(const void *p) {
    struct __attribute__((packed)) Npl16 { u16 value; };
    return ((const struct Npl16 *)p)->value;
}
static u32 npl_revision(void) { return __atomic_load_n(&npl_generation,__ATOMIC_ACQUIRE); }
static u32 npl_bump(void) {
    u32 value=__atomic_add_fetch(&npl_generation,1,__ATOMIC_ACQ_REL);
    return value ? value : __atomic_add_fetch(&npl_generation,1,__ATOMIC_ACQ_REL);
}
static u32 npl_acquire(u32 *gate) {
    u32 expected=0;
    return __atomic_compare_exchange_n(gate,&expected,1,0,__ATOMIC_ACQUIRE,__ATOMIC_RELAXED);
}
static void npl_unlock(void) { __atomic_store_n(&npl_gate,0,__ATOMIC_RELEASE); }
static void npl_cancel(void) {
    npl_gesture.blocked |= npl_gesture.active;
    npl_gesture.active=0;
}
void native_touch_private_list_reset(void) {
    __atomic_add_fetch(&npl_aborted,1,__ATOMIC_RELEASE);
    npl_bump();
    if (npl_acquire(&npl_gate)) { npl_view.valid=0; npl_unlock(); }
}
u64 native_touch_private_list_handler_for_draw(u64 fn) {
    return fn==0x4d33861b0ULL || fn==0x4d33865d0ULL ? NPL_INPUT : 0;
}
static u32 npl_equal(const u8 *a,const u8 *b) {
    for (u32 i=0;i<130;i++) if (a[i]!=b[i]) return 0;
    return 1;
}
/* 31a4b10's cached getter reads count/+7c and first-enabled/+81. Its lazy
 * path fixes the buffer to 405118d00. Never invoke that loading path from a
 * capture lock. Also retain record/link bytes, not just count, so replacing
 * entries at the same count cannot confirm a previously displayed index. */
static u32 npl_metadata(u8 out[130]) {
    u64 pointer=*(volatile u64 *)(uptr)0x4d72aa518ULL;
    if (pointer!=0x405118d00ULL) return 0;
    const volatile u8 *data=(const volatile u8 *)(uptr)pointer;
    for (u32 i=0;i<130;i++) out[i]=data[i];
    return out[0x7c]<=10 && pointer==*(volatile u64 *)(uptr)0x4d72aa518ULL;
}
static u32 npl_y(u32 index) { return index ? 146+90*index : 56; }
static u32 npl_native_matches(const struct NplView *v) {
    u8 metadata[130];
    return npl_metadata(metadata) && npl_equal(v->metadata,metadata) &&
        NPL_SELECTED==v->selected && NPL_OFFSET==v->offset &&
        NPL_HIGHLIGHT==142+npl_y(v->selected)-v->offset &&
        *(volatile u64 *)(uptr)(NPL_PRIVATE+8)==v->buffer &&
        *(volatile u16 *)(uptr)(NPL_PRIVATE+16)==2048 &&
        NPL_WORD(NPL_PRIVATE+20)==1136;
}

/* Nonblocking gate held only across drawing, never across native input.
 * Retain pending target depth for synchronous initial draws before hierarchy
 * publication. Input still requires idle12 at the final depth. */
u32 native_touch_private_list_begin(u64 input,const void *canvas,u32 epoch) {
    u32 token=npl_bump();
    if (!npl_acquire(&npl_gate)) {
        __atomic_add_fetch(&npl_aborted,1,__ATOMIC_RELEASE); return 0;
    }
    npl_view.valid=0;
    u32 pending=NPL_PENDING,depth=NPL_DEPTH;
    if (input!=NPL_INPUT || !canvas || !NATIVE_TOUCH_PRIVATE_LIST_ENABLED() ||
        pending>12 || depth>=12 || !npl_metadata(npl_view.metadata)) {
        __atomic_add_fetch(&npl_aborted,1,__ATOMIC_RELEASE);
        npl_unlock(); return 0;
    }
    npl_view.canvas=canvas; npl_view.epoch=epoch; npl_view.token=token;
    npl_view.entry_depth=depth; npl_view.pending=pending;
    npl_view.depth=pending<12 ? pending : depth;
    npl_view.selected=NPL_SELECTED; npl_view.offset=NPL_OFFSET;
    npl_view.count=npl_view.metadata[0x7c];
    npl_view.rows=1+(npl_view.count ? npl_view.count : 1);
    npl_view.buffer=*(volatile u64 *)(uptr)(NPL_PRIVATE+8);
    npl_view.seen=npl_view.bad=0;
    __atomic_store_n(&npl_capture,token,__ATOMIC_RELEASE);
    return token;
}

/* Observe ONLY in the known foreground's bracket. The private surface is
 * deliberately different from canvas. A stack pointer must not escape this
 * call; Y uniquely identifies a native selection index for this builder. */
void native_touch_private_list_observe(u32 token,const void *surface,const void *row) {
    if (!token || token!=__atomic_load_n(&npl_capture,__ATOMIC_ACQUIRE) ||
        token!=npl_revision()) return;
    if ((uptr)surface!=NPL_PRIVATE || !row) { npl_view.bad=1; return; }
    u32 y=npl_read16(row),index;
    if (y==56) index=0;
    else if (y>=236 && (y-236)%90==0) index=1+(y-236)/90;
    else { npl_view.bad=1; return; }
    if (index>=npl_view.rows) { npl_view.bad=1; return; }
    u8 flags=((const volatile u8 *)row)[2];
    if ((flags&~3u) || ((npl_view.seen&(1u<<index)) && npl_view.flags[index]!=flags))
        npl_view.bad=1;
    npl_view.flags[index]=flags;
    npl_view.seen |= 1u<<index;
}

u32 native_touch_private_list_end(u32 token,u32 displayed) {
    if (!token || token!=__atomic_load_n(&npl_capture,__ATOMIC_ACQUIRE)) return 0;
    u32 selected=npl_view.selected,marked=0;
    for (u32 i=0;i<npl_view.rows;i++) {
        if (npl_view.flags[i]&1) marked |= 1u<<i;
        u32 enabled=i ? npl_view.count!=0 : npl_view.metadata[0x81]!=0;
        if (((npl_view.flags[i]&2)!=0)!=enabled) npl_view.bad=1;
    }
    u32 max_offset=npl_view.count>3 ? 90*npl_view.count-304 : 11;
    u32 pending=NPL_PENDING,depth=NPL_DEPTH;
    u32 lifecycle=(pending==12 && depth==npl_view.depth) ||
        (npl_view.pending<12 && pending==npl_view.pending && depth==npl_view.entry_depth);
    u32 valid=displayed && NATIVE_TOUCH_PRIVATE_LIST_ENABLED() &&
        token==npl_revision() && !npl_view.bad && selected<npl_view.rows &&
        npl_view.buffer && NPL_HIGHLIGHT>=142 && NPL_HIGHLIGHT<=592 &&
        npl_view.offset>=11 && npl_view.offset<=max_offset &&
        npl_view.seen==((1u<<npl_view.rows)-1) && marked==(1u<<selected) &&
        lifecycle && npl_native_matches(&npl_view);
    npl_view.valid=valid;
    __atomic_store_n(&npl_capture,0,__ATOMIC_RELEASE);
    npl_unlock();
    return valid;
}

void native_touch_private_list_reorient(u32 epoch) {
    u32 previous=npl_revision();
    __atomic_add_fetch(&npl_aborted,1,__ATOMIC_RELEASE);
    u32 token=npl_bump();
    if (!npl_acquire(&npl_gate)) return;
    if (npl_view.valid && npl_view.token==previous && token==npl_revision() &&
        NATIVE_TOUCH_PRIVATE_LIST_ENABLED() && NPL_PENDING==12 &&
        NPL_DEPTH==npl_view.depth && npl_native_matches(&npl_view)) {
        npl_view.epoch=epoch; npl_view.token=token;
    } else npl_view.valid=0;
    npl_unlock();
}

static u32 npl_snapshot(struct NplView *v,u32 epoch) {
    if (!npl_acquire(&npl_gate)) return 0;
    u32 valid=npl_view.valid && npl_view.token==npl_revision() &&
        npl_view.epoch==epoch && NPL_PENDING==12 && NPL_DEPTH==npl_view.depth &&
        NATIVE_TOUCH_PRIVATE_LIST_ENABLED() && npl_native_matches(&npl_view);
    if (valid) *v=npl_view;
    npl_unlock(); return valid;
}
static u32 npl_refresh(struct NplView *v,u32 epoch,u32 aborted) {
    struct NplView next;
    if (__atomic_load_n(&npl_aborted,__ATOMIC_ACQUIRE)!=aborted ||
        !npl_snapshot(&next,epoch) || next.depth!=v->depth ||
        !npl_equal(next.metadata,v->metadata)) return 0;
    /* Same logical rows may have a NEW native viewport and surface token. */
    *v=next; return 1;
}
static u32 npl_call(u64 input,struct Event *e) {
    return ((u32 (*)(struct Event *))(uptr)input)(e);
}
static u32 npl_physical(const struct Event *e) {
    const u8 *k=(const u8 *)e->key,*d=(const u8 *)e->dial;
    return (k && (npl_read16(k)|npl_read16(k+2)|npl_read16(k+4)|npl_read16(k+6))) ||
        (d && (npl_read16(d)|npl_read16(d+2)));
}
static int npl_hit(const struct NplView *v,u32 x,u32 y) {
    if (x>=1024 || y<142 || y>=682) return -1;
    for (u32 i=0;i<v->rows;i++) {
        int top=142+(int)npl_y(i)-(int)v->offset;
        if ((int)y>=top && (int)y<top+90) return (int)i;
    }
    return -1;
}
static u32 npl_select(struct NplView *v,u32 target,u32 epoch,u32 aborted) {
    for (u32 n=0;n<11;n++) {
        if (!npl_refresh(v,epoch,aborted) || target>=v->rows) return 0;
        u32 old=v->selected;
        if (old==target) return 1;
        if (n==10) return 0;
        short dial[2]={(short)(target>old ? 1 : -1),0};
        struct Event step={.dial=dial};
        npl_call(NPL_INPUT,&step);
        if (NPL_SELECTED!=(target>old ? old+1 : old-1)) return 0;
    }
    return 0;
}
static u32 npl_take(const struct NplView *v,u32 aborted) {
    if (!npl_acquire(&npl_gate)) return 0;
    u32 valid=npl_view.valid && npl_view.token==v->token && v->token==npl_revision() &&
        __atomic_load_n(&npl_aborted,__ATOMIC_ACQUIRE)==aborted &&
        NPL_PENDING==12 && NPL_DEPTH==v->depth &&
        NATIVE_TOUCH_PRIVATE_LIST_ENABLED() && npl_native_matches(v);
    if (valid) npl_view.valid=0;
    npl_unlock(); return valid;
}

u32 native_touch_private_list_input(struct Event *e,u64 original,u32 epoch) {
    if (!e || !original) { native_touch_private_list_reset(); return 0; }
    if (original!=NPL_INPUT) {
        native_touch_private_list_reset(); return npl_call(original,e);
    }
    if (!npl_acquire(&npl_dispatch)) {
        native_touch_private_list_reset(); return npl_call(original,e);
    }
    u32 aborted=__atomic_load_n(&npl_aborted,__ATOMIC_ACQUIRE);
    u32 result=npl_call(original,e);
    struct NplView view;
    if (__atomic_load_n(&npl_aborted,__ATOMIC_ACQUIRE)!=aborted ||
        !npl_snapshot(&view,epoch) || npl_physical(e)) { npl_cancel(); goto done; }
    if (!e->lcd) goto done;
    if (npl_gesture.epoch!=epoch || npl_gesture.depth!=view.depth ||
        npl_gesture.aborted!=aborted || !npl_equal(npl_gesture.metadata,view.metadata))
        npl_cancel();
    npl_gesture.epoch=epoch; npl_gesture.depth=view.depth; npl_gesture.aborted=aborted;
    for (u32 i=0;i<130;i++) npl_gesture.metadata[i]=view.metadata[i];
    u8 mapped[20];
    NATIVE_TOUCH_PRIVATE_LIST_TRANSFORM(mapped,e->lcd);
    u32 flags=npl_read16(mapped+16);
    if (flags&0x7400) npl_gesture.active=npl_gesture.blocked=0;
    else if (flags&~0x301u) npl_cancel();
    else if (flags&0x300) {
        if (flags&0x100) {
            npl_gesture.x=npl_read16(mapped+4); npl_gesture.y=npl_read16(mapped+6);
            npl_gesture.selected=(int)view.selected;
            npl_gesture.active=npl_hit(&view,(u32)npl_gesture.x,(u32)npl_gesture.y)>=0;
        }
        npl_gesture.blocked=1;
        if (npl_gesture.active) {
            int x=npl_read16(mapped+8),y=npl_read16(mapped+10);
            int dx=x-npl_gesture.x,dy=npl_gesture.y-y;
            if (x>=1024 || y>=682 || dx*dx>dy*dy+256) npl_gesture.active=0;
            else {
                int target=npl_gesture.selected+dy/90;
                int lower=view.metadata[0x81] ? 0 : 1;
                int upper=view.count ? (int)view.count : lower;
                if (target<lower) target=lower;
                if (target>upper) target=upper;
                if (!npl_select(&view,(u32)target,epoch,aborted)) npl_cancel();
            }
        }
    } else if (flags==1) {
        u32 blocked=npl_gesture.active || npl_gesture.blocked;
        npl_gesture.active=npl_gesture.blocked=0;
        int target=npl_hit(&view,npl_read16(mapped),npl_read16(mapped+2));
        if (!blocked && target>=0 && (view.flags[target]&0x12)==2 &&
            npl_select(&view,(u32)target,epoch,aborted) &&
            npl_refresh(&view,epoch,aborted) && (view.flags[target]&0x12)==2 &&
            npl_take(&view,aborted)) {
            struct Key key={.changed=1,.press=1};
            struct Event confirm={.key=&key};
            result=npl_call(original,&confirm);
        }
    }
done:
    __atomic_store_n(&npl_dispatch,0,__ATOMIC_RELEASE);
    return result;
}
#undef NPL_WORD
#undef NPL_DEPTH
#undef NPL_PENDING
#undef NPL_SELECTED
#undef NPL_OFFSET
#undef NPL_HIGHLIGHT
#endif
