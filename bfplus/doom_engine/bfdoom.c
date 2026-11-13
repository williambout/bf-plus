/* SPDX-License-Identifier: GPL-2.0-or-later */
#include "bfdoom.h"
#include <stddef.h>

#if !defined(__clang__)
#error "Build with Clang: reset relies on its global-storage section attribute"
#endif

/* This applies to EVERY engine object with static storage duration, including
 * function-local statics. Snapshot the relocated pristine section into the
 * caller's heap before init; restore it on stop/error. No dangling Doom state
 * survives reentry, and no second permanent copy of the engine is needed. */
#ifdef __APPLE__
#pragma clang attribute push (__attribute__((section("__DATA,bfdoom_state"))), apply_to=variable(is_global))
#else
#pragma clang attribute push (__attribute__((section("bfdoom_state"))), apply_to=variable(is_global))
#endif
#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wall"
#pragma clang diagnostic ignored "-Wextra"
#pragma clang diagnostic ignored "-Wdeprecated-non-prototype"
#pragma clang diagnostic ignored "-Wpointer-sign"
#pragma clang diagnostic ignored "-Wenum-compare"
#define DOOM_IMPLEMENTATION
#include "PureDOOM_bf.h"
#pragma clang diagnostic pop
#pragma clang attribute pop

#ifdef __APPLE__
extern unsigned char state_begin[] __asm("section$start$__DATA$bfdoom_state");
extern unsigned char state_end[] __asm("section$end$__DATA$bfdoom_state");
#else
extern unsigned char state_begin[] __asm("__start_bfdoom_state") __attribute__((visibility("hidden")));
extern unsigned char state_end[] __asm("__stop_bfdoom_state") __attribute__((visibility("hidden")));
#endif

extern int bfdoom_setjmp(void *) __attribute__((returns_twice));
extern void bfdoom_longjmp(void *) __attribute__((noreturn));

/* Compilers may emit these even with -ffreestanding/-fno-builtin. Hidden,
 * local definitions prevent libc dependencies or symbol interposition. */
__attribute__((visibility("hidden")))
void *memcpy(void *dst, const void *src, size_t n)
{
    unsigned char *d = dst;
    const unsigned char *s = src;
    while (n--) *d++ = *s++;
    return dst;
}
__attribute__((visibility("hidden")))
void *memset(void *dst, int c, size_t n)
{
    unsigned char *d = dst;
    while (n--) *d++ = (unsigned char)c;
    return dst;
}
__attribute__((visibility("hidden")))
void *memmove(void *dst, const void *src, size_t n)
{
    unsigned char *d = dst;
    const unsigned char *s = src;
    if ((uintptr_t)d < (uintptr_t)s) return memcpy(dst, src, n);
    while (n) { --n; d[n] = s[n]; }
    return dst;
}

struct block {
    size_t size;
    struct block *prev, *next;
    uint32_t free, magic;
};
struct memfile { size_t pos; int open; };
static struct {
    const unsigned char *wad;
    size_t wad_size;
    unsigned char *heap, *snapshot;
    size_t heap_size, used, peak, zone;
    struct block *first;
    struct memfile files[8];
    const char *wad_name;
    uint32_t last_ms, fraction, keys, sequence;
    uint64_t ticks;
    unsigned char key_state[256];
    int initialized, clock_started;
} host;
static uint64_t jump_state[24];
static int last_status = BFDOOM_NOT_INITIALIZED;
static char message[256];
static size_t message_len;
static int message_newline;

static size_t state_size(void)
{
    return (size_t)((uintptr_t)state_end - (uintptr_t)state_begin);
}
/* The snapshot intentionally spans padding between globals, including ASan's
 * global redzones. Keep instrumentation on all actual engine/allocator code;
 * only this bounded section copy bypasses those artificial padding checks. */
__attribute__((no_sanitize("address"), noinline))
static void state_copy(void *dst, const void *src)
{
    unsigned char *d = dst;
    const unsigned char *s = src;
    size_t n = state_size();
    while (n--) *d++ = *s++;
}
static void log_message(const char *str)
{
    while (*str) {
        if (*str == '\n' || *str == '\r') {
            message_newline = 1;
        } else {
            if (message_newline) { message_len = 0; message_newline = 0; }
            if (message_len < sizeof(message) - 1) message[message_len++] = *str;
            message[message_len] = 0;
        }
        ++str;
    }
}
static int error(int status, const char *str)
{
    last_status = status;
    message_len = 0;
    message_newline = 0;
    message[0] = 0;
    log_message(str);
    return status;
}
static void fatal(int status, const char *str) __attribute__((noreturn));
static void fatal(int status, const char *str)
{
    if (str) error(status, str); else last_status = status;
    bfdoom_longjmp(jump_state);
}
static void engine_exit(int code)
{
    fatal(code == 0 ? BFDOOM_QUIT : BFDOOM_ENGINE_ERROR, 0);
}

#define BLOCK_MAGIC 0x4246444du
static void *heap_alloc(int requested)
{
    struct block *b;
    size_t n;
    if (requested < 0) fatal(BFDOOM_OUT_OF_MEMORY, "Invalid engine allocation");
    n = ((size_t)requested + 15u) & ~(size_t)15u;
    if (!n) n = 16;
    for (b = host.first; b; b = b->next) {
        if (!b->free || b->size < n) continue;
        if (b->size >= n + sizeof(*b) + 16) {
            struct block *next = (struct block *)((unsigned char *)(b + 1) + n);
            next->size = b->size - n - sizeof(*b);
            next->prev = b;
            next->next = b->next;
            next->free = 1;
            next->magic = BLOCK_MAGIC;
            if (next->next) next->next->prev = next;
            b->next = next;
            b->size = n;
        }
        b->free = 0;
        host.used += b->size + sizeof(*b);
        if (host.used > host.peak) host.peak = host.used;
        /* Upstream reads some padding and assumes initially clear screens. */
        memset(b + 1, 0, b->size);
        return b + 1;
    }
    fatal(BFDOOM_OUT_OF_MEMORY, "Doom heap exhausted");
}
static void heap_free(void *ptr)
{
    struct block *b;
    if (!ptr) return;
    if ((uintptr_t)ptr < (uintptr_t)host.heap + sizeof(*b) ||
        (uintptr_t)ptr >= (uintptr_t)host.heap + host.heap_size ||
        ((uintptr_t)ptr & 15)) fatal(BFDOOM_ENGINE_ERROR, "Invalid engine free");
    b = (struct block *)ptr - 1;
    if (b->magic != BLOCK_MAGIC || b->free)
        fatal(BFDOOM_ENGINE_ERROR, "Corrupt engine allocation");
    host.used -= b->size + sizeof(*b);
    b->free = 1;
    if (b->next && b->next->free) {
        struct block *next = b->next;
        b->size += sizeof(*b) + next->size;
        b->next = next->next;
        if (b->next) b->next->prev = b;
    }
    if (b->prev && b->prev->free) {
        struct block *prev = b->prev;
        prev->size += sizeof(*b) + b->size;
        prev->next = b->next;
        if (prev->next) prev->next->prev = prev;
    }
}

static int equal(const char *a, const char *b)
{
    while (*a && *a == *b) { ++a; ++b; }
    return *a == *b;
}
static void *file_open(const char *name, const char *mode)
{
    unsigned i;
    if (!equal(mode, "rb") && !equal(mode, "r")) return 0;
    if (name[0] == '.' && name[1] == '/') name += 2;
    if (!equal(name, host.wad_name)) return 0;
    for (i = 0; i < 8; ++i) if (!host.files[i].open) {
        host.files[i].pos = 0;
        host.files[i].open = 1;
        return &host.files[i];
    }
    fatal(BFDOOM_ENGINE_ERROR, "Too many memory WAD handles");
}
static struct memfile *file_handle(void *handle)
{
    unsigned i;
    for (i = 0; i < 8; ++i)
        if (handle == &host.files[i] && host.files[i].open) return handle;
    fatal(BFDOOM_ENGINE_ERROR, "Invalid memory WAD handle");
}
static void file_close(void *handle) { file_handle(handle)->open = 0; }
static int file_read(void *handle, void *buf, int count)
{
    struct memfile *f = file_handle(handle);
    size_t n;
    if (count < 0) fatal(BFDOOM_BAD_WAD, "Negative WAD read");
    n = (size_t)count;
    if (n > host.wad_size - f->pos) n = host.wad_size - f->pos;
    memcpy(buf, host.wad + f->pos, n);
    f->pos += n;
    return (int)n;
}
static int file_write(void *handle, const void *buf, int count)
{
    (void)handle; (void)buf; (void)count;
    return 0;
}
static int file_seek(void *handle, int offset, doom_seek_t origin)
{
    struct memfile *f = file_handle(handle);
    int64_t pos = offset;
    if (origin == DOOM_SEEK_CUR) pos += (int64_t)f->pos;
    else if (origin == DOOM_SEEK_END) pos += (int64_t)host.wad_size;
    else if (origin != DOOM_SEEK_SET) return -1;
    if (pos < 0 || (uint64_t)pos > host.wad_size) return -1;
    f->pos = (size_t)pos;
    return 0;
}
static int file_tell(void *handle) { return (int)file_handle(handle)->pos; }
static int file_eof(void *handle) { return file_handle(handle)->pos == host.wad_size; }
static char *env_get(const char *name)
{
    return equal(name, "HOME") || equal(name, "DOOMWADDIR") ? "." : 0;
}
static void time_get(int *sec, int *usec)
{
    /* Ceil the fractional microseconds so I_GetTime never rounds a tic down.
     * Base starts at 1 to satisfy upstream's zero-as-uninitialized sentinel. */
    *sec = (int)(1 + host.ticks / 35);
    *usec = (int)(((host.ticks % 35) * 1000000 + 34) / 35);
}
static uint32_t read32(const unsigned char *p)
{
    return (uint32_t)p[0] | (uint32_t)p[1] << 8 |
           (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}
static int lump_named(const unsigned char *p, const char *name)
{
    unsigned i;
    for (i = 0; i < 8; ++i) {
        unsigned c = p[i];
        if (c >= 'a' && c <= 'z') c -= 'a' - 'A';
        if (c != (unsigned char)name[i]) return 0;
        if (!c) return 1;
    }
    return 1;
}
static int validate_wad(const unsigned char *wad, size_t size, const char **name)
{
    uint32_t count, dir, i;
    int map01 = 0, e1m1 = 0, e2m1 = 0, e4m1 = 0, palette = 0;
    if (size < 12 || size > 0x7fffffff || wad[0] != 'I' || wad[1] != 'W' ||
        wad[2] != 'A' || wad[3] != 'D') return 0;
    count = read32(wad + 4); dir = read32(wad + 8);
    if (!count || count > 65535 || dir < 12 || dir > size ||
        count > (size - dir) / 16) return 0;
    for (i = 0; i < count; ++i) {
        const unsigned char *lump = wad + dir + (size_t)i * 16;
        uint32_t pos = read32(lump), len = read32(lump + 4);
        if (pos > size || len > size - pos) return 0;
        if (lump_named(lump + 8, "MAP01")) map01 = 1;
        if (lump_named(lump + 8, "E1M1")) e1m1 = 1;
        if (lump_named(lump + 8, "E2M1")) e2m1 = 1;
        if (lump_named(lump + 8, "E4M1")) e4m1 = 1;
        if (lump_named(lump + 8, "PLAYPAL") && len >= 14 * 768) palette = 1;
    }
    if (!palette || (!map01 && !e1m1)) return 0;
    *name = map01 ? "doom2.wad" : e4m1 ? "doomu.wad" : e2m1 ? "doom.wad" : "doom1.wad";
    return 1;
}
static void stop(void)
{
    /* No upstream shutdown calls: those write configs and may call exit(). */
    if (host.snapshot) state_copy(state_begin, host.snapshot);
    memset(&host, 0, sizeof(host));
}
static int init(const struct bfdoom_config *arg)
{
    struct bfdoom_config cfg;
    uintptr_t wp, hp;
    size_t alignment;
    const char *name;
    static char *argv[] = { "bfdoom", "-skill", "3", 0 };
    if (!arg) return error(BFDOOM_BAD_ARGUMENT, "Missing init config");
    cfg = *arg;
    stop();
    if (cfg.abi_version != BFDOOM_ABI_VERSION || cfg.struct_size != sizeof(cfg) ||
        cfg.reserved || (cfg.flags & ~BFDOOM_AUTOSTART) || !cfg.wad || !cfg.heap)
        return error(BFDOOM_BAD_ARGUMENT, "Invalid init config or ABI");
    wp = (uintptr_t)cfg.wad; hp = (uintptr_t)cfg.heap;
    if (cfg.wad_size > SIZE_MAX - wp || cfg.heap_size > SIZE_MAX - hp ||
        cfg.wad_size > 0x7fffffff || cfg.heap_size > 0x7fffffff ||
        (wp < hp + cfg.heap_size && hp < wp + cfg.wad_size))
        return error(BFDOOM_BAD_ARGUMENT, "Invalid or overlapping WAD/heap ranges");
    if (!validate_wad(cfg.wad, (size_t)cfg.wad_size, &name))
        return error(BFDOOM_BAD_WAD, "Expected a complete Doom-format IWAD with valid directory and PLAYPAL");
    alignment = (16 - (hp & 15)) & 15;
    if (cfg.heap_size < 8u * 1024u * 1024u + alignment)
        return error(BFDOOM_OUT_OF_MEMORY, "At least 8 MiB heap required; 24 MiB recommended");
    host.heap = (unsigned char *)cfg.heap + alignment;
    host.heap_size = ((size_t)cfg.heap_size - alignment) & ~(size_t)15;
    host.first = (struct block *)host.heap;
    host.first->size = host.heap_size - sizeof(struct block);
    host.first->prev = host.first->next = 0;
    host.first->magic = BLOCK_MAGIC;
    host.first->free = 1;
    host.wad = cfg.wad; host.wad_size = (size_t)cfg.wad_size; host.wad_name = name;
    host.snapshot = heap_alloc((int)state_size());
    state_copy(host.snapshot, state_begin);
    doom_set_malloc(heap_alloc, heap_free);
    doom_set_print(log_message);
    doom_set_file_io(file_open, file_close, file_read, file_write, file_seek, file_tell, file_eof);
    doom_set_gettime(time_get);
    doom_set_exit(engine_exit);
    doom_set_getenv(env_get);
    /* Leave two MiB outside Doom's zone for framebuffers, lump directory,
     * defaults, and transient mallocs. The zone has its own purging allocator. */
    mb_used = (int)((host.heap_size - host.used - 2u * 1024u * 1024u) / (1024u * 1024u));
    if (mb_used > 32) mb_used = 32;
    host.zone = (size_t)mb_used * 1024 * 1024;
    doom_set_default_int("sfx_volume", 0);
    doom_set_default_int("music_volume", 0);
    doom_set_default_int("screenblocks", 10);
    doom_init((cfg.flags & BFDOOM_AUTOSTART) ? 3 : 1, argv,
              DOOM_FLAG_HIDE_MOUSE_OPTIONS | DOOM_FLAG_HIDE_SOUND_OPTIONS | DOOM_FLAG_HIDE_MUSIC_OPTIONS);
    host.initialized = 1;
    ++host.ticks;
    doom_force_update();
    ++host.sequence;
    message[0] = 0; message_len = 0; message_newline = 0;
    last_status = BFDOOM_OK;
    return BFDOOM_OK;
}
static void key_event(unsigned key, unsigned down)
{
    if (host.key_state[key] == down) return;
    host.key_state[key] = (unsigned char)down;
    if (down) doom_key_down((doom_key_t)key); else doom_key_up((doom_key_t)key);
    /* Drain immediately. Otherwise rapid press/release events between ticks
     * can wrap Doom's 64-slot queue and leave a camera control stuck. */
    D_ProcessEvents();
}
static int tick(const struct bfdoom_tick *arg)
{
    static const unsigned char keys[] = {
        DOOM_KEY_UP_ARROW, DOOM_KEY_DOWN_ARROW, DOOM_KEY_LEFT_ARROW, DOOM_KEY_RIGHT_ARROW,
        DOOM_KEY_CTRL, DOOM_KEY_SPACE, DOOM_KEY_ENTER, DOOM_KEY_ESCAPE,
        DOOM_KEY_SHIFT, DOOM_KEY_ALT, DOOM_KEY_COMMA, DOOM_KEY_PERIOD, DOOM_KEY_TAB
    };
    uint32_t delta, count, i;
    if (!arg || arg->keys & ~((1u << 13) - 1))
        return error(BFDOOM_BAD_ARGUMENT, "Invalid tick or button mask");
    for (i = 0; i < sizeof(keys); ++i) key_event(keys[i], !!(arg->keys & (1u << i)));
    host.keys = arg->keys;
    if (!host.clock_started) { host.last_ms = arg->now_ms; host.clock_started = 1; }
    delta = arg->now_ms - host.last_ms;
    host.last_ms = arg->now_ms;
    /* Backwards clocks rebase; long stalls drop excess work rather than spin. */
    if (delta > 0x7fffffff) { host.fraction = 0; delta = 0; }
    if (delta > 1000) delta = 1000;
    host.fraction += delta * BFDOOM_TICRATE;
    count = host.fraction / 1000;
    host.fraction %= 1000;
    if (count > 4) count = 4;
    for (i = 0; i < count; ++i) {
        ++host.ticks;
        doom_force_update();
        ++host.sequence;
    }
    last_status = BFDOOM_OK;
    return BFDOOM_OK;
}

__attribute__((visibility("default"), used))
uint64_t bfdoom_entry(uint32_t op, void *arg)
{
    int status = BFDOOM_OK;
    if (bfdoom_setjmp(jump_state)) {
        stop();
        return (uint64_t)(int64_t)last_status;
    }
    if (op == BFDOOM_INIT) status = init(arg);
    else if (op == BFDOOM_STOP) { stop(); last_status = BFDOOM_NOT_INITIALIZED; }
    else if (op == BFDOOM_INFO) {
        struct bfdoom_info *info = arg;
        if (!info) status = BFDOOM_BAD_ARGUMENT;
        else {
            memset(info, 0, sizeof(*info));
            info->abi_version = BFDOOM_ABI_VERSION; info->status = last_status;
            info->heap_used = host.used; info->heap_peak = host.peak;
            info->heap_capacity = host.heap_size; info->state_bytes = state_size();
            info->zone_bytes = host.zone; info->sequence = host.sequence;
            info->game_tics = (uint32_t)gametic;
            memcpy(info->message, message, sizeof(message));
        }
    } else if (op != BFDOOM_TICK && op != BFDOOM_FRAME && op != BFDOOM_KEY)
        status = BFDOOM_BAD_ARGUMENT;
    else if (!host.initialized) status = BFDOOM_NOT_INITIALIZED;
    else if (op == BFDOOM_TICK) status = tick(arg);
    else if (op == BFDOOM_KEY) {
        const struct bfdoom_key *event = arg;
        if (!event || !event->key || event->key > 255 || event->down > 1)
            status = BFDOOM_BAD_ARGUMENT;
        else key_event(event->key, event->down);
    } else {
        struct bfdoom_frame *frame = arg;
        if (!frame) status = BFDOOM_BAD_ARGUMENT;
        else {
            frame->rgbx = doom_get_framebuffer(4);
            frame->indexed = screen_buffer; frame->palette = screen_palette;
            frame->width = BFDOOM_WIDTH; frame->height = BFDOOM_HEIGHT;
            frame->pitch = BFDOOM_WIDTH * 4; frame->sequence = host.sequence;
        }
    }
    return (uint64_t)(int64_t)status;
}
