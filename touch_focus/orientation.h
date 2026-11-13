/* BF 1.04 portrait menu renderer. Include after u8/u16/u32/u64/uptr.
 * No installation, MMIO, allocation, or shared menu state lives here.
 * Native painters execute inside the existing foreground draw callback.
 * See docs/UI-ORIENTATION.md for the required parent integration. */
#ifndef BF_ORIENTATION_H
#define BF_ORIENTATION_H

#define ORIENTATION_WIDTH 682u
#define ORIENTATION_HEIGHT 1024u
#define ORIENTATION_PIXELS (682u*1024u)
#define ORIENTATION_BYTES (ORIENTATION_PIXELS*2u)
#define ORIENTATION_TOP 96u
#define ORIENTATION_ROW_HEIGHT 128u
#define ORIENTATION_VISIBLE 7u

struct OrientationSurface {
    u16 dirty_first, dirty_end, reserved[2];
    u16 *pixels;
    u16 pitch, alpha_pitch, height, reserved22;
    u64 alpha_offset;
};
/* Binary compatible with the parent's MenuRow and native Settings rows. */
struct OrientationRow {
    u16 y;
    u8 flags, unused3;
    u32 unused4;
    const char *label, *value;
    u32 value_font, unused28;
};
_Static_assert(sizeof(struct OrientationSurface)==32, "native surface ABI");
_Static_assert(sizeof(struct OrientationRow)==32, "native row ABI");

/* Native TL4 reader handles boot state, mutex and shared-memory cache work.
 * Raw 1/3 are the two portrait positions. This is not an EXIF enum. */
static u32 orientation_read(void) {
    u32 raw=((u32 (*)(void))(uptr)0x4d31e36b0ULL)();
    return raw<4 ? raw : 0;
}
static u32 orientation_portrait(u32 raw) { return raw==1 || raw==3; }

/* Physical LCD -> logical portrait. Byte access accepts packed LCD packets.
 * Tap, drag origin and drag current position are independent coordinate pairs.
 * Preserve all flags, unused fields and the source packet. Any invalid pair
 * becomes (65535,65535); the caller still validates the active pair. */
static void orientation_touch(u8 out[20], const void *packet, u32 raw) {
    const u8 *in=packet;
    for (u32 i=0;i<20;i++) out[i]=in[i];
    if (!orientation_portrait(raw)) return;
    for (u32 i=0;i<12;i+=4) {
        u32 x=in[i] | ((u32)in[i+1]<<8);
        u32 y=in[i+2] | ((u32)in[i+3]<<8);
        if (x>=1024 || y>=682) {
            /* Both coordinates invalid prevents an invalid physical X from
             * becoming an apparently valid logical Y after the axis swap. */
            out[i]=out[i+1]=out[i+2]=out[i+3]=255;
            continue;
        }
        u32 u=raw==1 ? y : 681-y, v=raw==1 ? 1023-x : x;
        out[i]=(u8)u; out[i+1]=(u8)(u>>8);
        out[i+2]=(u8)v; out[i+3]=(u8)(v>>8);
    }
}

static void orientation_rect(struct OrientationSurface *s,
                             u16 x, u16 y, u16 w, u16 h, u32 color) {
    const u16 rect[4]={x,y,w,h};
    ((void (*)(void *,const void *,u32))(uptr)0x4d3325ca0ULL)(s,rect,color);
}

/* Native parser does not clip: reject unsupported text before drawing it.
 * Keep the line argument for parent ABI compatibility; no line storage needed. */
static int orientation_text(struct OrientationSurface *s, u16 *line,
                            const char *text, u32 y, u32 font, u32 color) {
    (void)line;
    if (!text) return 1;
    struct {
        u16 x,y,w,h;
        const char *text;
        u64 measured;
        u32 color,font;
        u16 flags,pad[3];
    } t={32,(u16)y,618,64,text,0,color,font,4,{0,0,0}};
    u32 width=((u32 (*)(u32,const void *,u32))(uptr)0x4d3327e50ULL)(font,&t.text,0);
    u32 height=((u32 (*)(u32,const void *))(uptr)0x4d3328000ULL)(font,&t.text);
    if (!width) return 1;
    if (width>618 || height>64 || y>960) return 0;
    ((u32 (*)(void *,const void *))(uptr)0x4d3328180ULL)(s,&t);
    return 1;
}

/* Full overwrite of the physical back buffer: no incremental double-rotation.
 * Raw 1 uses CW, raw 3 CCW. Physical sensor polarity remains provisional:
 * capture and movie-frame metadata use opposite quarter-turn conventions.
 * Stock display worker cleans this buffer and swaps banks after return. */
static int orientation_present(struct OrientationSurface *dst,
                               const u16 *portrait, u32 raw) {
    if (!orientation_portrait(raw) || !portrait || !dst || !dst->pixels ||
        dst->pitch<2048 || (dst->pitch&1) || dst->height!=682) return 0;
    for (u32 y=0;y<682;y++) {
        u16 *out=(u16 *)((u8 *)dst->pixels+y*dst->pitch);
        for (u32 x=0;x<1024;x++)
            out[x]=raw==1 ? portrait[(1023-x)*682+y] : portrait[x*682+681-y];
    }
    dst->dirty_first=0; dst->dirty_end=682;
    return 1;
}

/* Complete foreground callback body for a portrait list. The caller supplies
 * a separately allocated, draw-worker-only buffer of ORIENTATION_BYTES bytes.
 * Pass current menu metadata; never call the stock 1024-wide row painter here.
 * Title, labels, values and row flags remain the parent's owned/native data.
 * NULL values stay blank. The parent supplies any title back indicator.
 * Input activation and read-only enforcement remain the caller's job.
 * Geometry is also the contract for the parent's hit testing and scrolling. */
static int orientation_render(struct OrientationSurface *dst, u16 *buffer,
                              u32 raw, const char *title, const void *rows,
                              u32 count, u32 selected, u32 first) {
    if (!orientation_portrait(raw) || !buffer || !rows || first>count) return 0;
    struct OrientationSurface s={0,1024,{0,0},buffer,1364,0,1024,0,0};
    const struct OrientationRow *r=rows;
    orientation_rect(&s,0,0,682,1024,0);
    int ok=orientation_text(&s,0,title,16,6,1);
    for (u32 i=first;i<count && i-first<ORIENTATION_VISIBLE;i++) {
        u32 y=96+128*(i-first);
        if (i==selected) orientation_rect(&s,8,(u16)y,6,128,0xffff);
        ok&=orientation_text(&s,0,r[i].label,y,5,1);
        ok&=orientation_text(&s,0,r[i].value,y+64,r[i].value_font,6);
    }
    /* Publish only complete supported text, so the caller can fall back. */
    return ok && orientation_present(dst,buffer,raw);
}

/* Both portrait directions share a physical uniform background. Native
 * background is paired YUV422 + a separate alpha byte per pixel, not RGBA.
 * 0x008080ff = Y0, neutral chroma, opaque alpha. No extra background buffer. */
static void orientation_background(void *surface) {
    const u16 rect[4]={0,0,1024,682};
    ((void (*)(void *,const void *,u32))(uptr)0x4d3328cc0ULL)(surface,rect,0x008080ff);
    struct OrientationSurface *s=surface;
    s->dirty_first=0; s->dirty_end=682;
}

#endif
