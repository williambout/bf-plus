/* BF 1.04 extensions for ui_image_anchors.h. No transaction state or graphics.
 * Include before the root adapter and wire the five extension points documented
 * in UI-IMAGE-PROFILES.md. Existing capture/epoch/rebuild guards remain required.
 */
#ifndef BF_UI_IMAGE_PROFILES_H
#define BF_UI_IMAGE_PROFILES_H
#include <stdint.h>
#include <stddef.h>

#ifndef UI_IMAGE_PROFILES_READ32
#define UI_IMAGE_PROFILES_READ32(a) (*(const volatile uint32_t *)(uintptr_t)(a))
#endif
#ifndef UI_IMAGE_PROFILES_READ8
#define UI_IMAGE_PROFILES_READ8(a) (*(const volatile uint8_t *)(uintptr_t)(a))
#endif
#ifndef UI_IMAGE_PROFILES_CALL0
#define UI_IMAGE_PROFILES_CALL0(f) (((uint32_t (*)(void))(uintptr_t)(f))())
#endif
#ifndef UI_IMAGE_PROFILES_CALL1
#define UI_IMAGE_PROFILES_CALL1(f,s) (((uint32_t (*)(void *))(uintptr_t)(f))((s)))
#endif
#ifndef UI_IMAGE_PROFILES_CALL2
#define UI_IMAGE_PROFILES_CALL2(f,s,a) \
    (((uint32_t (*)(void *,uint32_t))(uintptr_t)(f))((s),(a)))
#endif
#ifndef UI_IMAGE_PROFILES_CALL3
#define UI_IMAGE_PROFILES_CALL3(f,s,p,n) \
    (((uint32_t (*)(void *,const void *,uint32_t))(uintptr_t)(f))((s),(p),(n)))
#endif
#ifndef UI_IMAGE_PROFILES_CALL4
#define UI_IMAGE_PROFILES_CALL4(f,s,p,a,b) \
    (((uint32_t (*)(void *,const void *,uint32_t,uint32_t))(uintptr_t)(f))((s),(p),(a),(b)))
#endif
#ifndef UI_IMAGE_PROFILES_CALL3I
#define UI_IMAGE_PROFILES_CALL3I(f,a,b,c) \
    (((uint32_t (*)(uint32_t,uint32_t,uint32_t))(uintptr_t)(f))((a),(b),(c)))
#endif

/* Append these initializer rows to ui_anchor_pairs. INITIAL comes first because
 * the parent normalizes same-family jobs to the first pair. No cross-pair match.
 */
#define UI_IMAGE_ANCHORS_EXTRA_PAIRS \
    {0x4d33b3ce0ULL,0x4d33b38e0ULL,3}, \
    {0x4d33b3a30ULL,0x4d33b38e0ULL,3}, \
    {0x4d33b5070ULL,0x4d33b4640ULL,4}, \
    {0x4d33b4820ULL,0x4d33b4640ULL,4}, \
    {0x4d338aa40ULL,0x4d338a940ULL,7}, \
    {0x4d33cd4b0ULL,0x4d33cc230ULL,8}, \
    {0x4d33cf410ULL,0x4d33cc450ULL,8}, \
    {0x4d33d3b50ULL,0x4d33d3200ULL,9}, \
    {0x4d33d3bf0ULL,0x4d33d3590ULL,9}, \
    {0x4d33d3bf0ULL,0x4d33d3800ULL,9}, \
    {0x4d33d2a10ULL,0x4d33d3650ULL,9}, \
    {0x4d33d2a10ULL,0x4d33d3970ULL,9}, \
    {0x4d33a23b0ULL,0x4d33a2120ULL,10}, \
    {0x4d33a2230ULL,0x4d33a2170ULL,10},

/* Intercept callers, never the wrappers' nested tail branches. The four
 * background callers discard x0; deferral still supplies the exact result.
 */
#define UI_IMAGE_ANCHORS_EXTRA_BL_HOOKS(X) \
    X(0x4d33b39c8ULL,0x4d339f1e0ULL) \
    X(0x4d33b39e8ULL,0x4d339f070ULL) \
    X(0x4d33b4710ULL,0x4d339f1e0ULL) \
    X(0x4d33b4734ULL,0x4d339f070ULL) \
    X(0x4d338ab0cULL,0x4d3367b40ULL) \
    X(0x4d338a9e0ULL,0x4d3368760ULL) \
    X(0x4d33cd604ULL,0x4d3367b40ULL) \
    X(0x4d33cd674ULL,0x4d3367b40ULL) \
    X(0x4d33cd688ULL,0x4d3367b40ULL) \
    X(0x4d33cfad4ULL,0x4d3367b40ULL) \
    X(0x4d33cfae8ULL,0x4d3367b40ULL) \
    X(0x4d33cfb94ULL,0x4d3367b40ULL) \
    X(0x4d33cfba8ULL,0x4d3367b40ULL) \
    X(0x4d33cfbbcULL,0x4d3367b40ULL) \
    X(0x4d33cfbd0ULL,0x4d3367b40ULL) \
    X(0x4d33cc410ULL,0x4d3368760ULL) \
    X(0x4d33cc59cULL,0x4d3368760ULL) \
    X(0x4d33cc2e4ULL,0x4d339f070ULL) \
    X(0x4d33cf8d0ULL,0x4d339f160ULL) \
    X(0x4d33cf998ULL,0x4d339f0f0ULL) \
    X(0x4d33d3de8ULL,0x4d3367b40ULL) \
    X(0x4d33d3298ULL,0x4d3368760ULL) \
    X(0x4d33d35d8ULL,0x4d3368760ULL) \
    X(0x4d33d3774ULL,0x4d3368760ULL) \
    X(0x4d33d390cULL,0x4d3368760ULL) \
    X(0x4d33d3a00ULL,0x4d3368760ULL) \
    X(0x4d33d37a8ULL,0x4d339f070ULL) \
    X(0x4d33d392cULL,0x4d339f070ULL) \
    X(0x4d33d3a20ULL,0x4d339f070ULL) \
    X(0x4d33d36c8ULL,0x4d332a8c0ULL) \
    X(0x4d33d36ecULL,0x4d332aba0ULL) \
    X(0x4d33d3724ULL,0x4d332a8c0ULL) \
    X(0x4d33d3854ULL,0x4d332a8c0ULL) \
    X(0x4d33d38f8ULL,0x4d332a8c0ULL) \
    X(0x4d33d3998ULL,0x4d332a8c0ULL) \
    X(0x4d33a22d4ULL,0x4d3367b40ULL) \
    X(0x4d33a2200ULL,0x4d3368760ULL)

static inline int ui_image_profiles_is_split(uint32_t family) {
    return family==3 || family==4 || family==8;
}
/* The root adapter has already validated the complete actual FG/BG pair.
 * Use rebuild_params() below. Native third/post callbacks are NOT replayed.
 */
static inline int ui_image_profiles_full_pair(uint32_t family,uint64_t draw[3]) {
    if (draw && family==8) {
        draw[0]=0x4d33cd4b0ULL; draw[1]=0x4d33cc230ULL; draw[2]=0; return 1;
    }
    if (draw && family==7) {
        draw[0]=0x4d338aa40ULL; draw[1]=0x4d338a940ULL; draw[2]=0; return 1;
    }
    if (!draw || !ui_image_profiles_is_split(family)) return 0;
    draw[0]=family==3 ? 0x4d33b3ce0ULL : 0x4d33b5070ULL;
    draw[1]=family==3 ? 0x4d33b38e0ULL : 0x4d33b4640ULL;
    draw[2]=0;
    return 1;
}
/* Retained-base families intentionally have NO standalone full pair. Parent
 * must reject unknown provenance and use every rebuild_step below, on entry
 * AND exit. The first registered pair identifies a scene, not full coverage.
 */
static inline uint32_t ui_image_profiles_base_mask(uint32_t family) {
    return family==9 || family==10 ? (1u<<1)|(1u<<2)|(1u<<8) : 0;
}
static inline int ui_image_profiles_accepts_base(uint32_t family,uint32_t base) {
    return base<32 && (ui_image_profiles_base_mask(family)&(1u<<base))!=0;
}
/* Full AF BG unconditionally copies one byte from x1, then never reads it.
 * FG ignores the parameters. Resident immutable storage avoids retaining a
 * worker's job/stack pointer. All other supported full pairs use NULL/0.
 */
static inline const void *ui_image_profiles_rebuild_params(uint32_t family,
                                                         uint32_t *length) {
    static const uint8_t af_parameter=0;
    if (!length) return NULL;
    *length=family==8 ? 1 : 0;
    return family==8 ? &af_parameter : NULL;
}

struct UIImageProfileStep {
    uintptr_t fn;
    const void *params;
    uint32_t length, family;
};
/* Only this extracted raster pass is pure. Never replay partial 33a2230:
 * it consumes 73031f4 and may invoke 331da90 even with mask 0x100. */
static inline uint32_t uip_overlay_gradient(void *s,const void *p,uint32_t n) {
    static const uint16_t r[4]={0,582,1024,100};
    (void)p; (void)n;
    if (UI_IMAGE_PROFILES_CALL0(0x4d331eb10ULL)!=5)
        UI_IMAGE_PROFILES_CALL4(0x4d332a0a0ULL,s,r,0x00808000,0x12);
    return 0;
}
/* Reset plane once, run steps until 0. Each step gets its OWN capture_family;
 * keep all anchors deferred even for identity restoration. No post callbacks,
 * initializer, sensor update, or caller-owned parameter pointer is replayed.
 * An actual partial job still runs ONCE after acquisition with original args.
 */
static inline int ui_image_profiles_rebuild_step(uint32_t family,uint32_t base,
        uint32_t plane,uint32_t index,struct UIImageProfileStep *out) {
    if (!out || plane>1 || !ui_image_profiles_accepts_base(family,base)) return 0;
    int needs_base=family==10 || !plane;
    if (index==0 && needs_base) {
        static const uintptr_t photo[2]={0x4d3394c90ULL,0x4d33970b0ULL};
        static const uintptr_t cine[2]={0x4d3391dc0ULL,0x4d3390ad0ULL};
        static const uintptr_t af[2]={0x4d33cd4b0ULL,0x4d33cc230ULL};
        *out=(struct UIImageProfileStep){0};
        out->fn=(base==1 ? photo : base==2 ? cine : af)[plane];
        out->family=base;
        out->params=ui_image_profiles_rebuild_params(base,&out->length);
        return 1;
    }
    if (needs_base) index--;
    if (index==0) {
        *out=(struct UIImageProfileStep){0}; out->family=family;
        out->fn=family==9 ? (plane ? 0x4d33d3200ULL : 0x4d33d3b50ULL) :
                                 (plane ? 0x4d33a2120ULL : 0x4d33a23b0ULL);
        return 1;
    }
    if (family==10 && plane && index==1) {
        *out=(struct UIImageProfileStep){(uintptr_t)uip_overlay_gradient,NULL,0,10};
        return 1;
    }
    return 0;
}

/* Display-worker value snapshot, never a native descriptor/job pointer.
 * Stage a copy before an ACTUAL S2 BG callback, publish only on job success.
 * Do not call begin/capture for synthetic rebuild steps. 3590 retains the last
 * field producer; it only updates the level. Record actual level mode even in
 * landscape. Scene changes discard this snapshot; orientation changes retain.
 */
struct UIImageProfileStyle {
    uintptr_t producer;
    uint32_t random_height, alpha, level_mode, valid, phase;
};
static inline int ui_image_profiles_style_begin(struct UIImageProfileStyle *s,
                                               uintptr_t bg) {
    if (!s) return 0;
    if (bg==0x4d33d3590ULL) return s->valid!=0;
    if (bg!=0x4d33d3200ULL && bg!=0x4d33d3650ULL &&
        bg!=0x4d33d3800ULL && bg!=0x4d33d3970ULL) return 0;
    *s=(struct UIImageProfileStyle){0}; s->producer=bg;
    if (bg==0x4d33d3200ULL) s->valid=1;
    if (bg==0x4d33d3650ULL) s->level_mode=3;
    return 1;
}
static inline int ui_image_profiles_level_mode_valid(uint32_t family,
                                                    uint32_t plane,uint32_t mode) {
    if (plane>1) return 0;
    if (family==7) return mode==5;
    if (family==9) return plane ? mode<=3 : mode==0;
    if (family==10 || family==11) return mode==(plane ? 4u : 0u);
    return (family==1 || family==2 || family==8) && mode==0;
}
static inline int ui_image_profiles_style_level(struct UIImageProfileStyle *s,
                                               uint32_t mode) {
    if (!s || mode>3) return 0;
    s->level_mode=mode; return 1;
}
static inline int uip_alpha_fn(uintptr_t fn) {
    return fn==0x4d332a8c0ULL || fn==0x4d332aba0ULL;
}
/* Observe ONLY the six listed S2 BL sites on the exact actual canonical
 * surface. Call before defer/original, including unsplit landscape. The native
 * random generator executes once; capture its resulting rectangle instead of
 * recomputing it from the later (possibly changed) level return byte. */
static inline int ui_image_profiles_capture_alpha(struct UIImageProfileStyle *s,
        uintptr_t fn,const void *rect,uint32_t a,uint32_t b) {
    if (!s || !rect || !uip_alpha_fn(fn)) return 0;
    const uint16_t *r=(const uint16_t *)rect;
    a&=255; b&=255; /* Native fill masks w2; 33d38f8 passes UINT32_MAX. */
    int fill=fn==0x4d332a8c0ULL;
    if (r[0]!=0 || r[2]!=1024) { s->valid=0; return 0; }
    if (s->producer==0x4d33d3650ULL) {
        if (fill && !r[1] && a==25 &&
            ((r[3]>=438 && r[3]<=480) || (r[3]>=548 && r[3]<=560)) && !(r[3]&1)) {
            s->random_height=r[3]; s->phase=1; s->valid=0; return 1;
        }
        if (!fill && s->phase==1 && r[1]==s->random_height && r[3]==200 && a==25 && b==76) {
            s->phase=2; s->valid=s->random_height+200>=682; return 1;
        }
        if (fill && s->phase==2 && s->random_height+200<682 &&
            r[1]==s->random_height+200 && r[3]==682-r[1] && a==76) {
            s->phase=3; s->valid=1; return 1;
        }
    } else if (s->producer==0x4d33d3800ULL && fill && !r[1] && r[3]==682 &&
               (a==76 || a==255)) {
        s->alpha=a; s->level_mode=a==76 ? 2 : 1; s->valid=1; return 1;
    } else if (s->producer==0x4d33d3970ULL && fill && !r[1] && r[3]==582 && !a) {
        s->valid=1; return 1;
    }
    s->valid=0; return 0;
}
/* At the six BL sites x0 is discarded. Alpha raster returns are unspecified;
 * the enclosing S2 BG callbacks return zero. Never hook all raster callers.
 * The parent checks capture_family, exact surface, epoch, and failed state. */
static inline int ui_image_profiles_defer_alpha(uint32_t family,uintptr_t fn,
        void *surface,const void *rect,uint32_t a,uint32_t b,uint32_t *result) {
    (void)a; (void)b;
    if (family!=9 || !surface || !rect || !result || !uip_alpha_fn(fn)) return 0;
    *result=0; return 1;
}
/* Safe original forwarding for those SAME sites, including unsplit jobs.
 * Native 332aba0 does not clip: S2 height548..560 +200 overruns a 682-row
 * allocation. Keep its 200-row slope and rounding, coalesce equal alpha rows
 * and use original fill on visible runs. No extra plane or custom rasterizer.
 * All caller-visible return uses were proved dead at these six sites. */
static inline uint32_t ui_image_profiles_alpha_original(uintptr_t fn,void *surface,
        const void *rect,uint32_t a,uint32_t b) {
    if (!surface || !rect || !uip_alpha_fn(fn)) return 0;
    const uint16_t *src=(const uint16_t *)rect;
    uint16_t r[4]={src[0],src[1],src[2],src[3]};
    uint32_t width=((const uint16_t *)surface)[9];
    uint32_t height=((const uint16_t *)surface)[10];
    if (!r[2] || !r[3] || (r[0]&1) || (r[2]&1) || r[0]+r[2]>width || r[1]>=height) return 0;
    uint32_t visible=height-r[1];
    if (visible>r[3]) visible=r[3];
    if (fn==0x4d332a8c0ULL) {
        r[3]=(uint16_t)visible;
        UI_IMAGE_PROFILES_CALL3(fn,surface,r,a);
    } else if (visible==r[3]) {
        UI_IMAGE_PROFILES_CALL4(fn,surface,r,a,b);
    } else {
        int64_t step=(((int64_t)(b&255)-(int64_t)(a&255))*65536)/(int64_t)r[3];
        uint32_t start=0,previous=a&255;
        for (uint32_t row=1;row<=visible;row++) {
            uint32_t value=(uint32_t)(((int64_t)(a&255)*65536+step*row+32768)>>16)&255;
            if (row==visible || value!=previous) {
                uint16_t run[4]={r[0],(uint16_t)(r[1]+start),r[2],(uint16_t)(row-start)};
                UI_IMAGE_PROFILES_CALL3(0x4d332a8c0ULL,surface,run,previous);
                start=row; previous=value;
            }
        }
    }
    return 0;
}
static inline int uip_style_valid(const struct UIImageProfileStyle *s) {
    if (!s || !s->valid || s->level_mode>3) return 0;
    if (s->producer==0x4d33d3200ULL || s->producer==0x4d33d3970ULL) return 1;
    if (s->producer==0x4d33d3800ULL) return s->alpha==76 || s->alpha==255;
    return s->producer==0x4d33d3650ULL && !(s->random_height&1) &&
        ((s->random_height>=438 && s->random_height<=480) ||
         (s->random_height>=548 && s->random_height<=560));
}
static inline int uip_style_paint(const struct UIImageProfileStyle *s,void *physical) {
    if (!uip_style_valid(s)) return 0;
    uint16_t r[4]={0,0,1024,682};
    if (s->producer==0x4d33d3970ULL) {
        r[3]=582;
        ui_image_profiles_alpha_original(0x4d332a8c0ULL,physical,r,0,0);
    } else if (s->producer==0x4d33d3800ULL)
        ui_image_profiles_alpha_original(0x4d332a8c0ULL,physical,r,s->alpha,0);
    else if (s->producer==0x4d33d3650ULL) {
        r[3]=(uint16_t)s->random_height;
        ui_image_profiles_alpha_original(0x4d332a8c0ULL,physical,r,25,0);
        r[1]=r[3]; r[3]=200;
        ui_image_profiles_alpha_original(0x4d332aba0ULL,physical,r,25,76);
        if (s->random_height+200<682) {
            r[1]=(uint16_t)(s->random_height+200); r[3]=(uint16_t)(682-r[1]);
            ui_image_profiles_alpha_original(0x4d332a8c0ULL,physical,r,76,0);
        }
    }
    return 1;
}
static inline void uip_identity_ui(const struct UIImageProfileStyle *style,void *physical) {
    if (style->producer!=0x4d33d3800ULL || style->alpha==76)
        UI_IMAGE_PROFILES_CALL2(0x4d3362e30ULL,physical,0);
    if (style->producer==0x4d33d3970ULL ||
        (style->producer==0x4d33d3200ULL && UI_IMAGE_PROFILES_CALL0(0x4d331eb10ULL)!=5)) {
        static const uint16_t r[4]={0,582,1024,100};
        UI_IMAGE_PROFILES_CALL4(0x4d332a0a0ULL,physical,r,0x00808000,0x12);
    }
}
/* Child restoration: alpha + post-mask glyph/gradient, NO parent center,
 * level or histogram. Parent then executes its verified child BG recipe.
 */
static inline int ui_image_profiles_finish_identity_underlay(uint32_t owner,
        uint32_t base,const struct UIImageProfileStyle *style,void *physical) {
    if (owner!=9 || !ui_image_profiles_accepts_base(owner,base) || !physical ||
        !uip_style_paint(style,physical)) return 0;
    uip_identity_ui(style,physical); return 1;
}
/* S2 identity restoration is COPY canonical UI -> this finish, NOT OVER onto
 * a neutral mask. Native alpha writes retain every color (including glyphs).
 * Compositing a second alpha field would produce A+C*(1-A), and clearing the
 * canonical alpha would lose colored BG widgets. This pure finish preserves
 * native order, replays no random/timer/sensor producer, and paints level once
 * (including that painter's normal render-cache updates).
 * Parent skips its ordinary underlay/OVER for this plane. FG remains normal.
 */
static inline int ui_image_profiles_finish_identity_bg(uint32_t family,
        uint32_t base,uint32_t bg_mode,const struct UIImageProfileStyle *style,
        void *physical) {
    if (family!=9 || !ui_image_profiles_accepts_base(family,base) || !physical ||
        bg_mode>3 || !uip_style_paint(style,physical)) return 0;
    if (style->producer!=0x4d33d3200ULL && UI_IMAGE_PROFILES_READ8(0x4d7303820ULL))
        UI_IMAGE_PROFILES_CALL1(0x4d339f070ULL,physical);
    if (UI_IMAGE_PROFILES_CALL0(0x4d3321530ULL)==1) {
        _Alignas(8) uint8_t desc[24];
        for (unsigned i=0;i<24;i++) desc[i]=UI_IMAGE_PROFILES_READ8(0x4d7035be8ULL+i);
        UI_IMAGE_PROFILES_CALL3(0x4d3368760ULL,physical,desc,bg_mode);
    } else if (UI_IMAGE_PROFILES_CALL0(0x4d3321360ULL)==1)
        UI_IMAGE_PROFILES_CALL2(0x4d3358660ULL,physical,0xff8080ff);
    uip_identity_ui(style,physical);
    return 1;
}
static inline void uip_clear_fg(void *s,uint16_t x,uint16_t y,uint16_t w,uint16_t h) {
    uint16_t r[4]={x,y,w,h};
    UI_IMAGE_PROFILES_CALL3(0x4d3325ca0ULL,s,r,0);
}
/* The primary17 center follows native331d2a0 XY, so it can reach either band.
 * Overlay initial BG clears top52; its later bottom gradient replaces colors
 * as well as alpha. Erase those inherited strokes before the new level. The
 * canonical UI supplies its own gradient/labels at the fitted coordinates. */
static inline void uip_mask_inherited_center(uint32_t owner,void *s) {
    if (owner!=10) return;
    uint16_t r[4]={0,0,1024,52};
    UI_IMAGE_PROFILES_CALL3(0x4d3328cc0ULL,s,r,0x00808000);
    if (UI_IMAGE_PROFILES_CALL0(0x4d331eb10ULL)!=5) {
        r[1]=582; r[3]=100;
        UI_IMAGE_PROFILES_CALL3(0x4d3328cc0ULL,s,r,0x00808000);
    }
}
/* Only the parts of the original initializer's zero fills intersecting the
 * inherited AF marker. Real native font dimensions and aspect0..6 geometry
 * were checked. Later rotated labels may occlude anchors at their new coords.
 */
static inline void uip_mask_inherited_marker(uint32_t owner,void *s) {
    if (owner==10) {
        uip_clear_fg(s,0,0,1024,52); uip_clear_fg(s,0,582,1024,100); return;
    }
    if (owner!=9) return;
    uint32_t mode=UI_IMAGE_PROFILES_CALL0(0x4d331eb10ULL);
    if (mode==2) { uip_clear_fg(s,0,0,1024,52); return; }
    uip_clear_fg(s,0,0,99,52); uip_clear_fg(s,847,0,177,52);
    uint32_t value=UI_IMAGE_PROFILES_CALL0(0x4d339ed90ULL);
    uint32_t flags=UI_IMAGE_PROFILES_CALL3I(0x4d3354940ULL,1,value,1);
    uint32_t k=UI_IMAGE_PROFILES_CALL0(0x4d3245040ULL);
    if (mode!=5 && UI_IMAGE_PROFILES_CALL0(0x4d331faa0ULL)!=0 &&
        (k==UINT32_MAX || k<=10239))
        uip_clear_fg(s,flags&16 ? 93 : 71,3,flags&16 ? 108 : 130,46);
    if (UI_IMAGE_PROFILES_CALL0(0x4d33201b0ULL)<=1 &&
        UI_IMAGE_PROFILES_CALL0(0x4d3320270ULL)==1) {
        if (mode==5) uip_clear_fg(s,749,3,98,46);
        else if (flags&64) uip_clear_fg(s,824,3,46,46);
    }
}
/* Reusable ancestor-only underlay for bounded child overlays: no center and
 * no level. FG can succeed before the current BG job finishes its snapshot.
 * Parent already cleared physical and enforces epoch/once-per-plane guards.
 */
static inline int ui_image_profiles_paint_underlay(uint32_t owner,uint32_t base,
        const struct UIImageProfileStyle *style,void *physical,uint32_t plane) {
    if (!physical || plane>1 ||
        !((owner==1 || owner==2 || owner==8) ? owner==base :
          ui_image_profiles_accepts_base(owner,base))) return 0;
    if (plane) return owner==9 ? uip_style_paint(style,physical) : 1;
    if (base==8 && UI_IMAGE_PROFILES_READ32(0x4d73037c4ULL)==2) {
        UI_IMAGE_PROFILES_CALL1(0x4d339f160ULL,physical);
        uip_mask_inherited_marker(owner,physical);
    }
    return 1;
}
static inline int ui_image_profiles_paint_inherited(uint32_t family,uint32_t base,
        uint32_t bg_mode,const struct UIImageProfileStyle *style,void *physical,
        uint32_t plane) {
    if (!ui_image_profiles_accepts_base(family,base) ||
        !ui_image_profiles_level_mode_valid(family,1,bg_mode) ||
        !ui_image_profiles_paint_underlay(family,base,style,physical,plane)) return 0;
    if (plane && (family==10 || (style->producer!=0x4d33d3200ULL &&
                                UI_IMAGE_PROFILES_READ8(0x4d7303820ULL)))) {
        UI_IMAGE_PROFILES_CALL1(0x4d339f070ULL,physical);
        uip_mask_inherited_center(family,physical);
    }
    if (UI_IMAGE_PROFILES_CALL0(0x4d3321530ULL)==1) {
        _Alignas(8) uint8_t desc[24];
        for (unsigned i=0;i<24;i++) desc[i]=UI_IMAGE_PROFILES_READ8(0x4d7035be8ULL+i);
        UI_IMAGE_PROFILES_CALL3(plane ? 0x4d3368760ULL : 0x4d3367b40ULL,
                               physical,desc,plane ? bg_mode : 0);
    }
    return 1;
}
/* The dedicated level menu uses a separate persistent descriptor and mode5,
 * which centers its level at y322 and changes native footprint clearing. */
static inline uintptr_t ui_image_profiles_level_descriptor(uint32_t family) {
    return family==7 ? 0x4d7043920ULL : 0;
}
static inline uint32_t ui_image_profiles_level_visible(uint32_t family,uint32_t plane) {
    return family==7 && (plane || UI_IMAGE_PROFILES_READ32(0x4d7043904ULL)==1);
}
/* Call ONLY inside the root adapter's successful canonical capture guard,
 * after verifying exact surface identity, epoch, and !failed. No native paint.
 */
static inline int ui_image_profiles_defer(uint32_t family,uint32_t plane,
        uintptr_t fn,uint32_t *native_result) {
    if ((!ui_image_profiles_is_split(family) && family!=9 && family!=10) ||
        plane>1 || !native_result) return 0;
    if (family==8 && plane==0) {
        if (fn==0x4d339f160ULL) {
            *native_result=UI_IMAGE_PROFILES_READ32(0x4d7043b70ULL)>18; return 1;
        }
        if (fn==0x4d339f0f0ULL) { *native_result=0; return 1; }
    }
    if (plane!=1) return 0;
    if ((family==8 || family==9 || family==10) && fn!=0x4d339f070ULL) return 0;
    if (fn==0x4d339f1e0ULL) { *native_result=0; return 1; }
    if (fn==0x4d339f070ULL) {
        uint32_t aspect=UI_IMAGE_PROFILES_CALL0(0x4d3320850ULL);
        *native_result=UI_IMAGE_PROFILES_READ32(0x4d7043b74ULL)==3 ? 0 : aspect;
        return 1;
    }
    return 0;
}
/* Call AFTER the root adapter's clean-plane/epoch/once-per-job checks and
 * before its root-specific level and popup gates. Physical must be cleared.
 * FG has no anchor; BG calls exactly one original surface-only wrapper.
 * Re-read native selector each job, including orientation-only no-ops.
 */
static inline int ui_image_profiles_paint(uint32_t family,void *physical,
                                         uint32_t plane) {
    if (!ui_image_profiles_is_split(family) || !physical || plane>1) return 0;
    if (family==8) {
        /* Known AF callbacks have no root/cine popup gates. A new scene must
         * invalidate selection. The BG wrapper is unconditional; the FG
         * marker is the substate2 overlay and gates its own selectorstate10.
         */
        if (plane) UI_IMAGE_PROFILES_CALL1(0x4d339f070ULL,physical);
        if (UI_IMAGE_PROFILES_CALL0(0x4d3321530ULL)==1) {
            _Alignas(8) uint8_t desc[24];
            for (unsigned i=0;i<24;i++)
                desc[i]=UI_IMAGE_PROFILES_READ8(0x4d7035be8ULL+i);
            UI_IMAGE_PROFILES_CALL3(plane ? 0x4d3368760ULL : 0x4d3367b40ULL,
                                   physical,desc,0);
        }
        if (!plane && UI_IMAGE_PROFILES_READ32(0x4d73037c4ULL)==2)
            UI_IMAGE_PROFILES_CALL1(0x4d339f160ULL,physical);
        return 1;
    }
    if (plane) {
        uintptr_t fn=UI_IMAGE_PROFILES_READ32(0x4d73033f0ULL)==1 ?
                     0x4d339f070ULL : 0x4d339f1e0ULL;
        UI_IMAGE_PROFILES_CALL1(fn,physical);
    }
    return 1;
}

/* Bounded UI-only playback callback inventory. These are NOT split families
 * and must NOT enter ui_anchor_pairs/full_pair/rebuild. Apply ordinary FIT to
 * their retained canonical UI. Native NULL plane callbacks retain that plane;
 * they do not identify a new scene. Keep native image-pan Event packets raw.
 * IDs5/6 can be used as scene keys only after independently validating current
 * hierarchy. This registry does not authorize replaying any timer or updater.
 */
static inline uint32_t ui_image_profiles_ui_for_draw(uintptr_t fn,uint32_t plane) {
    static const uintptr_t movie_fg[]={
        0x4d336cb50ULL,0x4d336eaa0ULL,0x4d336f570ULL,0x4d336c330ULL,
        0x4d336cc80ULL,0x4d336cda0ULL,0x4d336efd0ULL,0x4d336e640ULL
    };
    static const uintptr_t movie_bg[]={
        0x4d336c1b0ULL,0x4d336c2c0ULL,0x4d336c230ULL,0x4d336e1f0ULL
    };
    if (plane>1 || !fn) return 0;
    const uintptr_t *table=plane ? movie_bg : movie_fg;
    size_t count=plane ? sizeof(movie_bg)/sizeof(movie_bg[0]) :
                         sizeof(movie_fg)/sizeof(movie_fg[0]);
    for (size_t i=0;i<count;i++) if (fn==table[i]) return 5;
    if (fn==(plane ? 0x4d32e3b30ULL : 0x4d32e3600ULL)) return 6;
    return 0;
}
#endif
