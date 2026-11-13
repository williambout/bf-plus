/* BF 1.04 generic OSD compositor. Pure memory operations; no sensor, allocator,
 * cache, patch, queue or MMIO calls. Parent owns draw transactions and input.
 *
 * Storage: FG 0x155000, BG 0x1ff800, total 0x354800 bytes, each 2-byte aligned.
 * This excludes the existing physical banks and any owned-menu scratch.
 * bind() does not seed pixels. reset() supplies a transparent initial canvas;
 * seed() accepts ONLY known unrotated native pixels. After enabling mid-scene,
 * seed before changing scanout or run the scene's complete initial draw.
 *
 * Each plane has ONE persistent unrotated backing image. Native partial draws
 * and blends always target it; present fully overwrites the physical plane.
 * Parent must pair planes on orientation/policy changes, preserve stock cache
 * and bank switching, and publish input orientation only after both commit.
 * A missing native callback can use wrap(..., NULL, ...) to re-present backing.
 *
 * Owned menus: suppress their portrait path while draw_canonical() invokes the
 * native landscape painter, then run the owned reflow into the physical bank.
 * Keep that canonical underlay for later stock popups. Never seed from the
 * reflowed/rotated physical bank. These callbacks must not retain the supplied
 * descriptor or replace its geometry/pixels; external cached surfaces remain
 * the parent's audit responsibility. Serialize calls per plane.
 *
 * Verified worker BLR sites: FG 0x4d31ad2a4/0x4d31ad5cc use x4;
 * BG 0x4d31ad30c/0x4d31ad634 use x3. x0=surface,x1=params,w2=len.
 * No trampoline or address is installed here. A parent assembly bridge must
 * pass that original callback explicitly; a plain C replacement is not that
 * ABI. Shared C/installer/input policy is intentionally outside this header.
 */
#ifndef BF_GLOBAL_ORIENTATION_H
#define BF_GLOBAL_ORIENTATION_H
#include <stddef.h>
#include <stdint.h>

#define GLOBAL_ORIENTATION_WIDTH 1024u
#define GLOBAL_ORIENTATION_HEIGHT 682u
#define GLOBAL_ORIENTATION_FG_BYTES 1396736u
#define GLOBAL_ORIENTATION_BG_BYTES 2095104u
#define GLOBAL_ORIENTATION_BYTES 3491840u

enum GlobalOrientationKind { GLOBAL_ORIENTATION_FOREGROUND, GLOBAL_ORIENTATION_BACKGROUND };
enum GlobalOrientationPolicy {
    GLOBAL_ORIENTATION_NATIVE,          /* Identity, even when raw is 1/3. */
    GLOBAL_ORIENTATION_FIT_TRANSPARENT, /* Live imagery shows through margins. */
    GLOBAL_ORIENTATION_FIT_BLACK,       /* Opaque black outside fitted UI. */
    GLOBAL_ORIENTATION_FIT_OVER         /* UI over already-painted image anchors. */
};
struct GlobalOrientationSurface {
    uint16_t dirty_first, dirty_end, reserved[2];
    uint8_t *pixels;
    uint16_t pitch, alpha_pitch, height, reserved22;
    uint64_t alpha_offset;
};
_Static_assert(sizeof(struct GlobalOrientationSurface)==32, "native 64-bit surface ABI");
_Static_assert(offsetof(struct GlobalOrientationSurface,pixels)==8, "native pixels ABI");
_Static_assert(offsetof(struct GlobalOrientationSurface,alpha_offset)==24, "native alpha ABI");
struct GlobalOrientationPlane {
    struct GlobalOrientationSurface canonical;
    size_t capacity;
    uint32_t kind, ready;
};
typedef uint32_t (*GlobalOrientationDraw)(void *, const void *, uint32_t);

/* Required address span. The caller guarantees the native physical allocation
 * covers it; surface ABI has no allocation-capacity field. Padded rows allowed. */
static inline size_t global_orientation_span(const struct GlobalOrientationSurface *s,
                                           uint32_t kind) {
    if (!s || !s->pixels || ((uintptr_t)s->pixels&1u) || kind>1 ||
        s->height!=682 || s->pitch<2048 || (s->pitch&1u)) return 0;
    size_t end=(size_t)s->pitch*682;
    if (kind==GLOBAL_ORIENTATION_BACKGROUND) {
        size_t a=(size_t)s->alpha_pitch*682;
        if (s->alpha_pitch<1024 || s->alpha_offset<end ||
            s->alpha_offset>SIZE_MAX-a) return 0;
        end=(size_t)s->alpha_offset+a;
    }
    return (uintptr_t)s->pixels>UINTPTR_MAX-end ? 0 : end;
}
static inline int global_orientation_disjoint(const void *a,size_t an,
                                              const void *b,size_t bn) {
    uintptr_t x=(uintptr_t)a,y=(uintptr_t)b;
    return x<=y ? an<=y-x : bn<=x-y;
}
static inline int global_orientation_bound(const struct GlobalOrientationPlane *p) {
    if (!p || p->kind>1) return 0;
    const struct GlobalOrientationSurface *s=&p->canonical;
    size_t n=global_orientation_span(s,p->kind);
    return n && n<=p->capacity && s->pitch==2048 && s->alpha_pitch==1024 &&
        s->alpha_offset==(p->kind ? GLOBAL_ORIENTATION_FG_BYTES : 0);
}
static inline int global_orientation_bind(struct GlobalOrientationPlane *p,
                                         uint32_t kind, void *storage,size_t bytes) {
    if (!p || !storage || kind>1 || ((uintptr_t)storage&1u)) return 0;
    size_t need=kind ? GLOBAL_ORIENTATION_BG_BYTES : GLOBAL_ORIENTATION_FG_BYTES;
    if (bytes<need || (uintptr_t)storage>UINTPTR_MAX-need ||
        !global_orientation_disjoint(p,sizeof(*p),storage,need)) return 0;
    /* Native worker initializes alpha_pitch to 1024 in both descriptors;
     * foreground does not have a separate alpha plane (alpha_offset is 0). */
    struct GlobalOrientationSurface s={682,0,{0,0},storage,2048,
        1024,682,0,kind ? GLOBAL_ORIENTATION_FG_BYTES : 0};
    p->canonical=s; p->capacity=bytes; p->kind=kind; p->ready=0;
    return 1;
}
static inline int global_orientation_reset(struct GlobalOrientationPlane *p) {
    if (!global_orientation_bound(p)) return 0;
    uint8_t *b=p->canonical.pixels;
    for (size_t i=0;i<GLOBAL_ORIENTATION_FG_BYTES;i++)
        b[i]=(p->kind && !(i&1u)) ? 128 : 0; /* U Y0 V Y1 */
    if (p->kind)
        for (size_t i=GLOBAL_ORIENTATION_FG_BYTES;i<GLOBAL_ORIENTATION_BG_BYTES;i++) b[i]=0;
    p->canonical.dirty_first=682; p->canonical.dirty_end=0; p->ready=1;
    return 1;
}
static inline int global_orientation_destination(const struct GlobalOrientationPlane *p,
                                                const struct GlobalOrientationSurface *s) {
    if (!global_orientation_bound(p) || !p->ready) return 0;
    size_t n=global_orientation_span(s,p->kind);
    return n && global_orientation_disjoint(p->canonical.pixels,
        p->kind ? GLOBAL_ORIENTATION_BG_BYTES : GLOBAL_ORIENTATION_FG_BYTES,s->pixels,n) &&
        global_orientation_disjoint(p->canonical.pixels,
        p->kind ? GLOBAL_ORIENTATION_BG_BYTES : GLOBAL_ORIENTATION_FG_BYTES,s,sizeof(*s)) &&
        global_orientation_disjoint(p,sizeof(*p),s->pixels,n) &&
        global_orientation_disjoint(s,sizeof(*s),s->pixels,n);
}
static inline void global_orientation_copy(struct GlobalOrientationSurface *dst,
                                          const struct GlobalOrientationSurface *src,uint32_t kind) {
    for (uint32_t y=0;y<682;y++) {
        for (uint32_t x=0;x<2048;x++) dst->pixels[(size_t)y*dst->pitch+x]=src->pixels[(size_t)y*src->pitch+x];
        if (kind)
            for (uint32_t x=0;x<1024;x++) dst->pixels[dst->alpha_offset+(size_t)y*dst->alpha_pitch+x]=
                src->pixels[src->alpha_offset+(size_t)y*src->alpha_pitch+x];
    }
}
static inline int global_orientation_seed(struct GlobalOrientationPlane *p,
                                         const struct GlobalOrientationSurface *unrotated) {
    if (!global_orientation_bound(p)) return 0;
    size_t n=global_orientation_span(unrotated,p->kind);
    size_t need=p->kind ? GLOBAL_ORIENTATION_BG_BYTES : GLOBAL_ORIENTATION_FG_BYTES;
    if (!n || !global_orientation_disjoint(p->canonical.pixels,need,unrotated->pixels,n)) return 0;
    global_orientation_copy(&p->canonical,unrotated,p->kind);
    p->canonical.dirty_first=682; p->canonical.dirty_end=0; p->ready=1;
    return 1;
}
static inline uint32_t global_orientation_rotation(uint32_t raw,uint32_t policy) {
    return policy!=GLOBAL_ORIENTATION_NATIVE && (raw==1 || raw==3) ? raw : 0;
}
/* Exact uniform fit s=682/1024, centered in logical 682x1024. Pixel-center
 * sampling yields v=285..738 (454 rows), with no arbitrary crop or stretching.
 * This is a UI-only helper; never apply implicitly to AF/image coordinates. */
static inline int global_orientation_ui_xy(uint32_t x,uint32_t y,uint32_t raw,
                                          uint32_t policy,uint16_t *a,uint16_t *b) {
    if (!a || !b) return 0;
    *a=*b=65535;
    if (x>=1024 || y>=682 || policy>GLOBAL_ORIENTATION_FIT_OVER) return 0;
    uint32_t rot=global_orientation_rotation(raw,policy);
    if (!rot) { *a=(uint16_t)x; *b=(uint16_t)y; return 1; }
    uint32_t u=rot==1 ? y : 681-y, v=rot==1 ? 1023-x : x;
    int32_t n=(int32_t)((2*v+1)*1024)-583452;
    if (n<0 || n>=930248) return 0;
    *a=(uint16_t)(((2*u+1)*1024)/1364);
    *b=(uint16_t)(n/1364);
    return 1;
}
static inline uint32_t global_orientation_ui_directions(uint32_t bits,uint32_t raw,uint32_t policy) {
    if (policy>GLOBAL_ORIENTATION_FIT_OVER) return bits;
    uint32_t rot=global_orientation_rotation(raw,policy), d=bits&0xf0u;
    if (!rot) return bits;
    uint32_t mapped=rot==1 ? ((d&0x10)<<2)|((d&0x20)<<2)|((d&0x40)>>1)|((d&0x80)>>3) :
                            ((d&0x10)<<3)|((d&0x20)<<1)|((d&0x40)>>2)|((d&0x80)>>2);
    return (bits&~0xf0u)|mapped;
}
/* Optional packed UI copy. Returns validity bits 1/2/4 for tap/origin/current;
 * invalid pairs become 65535,65535. Other bytes preserved; source untouched.
 * Parent still owns gesture cancellation, mixed-input filtering and replay. */
static inline uint32_t global_orientation_ui_packet(uint8_t out[20],const void *packet,
                                                   uint32_t raw,uint32_t policy) {
    if (!out || !packet) return 0;
    uint8_t in[20]; const uint8_t *src=packet;
    for (uint32_t i=0;i<20;i++) in[i]=src[i];
    for (uint32_t i=0;i<20;i++) out[i]=in[i];
    uint32_t valid=0;
    for (uint32_t i=0;i<3;i++) {
        uint32_t o=4*i;
        uint16_t a,b;
        if (global_orientation_ui_xy(in[o]|((uint32_t)in[o+1]<<8),in[o+2]|((uint32_t)in[o+3]<<8),raw,policy,&a,&b)) valid|=1u<<i;
        out[o]=(uint8_t)a; out[o+1]=(uint8_t)(a>>8); out[o+2]=(uint8_t)b; out[o+3]=(uint8_t)(b>>8);
    }
    uint32_t bits=in[16]|((uint32_t)in[17]<<8)|((uint32_t)in[18]<<16)|((uint32_t)in[19]<<24);
    bits=global_orientation_ui_directions(bits,raw,policy);
    for (uint32_t i=0;i<4;i++) out[16+i]=(uint8_t)(bits>>(8*i));
    return valid;
}
/* Stock return values are passed separately because the display worker ignores
 * them. Return 1 for valid canonical draw, 0 before callback on invalid input,
 * -1 after callback if it changed descriptor geometry (backing now invalid).
 * This function alone never writes a physical bank. */
static inline int global_orientation_draw_canonical(struct GlobalOrientationPlane *p,
    GlobalOrientationDraw draw,const void *params,uint32_t len,uint32_t *native_result) {
    if (!global_orientation_bound(p) || !p->ready) return 0;
    struct GlobalOrientationSurface s=p->canonical;
    s.dirty_first=682; s.dirty_end=0;
    uint32_t result=draw ? draw(&s,params,len) : 0;
    if (native_result) *native_result=result;
    if (s.pixels!=p->canonical.pixels || s.pitch!=2048 || s.height!=682 ||
        s.alpha_pitch!=p->canonical.alpha_pitch || s.alpha_offset!=p->canonical.alpha_offset) {
        p->ready=0; return -1;
    }
    p->canonical.dirty_first=s.dirty_first; p->canonical.dirty_end=s.dirty_end;
    return 1;
}
/* Clear only visible pixels; native stride padding and descriptor identity
 * are retained. Used before painting a fresh unrotated image-anchor pass. */
static inline int global_orientation_clear(struct GlobalOrientationSurface *dst,uint32_t kind) {
    if (!global_orientation_span(dst,kind)) return 0;
    for (uint32_t y=0;y<682;y++) {
        uint8_t *row=dst->pixels+(size_t)y*dst->pitch;
        for (uint32_t x=0;x<2048;x++) row[x]=(kind && !(x&1u)) ? 128 : 0;
        if (kind) {
            row=dst->pixels+dst->alpha_offset+(size_t)y*dst->alpha_pitch;
            for (uint32_t x=0;x<1024;x++) row[x]=0;
        }
    }
    dst->dirty_first=0; dst->dirty_end=682;
    return 1;
}
static inline int global_orientation_present(const struct GlobalOrientationPlane *p,
    struct GlobalOrientationSurface *dst,uint32_t raw,uint32_t policy) {
    if (policy>GLOBAL_ORIENTATION_FIT_OVER || !global_orientation_destination(p,dst)) return 0;
    const struct GlobalOrientationSurface *src=&p->canonical;
    if (!global_orientation_rotation(raw,policy) && policy!=GLOBAL_ORIENTATION_FIT_OVER)
        global_orientation_copy(dst,src,p->kind);
    else if (!p->kind) {
        for (uint32_t y=0;y<682;y++) for (uint32_t x=0;x<1024;x++) {
            uint16_t a,b,value=policy==GLOBAL_ORIENTATION_FIT_BLACK ? 0x000f : 0;
            if (global_orientation_ui_xy(x,y,raw,policy,&a,&b)) {
                const uint8_t *q=src->pixels+(size_t)b*2048+2*a;
                value=(uint16_t)(q[0]|((uint16_t)q[1]<<8));
            }
            uint8_t *q=dst->pixels+(size_t)y*dst->pitch+2*x;
            if (policy==GLOBAL_ORIENTATION_FIT_OVER) {
                uint32_t old=q[0]|((uint32_t)q[1]<<8), alpha=value&15u;
                if (!alpha) continue;
                if (alpha!=15) {
                    uint32_t a=alpha*15, b=(old&15u)*(15-alpha), total=a+b;
                    uint32_t out=(total+7)/15;
                    for (uint32_t shift=4;shift<16;shift+=4)
                        out |= ((((value>>shift)&15u)*a+((old>>shift)&15u)*b+total/2)/total)<<shift;
                    value=(uint16_t)out;
                }
            }
            q[0]=(uint8_t)value; q[1]=(uint8_t)(value>>8);
        }
    } else {
        for (uint32_t y=0;y<682;y++) for (uint32_t x=0;x<1024;x+=2) {
            uint32_t luma[2]={0,0},alpha[2],chroma_u[2]={128,128},chroma_v[2]={128,128};
            for (uint32_t i=0;i<2;i++) {
                uint16_t a,b;
                alpha[i]=policy==GLOBAL_ORIENTATION_FIT_BLACK ? 255 : 0;
                if (global_orientation_ui_xy(x+i,y,raw,policy,&a,&b)) {
                    const uint8_t *q=src->pixels+(size_t)b*2048+4*(a/2);
                    chroma_u[i]=q[0]; chroma_v[i]=q[2]; luma[i]=q[1+2*(a&1)];
                    alpha[i]=src->pixels[GLOBAL_ORIENTATION_FG_BYTES+(size_t)b*1024+a];
                }
            }
            uint8_t *q=dst->pixels+(size_t)y*dst->pitch+2*x;
            if (policy==GLOBAL_ORIENTATION_FIT_OVER) {
                if (!alpha[0] && !alpha[1]) continue;
                const uint8_t *da=dst->pixels+dst->alpha_offset+(size_t)y*dst->alpha_pitch+x;
                for (uint32_t i=0;i<2;i++) {
                    uint32_t a=alpha[i]*255, b=da[i]*(255-alpha[i]), total=a+b;
                    if (total) {
                        luma[i]=(luma[i]*a+q[1+2*i]*b+total/2)/total;
                        chroma_u[i]=(chroma_u[i]*a+q[0]*b+total/2)/total;
                        chroma_v[i]=(chroma_v[i]*a+q[2]*b+total/2)/total;
                    }
                    alpha[i]=(total+127)/255;
                }
            }
            uint32_t sum=alpha[0]+alpha[1];
            q[0]=(uint8_t)(sum ? (chroma_u[0]*alpha[0]+chroma_u[1]*alpha[1]+sum/2)/sum : 128);
            q[1]=(uint8_t)luma[0];
            q[2]=(uint8_t)(sum ? (chroma_v[0]*alpha[0]+chroma_v[1]*alpha[1]+sum/2)/sum : 128);
            q[3]=(uint8_t)luma[1];
            q=dst->pixels+dst->alpha_offset+(size_t)y*dst->alpha_pitch+x;
            q[0]=(uint8_t)alpha[0]; q[1]=(uint8_t)alpha[1];
        }
    }
    dst->dirty_first=0; dst->dirty_end=682;
    return 1;
}
static inline int global_orientation_wrap(struct GlobalOrientationPlane *p,
    GlobalOrientationDraw draw,struct GlobalOrientationSurface *dst,const void *params,
    uint32_t len,uint32_t raw,uint32_t policy,uint32_t *native_result) {
    if (policy>GLOBAL_ORIENTATION_FIT_OVER || !global_orientation_destination(p,dst)) return 0;
    int ok=global_orientation_draw_canonical(p,draw,params,len,native_result);
    return ok==1 ? global_orientation_present(p,dst,raw,policy) : ok;
}
#endif
