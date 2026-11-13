/* Optional Doom scene for BF 1.04. Included from menu.h after its ABI types.
 * Only the display worker calls the engine. UI events publish held keys.
 * Files/module/heap are retained until reboot; no queued callback sees freed
 * memory. Normal photography does not allocate or execute the game. */
#ifndef BFPLUS_DOOM_SCENE_H
#define BFPLUS_DOOM_SCENE_H
#include "doom_package.h"
#include "doom_video.h"
#include "doom_engine/bfdoom.h"
#include "doom_storage.h"

#define DOOM_ISLAND 0x4d3320840ULL
#define DOOM_ISLAND_OLD ((u64)A64_BRANCH(DOOM_ISLAND,0x4d3317610ULL,0))
#define DOOM_RECEIVE_CALL 0x4d3323ac0ULL

u64 doom_scene[4], doom_callbacks[3];
static struct {
    volatile u32 active, generation, expected_depth, status;
    volatile u32 keys, weapon, error;
    u32 drawn_weapon, first_frame, last_ms;
    uptr owner, module, file, heap, stack_top, entry;
    u64 capacity;
    struct DoomPackage package;
    volatile u32 presses;
} doom_game;

/* Call the engine on its own 256 KiB stack, preserving the firmware task's
 * stack and all AAPCS callee-saved registers. Engine code is integer-only. */
u64 doom_engine_call(uptr entry,u32 operation,void *argument,uptr stack_top);
__asm__(".pushsection .text.doom_engine_call,\"ax\"\n.balign 4\n"
        ".global doom_engine_call\n.hidden doom_engine_call\ndoom_engine_call:\n"
        "stp x19,x30,[sp,#-16]!\nmov x19,sp\nmov x16,x0\n"
        "mov w0,w1\nmov x1,x2\nmov sp,x3\nblr x16\n"
        "mov sp,x19\nldp x19,x30,[sp],#16\nret\n.popsection\n");
static u64 doom_call(u32 op,void *argument) {
    return doom_engine_call(doom_game.entry,op,argument,doom_game.stack_top);
}
static u32 doom_now(void) {
    return (u32)(((u64 (*)(void))(uptr)0x4d31a5c00ULL)()/24000);
}
static void doom_queue(void) {
    u32 generation=__atomic_load_n(&doom_game.generation,__ATOMIC_ACQUIRE);
    ((void (*)(const u64 *,const void *,u32))(uptr)0x4d3322d90ULL)(
        doom_callbacks,&generation,sizeof(generation));
}
static int doom_frame_valid(const void *p,u32 n) {
    if (!p || n!=4 || state.mode==2 || !doom_game.active) return 0;
    u32 generation;
    memcpy(&generation,p,4);
    return generation==__atomic_load_n(&doom_game.generation,__ATOMIC_ACQUIRE);
}
static int doom_read_all(uptr file,void *out,u32 count) {
    u8 *p=out;
    while (count) {
        u32 chunk=count>65536 ? 65536 : count;
        int got=doom_file_read(file,p,chunk);
        if (got!=(int)chunk) return 0;
        p+=chunk; count-=chunk;
    }
    return 1;
}
/* Returns a stable error code; partially loaded code is never executable. */
static u32 doom_load(void) {
    uptr file=doom_file_open(DOOM_PACKAGE_PATH);
    if (!file) return 1;
    struct DoomPackage h;
    u32 error=2;
    if (!doom_read_all(file,&h,sizeof(h)) || !doom_package_header(&h)) goto done;
    size_t needed=doom_package_allocation(&h);
    if (!doom_game.owner) {
        u64 owner=0;
        u32 ok=((u32 (*)(u64,u64,u32,u32,u64 *,int))(uptr)0x4d330c850ULL)(
            needed,0x400000000ULL,0,0,&owner,100);
        if (!(ok&255) || owner<0x400d20c00ULL || owner>0x500000000ULL-needed) {
            error=3; goto done;
        }
        doom_game.owner=owner; doom_game.capacity=needed;
    }
    if (needed>doom_game.capacity) { error=4; goto done; }
    uptr base=(doom_game.owner+4095)&~4095ULL;
    uptr raw=base+h.memory_bytes;
    memcpy((void *)raw,&h,sizeof(h));
    if (!doom_read_all(file,(void *)(raw+128),h.file_bytes-128)) goto done;
    u8 extra;
    if (doom_file_read(file,&extra,1)!=0 || !doom_package_verify((void *)raw,h.file_bytes)) goto done;
    memcpy((void *)base,(const void *)(raw+128),h.image_bytes);
    memset((void *)(base+h.image_bytes),0,h.memory_bytes-h.image_bytes);
    const struct DoomRelocation *r=(const void *)(raw+h.reloc_offset);
    for (u32 i=0;i<h.reloc_count;i++) Q(base+r[i].offset)=base+r[i].addend;
    uptr heap=raw+((h.file_bytes+63u)&~63u);
    uptr stack_top=heap+h.heap_bytes+DOOM_STACK_BYTES;
    u64 ctr;
    __asm__ volatile("mrs %0, ctr_el0" : "=r"(ctr));
    clean_range(base,base+h.memory_bytes,ctr,1);
    doom_game.module=base; doom_game.file=raw; doom_game.heap=heap;
    doom_game.stack_top=stack_top; doom_game.entry=base+h.entry_offset;
    doom_game.package=h;
    struct bfdoom_config config={BFDOOM_ABI_VERSION,sizeof(config),
        (void *)(raw+h.wad_offset),h.wad_bytes,(void *)heap,h.heap_bytes,0,0};
    error=doom_call(BFDOOM_INIT,&config)==BFDOOM_OK ? 0 : 5;
done:
    doom_file_close(file);
    return error;
}
static void doom_text(void *surface,const char *text,u16 y) {
    struct {
        u16 x,y,w,h; const char *text; u64 measured;
        u32 color,font; u16 flags,pad[3];
    } t={32,y,960,64,text,0,1,6,4,{0,0,0}};
    ((u32 (*)(void *,const void *))(uptr)0x4d3328180ULL)(surface,&t);
}
static void doom_message(void *surface) {
    const char *message="Loading Doom...";
    if (doom_game.status==3) {
        if (doom_game.error==1) message="Copy DOOM.BFP To Camera Storage";
        else if (doom_game.error==3) message="Not Enough Memory";
        else if (doom_game.error==4) message="Restart Camera To Reload Doom";
        else message="Doom Package Could Not Be Loaded";
    } else if (doom_game.status==4) message="Game Closed";
    doom_text(surface,"Doom",80);
    doom_text(surface,message,230);
    doom_text(surface,"Playback: Return To BF+",500);
}
static u32 doom_buttons(u32 press,u32 touch) {
    u32 keys=0;
    if (press&16) keys|=BFDOOM_UP;
    if (press&8) keys|=BFDOOM_DOWN;
    if (press&2) keys|=BFDOOM_LEFT;
    if (press&4) keys|=BFDOOM_RIGHT;
    if (press&1) keys|=BFDOOM_FIRE|BFDOOM_ENTER;
    if ((touch&1) && !(press&1)) keys|=BFDOOM_USE;
    if (press&32) keys|=BFDOOM_ESCAPE;
    return keys;
}
u32 doom_foreground(void *surface,const void *params,u32 n) {
    if (!doom_frame_valid(params,n)) return 0;
    const u16 rect[4]={0,0,1024,682};
    ((void (*)(void *,const void *,u32))(uptr)0x4d3325ca0ULL)(surface,rect,0x000f);
    if (!doom_game.first_frame) {
        doom_game.first_frame=1; doom_message(surface); return 0;
    }
    if (doom_game.status==1) {
        doom_game.error=doom_load();
        doom_game.status=doom_game.error ? 3 : 2;
    }
    if (!doom_frame_valid(params,n)) return 0;
    if (doom_game.status==2) {
        u32 weapon=__atomic_load_n(&doom_game.weapon,__ATOMIC_ACQUIRE);
        if (weapon!=doom_game.drawn_weapon) {
            struct bfdoom_key key={(u32)'1'+weapon,1};
            doom_call(BFDOOM_KEY,&key); key.down=0; doom_call(BFDOOM_KEY,&key);
            doom_game.drawn_weapon=weapon;
        }
        /* The stock UI translator keeps only one rear Push index. Poll the
         * aligned published snapshot to allow moving/turning/firing together.
         * Short presses between frames are retained by the event handler. */
        u32 raw=W(RAW_KEYS);
        struct bfdoom_tick tick={doom_now(),doom_buttons(raw>>10,raw) |
            __atomic_exchange_n(&doom_game.presses,0,__ATOMIC_ACQ_REL)};
        u64 result=doom_call(BFDOOM_TICK,&tick);
        struct bfdoom_frame frame={0};
        if (result==BFDOOM_OK && doom_call(BFDOOM_FRAME,&frame)==BFDOOM_OK &&
            frame.width==320 && frame.height==200 && frame.pitch==1280 &&
            doom_frame_valid(params,n) && doom_video_present(surface,frame.rgbx,256000)) return 0;
        doom_game.status=result==BFDOOM_QUIT ? 4 : 3;
        doom_game.error=5;
    }
    doom_message(surface);
    return 0;
}
u32 doom_background(void *surface,const void *params,u32 n) {
    if (!doom_frame_valid(params,n)) return 0;
    const u16 rect[4]={0,0,1024,682};
    ((void (*)(void *,const void *,u32))(uptr)0x4d3328cc0ULL)(surface,rect,0x008080ff);
    return 0;
}
u32 doom_input(struct Event *e) {
    if (state.mode==2 || !doom_game.active || !e ||
        W(MENU_DEPTH)!=doom_game.expected_depth || W(MENU_PENDING)!=12) return 0;
    if (e->key) {
        struct Key k=*e->key;
        if ((k.changed&k.press)&64) {
            doom_game.active=0; doom_game.keys=0;
            ((int (*)(void))(uptr)0x4d3324250ULL)(); return 0;
        }
        u32 keys=doom_buttons(k.press,k.touch);
        __atomic_fetch_or(&doom_game.presses,keys,__ATOMIC_RELEASE);
        __atomic_store_n(&doom_game.keys,keys,__ATOMIC_RELEASE);
    }
    if (e->dial) {
        u16 step=menu_read16(e->dial);
        if (step) {
            u32 w=doom_game.weapon;
            doom_game.weapon=step<0x8000 ? (w+1)%7 : (w+6)%7;
        }
    }
    return 0; /* No shooting actions are forwarded from the game scene. */
}
u32 doom_resume(u64 *next,u64 *handlers,u32 unwind) {
    (void)next;
    if (unwind&255) return 0;
    if (state.mode==2) { handlers[0]=handlers[1]=0; return 0; }
    handlers[0]=(uptr)doom_input; handlers[1]=0;
    doom_game.keys=doom_game.presses=0; doom_game.active=1; doom_game.last_ms=doom_now();
    __atomic_fetch_add(&doom_game.generation,1,__ATOMIC_RELEASE);
    doom_queue();
    return 0;
}
u32 doom_enter(u64 *next,u64 *handlers,u32 unwind) {
    if (!(unwind&255)) {
        doom_game.status=1; doom_game.error=0; doom_game.first_frame=0;
        doom_game.weapon=doom_game.drawn_weapon=1;
    }
    return doom_resume(next,handlers,unwind);
}
u32 doom_leave(void) {
    doom_game.active=0; doom_game.keys=doom_game.presses=0;
    __atomic_fetch_add(&doom_game.generation,1,__ATOMIC_RELEASE);
    return 0;
}
static void doom_open(void) {
    if (state.mode==2 || W(MENU_PENDING)!=12 || W(MENU_DEPTH)>=11) return;
    doom_game.expected_depth=W(MENU_DEPTH)+1;
    ((int (*)(const u64 *))(uptr)0x4d3324110ULL)(doom_scene);
}
/* Only the audited UI receive caller gets timed receives. Every original
 * caller of the borrowed setter thunk keeps its stock implementation. */
u64 doom_receive_wrapper(u64 a,u64 b) {
    uptr caller;
    __asm__ volatile("mov %0,x30" : "=r"(caller));
    if (caller!=DOOM_RECEIVE_CALL+4)
        return ((u64 (*)(u64,u64))(uptr)0x4d3317610ULL)(a,b);
    for (;;) {
        if (state.mode==2 || !doom_game.active)
            return ((u32 (*)(u32,void *))(uptr)0x4d3033a50ULL)((u32)a,(void *)b);
        u32 now=doom_now();
        if ((u32)(now-doom_game.last_ms)>=28 && W(MENU_PENDING)==12 &&
            W(MENU_DEPTH)==doom_game.expected_depth && doom_game.status<3) {
            doom_game.last_ms=now;
            doom_queue();
        }
        int result=((int (*)(u32,void *,int))(uptr)0x4d3033ab0ULL)((u32)a,(void *)b,28);
        if (result!=-50) return (u32)result;
    }
}
#endif
