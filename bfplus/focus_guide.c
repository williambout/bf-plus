#include "focus_guide.h"

static int visible(const struct FocusGuide *g) {
    return g->enabled && g->manual_focus && !g->magnified;
}

static void invalidate(struct FocusGuide *g) {
    /* Retain the consumed sequence: an invalid/stale interval must not let a
     * repeated publication count toward confirmation again. */
    g->confirmed=0;
    g->state=visible(g) ? FG_UNAVAILABLE : FG_HIDDEN;
}

static void restart(struct FocusGuide *g) {
    g->generation++;
    g->have_sample=0;
    invalidate(g);
}

static int configured(const struct FocusGuideConfig *c) {
    return c && c->focus_enter && c->focus_enter<c->focus_leave &&
        c->focus_leave<c->large_adjustment && c->large_adjustment<=INT32_MAX &&
        c->max_age_ms && c->max_age_ms<0x80000000u &&
        c->min_confidence && c->min_confidence<=1000 &&
        c->confirmation_frames && c->confirmation_frames<=120;
}

static uint32_t magnitude(int32_t v) {
    /* Avoid signed overflow for INT32_MIN. */
    return v<0 ? 0u-(uint32_t)v : (uint32_t)v;
}

void focus_guide_init(struct FocusGuide *g) {
    /* Keep the standalone freestanding object free of a libc memset call. */
    volatile uint8_t *bytes=(volatile uint8_t *)g;
    for (unsigned i=0;i<sizeof(*g);i++) bytes[i]=0;
    g->x=512; g->y=341; g->generation=1;
}

void focus_guide_configure(struct FocusGuide *g, const struct FocusGuideConfig *c) {
    g->config=c ? *c : (struct FocusGuideConfig){0};
    restart(g);
}

void focus_guide_mode(struct FocusGuide *g, int enabled, int manual_focus, int magnified) {
    uint32_t e=!!enabled, mf=!!manual_focus, m=!!magnified;
    if (g->enabled==e && g->manual_focus==mf && g->magnified==m) return;
    g->enabled=e; g->manual_focus=mf; g->magnified=m;
    restart(g);
}

void focus_guide_target(struct FocusGuide *g, int x, int y, uint32_t target_id) {
    /* Includes the full brackets and adjustment markers within live view. */
    x=x<52 ? 52 : x>971 ? 971 : x;
    y=y<72 ? 72 : y>633 ? 633 : y;
    if (g->x==x && g->y==y && g->target_id==target_id) return;
    g->x=(uint16_t)x; g->y=(uint16_t)y; g->target_id=target_id;
    restart(g);
}

void focus_guide_update(struct FocusGuide *g, const struct FocusGuideSample *s, uint32_t now) {
    const struct FocusGuideConfig *c=&g->config;
    if (!visible(g) || !configured(c)) { invalidate(g); return; }
    if (g->have_sample && now-g->last.captured_ms>c->max_age_ms) invalidate(g);
    if (!s) return;
    if (s->generation!=g->generation || now-s->captured_ms>c->max_age_ms) {
        invalidate(g); return;
    }
    if (g->have_sample) {
        /* Repainting the same sample cannot confirm focus or refresh its age.
         * Changed data under the same sequence is a torn/invalid publication. */
        uint32_t advance=s->sequence-g->last.sequence;
        if (!advance) {
            if (s->captured_ms!=g->last.captured_ms || s->defocus!=g->last.defocus ||
                s->confidence!=g->last.confidence || s->valid!=g->last.valid)
                invalidate(g);
            return;
        }
        uint32_t elapsed=s->captured_ms-g->last.captured_ms;
        if (advance>=0x80000000u || elapsed>=0x80000000u) {
            invalidate(g); return;
        }
        if (!elapsed || elapsed>c->max_age_ms) invalidate(g);
        if (!elapsed) { g->last=*s; return; }
    }
    uint32_t error=magnitude(s->defocus);
    int locked=g->state==FG_IN_FOCUS;
    g->have_sample=1; g->last=*s;
    if (s->valid!=1 || s->confidence<c->min_confidence || s->confidence>1000) {
        invalidate(g); return;
    }
    if (error<=(locked ? c->focus_leave : c->focus_enter)) {
        if (g->confirmed<c->confirmation_frames) g->confirmed++;
        g->state=g->confirmed>=c->confirmation_frames ? FG_IN_FOCUS : FG_UNAVAILABLE;
        return;
    }
    g->confirmed=0;
    int large=error>=c->large_adjustment;
    g->state=s->defocus>0 ? (large ? FG_FAR_LARGE : FG_FAR_SMALL) :
                              (large ? FG_NEAR_LARGE : FG_NEAR_SMALL);
}

static void rect(FocusGuidePaint paint, void *ctx, enum FocusGuideColor color,
                 int x, int y, int w, int h) {
    struct FocusGuideMark m={FG_RECT,color,{(int16_t)x,(int16_t)(x+w),0},
                                            {(int16_t)y,(int16_t)(y+h),0}};
    paint(ctx,&m);
}

static void triangle(FocusGuidePaint paint, void *ctx, enum FocusGuideColor color,
                     int x, int y, int up) {
    struct FocusGuideMark m={FG_TRIANGLE,color,
        {(int16_t)(x-6),(int16_t)(x+6),(int16_t)x},
        {(int16_t)y,(int16_t)y,(int16_t)(y+(up ? -9 : 9))}};
    paint(ctx,&m);
}

void focus_guide_paint(struct FocusGuide *g, uint32_t now,
                       FocusGuidePaint paint, void *ctx) {
    focus_guide_update(g,0,now);
    if (!paint || !visible(g) || g->state==FG_HIDDEN) return;
    const struct FocusGuideConfig *c=&g->config;
    enum FocusGuideState state=configured(c) && g->state>=FG_UNAVAILABLE &&
        g->state<=FG_NEAR_LARGE ? g->state : FG_UNAVAILABLE;
    enum FocusGuideColor color=state==FG_IN_FOCUS ? FG_GREEN :
                               state==FG_UNAVAILABLE ? FG_GRAY : FG_WHITE;
    int x=g->x, y=g->y;
    /* Four open corners leave the subject unobscured. */
    for (int side=-1;side<=1;side+=2) {
        for (int top=-1;top<=1;top+=2) {
            int left=x+side*40, upper=y+top*28;
            rect(paint,ctx,color,left-(side>0 ? 14 : 0),upper,16,2);
            rect(paint,ctx,color,left,upper-(top>0 ? 12 : 0),2,14);
        }
    }
    if (state==FG_UNAVAILABLE) {
        /* No direction or apparent alignment when information is missing. */
        for (int i=-1;i<=1;i++) rect(paint,ctx,color,x+i*12-2,y-43,4,4);
        return;
    }
    int spread=0;
    if (state!=FG_IN_FOCUS) {
        uint32_t amount=magnitude(g->last.defocus);
        if (amount>c->large_adjustment) amount=c->large_adjustment;
        spread=8+(int)((uint64_t)amount*24/c->large_adjustment);
    }
    int near=state==FG_NEAR_SMALL || state==FG_NEAR_LARGE;
    if (state==FG_IN_FOCUS) {
        /* All three pointers meet, without painting one on top of another. */
        triangle(paint,ctx,color,x,y-40,1);
        triangle(paint,ctx,color,x-6,y-58,0);
        triangle(paint,ctx,color,x+6,y-58,0);
    } else if (near) {
        triangle(paint,ctx,color,x,y-58,0);
        triangle(paint,ctx,color,x-spread,y-40,1);
        triangle(paint,ctx,color,x+spread,y-40,1);
    } else {
        triangle(paint,ctx,color,x,y-40,1);
        triangle(paint,ctx,color,x-spread,y-58,0);
        triangle(paint,ctx,color,x+spread,y-58,0);
    }
}
