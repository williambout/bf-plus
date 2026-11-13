/* SPDX-License-Identifier: GPL-2.0-or-later */
#ifndef BFPLUS_DOOM_ENGINE_H
#define BFPLUS_DOOM_ENGINE_H
#include <stdint.h>

#define BFDOOM_ABI_VERSION 1u
#define BFDOOM_WIDTH 320u
#define BFDOOM_HEIGHT 200u
#define BFDOOM_TICRATE 35u
#define BFDOOM_RECOMMENDED_HEAP (24u * 1024u * 1024u)

/* One singleton, one calling thread. No firmware, libc, or host callbacks.
 * Load the separate ELF module, apply R_AARCH64_RELATIVE relocations, then
 * call its bfdoom_entry symbol (offset supplied by module.json).
 * Every operation returns a status, sign-extended to uint64_t. */
enum bfdoom_op {
    BFDOOM_INIT = 0, BFDOOM_TICK = 1, BFDOOM_FRAME = 2,
    BFDOOM_STOP = 3, BFDOOM_INFO = 4, BFDOOM_KEY = 5
};
enum bfdoom_status {
    BFDOOM_OK = 0, BFDOOM_QUIT = 1,
    BFDOOM_NOT_INITIALIZED = -1, BFDOOM_BAD_ARGUMENT = -2,
    BFDOOM_BAD_WAD = -3, BFDOOM_OUT_OF_MEMORY = -4,
    BFDOOM_ENGINE_ERROR = -5
};
enum bfdoom_flags { BFDOOM_AUTOSTART = 1u };
enum bfdoom_buttons {
    BFDOOM_UP = 1u << 0, BFDOOM_DOWN = 1u << 1,
    BFDOOM_LEFT = 1u << 2, BFDOOM_RIGHT = 1u << 3,
    BFDOOM_FIRE = 1u << 4, BFDOOM_USE = 1u << 5,
    BFDOOM_ENTER = 1u << 6, BFDOOM_ESCAPE = 1u << 7,
    BFDOOM_RUN = 1u << 8, BFDOOM_STRAFE = 1u << 9,
    BFDOOM_STRAFE_LEFT = 1u << 10, BFDOOM_STRAFE_RIGHT = 1u << 11,
    BFDOOM_MAP = 1u << 12
};

/* INIT: immutable complete IWAD and writable nonoverlapping heap must remain
 * alive until STOP. INIT replaces an existing game. No WAD bytes are copied.
 * flags=0 starts at the title; AUTOSTART starts medium skill on the first map.
 * heap is aligned internally. 24 MiB is recommended, excluding the WAD. */
struct bfdoom_config {
    uint32_t abi_version, struct_size;
    const void *wad;
    uint64_t wad_size;
    void *heap;
    uint64_t heap_size;
    uint32_t flags, reserved;
};

/* TICK: monotonically increasing wrapping milliseconds, plus held buttons.
 * The first call establishes the clock. Call at >=35 Hz; fractional ticks
 * are retained. Catch-up is limited to four ticks per call. */
struct bfdoom_tick { uint32_t now_ms, keys; };

/* FRAME: borrowed pointers valid until the next TICK/INIT/STOP. RGBX uses
 * BYTES R,G,B,255 (not a native-endian 0x00RRGGBB integer). Row pitch=1280.
 * indexed is 320x200 bytes; palette is 256 RGB triples including flashes.
 * sequence counts completed engine frames, including transition wipes. */
struct bfdoom_frame {
    const uint8_t *rgbx;
    const uint8_t *indexed;
    const uint8_t *palette;
    uint32_t width, height, pitch, sequence;
};

/* KEY: optional raw Doom key events, for keys outside the button mask.
 * ASCII lowercase, Enter=13, Escape=27, arrows=0xac..0xaf,
 * Ctrl=0x9d, Shift=0xb6, Alt=0xb8. down must be 0 or 1.
 * Do not mix raw events and mask control for the same key. */
struct bfdoom_key { uint32_t key, down; };

/* INFO is available before INIT and after errors/STOP. Error text is copied
 * into the caller's structure, so it survives releasing the game heap. */
struct bfdoom_info {
    uint32_t abi_version;
    int32_t status;
    uint64_t heap_used, heap_peak, heap_capacity, state_bytes, zone_bytes;
    uint32_t sequence, game_tics;
    char message[256];
};

#ifdef __cplusplus
extern "C" {
#endif
uint64_t bfdoom_entry(uint32_t op, void *arg);
#ifdef __cplusplus
}
#endif
#endif
