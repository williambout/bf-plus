/* BF 1.04 bounded live OSD split. No hooks, allocation, graphics or input here.
 * Parent owns the one display-worker transaction. See UI-IMAGE-ANCHORS.md.
 * REQUIRED: reset BOTH canonical planes, draw bootstrap() with NULL/0 under
 * capture, then commit_rebuild(). Seeded or landscape pixels are NOT clean.
 * Present portrait: clear physical -> paint() -> canonical FIT_OVER.
 * Identity: bypass the split; select(raw=0) revokes clean certification.
 */
#ifndef BF_UI_IMAGE_ANCHORS_H
#define BF_UI_IMAGE_ANCHORS_H
#include <stdint.h>
#include <stddef.h>

#ifndef UI_IMAGE_ANCHORS_READ8
#define UI_IMAGE_ANCHORS_READ8(a) (*(const volatile uint8_t *)(uintptr_t)(a))
#endif
#ifndef UI_IMAGE_ANCHORS_READ32
#define UI_IMAGE_ANCHORS_READ32(a) (*(const volatile uint32_t *)(uintptr_t)(a))
#endif
#ifndef UI_IMAGE_ANCHORS_CALL0
#define UI_IMAGE_ANCHORS_CALL0(f) (((uint32_t (*)(void))(uintptr_t)(f))())
#endif
#ifndef UI_IMAGE_ANCHORS_CALL1
#define UI_IMAGE_ANCHORS_CALL1(f,s) (((uint32_t (*)(void *))(uintptr_t)(f))((s)))
#endif
#ifndef UI_IMAGE_ANCHORS_CALL3
#define UI_IMAGE_ANCHORS_CALL3(f,s,p,n) \
    (((uint32_t (*)(void *,const void *,uint32_t))(uintptr_t)(f))((s),(p),(n)))
#endif

/* Exact direct BL sites. Intercept the root call to the pure center wrapper,
 * not its nested tail B. All native instructions beyond these BLs stay intact. */
#define UI_IMAGE_ANCHORS_BL_HOOKS(X) \
    X(0x4d3390228ULL,0x4d3367b40ULL) \
    X(0x4d3390278ULL,0x4d3367b40ULL) \
    X(0x4d339028cULL,0x4d3367b40ULL) \
    X(0x4d3394038ULL,0x4d3367b40ULL) \
    X(0x4d3394088ULL,0x4d3367b40ULL) \
    X(0x4d339409cULL,0x4d3367b40ULL) \
    X(0x4d339010cULL,0x4d3368760ULL) \
    X(0x4d3393c7cULL,0x4d3368760ULL) \
    X(0x4d3390b74ULL,0x4d339f070ULL) \
    X(0x4d3390dc8ULL,0x4d339f070ULL) \
    X(0x4d339163cULL,0x4d339f070ULL) \
    X(0x4d3393f48ULL,0x4d339f070ULL) \
    X(0x4d3397144ULL,0x4d339f070ULL) \
    X(0x4d33973b8ULL,0x4d339f070ULL) \
    X(0x4d33d46d8ULL,0x4d3367b40ULL) \
    X(0x4d33d4ab8ULL,0x4d3368760ULL) \
    X(0x4d33d4ac4ULL,0x4d339f070ULL)

struct UIAnchorPair { uintptr_t foreground, background; uint32_t family; };
static const struct UIAnchorPair ui_anchor_pairs[] = {
    {0x4d3394c90ULL,0x4d33970b0ULL,1},
    {0x4d33944d0ULL,0x4d3393e00ULL,1},
    {0x4d33946c0ULL,0x4d3397240ULL,1},
    {0x4d3391dc0ULL,0x4d3390ad0ULL,2},
    {0x4d3390770ULL,0x4d3390d20ULL,2},
    {0x4d3391b40ULL,0x4d3391550ULL,2},
    {0x4d33d4590ULL,0x4d33d4a50ULL,11},
#ifdef UI_IMAGE_ANCHORS_EXTRA_PAIRS
    UI_IMAGE_ANCHORS_EXTRA_PAIRS
#endif
};

/* Mutable only on the display worker; never hold an input/draw lock across
 * the native calls. Parent serializes select/begin/end/paint/reset. */
struct UIImageAnchors {
    uintptr_t foreground, background;
    const void *canonical;
    uint32_t epoch, family, raw, clean, capturing, plane, failed;
    uint32_t painted, captured, rebuilding, level_valid[2], level_default[2];
    _Alignas(8) uint8_t level[2][24];
    uint32_t capture_family, inherited_base, level_mode[2], inherited_owner;
    const void *style;
};

static inline uint32_t ui_image_anchors_family_for_draw(uintptr_t fn) {
    for (size_t i=0;i<sizeof(ui_anchor_pairs)/sizeof(ui_anchor_pairs[0]);i++)
        if (fn==ui_anchor_pairs[i].foreground || fn==ui_anchor_pairs[i].background)
            return ui_anchor_pairs[i].family;
    return 0;
}
/* Independently callable on EXIT after select(raw=0) invalidated state.
 * Always choose the family INITIAL full pair, never the retained/partial
 * pair that happened to trigger the transition. Caller supplies NULL/0. */
static inline int ui_image_anchors_full_pair(uintptr_t fg,uintptr_t bg,uint64_t draw[3]) {
    uint32_t family=0;
    for (size_t i=0;i<sizeof(ui_anchor_pairs)/sizeof(ui_anchor_pairs[0]);i++)
        if (fg==ui_anchor_pairs[i].foreground && bg==ui_anchor_pairs[i].background)
            family=ui_anchor_pairs[i].family;
    if (!family) return 0;
#ifdef BF_UI_IMAGE_PROFILES_H
    if (ui_image_profiles_full_pair(family,draw)) return 1;
#endif
    if (family!=1 && family!=2) return 0;
    draw[0]=family==1 ? 0x4d3394c90ULL : 0x4d3391dc0ULL;
    draw[1]=family==1 ? 0x4d33970b0ULL : 0x4d3390ad0ULL;
    draw[2]=0; return 1;
}
/* Known image-bearing families that this ROOT-only adapter does not split.
 * Parent must keep these at native geometry; this is a bounded inventory,
 * not an assertion that all other callbacks are pure UI. */
static inline int ui_image_anchors_unsplit_draw(uintptr_t fn) {
    static const uintptr_t callbacks[]={
        0x4d338aa40ULL,0x4d338a940ULL,0x4d33a2230ULL,0x4d33a2170ULL,
        0x4d33b3a30ULL,0x4d33b38e0ULL,0x4d33b4820ULL,0x4d33b4640ULL,
        0x4d33cd4b0ULL,0x4d33cc230ULL,0x4d33cf410ULL,0x4d33cc450ULL,
        0x4d33d3bf0ULL,0x4d33d3200ULL,0x4d33d3590ULL,0x4d33d3650ULL,
        0x4d33d3800ULL,0x4d33d3970ULL,0x4d33d4590ULL,0x4d33d4a50ULL
    };
    for (size_t i=0;i<sizeof(callbacks)/sizeof(callbacks[0]);i++)
        if (fn==callbacks[i]) return 1;
    return 0;
}
static inline void ui_image_anchors_reset(struct UIImageAnchors *a) {
    *a=(struct UIImageAnchors){0};
}
/* Pass the actual last native pair on a no-op; never classify the no-op fn.
 * A different pair or epoch requires a new reset/full redraw acquisition. */
static inline int ui_image_anchors_select(struct UIImageAnchors *a,
        uintptr_t fg,uintptr_t bg,uint32_t epoch,uint32_t raw) {
    uint32_t family=0;
    for (size_t i=0;i<sizeof(ui_anchor_pairs)/sizeof(ui_anchor_pairs[0]);i++)
        if (fg==ui_anchor_pairs[i].foreground && bg==ui_anchor_pairs[i].background)
            family=ui_anchor_pairs[i].family;
    uint32_t identity=0;
#ifdef BF_UI_IMAGE_PROFILES_H
    identity=raw==0 && (ui_image_profiles_base_mask(family) || family==11);
#endif
    if (!family || (raw!=1 && raw!=3 && !identity)) { ui_image_anchors_reset(a); return 0; }
    if (a->foreground!=fg || a->background!=bg || a->epoch!=epoch)
        ui_image_anchors_reset(a);
    a->foreground=fg; a->background=bg; a->family=family;
    a->epoch=epoch; a->raw=raw; a->painted=0;
    return 1;
}
/* Native initializers submit these exact pairs with x1=NULL,w2=0.
 * Do not call their initializer/input/post callback twice. Parent resets
 * canonical storage and invokes only these two draw callbacks once each. */
static inline int ui_image_anchors_bootstrap(const struct UIImageAnchors *a,
                                            uint64_t draw[3]) {
    if (!a->family || a->failed) return 0;
    return ui_image_anchors_full_pair(a->foreground,a->background,draw);
}
/* Call before resetting the canonical planes. Their reset/draw success is
 * reported explicitly below. A failed transaction cannot certify itself. */
static inline void ui_image_anchors_start_rebuild(struct UIImageAnchors *a) {
    a->clean=a->captured=a->painted=a->failed=a->capturing=0;
    a->canonical=NULL; a->rebuilding=1;
    a->level_valid[0]=a->level_valid[1]=0;
}
static inline int ui_image_anchors_begin(struct UIImageAnchors *a,
        const void *canonical,uint32_t background,uint32_t epoch) {
    if (!a->family || a->failed || !canonical || background>1 || epoch!=a->epoch ||
        (!a->rebuilding && a->clean!=3))
        return 0;
    if (a->capturing) { a->failed=1; a->clean=0; return 0; }
    a->canonical=canonical; a->plane=background; a->capturing=1;
    return 1;
}
static inline void ui_image_anchors_end(struct UIImageAnchors *a,int success) {
    if (a->capturing && success && !a->failed) a->captured|=1u<<a->plane;
    else { a->failed=1; a->clean=0; }
    a->capturing=0; a->canonical=NULL;
}
/* A single native worker transaction visits FG then BG. Certify each reset+
 * full redraw before painting that bank, but publish only after ready()==1
 * AND the parent bank-selection boundary. Mask3 also accepts a staged pair. */
static inline int ui_image_anchors_rebuilt(struct UIImageAnchors *a,
        uint32_t epoch,uint32_t mask,int success) {
    if (!success || !a->family || !a->rebuilding || a->failed || a->capturing ||
        epoch!=a->epoch || !mask || (mask&~3u) || (a->captured&mask)!=mask) {
        a->clean=0; return 0;
    }
    a->clean|=mask;
    if (a->clean==3) a->rebuilding=0;
    return 1;
}
static inline int ui_image_anchors_commit_rebuild(struct UIImageAnchors *a,
                                                uint32_t epoch,int success) {
    return ui_image_anchors_rebuilt(a,epoch,3,success);
}
static inline int ui_image_anchors_ready(const struct UIImageAnchors *a,uint32_t epoch) {
    return a->family && a->clean==3 && !a->failed && !a->capturing && a->epoch==epoch;
}
static inline void uia_copy_level(uint8_t out[24],const void *in) {
    if (in) for (unsigned i=0;i<24;i++) out[i]=((const uint8_t *)in)[i];
    else for (unsigned i=0;i<24;i++) out[i]=UI_IMAGE_ANCHORS_READ8(0x4d7035be8ULL+i);
}
/* Return 1 only when native invocation was deferred; return value is exact
 * for the bounded leaf ABI. Parent calls the original on return 0. If failed
 * becomes set, discard this transaction and reacquire; do not publish it. */
static inline int ui_image_anchors_defer(struct UIImageAnchors *a,uintptr_t fn,
        void *surface,const void *arg1,uint32_t arg2,uint32_t *native_result) {
    if (!a->capturing || a->failed || surface!=a->canonical || !native_result) return 0;
    uint32_t family=a->capture_family ? a->capture_family : a->family;
#ifdef BF_UI_IMAGE_PROFILES_H
    if (ui_image_profiles_defer(family,a->plane,fn,native_result)) return 1;
#endif
    if (fn==0x4d3367b40ULL || fn==0x4d3368760ULL) {
        uint32_t bg=fn==0x4d3368760ULL;
        uint32_t valid=arg2==0;
#ifdef BF_UI_IMAGE_PROFILES_H
        valid=family==11 ? arg2==(bg ? 4u : 0u) :
                          ui_image_profiles_level_mode_valid(family,bg,arg2);
#else
        (void)family;
#endif
        if (bg!=a->plane || !valid) { a->failed=1; a->clean=0; return 0; }
        uia_copy_level(a->level[bg],arg1);
        a->level_default[bg]=arg1==NULL; a->level_valid[bg]=1;
        a->level_mode[bg]=arg2;
        *native_result=bg ? UI_IMAGE_ANCHORS_READ8(0x4d7035becULL) : 0;
        return 1;
    }
    if (fn==0x4d339f070ULL && a->plane==1) {
        /* All six root callers discard x0. Preserve its native value anyway:
         * secondary state3 tail-calls center leaf(return0), otherwise the
         * last call is the read-only aspect getter, including hidden state. */
        uint32_t aspect=UI_IMAGE_ANCHORS_CALL0(0x4d3320850ULL);
        *native_result=UI_IMAGE_ANCHORS_READ32(0x4d7043b74ULL)==3 ? 0 : aspect;
        return 1;
    }
    return 0;
}
/* Native popup/alternate painters are not replayed. Suppress the anchor
 * underlay while a root-scene overlay is active; a different scene resets
 * selection entirely. These flags are visibility gates, not UI hit mapping. */
static inline int uia_unobscured(const struct UIImageAnchors *a) {
    if (a->family==1) return !UI_IMAGE_ANCHORS_READ8(0x4d7303048ULL);
    return !(UI_IMAGE_ANCHORS_READ8(0x4d7302fd3ULL) |
             UI_IMAGE_ANCHORS_READ8(0x4d7302fd6ULL) |
             UI_IMAGE_ANCHORS_READ8(0x4d7302fd7ULL) |
             UI_IMAGE_ANCHORS_READ8(0x4d7302fdaULL) |
             UI_IMAGE_ANCHORS_READ8(0x4d7302fddULL) |
             UI_IMAGE_ANCHORS_READ8(0x4d7302fdfULL));
}
#ifdef BF_UI_IMAGE_PROFILES_H
/* S2 alpha masks overwrite alpha while retaining colored UI pixels. Identity
 * must copy canonical colors first, then apply its native-order final pass. */
static inline int ui_image_anchors_identity_bg(struct UIImageAnchors *a,
                                              void *physical,uint32_t epoch) {
    uint32_t child=a->family==11 && a->inherited_owner==9;
    if (!physical || (a->family!=9 && !child) || a->failed || a->capturing ||
        epoch!=a->epoch || !(a->clean&2) || (a->painted&2)) return 0;
    a->painted|=2;
    const struct UIImageProfileStyle *style=a->style;
    if (child) {
        static const uint32_t full_mask=UINT32_MAX;
        if (!ui_image_profiles_finish_identity_underlay(9,a->inherited_base,style,physical)) return 0;
        /* This BG renderer has no lifecycle/timer actions. Its formatting
         * scratch and level render caches retain native semantics. Canonical
         * center/level calls were deferred, so this physical pass owns them.
         * Never replay the child's stateful foreground painter. */
        UI_IMAGE_ANCHORS_CALL3(0x4d33d4a50ULL,physical,&full_mask,4);
        return 1;
    }
    return ui_image_profiles_finish_identity_bg(a->family,a->inherited_base,
        style ? style->level_mode : 0,style,physical);
}
#endif
/* Caller cleared the physical plane already. No UI callback, sensor-update
 * function, hardware grid/AF operation, or input handler is replayed here.
 * Mode0 paints current level geometry on a fresh surface; it is NOT a
 * special force bit. Native hysteresis/history stays intact. */
static inline int ui_image_anchors_paint(struct UIImageAnchors *a,void *physical,
                                        uint32_t background,uint32_t epoch) {
    if (!physical || background>1 || !a->family || a->failed || a->capturing ||
        epoch!=a->epoch || !(a->clean&(1u<<background)) ||
        (a->painted&(1u<<background))) return 0;
    a->painted|=1u<<background;
#ifdef BF_UI_IMAGE_PROFILES_H
    if (a->family==11) {
        if (!ui_image_profiles_paint_underlay(a->inherited_owner,a->inherited_base,
                                             a->style,physical,background)) return 0;
        if (background) UI_IMAGE_ANCHORS_CALL1(0x4d339f070ULL,physical);
        if (UI_IMAGE_ANCHORS_CALL0(0x4d3321530ULL)==1) {
            _Alignas(8) uint8_t desc[24];
            uia_copy_level(desc,NULL);
            UI_IMAGE_ANCHORS_CALL3(background ? 0x4d3368760ULL : 0x4d3367b40ULL,
                                  physical,desc,background ? 4 : 0);
        }
        return 1;
    }
    if (ui_image_profiles_base_mask(a->family)) {
        const struct UIImageProfileStyle *style=a->style;
        return ui_image_profiles_paint_inherited(a->family,a->inherited_base,
            a->family==10 ? 4 : style ? style->level_mode : 0,style,physical,background);
    }
    uintptr_t level=ui_image_profiles_level_descriptor(a->family);
    if (level) {
        if (ui_image_profiles_level_visible(a->family,background)) {
            _Alignas(8) uint8_t desc[24];
            for (unsigned i=0;i<24;i++) desc[i]=UI_IMAGE_ANCHORS_READ8(level+i);
            UI_IMAGE_ANCHORS_CALL3(background ? 0x4d3368760ULL : 0x4d3367b40ULL,
                                  physical,desc,5);
        }
        return 1;
    }
    if (ui_image_profiles_is_split(a->family))
        return ui_image_profiles_paint(a->family,physical,background);
#endif
    if (!uia_unobscured(a)) return 1;
    if (UI_IMAGE_ANCHORS_CALL0(0x4d3321530ULL)==1) {
        _Alignas(8) uint8_t desc[24];
        if (!a->level_valid[background] || a->level_default[background])
            uia_copy_level(desc,NULL);
        else uia_copy_level(desc,a->level[background]);
        UI_IMAGE_ANCHORS_CALL3(background ? 0x4d3368760ULL : 0x4d3367b40ULL,
                              physical,desc,0);
    }
    if (background) UI_IMAGE_ANCHORS_CALL1(0x4d339f070ULL,physical);
    return 1;
}
#endif
