/* SPDX-License-Identifier: GPL-2.0-or-later
 * Native real-engine harness. SDL is optional and never linked into the module.
 * Usage: bfdoom-host IWAD [ticks [output.ppm]]; bfdoom-sdl IWAD */
#include "bfdoom.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#ifdef BFDOOM_SDL
#include <SDL.h>
#endif

static int call(unsigned op, void *arg)
{
    return (int)(int64_t)bfdoom_entry(op, arg);
}
static int failure(const char *what, int status)
{
    struct bfdoom_info info;
    call(BFDOOM_INFO, &info);
    fprintf(stderr, "%s: status %d: %s\n", what, status, info.message);
    return 1;
}
static uint32_t hash_frame(const unsigned char *p, size_t n)
{
    uint32_t hash = 2166136261u;
    while (n--) hash = (hash ^ *p++) * 16777619u;
    return hash;
}

int main(int argc, char **argv)
{
    FILE *file;
    long length;
    unsigned char *wad;
    void *heap;
    int status;
    struct bfdoom_frame frame;
    struct bfdoom_info info;
    struct bfdoom_config cfg = { BFDOOM_ABI_VERSION, sizeof(cfg), 0, 0, 0,
        BFDOOM_RECOMMENDED_HEAP, BFDOOM_AUTOSTART, 0 };
    if (argc < 2) { fprintf(stderr, "Usage: %s IWAD [ticks [output.ppm]]\n", argv[0]); return 2; }
    file = fopen(argv[1], "rb");
    if (!file) { perror(argv[1]); return 2; }
    if (fseek(file, 0, SEEK_END) || (length = ftell(file)) <= 0 || fseek(file, 0, SEEK_SET)) return 2;
    wad = malloc((size_t)length);
    heap = malloc(BFDOOM_RECOMMENDED_HEAP);
    if (!wad || !heap || fread(wad, 1, (size_t)length, file) != (size_t)length) return 2;
    fclose(file);
    cfg.wad = wad; cfg.wad_size = (size_t)length; cfg.heap = heap;
    status = call(BFDOOM_INIT, &cfg);
    if (status) return failure("init", status);
#ifdef BFDOOM_SDL
    if (SDL_Init(SDL_INIT_VIDEO | SDL_INIT_TIMER)) { fprintf(stderr, "%s\n", SDL_GetError()); return 2; }
    SDL_Window *window = SDL_CreateWindow("BF+ Doom", SDL_WINDOWPOS_CENTERED, SDL_WINDOWPOS_CENTERED,
                                         960, 720, SDL_WINDOW_RESIZABLE);
    SDL_Renderer *renderer = window ? SDL_CreateRenderer(window, -1, 0) : 0;
    SDL_Texture *texture = renderer ? SDL_CreateTexture(renderer, SDL_PIXELFORMAT_RGBA32,
                             SDL_TEXTUREACCESS_STREAMING, BFDOOM_WIDTH, BFDOOM_HEIGHT) : 0;
    if (!texture) { fprintf(stderr, "%s\n", SDL_GetError()); return 2; }
    SDL_RenderSetLogicalSize(renderer, 320, 240); /* Doom's intended 4:3 display aspect. */
    int running = 1;
    while (running) {
        SDL_Event e;
        while (SDL_PollEvent(&e)) {
            if (e.type == SDL_QUIT) running = 0;
            if ((e.type == SDL_KEYDOWN || e.type == SDL_KEYUP) && !e.key.repeat) {
                unsigned k = 0;
                if (e.key.keysym.sym >= SDLK_1 && e.key.keysym.sym <= SDLK_7) k = e.key.keysym.sym;
                if (e.key.keysym.sym == SDLK_y || e.key.keysym.sym == SDLK_n) k = e.key.keysym.sym;
                if (e.key.keysym.sym == SDLK_BACKSPACE) k = 127;
                if (e.key.keysym.sym == SDLK_PAUSE) k = 255;
                if (k) {
                    struct bfdoom_key event = { k, e.type == SDL_KEYDOWN };
                    status = call(BFDOOM_KEY, &event);
                    if (status) running = 0;
                }
            }
        }
        if (!running) break;
        const Uint8 *k = SDL_GetKeyboardState(0);
        uint32_t mask = 0;
#define HELD(key, bit) do { if (k[SDL_SCANCODE_##key]) mask |= BFDOOM_##bit; } while (0)
        HELD(UP, UP); HELD(W, UP); HELD(DOWN, DOWN); HELD(S, DOWN);
        HELD(LEFT, LEFT); HELD(RIGHT, RIGHT); HELD(A, STRAFE_LEFT); HELD(D, STRAFE_RIGHT);
        HELD(LCTRL, FIRE); HELD(RCTRL, FIRE); HELD(SPACE, USE); HELD(E, USE);
        HELD(RETURN, ENTER); HELD(ESCAPE, ESCAPE); HELD(LSHIFT, RUN); HELD(RSHIFT, RUN);
        HELD(LALT, STRAFE); HELD(RALT, STRAFE); HELD(TAB, MAP);
#undef HELD
        struct bfdoom_tick tick = { SDL_GetTicks(), mask };
        status = call(BFDOOM_TICK, &tick);
        if (status) break;
        status = call(BFDOOM_FRAME, &frame);
        if (status) break;
        SDL_UpdateTexture(texture, 0, frame.rgbx, frame.pitch);
        SDL_RenderClear(renderer); SDL_RenderCopy(renderer, texture, 0, 0); SDL_RenderPresent(renderer);
        SDL_Delay(1);
    }
    SDL_DestroyTexture(texture); SDL_DestroyRenderer(renderer); SDL_DestroyWindow(window); SDL_Quit();
#else
    uint32_t ticks = argc > 2 ? (uint32_t)strtoul(argv[2], 0, 10) : 350;
    struct bfdoom_tick tick = { 0, 0 };
    call(BFDOOM_TICK, &tick);
    for (uint32_t i = 1; i <= ticks; ++i) {
        tick.now_ms = (uint32_t)(((uint64_t)i * 1000 + 34) / 35);
        /* Exercise real player control: walk, turn, then shoot. */
        tick.keys = i < 100 ? BFDOOM_UP : i < 160 ? BFDOOM_RIGHT : i < 240 ? BFDOOM_FIRE : 0;
        status = call(BFDOOM_TICK, &tick);
        if (status) return failure("tick", status);
    }
#endif
    if (status < 0) return failure("engine", status);
    if (!status) {
        call(BFDOOM_FRAME, &frame); call(BFDOOM_INFO, &info);
        printf("{\"frames\":%u,\"game_tics\":%u,\"frame_hash\":%u,\"heap_used\":%llu,"
               "\"heap_peak\":%llu,\"zone_bytes\":%llu,\"state_bytes\":%llu}\n",
               frame.sequence, info.game_tics, hash_frame(frame.rgbx, 320*200*4),
               (unsigned long long)info.heap_used, (unsigned long long)info.heap_peak,
               (unsigned long long)info.zone_bytes, (unsigned long long)info.state_bytes);
        if (argc > 3) {
            file = fopen(argv[3], "wb");
            if (!file) { perror(argv[3]); return 2; }
            fprintf(file, "P6\n320 200\n255\n");
            for (size_t i = 0; i < 320*200; ++i) fwrite(frame.rgbx+i*4, 1, 3, file);
            fclose(file);
        }
    }
    call(BFDOOM_STOP, 0);
    free(heap); free(wad);
    return 0;
}
