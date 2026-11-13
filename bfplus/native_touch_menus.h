/* BF 1.04 segment 05 compact pickers only. Include after u8/u16/u32/u64,
 * uptr, struct Key and struct Event. No menu.h/state dependency is required.
 * LCD coordinates MUST already be in native 1024x682 space. See
 * docs/NATIVE-TOUCH-MENUS.md for installation/lifecycle and coverage limits. */
#ifndef BF_NATIVE_TOUCH_MENUS_H
#define BF_NATIVE_TOUCH_MENUS_H

/* Parent may gate stale callbacks after removal. Physical input still goes
 * to the original function when this predicate is false. */
#ifndef NATIVE_TOUCH_MENU_ENABLED
#define NATIVE_TOUCH_MENU_ENABLED() 1
#endif
#ifndef NATIVE_TOUCH_MENU_TRANSFORM
#define NATIVE_TOUCH_MENU_TRANSFORM(out,source) \
    do { for (u32 ntm_i=0;ntm_i<20;ntm_i++) (out)[ntm_i]=((const u8 *)(source))[ntm_i]; } while (0)
#endif

/* X(id, input, descriptor, init input literal, resume input literal, limit).
 * Zero means no second literal. These are expected-value pointer hooks,
 * never scene descriptors or instruction patches. */
#define NATIVE_TOUCH_MENU_FAMILIES(X) \
 X(0,0x4d3375730ULL,0x4d7042f50ULL,0x4d3374fd8ULL,0x4d3375628ULL,2) \
 X(1,0x4d3379ea0ULL,0x4d7302890ULL,0x4d3379c78ULL,0,32) \
 X(2,0x4d33807e0ULL,0x4d70435b8ULL,0x4d3380398ULL,0x4d33807a8ULL,2) \
 X(3,0x4d33809f0ULL,0x4d7043588ULL,0x4d33805d8ULL,0,17) \
 X(4,0x4d3381c80ULL,0x4d7043618ULL,0x4d3381830ULL,0x4d3381b30ULL,2) \
 X(5,0x4d3381e70ULL,0x4d70435e8ULL,0x4d33819e0ULL,0x4d3381c50ULL,2) \
 X(6,0x4d3387f80ULL,0x4d7043728ULL,0x4d3387e10ULL,0x4d3387f50ULL,2) \
 X(7,0x4d3388f10ULL,0x4d7043890ULL,0x4d3388d88ULL,0x4d3388ee8ULL,2)

struct NativeTouchMenuFamily { u64 input, descriptor, hooks[2]; u32 limit; };
#define NTM_FAMILY(i,f,d,h,r,n) {f,d,{h,r},n},
static const struct NativeTouchMenuFamily native_touch_menu_families[8]={
    NATIVE_TOUCH_MENU_FAMILIES(NTM_FAMILY)
};
#undef NTM_FAMILY

/* Separate tag allows inclusion before or after menu.h; the native ABI is
 * identical to MenuPicker. The adapter only READS this descriptor. */
struct NativeTouchPicker {
    u16 y;
    u8 count, selected, previous, committed, widest, first_visible;
    u8 visible_count, flags, reserved[6];
    const char *const *labels, *const *secondary;
    const u8 *disabled;
    const void *language_data;
};
_Static_assert(sizeof(struct NativeTouchPicker)==48,"native picker ABI");
_Static_assert(__builtin_offsetof(struct NativeTouchPicker,labels)==16,"labels ABI");
_Static_assert(__builtin_offsetof(struct NativeTouchPicker,disabled)==32,"disabled ABI");
_Static_assert(__builtin_offsetof(struct NativeTouchPicker,language_data)==40,"language ABI");

#define NTM_DEPTH (*(volatile u32 *)(uptr)0x4d70346a0ULL)
#define NTM_PENDING (*(volatile u32 *)(uptr)0x4d70346a4ULL)
#define NTM_MODE (*(volatile u32 *)(uptr)0x4d730288cULL)
static struct {
    u32 family, depth, mode, active, blocked;
    const void *labels;
    u32 count;
    int x, y, selected;
} native_touch_menu_gesture;

/* Call on scene entry/exit, orientation changes and disable/removal. An
 * interrupted drag remains blocked until its release or a fresh BEGIN. */
void native_touch_menu_reset(void) {
    native_touch_menu_gesture.blocked |= native_touch_menu_gesture.active;
    native_touch_menu_gesture.active=0;
    native_touch_menu_gesture.family=8;
}

static u16 ntm_read16(const void *p) {
    struct __attribute__((packed)) Ntm16 { u16 value; };
    return ((const struct Ntm16 *)p)->value;
}
static u32 ntm_call(u64 input, struct Event *e) {
    return ((u32 (*)(struct Event *))(uptr)input)(e);
}
static u32 ntm_physical(const struct Event *e) {
    const u8 *k=(const u8 *)e->key, *d=(const u8 *)e->dial;
    return (k && (ntm_read16(k)|ntm_read16(k+2)|ntm_read16(k+4)|ntm_read16(k+6))) ||
        (d && (ntm_read16(d)|ntm_read16(d+2)));
}
static u32 ntm_valid(const volatile struct NativeTouchPicker *p,
                     const struct NativeTouchMenuFamily *f, u32 family) {
    u32 count=f->limit;
    if (family==1) {
        u32 mode=NTM_MODE;
        if (mode>6) return 0;
        count=mode==0 ? 32 : (mode==2 || mode==5) ? 3 : 2;
    }
    if (p->count!=count ||
        p->selected>=p->count || p->widest>=p->count ||
        !p->visible_count || p->visible_count>7 ||
        p->first_visible+p->visible_count>p->count ||
        p->y<52 || p->y>=682 || (p->flags&~1u) || !p->labels || !p->disabled)
        return 0;
    return 1;
}
static int ntm_left(const volatile struct NativeTouchPicker *p) {
    const char *text[2]={p->labels[p->widest],0};
    if (!text[0]) return -1;
    u32 primary=((u32 (*)(u32,const void *,u32))(uptr)0x4d3327e50ULL)(5,text,0)&65535u;
    u32 secondary=0;
    if (p->secondary) {
        text[0]=p->secondary[p->widest];
        if (!text[0]) return -1;
        secondary=((u32 (*)(u32,const void *,u32))(uptr)0x4d3327e50ULL)(4,text,0)&65535u;
    }
    u32 width=(primary+(secondary ? secondary+191 : 141))&~1u;
    return width<=1024 ? (int)(1024-width) : -1;
}
static int ntm_hit(const volatile struct NativeTouchPicker *p, int left, int x, int y) {
    if (left<0 || x<left || x>=1024 || y<p->y || y>=682 ||
        y>=p->y+90*p->visible_count) return -1;
    return p->first_visible+(y-p->y)/90;
}

/* Native dial magnitude is ignored: issue one synchronous event per row,
 * bounded by 31, and abort on transitions or unexpected/no progress. Never
 * publish selected/previous/window/committed bytes ourselves. */
static u32 ntm_select(const struct NativeTouchMenuFamily *f,
                      const volatile struct NativeTouchPicker *p,
                      u32 family, u32 target, u32 depth, u32 mode) {
    const void *labels=p->labels;
    for (u32 n=0;n<32;n++) {
        if (NTM_PENDING!=12 || NTM_DEPTH!=depth || !ntm_valid(p,f,family) ||
            p->labels!=labels || target>=p->count || (family==1 && NTM_MODE!=mode)) return 0;
        u32 old=p->selected;
        if (old==target) return 1;
        if (n==31) return 0;
        short dial[2]={(short)(target>old ? 1 : -1),0};
        struct Event step={.dial=dial};
        ntm_call(f->input,&step);
        if (p->selected!=(target>old ? old+1 : old-1)) return 0;
    }
    return 0;
}

/* Returns the original handler result (or final native confirm result).
 * Every caller packet, including all five nullable parts, is forwarded once
 * unchanged. Original picker inputs ignore LCD; synthetic events contain
 * only a dial OR center key, never duplicate caller side channels. */
u32 native_touch_menu_input(struct Event *e, u32 family) {
    if (!e || family>=8) { native_touch_menu_reset(); return 0; }
    const struct NativeTouchMenuFamily *f=&native_touch_menu_families[family];
    const volatile struct NativeTouchPicker *p=(const volatile void *)(uptr)f->descriptor;
    u32 depth=NTM_DEPTH, mode=family==1 ? NTM_MODE : 0;
    u32 result=ntm_call(f->input,e);
    if (!NATIVE_TOUCH_MENU_ENABLED() || NTM_PENDING!=12 || NTM_DEPTH!=depth) {
        native_touch_menu_reset(); return result;
    }
    if (ntm_physical(e)) { native_touch_menu_reset(); return result; }
    if (!e->lcd) return result;
    if (!ntm_valid(p,f,family)) { native_touch_menu_reset(); return result; }
    if (native_touch_menu_gesture.family!=family || native_touch_menu_gesture.depth!=depth ||
        native_touch_menu_gesture.mode!=mode || native_touch_menu_gesture.labels!=p->labels ||
        native_touch_menu_gesture.count!=p->count) native_touch_menu_reset();
    native_touch_menu_gesture.family=family;
    native_touch_menu_gesture.depth=depth;
    native_touch_menu_gesture.mode=mode;
    native_touch_menu_gesture.labels=p->labels;
    native_touch_menu_gesture.count=p->count;
    u8 mapped[20];
    NATIVE_TOUCH_MENU_TRANSFORM(mapped,e->lcd);
    const u8 *packet=mapped;
    u32 flags=ntm_read16(packet+16);
    /* Native releases may also carry direction bits (e.g. 0x410) or tap
     * (0x401). Neither activates; the next independent tap is eligible. */
    if (flags&0x7400) {
        native_touch_menu_gesture.active=native_touch_menu_gesture.blocked=0;
        return result;
    }
    if (flags&~0x301u) { native_touch_menu_reset(); return result; }
    if (!flags) return result;
    int left=ntm_left(p);
    if (flags&0x100) {
        int x=ntm_read16(packet+4), y=ntm_read16(packet+6);
        native_touch_menu_gesture.active=ntm_hit(p,left,x,y)>=0;
        native_touch_menu_gesture.blocked=1;
        native_touch_menu_gesture.x=x; native_touch_menu_gesture.y=y;
        native_touch_menu_gesture.selected=p->selected;
    }
    if (flags&0x300) {
        native_touch_menu_gesture.blocked=1;
        if (!native_touch_menu_gesture.active) return result;
        int x=ntm_read16(packet+8), y=ntm_read16(packet+10);
        int dx=x-native_touch_menu_gesture.x, dy=native_touch_menu_gesture.y-y;
        if (left<0 || x<left || x>=1024 || y>=682 || dx*dx>dy*dy+256) {
            native_touch_menu_gesture.active=0; return result;
        }
        int target=native_touch_menu_gesture.selected+dy/90;
        if (target<0) target=0;
        if (target>=p->count) target=p->count-1;
        if (!ntm_select(f,p,family,(u32)target,depth,mode)) native_touch_menu_reset();
        return result;
    }
    if (flags!=1) return result;
    u32 blocked=native_touch_menu_gesture.active || native_touch_menu_gesture.blocked;
    native_touch_menu_gesture.active=native_touch_menu_gesture.blocked=0;
    if (blocked) return result;
    int target=ntm_hit(p,left,ntm_read16(packet),ntm_read16(packet+2));
    if (target<0 || p->disabled[target]) return result;
    if (!ntm_select(f,p,family,(u32)target,depth,mode) || p->disabled[target]) return result;
    struct Key key={.changed=1,.press=1};
    struct Event confirm={.key=&key};
    native_touch_menu_reset();
    return ntm_call(f->input,&confirm);
}

/* Names for parent-owned installation/relocation tables. */
#define NTM_WRAPPER(i,f,d,h,r,n) \
 u32 native_touch_menu_##i(struct Event *e) { return native_touch_menu_input(e,i); }
NATIVE_TOUCH_MENU_FAMILIES(NTM_WRAPPER)
#undef NTM_WRAPPER
#undef NTM_DEPTH
#undef NTM_PENDING
#undef NTM_MODE
#endif
