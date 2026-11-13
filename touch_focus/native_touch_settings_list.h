/* V104 normal Settings row 0: private-backed mixed information/action list.
 * Include after u8/u16/u32/u64/uptr, Key, Event. No hooks installed here.
 * Parent brackets ONLY 337d180 foreground, observes its 337d28c copy, and
 * publishes end(...,1) only after successful display in the matching epoch.
 * Native input owns selection/scroll/actions; this adapter never writes it. */
#ifndef BF_NATIVE_TOUCH_SETTINGS_LIST_H
#define BF_NATIVE_TOUCH_SETTINGS_LIST_H

#ifndef NATIVE_TOUCH_SETTINGS_LIST_ENABLED
#define NATIVE_TOUCH_SETTINGS_LIST_ENABLED() 1
#endif
#ifndef NATIVE_TOUCH_SETTINGS_LIST_TRANSFORM
#define NATIVE_TOUCH_SETTINGS_LIST_TRANSFORM(out,source) \
 do { for (u32 ntsl_i=0;ntsl_i<20;ntsl_i++) (out)[ntsl_i]=((const u8 *)(source))[ntsl_i]; } while (0)
#endif
#define NATIVE_TOUCH_SETTINGS_LIST_INPUT 0x4d337d8e0ULL
#define NATIVE_TOUCH_SETTINGS_LIST_FOREGROUND 0x4d337d180ULL
/* X(source, original target). Parent owns trampoline/register preservation. */
#define NATIVE_TOUCH_SETTINGS_LIST_COPY_HOOKS(X) \
 X(0x4d337d28cULL,0x4d3007fc0ULL)

#define NTSL_WORD(a) (*(volatile u32 *)(uptr)(a))
#define NTSL_DEPTH NTSL_WORD(0x4d70346a0ULL)
#define NTSL_PENDING NTSL_WORD(0x4d70346a4ULL)
#define NTSL_NODE NTSL_WORD(0x4d703469cULL)
#define NTSL_SELECTED NTSL_WORD(0x4d70431fcULL)
#define NTSL_OFFSET (*(volatile u16 *)(uptr)0x4d7043204ULL)

struct NtslSurface { u16 dirty[4]; uptr pixels; u16 pitch,alpha_pitch,height,reserved; u64 alpha; };
_Static_assert(sizeof(struct NtslSurface)==32,"V104 surface ABI");
struct NtslView {
    uptr pixels;
    u32 token,epoch,depth,entry_depth,pending,node,selected,offset;
    u32 seen,bad,valid;
    u8 flags[20];
};
static struct NtslView ntsl_view;
static u32 ntsl_gate,ntsl_dispatch,ntsl_generation,ntsl_capture,ntsl_aborted;
static struct { u32 active,blocked,epoch,depth,aborted; int x,y,selected; } ntsl_gesture;

static u32 ntsl_acquire(u32 *gate) {
    u32 zero=0;
    return __atomic_compare_exchange_n(gate,&zero,1,0,__ATOMIC_ACQUIRE,__ATOMIC_RELAXED);
}
static void ntsl_unlock(void) { __atomic_store_n(&ntsl_gate,0,__ATOMIC_RELEASE); }
static u32 ntsl_revision(void) { return __atomic_load_n(&ntsl_generation,__ATOMIC_ACQUIRE); }
static u32 ntsl_bump(void) {
    u32 n=__atomic_add_fetch(&ntsl_generation,1,__ATOMIC_ACQ_REL);
    return n ? n : __atomic_add_fetch(&ntsl_generation,1,__ATOMIC_ACQ_REL);
}
static void ntsl_cancel(void) {
    ntsl_gesture.blocked |= ntsl_gesture.active;
    ntsl_gesture.active=0;
}
void native_touch_settings_list_reset(void) {
    __atomic_add_fetch(&ntsl_aborted,1,__ATOMIC_RELEASE); ntsl_bump();
    if (ntsl_acquire(&ntsl_gate)) { ntsl_view.valid=0; ntsl_unlock(); }
}
u64 native_touch_settings_list_handler_for_draw(u64 callback) {
    return callback==NATIVE_TOUCH_SETTINGS_LIST_FOREGROUND ? NATIVE_TOUCH_SETTINGS_LIST_INPUT : 0;
}
static u32 ntsl_y(u32 i) {
    return i<11 ? i*90 : i<15 ? 990+(i-11)*225 : 1980+(i-15)*225;
}
static u32 ntsl_height(u32 i) { return i<11 ? 90 : i==14 ? 315 : 225; }
static const volatile u8 *ntsl_row(u32 i) {
    return (const volatile u8 *)(uptr)(i<11 ? 0x4d7043260ULL+32*i : 0x4d70433c0ULL+16*(i-11));
}
static u16 ntsl_read16(const void *p) {
    struct __attribute__((packed)) Ntsl16 { u16 value; };
    return ((const struct Ntsl16 *)p)->value;
}
/* Exact compiled native geometry, including two blank separators and the
 * 315-pixel information row. Mutable text pointers are never dereferenced. */
static u32 ntsl_geometry(void) {
    for (u32 i=0;i<20;i++) {
        const volatile u8 *r=ntsl_row(i);
        if (*(const volatile u16 *)r!=ntsl_y(i) ||
            (i>=11 && (r[12]!=0)!=(i==14))) return 0;
    }
    return 1;
}
static u32 ntsl_live(const struct NtslView *v) {
    if (NTSL_SELECTED!=v->selected || NTSL_OFFSET!=v->offset || !ntsl_geometry()) return 0;
    for (u32 i=0;i<20;i++) if (ntsl_row(i)[2]!=v->flags[i]) return 0;
    return 1;
}
static u32 ntsl_idle(const struct NtslView *v) {
    return NATIVE_TOUCH_SETTINGS_LIST_ENABLED() && NTSL_PENDING==12 &&
        NTSL_NODE==12 && NTSL_DEPTH==v->depth;
}

/* Nonblocking token ownership, retained until end. Initial hierarchy drawing
 * may precede native depth/node publication; input still requires idle12. */
u32 native_touch_settings_list_begin(u64 input,const void *canvas,u32 epoch) {
    u32 token=ntsl_bump();
    if (!ntsl_acquire(&ntsl_gate)) {
        __atomic_add_fetch(&ntsl_aborted,1,__ATOMIC_RELEASE); return 0;
    }
    ntsl_view.valid=0;
    const struct NtslSurface *s=canvas;
    u32 depth=NTSL_DEPTH,pending=NTSL_PENDING,node=NTSL_NODE;
    if (input!=NATIVE_TOUCH_SETTINGS_LIST_INPUT || !s || !s->pixels ||
        (s->pixels&1) || s->pixels>~(uptr)0-2048*682 ||
        s->pitch!=2048 || s->height!=682 || depth>=12 || pending>12 ||
        (node!=12 && node>1) || !NATIVE_TOUCH_SETTINGS_LIST_ENABLED()) {
        __atomic_add_fetch(&ntsl_aborted,1,__ATOMIC_RELEASE); ntsl_unlock(); return 0;
    }
    ntsl_view.pixels=s->pixels; ntsl_view.token=token; ntsl_view.epoch=epoch;
    ntsl_view.entry_depth=depth; ntsl_view.pending=pending; ntsl_view.node=node;
    ntsl_view.depth=pending<12 ? pending : depth;
    ntsl_view.seen=ntsl_view.bad=0;
    __atomic_store_n(&ntsl_capture,token,__ATOMIC_RELEASE);
    return token;
}

/* Only from BL 337d28c, with its unmodified memcpy operands. Called before
 * the original copy; a completed foreground + successful display is required
 * at end. A different copy, partial viewport or repeated observation fails. */
void native_touch_settings_list_observe_copy(u32 token,const void *dst,const void *src,u64 bytes) {
    if (!token || token!=__atomic_load_n(&ntsl_capture,__ATOMIC_ACQUIRE) || token!=ntsl_revision()) return;
    const volatile struct NtslSurface *s=(const volatile void *)(uptr)0x4d7043220ULL;
    u32 selected=NTSL_SELECTED,offset=NTSL_OFFSET;
    if (ntsl_view.seen++ || selected>=20 || offset>2565 ||
        s->pixels!=0x402972800ULL || s->pitch!=2048 || s->height!=3105 ||
        (uptr)dst!=ntsl_view.pixels+142*2048 ||
        (uptr)src!=s->pixels+offset*2048 || bytes!=540*2048 || !ntsl_geometry()) {
        ntsl_view.bad=1; return;
    }
    ntsl_view.selected=selected; ntsl_view.offset=offset;
    for (u32 i=0;i<20;i++) ntsl_view.flags[i]=ntsl_row(i)[2];
}
u32 native_touch_settings_list_end(u32 token,u32 displayed) {
    if (!token || token!=__atomic_load_n(&ntsl_capture,__ATOMIC_ACQUIRE)) return 0;
    u32 pending=NTSL_PENDING,depth=NTSL_DEPTH,node=NTSL_NODE;
    u32 lifecycle=(pending==12 && node==12 && depth==ntsl_view.depth) ||
        (pending==ntsl_view.pending && depth==ntsl_view.entry_depth && node==ntsl_view.node);
    ntsl_view.valid=displayed && NATIVE_TOUCH_SETTINGS_LIST_ENABLED() &&
        token==ntsl_revision() && ntsl_view.seen==1 && !ntsl_view.bad &&
        lifecycle && ntsl_live(&ntsl_view);
    u32 valid=ntsl_view.valid;
    __atomic_store_n(&ntsl_capture,0,__ATOMIC_RELEASE); ntsl_unlock(); return valid;
}
void native_touch_settings_list_reorient(u32 epoch) {
    u32 previous=ntsl_revision();
    __atomic_add_fetch(&ntsl_aborted,1,__ATOMIC_RELEASE);
    u32 token=ntsl_bump();
    if (!ntsl_acquire(&ntsl_gate)) return;
    if (ntsl_view.valid && ntsl_view.token==previous && token==ntsl_revision() &&
        ntsl_idle(&ntsl_view) && ntsl_live(&ntsl_view)) {
        ntsl_view.token=token; ntsl_view.epoch=epoch;
    } else ntsl_view.valid=0;
    ntsl_unlock();
}
static u32 ntsl_snapshot(struct NtslView *v,u32 epoch,u32 aborted) {
    if (!ntsl_acquire(&ntsl_gate)) return 0;
    u32 valid=ntsl_view.valid && ntsl_view.token==ntsl_revision() &&
        ntsl_view.epoch==epoch && ntsl_idle(&ntsl_view) && ntsl_live(&ntsl_view) &&
        __atomic_load_n(&ntsl_aborted,__ATOMIC_ACQUIRE)==aborted;
    if (valid) *v=ntsl_view;
    ntsl_unlock(); return valid;
}
static u32 ntsl_call(u64 input,struct Event *e) {
    return ((u32 (*)(struct Event *))(uptr)input)(e);
}
static u32 ntsl_physical(const struct Event *e) {
    const u8 *k=(const u8 *)e->key,*d=(const u8 *)e->dial;
    return (k && (ntsl_read16(k)|ntsl_read16(k+2)|ntsl_read16(k+4)|ntsl_read16(k+6))) ||
        (d && (ntsl_read16(d)|ntsl_read16(d+2))) ||
        (e->one && *(const u8 *)e->one) || (e->five && *(const u8 *)e->five);
}
static int ntsl_hit(u32 x,u32 y,const struct NtslView *v) {
    if (x>=1018 || y<142 || y>=682) return -1; /* exclude native scrollbar */
    y=y-142+v->offset;
    for (u32 i=0;i<20;i++) if (y>=ntsl_y(i) && y<ntsl_y(i)+ntsl_height(i)) return (int)i;
    return -1;
}
static u32 ntsl_select(struct NtslView *v,u32 target,u32 epoch,u32 aborted) {
    u32 depth=v->depth;
    for (u32 i=0;i<20;i++) {
        if (!ntsl_snapshot(v,epoch,aborted) || v->depth!=depth) return 0;
        u32 old=v->selected;
        if (old==target) return 1;
        if (i==19) return 0;
        short dial[2]={(short)(target>old ? 1 : -1),0};
        struct Event e={.dial=dial};
        ntsl_call(NATIVE_TOUCH_SETTINGS_LIST_INPUT,&e);
        if (NTSL_SELECTED!=(target>old ? old+1 : old-1)) return 0;
    }
    return 0;
}
static u32 ntsl_take(const struct NtslView *v,u32 aborted) {
    if (!ntsl_acquire(&ntsl_gate)) return 0;
    u32 valid=ntsl_view.valid && ntsl_view.token==v->token && v->token==ntsl_revision() &&
        __atomic_load_n(&ntsl_aborted,__ATOMIC_ACQUIRE)==aborted &&
        ntsl_idle(v) && ntsl_live(v);
    if (valid) ntsl_view.valid=0;
    ntsl_unlock(); return valid;
}

/* Original event forwarded once, unchanged. Only synthetic dial/center events
 * have other channels zeroed. No capture lock is held across synchronous
 * native input/redraw. Read-only rows select but never receive center. */
u32 native_touch_settings_list_input(struct Event *e,u64 input,u32 epoch) {
    if (!e || !input) { native_touch_settings_list_reset(); return 0; }
    if (!ntsl_acquire(&ntsl_dispatch)) {
        native_touch_settings_list_reset(); return ntsl_call(input,e);
    }
    u32 aborted=__atomic_load_n(&ntsl_aborted,__ATOMIC_ACQUIRE);
    u32 result=ntsl_call(input,e);
    struct NtslView view;
    if (input!=NATIVE_TOUCH_SETTINGS_LIST_INPUT || ntsl_physical(e) ||
        !ntsl_snapshot(&view,epoch,aborted)) { ntsl_cancel(); goto done; }
    if (!e->lcd) goto done;
    if (ntsl_gesture.epoch!=epoch || ntsl_gesture.depth!=view.depth ||
        ntsl_gesture.aborted!=aborted) ntsl_cancel();
    ntsl_gesture.epoch=epoch; ntsl_gesture.depth=view.depth; ntsl_gesture.aborted=aborted;
    u8 mapped[20]; NATIVE_TOUCH_SETTINGS_LIST_TRANSFORM(mapped,e->lcd);
    u32 flags=ntsl_read16(mapped+16);
    if (flags&0x7400) { ntsl_gesture.active=ntsl_gesture.blocked=0; }
    else if (flags&~0x301u) ntsl_cancel();
    else if (flags&0x300) {
        if (flags&0x100) {
            ntsl_gesture.x=ntsl_read16(mapped+4); ntsl_gesture.y=ntsl_read16(mapped+6);
            ntsl_gesture.selected=(int)view.selected;
            ntsl_gesture.active=ntsl_hit((u32)ntsl_gesture.x,(u32)ntsl_gesture.y,&view)>=0;
        }
        ntsl_gesture.blocked=1;
        if (ntsl_gesture.active) {
            int x=ntsl_read16(mapped+8),y=ntsl_read16(mapped+10);
            int dx=x-ntsl_gesture.x,dy=ntsl_gesture.y-y;
            if (x>=1024 || y>=682 || dx*dx>dy*dy+256) ntsl_gesture.active=0;
            else {
                int target=ntsl_gesture.selected+dy/90;
                if (target<0) target=0;
                if (target>19) target=19;
                if (!ntsl_select(&view,(u32)target,epoch,aborted)) ntsl_cancel();
            }
        }
    } else if (flags==1) {
        u32 blocked=ntsl_gesture.active || ntsl_gesture.blocked;
        ntsl_gesture.active=ntsl_gesture.blocked=0;
        int hit=ntsl_hit(ntsl_read16(mapped),ntsl_read16(mapped+2),&view);
        if (!blocked && hit>=0 && hit!=5 && hit!=10 &&
            ntsl_select(&view,(u32)hit,epoch,aborted) && (hit==4 || hit==9) &&
            (view.flags[hit]&0x12)==2 && ntsl_take(&view,aborted)) {
            struct Key key={.changed=1,.press=1}; struct Event confirm={.key=&key};
            result=ntsl_call(input,&confirm);
        }
    }
done:
    __atomic_store_n(&ntsl_dispatch,0,__ATOMIC_RELEASE); return result;
}
#undef NTSL_WORD
#undef NTSL_DEPTH
#undef NTSL_PENDING
#undef NTSL_NODE
#undef NTSL_SELECTED
#undef NTSL_OFFSET
#endif
