/* BF V104: five verified ordinary row-list inputs, NOT arbitrary row painters.
 * Include after payload integer types, Key and Event. Parent owns dispatch,
 * foreground capture brackets, canonical coordinates and lifecycle epoch.
 * No native descriptor, graphics implementation or patch site is modified. */
#ifndef BF_NATIVE_TOUCH_ROWS_H
#define BF_NATIVE_TOUCH_ROWS_H

#ifndef NATIVE_TOUCH_ROWS_ENABLED
#define NATIVE_TOUCH_ROWS_ENABLED() 1
#endif
#ifndef NATIVE_TOUCH_ROWS_TRANSFORM
#define NATIVE_TOUCH_ROWS_TRANSFORM(out,source) \
    do { for (u32 ntr_i=0;ntr_i<20;ntr_i++) (out)[ntr_i]=((const u8 *)(source))[ntr_i]; } while (0)
#endif

/* X(id,input,u32 selection,stable rows or NULL,count,regular FG,initial FG).
 * Sound uses stack rows: its verified Y142/Y232 maps to index0/index1. */
#define NATIVE_TOUCH_ROW_FAMILIES(X) \
 X(0,0x4d3375a50ULL,0x4d7302640ULL,0x4d7042ee8ULL,3,0x4d3375230ULL,0x4d3375930ULL) \
 X(1,0x4d3381270ULL,0x4d7302e54ULL,0,2,0x4d3380f30ULL,0x4d3381020ULL) \
 X(2,0x4d337fde0ULL,0x4d7302be0ULL,0x4d7043450ULL,2,0x4d337f960ULL,0x4d337f960ULL) \
 X(3,0x4d3384930ULL,0x4d7043650ULL,0x4d7043678ULL,3,0x4d33844e0ULL,0x4d33844e0ULL) \
 X(4,0x4d338a3f0ULL,0x4d7302f48ULL,0x4d70438c0ULL,2,0x4d3389f20ULL,0x4d3389f60ULL) \
 X(5,0x4d3352220ULL,0x4d7302508ULL,0x4d7035760ULL,2,0x4d3351e80ULL,0x4d3351ec0ULL)
struct NativeTouchRowFamily { u64 input, selected, rows, foreground, initial; u32 count; };
#define NTR_FAMILY(i,f,s,r,n,g,h) {f,s,r,g,h,n},
static const struct NativeTouchRowFamily native_touch_row_families[]={
    NATIVE_TOUCH_ROW_FAMILIES(NTR_FAMILY)
};
#undef NTR_FAMILY
#define NTR_FAMILY_COUNT (sizeof(native_touch_row_families)/sizeof(native_touch_row_families[0]))

struct NativeTouchRow { u16 y; u8 flags, unused3; u32 unused4;
    const void *label, *value; u32 font, unused28; };
_Static_assert(sizeof(struct NativeTouchRow)==32,"native ordinary row ABI");

#define NTR_DEPTH (*(volatile u32 *)(uptr)0x4d70346a0ULL)
#define NTR_PENDING (*(volatile u32 *)(uptr)0x4d70346a4ULL)
static u32 ntr_gate, ntr_dispatch, ntr_generation, ntr_capture, ntr_aborted;
struct NtrView {
    const void *canvas;
    u32 token, epoch, depth, entry_depth, pending, family, seen, bad, valid;
    struct { u16 y; u8 flags, pad; } rows[3];
};
static struct NtrView ntr_view;
static struct {
    u32 active, blocked, epoch, depth, family, aborted;
    u16 rows[3];
    int x, y, selected;
} ntr_gesture;

static u32 ntr_revision(void) { return __atomic_load_n(&ntr_generation,__ATOMIC_ACQUIRE); }
static u32 ntr_bump(void) {
    u32 value=__atomic_add_fetch(&ntr_generation,1,__ATOMIC_ACQ_REL);
    return value ? value : __atomic_add_fetch(&ntr_generation,1,__ATOMIC_ACQ_REL);
}
static u32 ntr_acquire(u32 *gate) {
    u32 expected=0;
    return __atomic_compare_exchange_n(gate,&expected,1,0,__ATOMIC_ACQUIRE,__ATOMIC_RELAXED);
}
static u32 ntr_trylock(void) { return ntr_acquire(&ntr_gate); }
static void ntr_unlock(void) { __atomic_store_n(&ntr_gate,0,__ATOMIC_RELEASE); }
static void ntr_cancel(void) {
    ntr_gesture.blocked |= ntr_gesture.active;
    ntr_gesture.active=0;
}
void native_touch_rows_reset(void) {
    __atomic_add_fetch(&ntr_aborted,1,__ATOMIC_RELEASE);
    ntr_bump();
    if (ntr_trylock()) { ntr_view.valid=0; ntr_unlock(); }
}
/* Canonical geometry survives rotation's no-op native redraw. Cancel gesture
 * ownership, then retag only an intact published snapshot. Contending with
 * an active capture invalidates that capture rather than stealing its gate. */
void native_touch_rows_reorient(u32 epoch) {
    u32 previous=ntr_revision();
    __atomic_add_fetch(&ntr_aborted,1,__ATOMIC_RELEASE);
    u32 token=ntr_bump();
    if (!ntr_trylock()) return;
    if (ntr_view.valid && ntr_view.token==previous && token==ntr_revision() &&
        NTR_PENDING==12 && NTR_DEPTH==ntr_view.depth && NATIVE_TOUCH_ROWS_ENABLED()) {
        ntr_view.epoch=epoch; ntr_view.token=token;
    } else ntr_view.valid=0;
    ntr_unlock();
}
static int ntr_family(u64 input) {
    for (u32 i=0;i<NTR_FAMILY_COUNT;i++) if (native_touch_row_families[i].input==input) return (int)i;
    return -1;
}
/* Discover ownership from the native FG callback BEFORE its first event. */
u64 native_touch_rows_handler_for_draw(u64 fn) {
    for (u32 i=0;i<NTR_FAMILY_COUNT;i++) {
        const struct NativeTouchRowFamily *f=&native_touch_row_families[i];
        if (fn==f->foreground || fn==f->initial) return f->input;
    }
    return 0;
}
static u32 ntr_selected(const struct NativeTouchRowFamily *f) {
    return *(volatile u32 *)(uptr)f->selected;
}

/* Foreground ONLY. A nonzero token owns the gate until end(token,...).
 * On zero, render normally but do not observe/end that bracket. Never wait
 * for the gate: nested/concurrent calls invalidate instead of deadlocking. */
u32 native_touch_rows_begin(u64 input, const void *canvas, u32 epoch) {
    u32 token=ntr_bump();
    if (!ntr_trylock()) {
        __atomic_add_fetch(&ntr_aborted,1,__ATOMIC_RELEASE);
        return 0;
    }
    ntr_view.valid=0;
    int family=ntr_family(input);
    u32 pending=NTR_PENDING, depth=NTR_DEPTH;
    if (!canvas || family<0 || !NATIVE_TOUCH_ROWS_ENABLED() || pending>12 || depth>=12) {
        __atomic_add_fetch(&ntr_aborted,1,__ATOMIC_RELEASE);
        ntr_unlock(); return 0;
    }
    ntr_view.canvas=canvas; ntr_view.token=token; ntr_view.epoch=epoch;
    /* Hierarchy init draws synchronously BEFORE publishing depth and idle12
     * (3323ea4 -> 3323eb0/ebc). A pending value below12 is its target depth.
     * Retain initial geometry, but snapshot/input still requires idle12 and
     * the expected final depth. No touch runs during that transition. */
    ntr_view.entry_depth=depth; ntr_view.pending=pending;
    ntr_view.depth=pending<12 ? pending : depth; ntr_view.family=(u32)family;
    ntr_view.seen=ntr_view.bad=0;
    __atomic_store_n(&ntr_capture,token,__ATOMIC_RELEASE);
    return token;
}

/* Called before the original 3363df0 painter, with the SAME token as begin.
 * Copy only geometry/flags; stack rows must never be retained as pointers.
 * Exact surface identity excludes private backing descriptors and blits. */
void native_touch_rows_observe(u32 token, const void *surface, const void *row) {
    if (!token || token!=__atomic_load_n(&ntr_capture,__ATOMIC_ACQUIRE) ||
        token!=ntr_revision() || surface!=ntr_view.canvas) return;
    if (!row) { ntr_view.bad=1; return; }
    const struct NativeTouchRowFamily *f=&native_touch_row_families[ntr_view.family];
    const volatile struct NativeTouchRow *r=row;
    u32 y=r->y, index;
    if (f->rows) {
        uptr offset=(uptr)row-f->rows;
        if (offset>=32*f->count || (offset&31)) { ntr_view.bad=1; return; }
        index=(u32)(offset/32);
    } else {
        if (y!=142 && y!=232) { ntr_view.bad=1; return; }
        index=(y-142)/90;
    }
    if (y<52 || y>592) { ntr_view.bad=1; return; }
    u8 flags=r->flags;
    if ((ntr_view.seen&(1u<<index)) &&
        (ntr_view.rows[index].y!=y || ntr_view.rows[index].flags!=flags)) ntr_view.bad=1;
    ntr_view.rows[index].y=(u16)y; ntr_view.rows[index].flags=flags;
    ntr_view.seen |= 1u<<index;
}

/* displayed=1 only after successful foreground display in this epoch.
 * Full known row set, disjoint geometry and one matching selected flag are
 * required. A failed/partial draw never publishes hit targets. */
u32 native_touch_rows_end(u32 token, u32 displayed) {
    if (!token || token!=__atomic_load_n(&ntr_capture,__ATOMIC_ACQUIRE)) return 0;
    const struct NativeTouchRowFamily *f=&native_touch_row_families[ntr_view.family];
    u32 selected=ntr_selected(f), marked=0;
    for (u32 i=0;i<f->count;i++) {
        if (i && ntr_view.rows[i].y<ntr_view.rows[i-1].y+90) ntr_view.bad=1;
        if (ntr_view.rows[i].flags&1) marked |= 1u<<i;
    }
    u32 pending=NTR_PENDING, depth=NTR_DEPTH;
    u32 lifecycle=(pending==12 && depth==ntr_view.depth) ||
        (ntr_view.pending<12 && pending==ntr_view.pending && depth==ntr_view.entry_depth);
    u32 valid=displayed && NATIVE_TOUCH_ROWS_ENABLED() && token==ntr_revision() &&
        !ntr_view.bad && ntr_view.seen==((1u<<f->count)-1) && selected<f->count &&
        marked==(1u<<selected) && lifecycle;
    ntr_view.valid=valid;
    __atomic_store_n(&ntr_capture,0,__ATOMIC_RELEASE);
    ntr_unlock();
    return valid;
}

static u16 ntr_read16(const void *p) {
    struct __attribute__((packed)) Ntr16 { u16 value; };
    return ((const struct Ntr16 *)p)->value;
}
static u32 ntr_call(u64 input, struct Event *e) {
    return ((u32 (*)(struct Event *))(uptr)input)(e);
}
static u32 ntr_physical(const struct Event *e) {
    const u8 *k=(const u8 *)e->key,*d=(const u8 *)e->dial;
    return (k && (ntr_read16(k)|ntr_read16(k+2)|ntr_read16(k+4)|ntr_read16(k+6))) ||
        (d && (ntr_read16(d)|ntr_read16(d+2)));
}
/* Copy under the capture gate; NEVER hold it across native calls. The native
 * draw queue waits synchronously for a renderer which can reenter begin/end. */
static u32 ntr_snapshot(struct NtrView *v,u64 input,u32 epoch) {
    if (!ntr_trylock()) return 0;
    u32 valid=ntr_view.valid && ntr_view.token==ntr_revision() &&
        ntr_view.epoch==epoch && native_touch_row_families[ntr_view.family].input==input &&
        NTR_PENDING==12 && NTR_DEPTH==ntr_view.depth && NATIVE_TOUCH_ROWS_ENABLED();
    if (valid) *v=ntr_view;
    ntr_unlock();
    return valid;
}
/* A legitimate same-scene redraw may change token, surface pointer and
 * selection flags. Family, epoch, depth and all row geometry must stay fixed. */
static u32 ntr_refresh(struct NtrView *v,u64 input,u32 epoch,u32 aborted) {
    struct NtrView next;
    if (__atomic_load_n(&ntr_aborted,__ATOMIC_ACQUIRE)!=aborted ||
        !ntr_snapshot(&next,input,epoch) || next.family!=v->family || next.depth!=v->depth) return 0;
    for (u32 i=0;i<native_touch_row_families[v->family].count;i++)
        if (next.rows[i].y!=v->rows[i].y) return 0;
    *v=next;
    return __atomic_load_n(&ntr_aborted,__ATOMIC_ACQUIRE)==aborted;
}
static int ntr_hit(u32 x,u32 y,const struct NtrView *v) {
    if (x>=1024 || y>=682) return -1;
    for (u32 i=0;i<native_touch_row_families[v->family].count;i++)
        if (y>=v->rows[i].y && y<v->rows[i].y+90u) return (int)i;
    return -1;
}
static u32 ntr_editable(struct NtrView *v,u32 target,u32 epoch,u32 aborted) {
    const struct NativeTouchRowFamily *f=&native_touch_row_families[v->family];
    /* This family's dial checks the master getter; its center branch does
     * not. A late disabled state must not activate from a stale painted row. */
    u32 allowed=f->input!=0x4d3375a50ULL || !target ||
        ((u32 (*)(void))(uptr)0x4d3322550ULL)()!=0;
    return ntr_refresh(v,f->input,epoch,aborted) && allowed &&
        (v->rows[target].flags&0x12)==2 && (!f->rows ||
        ((*(volatile u8 *)(uptr)(f->rows+32*target+2))&0x12)==2);
}
static u32 ntr_select(struct NtrView *v,u32 target,u32 epoch,u32 aborted) {
    const struct NativeTouchRowFamily *f=&native_touch_row_families[v->family];
    for (u32 n=0;n<f->count;n++) {
        if (!ntr_refresh(v,f->input,epoch,aborted)) return 0;
        u32 old=ntr_selected(f);
        if (old>=f->count) return 0;
        if (old==target) return 1;
        if (n+1==f->count) return 0;
        short dial[2]={(short)(target>old ? 1 : -1),0};
        struct Event step={.dial=dial};
        ntr_call(f->input,&step);
        if (ntr_selected(f)!=(target>old ? old+1 : old-1)) return 0;
    }
    return 0;
}
/* Invalidate the displayed hit targets before center can transition scenes.
 * A concurrent capture prevents this commit; it never makes input wait. */
static u32 ntr_take(const struct NtrView *v,u32 aborted) {
    if (!ntr_trylock()) return 0;
    u32 valid=ntr_view.valid && ntr_view.token==v->token && v->token==ntr_revision() &&
        __atomic_load_n(&ntr_aborted,__ATOMIC_ACQUIRE)==aborted &&
        NTR_PENDING==12 && NTR_DEPTH==v->depth && NATIVE_TOUCH_ROWS_ENABLED();
    if (valid) ntr_view.valid=0;
    ntr_unlock();
    return valid;
}

/* Every original packet is forwarded exactly once. Only input owns gesture
 * state; draw/reset communicate invalidation atomically. A separate dispatch
 * guard rejects recursive synthesis without blocking synchronous rendering. */
u32 native_touch_rows_input(struct Event *e,u64 input,u32 epoch) {
    if (!e || !input) { native_touch_rows_reset(); return 0; }
    if (!ntr_acquire(&ntr_dispatch)) {
        native_touch_rows_reset();
        return ntr_call(input,e);
    }
    u32 aborted=__atomic_load_n(&ntr_aborted,__ATOMIC_ACQUIRE);
    u32 result=ntr_call(input,e);
    struct NtrView view;
    if (__atomic_load_n(&ntr_aborted,__ATOMIC_ACQUIRE)!=aborted ||
        !ntr_snapshot(&view,input,epoch) || ntr_physical(e)) {
        ntr_cancel(); goto done;
    }
    if (!e->lcd) goto done;
    const struct NativeTouchRowFamily *f=&native_touch_row_families[view.family];
    u32 changed=ntr_gesture.aborted!=aborted ||
        ntr_gesture.family!=view.family || ntr_gesture.epoch!=epoch ||
        ntr_gesture.depth!=view.depth;
    for (u32 i=0;i<f->count;i++) {
        changed |= ntr_gesture.rows[i]!=view.rows[i].y;
        ntr_gesture.rows[i]=view.rows[i].y;
    }
    if (changed) ntr_cancel();
    ntr_gesture.aborted=aborted;
    ntr_gesture.family=view.family; ntr_gesture.epoch=epoch; ntr_gesture.depth=view.depth;
    u8 mapped[20];
    NATIVE_TOUCH_ROWS_TRANSFORM(mapped,e->lcd);
    const u8 *packet=mapped;
    u32 flags=ntr_read16(packet+16);
    if (flags&0x7400) {
        ntr_gesture.active=ntr_gesture.blocked=0;
    } else if (flags&~0x301u) {
        ntr_cancel();
    } else if (flags&0x300) {
        if (flags&0x100) {
            ntr_gesture.x=ntr_read16(packet+4); ntr_gesture.y=ntr_read16(packet+6);
            ntr_gesture.selected=(int)ntr_selected(f);
            ntr_gesture.active=ntr_hit((u32)ntr_gesture.x,(u32)ntr_gesture.y,&view)>=0;
        }
        ntr_gesture.blocked=1;
        if (ntr_gesture.active) {
            int x=ntr_read16(packet+8),y=ntr_read16(packet+10);
            int dx=x-ntr_gesture.x,dy=ntr_gesture.y-y;
            if (x>=1024 || y>=682 || dx*dx>dy*dy+256) ntr_gesture.active=0;
            else {
                int target=ntr_gesture.selected+dy/90;
                if (target<0) target=0;
                if ((u32)target>=f->count) target=(int)f->count-1;
                if (!ntr_select(&view,(u32)target,epoch,aborted)) ntr_cancel();
            }
        }
    } else if (flags==1) {
        u32 blocked=ntr_gesture.active || ntr_gesture.blocked;
        ntr_gesture.active=ntr_gesture.blocked=0;
        int target=ntr_hit(ntr_read16(packet),ntr_read16(packet+2),&view);
        if (!blocked && target>=0 && ntr_editable(&view,(u32)target,epoch,aborted) &&
            ntr_select(&view,(u32)target,epoch,aborted) &&
            ntr_editable(&view,(u32)target,epoch,aborted) && ntr_take(&view,aborted)) {
            struct Key key={.changed=1,.press=1};
            struct Event confirm={.key=&key};
            result=ntr_call(input,&confirm);
        }
    }
done:
    __atomic_store_n(&ntr_dispatch,0,__ATOMIC_RELEASE);
    return result;
}
#undef NTR_DEPTH
#undef NTR_PENDING
#endif
