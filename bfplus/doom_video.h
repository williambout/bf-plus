/* Doom's 320x200 image, corrected to its original 4:3 display aspect.
 * Pure memory operations: the native display worker owns cache publication
 * and bank switching. No global display registers are changed. */
#ifndef BFPLUS_DOOM_VIDEO_H
#define BFPLUS_DOOM_VIDEO_H
#include <stdint.h>
#include <stddef.h>

struct DoomSurface {
    uint16_t dirty_first, dirty_end, reserved[2];
    uint8_t *pixels;
    uint16_t pitch, alpha_pitch, height, reserved22;
    uint64_t alpha_offset;
};
_Static_assert(sizeof(struct DoomSurface)==32, "native surface ABI");

/* Input is byte-ordered RGBX, irrespective of the host's endian convention.
 * The camera foreground is RGB444+A4; black margins are opaque. Reject a
 * malformed descriptor before writing anything, including dirty markers. */
static inline int doom_video_present(struct DoomSurface *s,
                                     const uint8_t *rgbx, size_t bytes) {
    if (!s || !s->pixels || !rgbx || bytes<320u*200u*4u ||
        ((uintptr_t)s->pixels&1u) || s->pitch<2048 || (s->pitch&1u) ||
        s->height!=682 || s->alpha_offset ||
        (uintptr_t)s->pixels>UINTPTR_MAX-(size_t)s->pitch*682) return 0;
    for (uint32_t y=0;y<682;y++) {
        uint16_t *row=(uint16_t *)(void *)(s->pixels+(size_t)y*s->pitch);
        for (uint32_t x=0;x<1024;x++) {
            uint16_t color=15;
            /* 880x660, centered. Scale 320x200 with pixel-center sampling. */
            if (x>=72 && x<952 && y>=11 && y<671) {
                uint32_t sx=((2*(x-72)+1)*320)/1760;
                uint32_t sy=((2*(y-11)+1)*200)/1320;
                const uint8_t *p=rgbx+4*(sy*320+sx);
                color=(uint16_t)(((uint16_t)(p[0]&240)<<8) |
                                ((uint16_t)(p[1]&240)<<4) | (p[2]&240) | 15);
            }
            row[x]=color;
        }
    }
    s->dirty_first=0; s->dirty_end=682;
    return 1;
}
#endif
