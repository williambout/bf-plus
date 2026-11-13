#include "focus_guide_render.h"
#include <stddef.h>

struct NativeSurface {
    uint16_t dirty_start, dirty_end;
    uint32_t reserved;
    uint16_t *pixels;
    uint16_t pitch, unknown, height;
};
_Static_assert(offsetof(struct NativeSurface,pixels)==8, "native surface buffer");
_Static_assert(offsetof(struct NativeSurface,pitch)==0x10, "native byte pitch");
_Static_assert(offsetof(struct NativeSurface,height)==0x14, "native height");

static void span(void *surface, int x0, int y0, int x1, int y1, uint32_t pixel) {
    if (x0<0) x0=0;
    if (y0<0) y0=0;
    if (x1>1024) x1=1024;
    if (y1>682) y1=682;
    if (x0>=x1 || y0>=y1) return;
    uint16_t rect[4]={(uint16_t)x0,(uint16_t)y0,(uint16_t)(x1-x0),(uint16_t)(y1-y0)};
    ((void (*)(void *,const uint16_t *,uint32_t))(uintptr_t)0x4d3325ca0ULL)(surface,rect,pixel);
}

void focus_guide_native_mark(void *surface, const struct FocusGuideMark *m) {
    const struct NativeSurface *s=surface;
    if (!s || !m || !s->pixels || (uintptr_t)s->pixels%2 || s->height!=682 ||
        s->pitch<2048 || s->pitch>4096 || s->pitch%2 ||
        m->color<FG_GRAY || m->color>FG_GREEN) return;
    /* Native foreground uses four color/alpha nibbles, not RGB565. The
     * physical green appearance still needs on-camera verification. */
    uint32_t pixel=m->color==FG_GRAY ? 0x888f : m->color==FG_WHITE ? 0xffff : 0x0f0f;
    if (m->shape==FG_RECT) {
        span(surface,m->x[0],m->y[0],m->x[1],m->y[1],pixel);
    } else if (m->shape==FG_TRIANGLE && m->y[0]==m->y[1] && m->x[0]<=m->x[2] &&
               m->x[2]<=m->x[1]) {
        int dy=m->y[2]-m->y[0], height=dy<0 ? -dy : dy;
        if (!height || height>32) return;
        for (int row=0;row<=height;row++) {
            int left=m->x[0]+(m->x[2]-m->x[0])*row/height;
            int right=m->x[1]+(m->x[2]-m->x[1])*row/height;
            int y=m->y[0]+(dy<0 ? -row : row);
            span(surface,left,y,right+1,y+1,pixel);
        }
    }
}
