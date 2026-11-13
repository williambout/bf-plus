/* BF 1.04 segment 05: append BF+ and a native child settings scene. See
 * docs/TOUCH-FOCUS-MENU-NOTES.md for the fourteen pointer hooks and evidence.
 * Included after Key/Event, State/state, focus_target and stock(). */
#ifndef BF_TOUCH_MENU_H
#define BF_TOUCH_MENU_H
#include "aspect_ratio.h"

#define MENU_STOCK_ROWS 0x4d7042c18ULL
#define MENU_ALTERNATE  0x4d73025f4ULL
#define MENU_CURRENT    0x4d73025f6ULL
#define MENU_PREVIOUS   0x4d73025f7ULL
#define MENU_REPAINT    0x4d7042e98ULL
#define MENU_HIGHLIGHT  0x4d7042ea0ULL
#define MENU_BACKING    0x4d7042ec0ULL
#define MENU_SCROLL     0x4d7042ee0ULL
#define MENU_INPUT      0x4d3373200ULL
#define MENU_DRAW       0x4d33726d0ULL
#define MENU_INITIAL    0x4d33729c0ULL
#define MENU_PARENT_RESUME 0x4d3372d90ULL
#define MENU_DEPTH      0x4d70346a0ULL
#define MENU_PENDING    0x4d70346a4ULL

struct MenuRow {
    u16 y;
    u8 flags, unused3;
    u32 unused4;
    const char *label, *value;
    u32 value_font, unused28;
};
_Static_assert(sizeof(struct MenuRow)==32, "stock settings row ABI");
_Static_assert(__builtin_offsetof(struct MenuRow,label)==8, "row label ABI");
_Static_assert(__builtin_offsetof(struct MenuRow,value_font)==24, "row font ABI");

struct MenuRow menu_rows[11];
u64 menu_callbacks[6];
/* Scene descriptor: init, resume, suspend, exit; copied by stock push/pop.
 * Init/resume: u32(next_scene[4], handlers[2], u32 unwind). Exit/suspend: u32(). */
u64 menu_parent_scene[4], menu_submenu_scene[4], menu_submenu_callbacks[3];
struct MenuRow menu_submenu_rows[5];
struct MenuTitle { u16 y; u8 unused[6]; const char *text; u8 back, pad[7]; };
_Static_assert(sizeof(struct MenuTitle)==24, "stock submenu title ABI");
static struct MenuTitle menu_submenu_title;
struct MenuView { u32 parent_depth, active, returning, restore_draw, selected; };
static volatile struct MenuView menu_view;
/* Native compact-picker metadata, verified against 33646d0/4750/4970.
 * +0x20 is DISABLED flags (zero enables); +0x28 must remain NULL because
 * the native foreground otherwise calls the camera's language setter. */
struct MenuPicker {
    u16 y;
    u8 count, selected, previous, committed, widest, first_visible;
    u8 visible_count, flags, reserved[6];
    const char *const *labels, *const *secondary;
    const u8 *disabled;
    const void *language_data;
};
_Static_assert(sizeof(struct MenuPicker)==48, "native picker ABI");
_Static_assert(__builtin_offsetof(struct MenuPicker,labels)==16, "picker labels ABI");
_Static_assert(__builtin_offsetof(struct MenuPicker,language_data)==40, "picker language ABI");
static struct MenuPicker menu_picker;
/* All editable BF+ rows use the native OFF/ON picker. */
static const char *menu_picker_labels[2];
static const u8 menu_picker_disabled[2] __attribute__((used))={0,0};
u64 menu_picker_scene[4], menu_picker_callbacks[6];
static volatile u32 menu_picker_active;
static const char menu_label[] __attribute__((used))="BF+";
/* Stock row labels start in font5, which lacks most lowercase ASCII glyphs.
 * Native ESC + font index selects font6 (60-pixel cell, 36-pixel capitals),
 * matching the stock menu label style with full mixed-case coverage.
 * Separate literals keep the control byte's hex escape bounded. */
static const char menu_option[] __attribute__((used))="\x1b\x06" "Touch Focus Zoom";
static const char menu_subject_option[] __attribute__((used))="\x1b\x06" "MF Subject Detection";
static const char menu_aspect_option[] __attribute__((used))="\x1b\x06" "Extra Aspect Ratios";
static const char menu_doom_label[] __attribute__((used))="\x1b\x06" "Doom";
static const char menu_version_label[] __attribute__((used))="\x1b\x06" "Version";
static const char menu_version_value[] __attribute__((used))="1.0";
/* Uppercase option values share native font6 with the Title Case row labels.
 * The explicit control keeps the compact picker in the matching font too. */
static const char menu_picker_off[] __attribute__((used))="\x1b\x06" "OFF";
static const char menu_picker_on[] __attribute__((used))="\x1b\x06" "ON";
static u64 relocate(const void *symbol, uptr base);

/* Packed loads accept the unaligned serialized dial/key/LCD payloads. */
static u16 menu_read16(const void *p) {
    struct __attribute__((packed)) Packed16 { u16 value; };
    return ((const struct Packed16 *)p)->value;
}
static void menu_write16(uptr p, u16 value) {
    /* All writes are to the two aligned native scroll/highlight globals. */
    *(volatile u16 *)p=value;
}
#define MENU_SCROLL_VALUE (*(volatile u16 *)(uptr)MENU_SCROLL)

/* The parent removes outside settings and retains this allocation. A stale
 * queued callback must nevertheless never index row10 in the restored table. */
static void menu_removed_selection(void) {
    u32 current=B(MENU_CURRENT), previous=B(MENU_PREVIOUS);
    u32 scroll=MENU_SCROLL_VALUE;
    if (current<=9 && previous<=9 && scroll>=52 && scroll<=322) return;
    if (current>9) current=9;
    if (previous>9) previous=9;
    if (scroll<52) scroll=52;
    if (scroll>322) scroll=322;
    /* Also keep the selected stock row inside the viewport if only the
     * previous index was stale, or removal raced a selection reset. */
    u32 y=52+90*current;
    if (scroll>y) scroll=y;
    if (y+90>scroll+630) scroll=y-540;
    B(MENU_CURRENT)=(u8)current; B(MENU_PREVIOUS)=(u8)previous;
    menu_write16(MENU_SCROLL,(u16)scroll);
    menu_write16(MENU_HIGHLIGHT,(u16)(52+y-scroll));
    B(MENU_REPAINT)=1;
}

static void menu_refresh_row(void) {
    menu_rows[10].flags=(u8)(2 | (B(MENU_CURRENT)==10));
    menu_rows[10].value=0; /* Native submenu arrow. The toggle lives inside. */
}
static void menu_refresh_submenu(void) {
    menu_submenu_rows[0].flags=(u8)(2 | (menu_view.selected==0));
    menu_submenu_rows[0].value=state.mode==1 ? menu_picker_on : menu_picker_off;
    menu_submenu_rows[1].flags=(u8)(2 | (menu_view.selected==1));
    menu_submenu_rows[1].value=focus_target.enabled ? menu_picker_on : menu_picker_off;
    menu_submenu_rows[2].flags=(u8)(2 | (menu_view.selected==2));
    menu_submenu_rows[2].value=aspect_extra_enabled ? menu_picker_on : menu_picker_off;
    /* Stock special style omits the editing chevron on the read-only row. */
    menu_submenu_rows[3].flags=(u8)(2 | (menu_view.selected==3));
    menu_submenu_rows[3].value=0;
    menu_submenu_rows[4].flags=(u8)(0x12 | (menu_view.selected==4));
}
static void menu_queue(void) {
    ((void (*)(const u64 *,const void *,u32))(uptr)0x4d3322d90ULL)(
        menu_callbacks,0,0);
}

static void menu_restore_parent(void) {
    B(MENU_ALTERNATE)=0;
    B(MENU_CURRENT)=10; B(MENU_PREVIOUS)=10;
    menu_write16(MENU_SCROLL,412); menu_write16(MENU_HIGHLIGHT,592);
    ((void (*)(u32))(uptr)0x4d3372a20ULL)(1);
    menu_refresh_row();
    menu_view.restore_draw=0;
}

u32 menu_parent_resume_wrapper(u64 *next_scene, u64 *handlers, u32 unwind) {
    typedef u32 (*Resume)(u64 *,u64 *,u32);
    if (state.mode==2) {
        menu_removed_selection();
        return ((Resume)(uptr)MENU_PARENT_RESUME)(next_scene,handlers,unwind);
    }
    u32 returning=menu_view.returning && !(unwind&255);
    menu_view.returning=0;
    if (returning) {
        /* Stock resume rejects index10. Give its setup a valid selection,
         * then restore BF+ before its queued initial draw is rendered. */
        B(MENU_CURRENT)=9; B(MENU_PREVIOUS)=9;
        menu_write16(MENU_SCROLL,322);
        menu_view.restore_draw=1;
    }
    u32 result=((Resume)(uptr)MENU_PARENT_RESUME)(next_scene,handlers,unwind);
    /* Works for both synchronous and deferred draw-queue execution. */
    if (returning && menu_view.restore_draw) menu_restore_parent();
    return result;
}

static void menu_open_submenu(void) {
    u32 depth=W(MENU_DEPTH);
    if (W(MENU_PENDING)!=12 || depth<1 || depth>=11 || state.mode==2) return;
    menu_view.parent_depth=depth;
    menu_view.returning=1;
    int result=((int (*)(const u64 *))(uptr)0x4d3324110ULL)(menu_submenu_scene);
    if (result) menu_view.returning=0;
}

u32 menu_input_wrapper(struct Event *e) {
    if (state.mode==2) {
        menu_removed_selection();
        return stock(e,MENU_INPUT);
    }
    if (!e || B(MENU_ALTERNATE)) return stock(e,MENU_INPUT);
    u32 current=B(MENU_CURRENT);
    if (current!=9 && current!=10) return stock(e,MENU_INPUT);

    struct Key key={0};
    if (e->key) key=*e->key; /* Key is packed; serialized input may be unaligned. */
    u32 edges=key.changed & key.press;
    u32 down=(edges | key.repeat) & 8;
    u32 forward=0;
    if (e->dial) {
        u32 step=menu_read16(e->dial);
        forward=step && step<0x8000;
    }
    /* Keep the stock 200/100ms repeat gate. Consume an ineligible repeat too,
     * so it cannot hide a simultaneous exit or run the gate a second time. */
    u32 advance=forward;
    if (current==9 && down && !advance)
        advance=((u32 (*)(const struct Key *,u32))(uptr)0x4d3323400ULL)(&key,3)&255;
    u32 consumed=down, redraw=0, open=0;
    if (current==9 && advance) {
        B(MENU_PREVIOUS)=9; B(MENU_CURRENT)=10;
        menu_write16(MENU_SCROLL,412);
        menu_write16(MENU_HIGHLIGHT,592);
        ((void (*)(u32))(uptr)0x4d3372a20ULL)(0);
        redraw=1;
    }
    if (current==10 || advance) {
        /* Enter only on a press on an already selected BF+ row. */
        consumed |= (edges | key.repeat) & 5;
        open=current==10 && (edges & 5);
    }
    if (redraw) { menu_refresh_row(); menu_queue(); }
    if (!consumed && !forward) return stock(e,MENU_INPUT);

    struct Event rest=*e;
    u8 dial[4];
    if (e->key && consumed) {
        key.changed &= (u16)~consumed;
        key.repeat &= (u16)~consumed;
        /* Preserve physical touch/press state, count, padding and all other
         * action bits. Never alias a NULL key to this local copy. */
        rest.key=&key;
    }
    if (forward) {
        const u8 *src=e->dial;
        dial[0]=0; dial[1]=0; dial[2]=src[2]; dial[3]=src[3];
        rest.dial=dial;
    }
    /* Synchronous only: stock does not retain these stack payloads. Even an
     * otherwise empty remainder keeps optional events and the exact return. */
    u32 result=stock(&rest,MENU_INPUT);
    /* Give simultaneous exits/navigation priority. Never overwrite a stock
     * transition requested by the filtered remainder. */
    if (open && B(MENU_CURRENT)==10 && !B(MENU_ALTERNATE)) menu_open_submenu();
    return result;
}

#include "doom_scene.h"

static u32 menu_child_input(struct Event *e, u32 picker) {
    if (state.mode==2 || !(picker ? menu_picker_active : menu_view.active) || !e ||
        W(MENU_DEPTH)!=menu_view.parent_depth+1+picker || W(MENU_PENDING)!=12) return 0;
    struct Key key={0};
    if (e->key) key=*e->key; /* Key is packed; serialized input may be unaligned. */
    u32 edges=key.changed & key.press;
    int direction=0;
    u32 navigation=edges | key.repeat;
    if ((navigation&16) &&
        (((u32 (*)(const struct Key *,u32))(uptr)0x4d3323400ULL)(&key,4)&255)) direction=-1;
    else if ((navigation&8) &&
        (((u32 (*)(const struct Key *,u32))(uptr)0x4d3323400ULL)(&key,3)&255)) direction=1;
    else if (e->dial) {
        u32 step=menu_read16(e->dial);
        if (step) direction=step<0x8000 ? 1 : -1;
    }
    struct Event rest=*e;
    if (e->key) {
        /* Consume this list's navigation/activation, including repeats.
         * Stock still handles Menu/playback exits and unrelated payloads. */
        key.changed&=(u16)~31; key.repeat&=(u16)~31;
        rest.key=&key;
    }
    u8 dial[4];
    if (e->dial) {
        const u8 *src=e->dial;
        dial[0]=0; dial[1]=0; dial[2]=src[2]; dial[3]=src[3];
        rest.dial=dial;
    }
    u32 result=stock(&rest,MENU_INPUT);
    /* Exits win even if the stock handler defers its transition. Never let
     * a simultaneous center press commit after Menu/playback or removal. */
    if (state.mode==2 || W(MENU_PENDING)!=12 || (edges&96)) return result;
    if (edges&2) {
        ((int (*)(void))(uptr)0x4d3324250ULL)();
    } else {
        u32 redraw=0;
        if (direction) {
            u32 old=picker ? menu_picker.selected : menu_view.selected;
            u32 selected=old, count=picker ? menu_picker.count : 5;
            if (direction>0 && selected+1<count) selected++;
            if (direction<0 && selected) selected--;
            redraw=old!=selected;
            if (picker) {
                menu_picker.previous=(u8)old;
                menu_picker.selected=(u8)selected;
            } else {
                menu_view.selected=selected;
            }
        } else if (edges&5) {
            if (picker) {
                /* Navigation stays tentative; only physical confirmation
                 * applies this row's boolean setting. */
                u32 value=menu_picker.selected;
                if (value<2) {
                    if (menu_view.selected==0) state.mode=value;
                    else if (menu_view.selected==1) focus_target.enabled=value;
                    else if (menu_view.selected==2) aspect_extra_select(value);
                }
                ((int (*)(void))(uptr)0x4d3324250ULL)();
            } else if (menu_view.selected==3) {
                doom_open();
            } else if (menu_view.selected<3 && W(MENU_DEPTH)<11) {
                ((int (*)(const u64 *))(uptr)0x4d3324110ULL)(menu_picker_scene);
            }
        }
        if (redraw) {
            if (!picker) menu_refresh_submenu();
            ((void (*)(const u64 *,const void *,u32))(uptr)0x4d3322d90ULL)(
                picker ? menu_picker_callbacks : menu_submenu_callbacks,0,0);
        }
    }
    return result;
}
u32 menu_submenu_input_wrapper(struct Event *e) { return menu_child_input(e,0); }
u32 menu_picker_input_wrapper(struct Event *e) { return menu_child_input(e,1); }

static u32 menu_submenu_paint(void *surface, u32 background);
static u32 menu_picker_paint(void *surface, u32 initial, u32 background) {
    if (state.mode==2 || !menu_picker_active) return 0;
    const u16 viewport[4]={0,52,1024,630};
    if (initial) {
        /* These native blends preserve the parent pixels. Partial redraws
         * must not repeat them or the parent progressively darkens. */
        ((void (*)(void *,const void *,u32))(uptr)(background ?
            0x4d332b110ULL : 0x4d3327240ULL))(
                surface,viewport,background ? 0x00808085 : 8);
    }
    ((u32 (*)(void *,struct MenuPicker *))(uptr)(background ?
        0x4d3364750ULL : 0x4d3364970ULL))(surface,&menu_picker);
    if (initial) {
        if (background) ((void (*)(void *))(uptr)0x4d335d380ULL)(surface);
        else ((void (*)(void *,u32,u32,u32))(uptr)0x4d335d4b0ULL)(surface,0x2f,0,0);
    }
    return 0;
}
u32 menu_picker_draw_wrapper(void *s, void *p, u32 n) {
    (void)p; (void)n; return menu_picker_paint(s,0,0);
}
u32 menu_picker_background_wrapper(void *s, void *p, u32 n) {
    (void)p; (void)n; return menu_picker_paint(s,0,1);
}
u32 menu_picker_initial_draw_wrapper(void *s, void *p, u32 n) {
    (void)p; (void)n; return menu_picker_paint(s,1,0);
}
u32 menu_picker_initial_background_wrapper(void *s, void *p, u32 n) {
    (void)p; (void)n; return menu_picker_paint(s,1,1);
}
u32 menu_picker_enter(u64 *next_scene, u64 *handlers, u32 unwind) {
    (void)next_scene;
    if (unwind&255) return 0;
    if (state.mode==2 || menu_view.selected>=3) {
        menu_picker_active=0; handlers[0]=0; handlers[1]=0; return 0;
    }
    handlers[0]=(uptr)menu_picker_input_wrapper; handlers[1]=0;
    menu_picker.y=(u16)(142+90*menu_view.selected);
    menu_picker.count=menu_picker.visible_count=2;
    menu_picker.labels=menu_picker_labels;
    u32 value=menu_view.selected==0 ? state.mode==1 :
              menu_view.selected==1 ? !!focus_target.enabled : !!aspect_extra_enabled;
    menu_picker.selected=menu_picker.committed=(u8)value;
    menu_picker.previous=255; menu_picker.first_visible=0;
    menu_picker.widest=(u8)((u32 (*)(struct MenuPicker *))(uptr)0x4d33646d0ULL)(&menu_picker);
    menu_picker_active=1;
    ((void (*)(u32))(uptr)0x4d335f000ULL)(0x2f);
    ((void (*)(const u64 *,const void *,u32))(uptr)0x4d3322d90ULL)(
        menu_picker_callbacks+3,0,0);
    return 0;
}
u32 menu_picker_leave(void) { menu_picker_active=0; return 0; }

u32 menu_submenu_draw_wrapper(void *surface, void *params, u32 len) {
    (void)params; (void)len;
    if (state.mode==2 || !menu_view.active) return 0;
    return menu_submenu_paint(surface,0);
}
static u32 menu_submenu_paint(void *surface, u32 background) {
    menu_refresh_submenu();
    const u16 viewport[4]={0,52,1024,630};
    ((void (*)(void *,const void *,u32))(uptr)(background ? 0x4d3328cc0ULL : 0x4d3325ca0ULL))(
        surface,viewport,background ? 0x228080ff : 0);
    ((void (*)(void *,const void *))(uptr)(background ? 0x4d3363c60ULL : 0x4d3363ca0ULL))(
        surface,&menu_submenu_title);
    for (u32 i=0;i<5;i++)
        ((void (*)(void *,const void *))(uptr)(background ? 0x4d3363d80ULL : 0x4d3363df0ULL))(
            surface,&menu_submenu_rows[i]);
    if (!background) ((void (*)(void *,u32,u32,u32))(uptr)0x4d335d4b0ULL)(surface,0x2f,0,0);
    return 0;
}
u32 menu_submenu_background_wrapper(void *surface, void *params, u32 len) {
    (void)params; (void)len;
    if (state.mode==2 || !menu_view.active) return 0;
    return menu_submenu_paint(surface,1);
}
u32 menu_submenu_resume(u64 *next_scene, u64 *handlers, u32 unwind) {
    (void)next_scene;
    if (unwind&255) return 0;
    if (state.mode==2) { handlers[0]=0; handlers[1]=0; return 0; }
    handlers[0]=(uptr)menu_submenu_input_wrapper;
    handlers[1]=0;
    menu_view.active=1;
    menu_refresh_submenu();
    ((void (*)(u32))(uptr)0x4d335f000ULL)(0x2f);
    ((void (*)(const u64 *,const void *,u32))(uptr)0x4d3322d90ULL)(
        menu_submenu_callbacks,0,0);
    return 0;
}
u32 menu_submenu_enter(u64 *next_scene, u64 *handlers, u32 unwind) {
    if (!(unwind&255)) menu_view.selected=0;
    return menu_submenu_resume(next_scene,handlers,unwind);
}
u32 menu_submenu_leave(void) {
    menu_view.active=0;
    return 0;
}

static void menu_scrollbar(void *surface) {
    struct { u16 x,y,width,height; } rect={1018,52,6,630};
    typedef void (*RectPainter)(void *,const void *,u32);
    RectPainter paint=(RectPainter)(uptr)0x4d3325ca0ULL;
    paint(surface,&rect,0);
    u32 scroll=MENU_SCROLL_VALUE;
    u32 offset=scroll>52 ? scroll-52 : 0;
    if (offset>360) offset=360;
    /* floor(630*630/990)=400, leaving 230 pixels of thumb travel. */
    rect.y=(u16)(52+offset*230/360); rect.height=400;
    paint(surface,&rect,0xffff);
}

static u32 menu_draw_common(void *surface, void *params, u32 len, u64 fn) {
    typedef u32 (*Draw)(void *,void *,u32);
    if (state.mode==2) {
        menu_removed_selection();
        return ((Draw)(uptr)fn)(surface,params,len);
    }
    if (B(MENU_ALTERNATE)) return ((Draw)(uptr)fn)(surface,params,len);
    if (menu_view.restore_draw) menu_restore_parent();
    if (fn==MENU_INITIAL) {
        /* The stock initial callback sets these too, but prepainting needs
         * the current pitch before entering that callback. */
        const u8 *src=surface;
        for (u32 i=16;i<20;i++) B(MENU_BACKING+i)=src[i];
    }
    menu_refresh_row();
    ((void (*)(void *,const struct MenuRow *))(uptr)0x4d3363df0ULL)(
        (void *)MENU_BACKING,&menu_rows[10]);
    u32 result=((Draw)(uptr)fn)(surface,params,len);
    menu_scrollbar(surface);
    return result;
}
u32 menu_draw_wrapper(void *surface, void *params, u32 len) {
    return menu_draw_common(surface,params,len,MENU_DRAW);
}
u32 menu_initial_draw_wrapper(void *surface, void *params, u32 len) {
    return menu_draw_common(surface,params,len,MENU_INITIAL);
}
/* Runs in staging AFTER the image copy and resident state initialization,
 * BEFORE cache publication and pointer installation. Do not seed staging
 * pointers into the resident image, including the ON/OFF string pointers. */
/* Immutable resident pointers use link-relative pairs, so initialization stays
 * compact without absolute relocations. Each word is relative to itself. */
extern const int menu_fixups[] __attribute__((visibility("hidden")));
extern const int menu_fixups_end[] __attribute__((visibility("hidden")));
__asm__(".pushsection .rodata.menu_fixups,\"a\"\n.balign 4\n"
        ".global menu_fixups\n.hidden menu_fixups\nmenu_fixups:\n"
        ".long menu_rows+328 - ., menu_label - .\n"
        ".long menu_callbacks+0 - ., menu_draw_wrapper - .\n"
        ".long menu_callbacks+24 - ., menu_initial_draw_wrapper - .\n"
        ".long menu_parent_scene+8 - ., menu_parent_resume_wrapper - .\n"
        ".long menu_submenu_scene+0 - ., menu_submenu_enter - .\n"
        ".long menu_submenu_scene+8 - ., menu_submenu_resume - .\n"
        ".long menu_submenu_scene+16 - ., menu_submenu_leave - .\n"
        ".long menu_submenu_scene+24 - ., menu_submenu_leave - .\n"
        ".long menu_submenu_callbacks+0 - ., menu_submenu_draw_wrapper - .\n"
        ".long menu_submenu_callbacks+8 - ., menu_submenu_background_wrapper - .\n"
        ".long menu_picker_labels+0 - ., menu_picker_off - .\n"
        ".long menu_picker_labels+8 - ., menu_picker_on - .\n"
        ".long menu_submenu_rows+8 - ., menu_option - .\n"
        ".long menu_submenu_rows+40 - ., menu_subject_option - .\n"
        ".long menu_submenu_rows+72 - ., menu_aspect_option - .\n"
        ".long menu_submenu_rows+104 - ., menu_doom_label - .\n"
        ".long menu_submenu_rows+136 - ., menu_version_label - .\n"
        ".long menu_submenu_rows+144 - ., menu_version_value - .\n"
        ".long doom_scene+0 - ., doom_enter - .\n"
        ".long doom_scene+8 - ., doom_resume - .\n"
        ".long doom_scene+16 - ., doom_leave - .\n"
        ".long doom_scene+24 - ., doom_leave - .\n"
        ".long doom_callbacks+0 - ., doom_foreground - .\n"
        ".long doom_callbacks+8 - ., doom_background - .\n"
        ".long menu_submenu_title+8 - ., menu_label - .\n"
        ".long menu_picker+32 - ., menu_picker_disabled - .\n"
        ".long menu_picker_scene+0 - ., menu_picker_enter - .\n"
        ".long menu_picker_scene+8 - ., menu_picker_enter - .\n"
        ".long menu_picker_scene+16 - ., menu_picker_leave - .\n"
        ".long menu_picker_scene+24 - ., menu_picker_leave - .\n"
        ".long menu_picker_callbacks+0 - ., menu_picker_draw_wrapper - .\n"
        ".long menu_picker_callbacks+8 - ., menu_picker_background_wrapper - .\n"
        ".long menu_picker_callbacks+24 - ., menu_picker_initial_draw_wrapper - .\n"
        ".long menu_picker_callbacks+32 - ., menu_picker_initial_background_wrapper - .\n"
        ".global menu_fixups_end\n.hidden menu_fixups_end\nmenu_fixups_end:\n"
        ".popsection\n");

/* Bootstrap has zeroed the resident BSS before this one-time initializer. */
void menu_initialize(uptr base) {
    volatile struct MenuRow *rows=(volatile struct MenuRow *)(uptr)relocate(menu_rows,base);
    volatile struct State *s=(volatile struct State *)(uptr)relocate((const void *)&state,base);
    volatile u8 *dst=(volatile u8 *)rows;
    for (u32 i=0;i<10*sizeof(struct MenuRow);i++) dst[i]=B(MENU_STOCK_ROWS+i);
    rows[10].y=952;
    rows[10].flags=(u8)(2 | (B(MENU_CURRENT)==10));

    rows[10].value_font=4;

    volatile u64 *parent=(volatile u64 *)(uptr)relocate(menu_parent_scene,base);
    parent[0]=0x4d3372ff0ULL;

    parent[2]=0x4d33725f0ULL; parent[3]=0x4d3372610ULL;

    volatile struct MenuRow *option=(volatile struct MenuRow *)(uptr)relocate(menu_submenu_rows,base);
    volatile struct MenuTitle *title=(volatile struct MenuTitle *)(uptr)relocate(&menu_submenu_title,base);
    volatile u64 *labels=(volatile u64 *)(uptr)relocate(menu_picker_labels,base);

    for (u32 i=0;i<5;i++) {
        option[i].y=(u16)(142+90*i); option[i].flags=2; option[i].value_font=6;
    }
    option->flags=3;

    option->value=(const char *)(uptr)relocate(s->mode==1 ? menu_picker_on : menu_picker_off,base);

    volatile struct FocusTarget *target=(volatile struct FocusTarget *)(uptr)relocate((const void *)&focus_target,base);
    option[1].value=(const char *)(uptr)relocate(target->enabled ? menu_picker_on : menu_picker_off,base);

    volatile u32 *extra=(volatile u32 *)(uptr)relocate((const void *)&aspect_extra_enabled,base);
    option[2].value=(const char *)(uptr)relocate(*extra ? menu_picker_on : menu_picker_off,base);
    option[4].flags=0x12;
    volatile u64 *callbacks=(volatile u64 *)(uptr)relocate(menu_callbacks,base);
    callbacks[1]=0x4d3372680ULL; callbacks[4]=0x4d3372f50ULL;

    title->y=52;  title->back=1;

    volatile struct MenuPicker *picker=(volatile struct MenuPicker *)(uptr)relocate(&menu_picker,base);
    picker->y=142; picker->count=2; picker->visible_count=2;
    picker->selected=picker->committed=(u8)(s->mode==1); picker->previous=255;
    picker->labels=(const char *const *)labels;

    for (const int *at=menu_fixups;at<menu_fixups_end;at+=2) {
        Q(relocate((const u8 *)at+at[0],base))=
            relocate((const u8 *)(at+1)+at[1],base);
    }

}

#endif
