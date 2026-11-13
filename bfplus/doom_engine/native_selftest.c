/* SPDX-License-Identifier: GPL-2.0-or-later
 * Test-only translation unit: reads real engine state to verify gameplay.
 * Never linked into bfdoom.elf. Door fixture moves the player in front of an
 * actual first-map door, then opens it exclusively through the public USE key.
 */
#include <stdio.h>
#include <stdlib.h>
#include "bfdoom.c"

#define CHECK(x) do { if (!(x)) { fprintf(stderr, "FAIL line %d: %s (%s)\n", __LINE__, #x, message); exit(1); } } while (0)
static uint32_t now_ms;
static int op(unsigned code, void *arg) { return (int)(int64_t)bfdoom_entry(code, arg); }
static void advance(unsigned n, unsigned buttons)
{
    for (unsigned i = 0; i < n; ++i) {
        struct bfdoom_tick t = { now_ms, buttons };
        CHECK(op(BFDOOM_TICK, &t) == BFDOOM_OK);
        now_ms += 29;
    }
}
static int key(unsigned code, unsigned down)
{
    struct bfdoom_key k = { code, down };
    return op(BFDOOM_KEY, &k);
}
static void tap(unsigned code)
{
    CHECK(key(code, 1) == BFDOOM_OK);
    CHECK(key(code, 0) == BFDOOM_OK);
}
static uint32_t frame_hash(void)
{
    struct bfdoom_frame f;
    CHECK(op(BFDOOM_FRAME, &f) == BFDOOM_OK);
    uint32_t h = 2166136261u;
    for (unsigned i = 0; i < 320*200; ++i) {
        for (unsigned c = 0; c < 3; ++c) CHECK(f.rgbx[i*4+c] == f.palette[f.indexed[i]*3+c]);
        CHECK(f.rgbx[i*4+3] == 255);
        h = (h ^ f.indexed[i]) * 16777619u;
    }
    return h;
}
static int open_real_door(void)
{
    /* The only fixture intervention is player placement. Pick an unlocked
     * manual door (normal/fast, raise/open), 32 units in front of its line.
     * Freedoom2 MAP01 uses types 31/117, with no type-1 doors. */
    mobj_t *mo = players[0].mo;
    for (int i = 0; i < numlines; ++i) {
        line_t *line = &lines[i];
        if ((line->special != 1 && line->special != 31 && line->special != 117 && line->special != 118) ||
            !line->backsector || !line->frontsector ||
            line->backsector->ceilingheight > line->backsector->floorheight) continue;
        angle_t along = R_PointToAngle2(line->v1->x, line->v1->y, line->v2->x, line->v2->y);
        angle_t facing = along + ANG90;
        unsigned fine = (unsigned)(facing >> ANGLETOFINESHIFT) & FINEMASK;
        fixed_t x = line->v1->x/2 + line->v2->x/2 - FixedMul(32*FRACUNIT, finecosine[fine]);
        fixed_t y = line->v1->y/2 + line->v2->y/2 - FixedMul(32*FRACUNIT, finesine[fine]);
        if (P_PointOnLineSide(x, y, line) != 0) continue;
        if (!P_TeleportMove(mo, x, y)) continue;
        mo->angle = facing;
        mo->z = mo->floorz;
        mo->momx = mo->momy = mo->momz = 0;
        players[0].viewz = mo->z + players[0].viewheight;
        fixed_t ceiling = line->backsector->ceilingheight;
        advance(2, 0);
        advance(4, BFDOOM_USE);
        advance(4, 0);
        if (line->backsector->ceilingheight > ceiling) return 1;
    }
    return 0;
}

int main(int argc, char **argv)
{
    CHECK(argc == 2);
    FILE *file = fopen(argv[1], "rb");
    CHECK(file);
    CHECK(!fseek(file, 0, SEEK_END));
    long size = ftell(file);
    CHECK(size > 0 && !fseek(file, 0, SEEK_SET));
    unsigned char *wad = malloc((size_t)size);
    void *heap = malloc(BFDOOM_RECOMMENDED_HEAP);
    void *second_heap = malloc(BFDOOM_RECOMMENDED_HEAP);
    CHECK(wad && heap && second_heap);
    CHECK(fread(wad, 1, (size_t)size, file) == (size_t)size);
    fclose(file);
    struct bfdoom_config cfg = { 1, sizeof(cfg), wad, (uint64_t)size, heap,
        BFDOOM_RECOMMENDED_HEAP, 0, 0 };
    CHECK(!op(BFDOOM_INIT, &cfg));
    advance(70, 0);
    CHECK(gamestate == GS_DEMOSCREEN);
    uint32_t title = frame_hash();
    tap(DOOM_KEY_ESCAPE);
    CHECK(menuactive);
    tap(DOOM_KEY_ENTER); /* New game */
    if (gamemode != commercial) tap(DOOM_KEY_ENTER); /* Episode 1 */
    tap(DOOM_KEY_ENTER); /* Medium */
    advance(100, 0);
    CHECK(gamestate == GS_LEVEL && gameepisode == 1 && gamemap == 1 && !menuactive);
    CHECK(frame_hash() != title);
    fixed_t px = players[0].mo->x, py = players[0].mo->y;
    advance(10, BFDOOM_UP);
    advance(2, 0);
    CHECK(players[0].mo->x != px || players[0].mo->y != py);
    angle_t angle = players[0].mo->angle;
    advance(8, BFDOOM_RIGHT);
    advance(2, 0);
    CHECK(players[0].mo->angle != angle);
    int ammo = players[0].ammo[am_clip];
    advance(40, BFDOOM_FIRE);
    advance(2, 0);
    CHECK(players[0].ammo[am_clip] < ammo);
    CHECK(open_real_door());
    tap(DOOM_KEY_F10);
    CHECK(key(DOOM_KEY_Y, 1) == BFDOOM_QUIT);
    CHECK(op(BFDOOM_FRAME, 0) == BFDOOM_NOT_INITIALIZED);

    /* A failed engine init must unwind safely, and an entirely new heap must
     * work afterwards. Remove a required lump while keeping a valid IWAD. */
    uint32_t dir = read32(wad+8), count = read32(wad+4);
    unsigned char *colormap = 0;
    for (uint32_t i = 0; i < count; ++i)
        if (lump_named(wad+dir+i*16+8, "COLORMAP")) colormap = wad+dir+i*16+8;
    CHECK(colormap);
    *colormap = 'X';
    cfg.heap = second_heap;
    CHECK(op(BFDOOM_INIT, &cfg) == BFDOOM_ENGINE_ERROR);
    CHECK(!host.initialized && !host.snapshot);
    *colormap = 'C';

    cfg.flags = BFDOOM_AUTOSTART;
    uint32_t baseline = 0;
    for (unsigned pass = 0; pass < 5; ++pass) {
        cfg.heap = pass & 1 ? heap : second_heap;
        memset(cfg.heap, 0x51 + pass, BFDOOM_RECOMMENDED_HEAP);
        CHECK(!op(BFDOOM_INIT, &cfg));
        now_ms = 0;
        advance(100, 0);
        uint32_t h = frame_hash();
        if (!pass) baseline = h; else CHECK(h == baseline);
        CHECK(!op(BFDOOM_STOP, 0));
        CHECK(!op(BFDOOM_STOP, 0));
    }
    free(second_heap); free(heap); free(wad);
    puts("PASS title/new-game, E1M1/MAP01, walk, turn, fire, door/use, quit, error unwind, 5 fresh-heap restarts, palette/RGBX");
    return 0;
}
