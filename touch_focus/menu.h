/* BF 1.04 segment 05: append one owned settings row. See
 * docs/TOUCH-FOCUS-MENU-NOTES.md for the thirteen pointer hooks and evidence.
 * Included by payload.c after Key/Event, State/state and stock(). */
#ifndef BF_TOUCH_MENU_H
#define BF_TOUCH_MENU_H

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
static const char menu_label[]="BF+";
static const char menu_on[]="ON";
static const char menu_off[]="OFF";
static u64 relocate(const void *symbol, uptr base);

/* Byte accesses also accept the unaligned serialized dial/key payloads. */
static u16 menu_read16(const void *p) {
    const volatile u8 *b=p;
    return (u16)(b[0] | ((u16)b[1]<<8));
}
static void menu_write16(uptr p, u16 value) {
    B(p)=(u8)value; B(p+1)=(u8)(value>>8);
}

/* The parent removes outside settings and retains this allocation. A stale
 * queued callback must nevertheless never index row10 in the restored table. */
static void menu_removed_selection(void) {
    u32 current=B(MENU_CURRENT), previous=B(MENU_PREVIOUS);
    u32 scroll=menu_read16((void *)MENU_SCROLL);
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
    menu_rows[10].value=state.mode==1 ? menu_on : menu_off;
}
static void menu_queue(void) {
    ((void (*)(const u64 *,const void *,u32))(uptr)0x4d3322d90ULL)(
        menu_callbacks,0,0);
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
    if (e->key) {
        const u8 *src=(const u8 *)e->key;
        u8 *dst=(u8 *)&key;
        for (u32 i=0;i<sizeof(key);i++) dst[i]=src[i];
    }
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
    u32 consumed=down, redraw=0;
    if (current==9 && advance) {
        B(MENU_PREVIOUS)=9; B(MENU_CURRENT)=10;
        menu_write16(MENU_SCROLL,412);
        menu_write16(MENU_HIGHLIGHT,592);
        ((void (*)(u32))(uptr)0x4d3372a20ULL)(0);
        redraw=1;
    }
    if (current==10 || advance) {
        /* One toggle per bundle, only on a press edge on an already selected
         * BF+ row. Touch/release edges do not toggle; repeats are swallowed. */
        consumed |= (edges | key.repeat) & 5;
        if (current==10 && (edges & 5)) {
            state.mode=state.mode==1 ? 0 : 1;
            redraw=1;
        }
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
    return stock(&rest,MENU_INPUT);
}

static void menu_scrollbar(void *surface) {
    struct { u16 x,y,width,height; } rect={1018,52,6,630};
    typedef void (*RectPainter)(void *,const void *,u32);
    RectPainter paint=(RectPainter)(uptr)0x4d3325ca0ULL;
    paint(surface,&rect,0);
    u32 scroll=menu_read16((void *)MENU_SCROLL);
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
void menu_initialize(uptr base) {
    volatile struct MenuRow *rows=(volatile struct MenuRow *)(uptr)relocate(menu_rows,base);
    volatile u64 *callbacks=(volatile u64 *)(uptr)relocate(menu_callbacks,base);
    volatile struct State *s=(volatile struct State *)(uptr)relocate((const void *)&state,base);
    volatile u8 *dst=(volatile u8 *)rows;
    for (u32 i=0;i<10*sizeof(struct MenuRow);i++) dst[i]=B(MENU_STOCK_ROWS+i);
    for (u32 i=10*sizeof(struct MenuRow);i<11*sizeof(struct MenuRow);i++) dst[i]=0;
    rows[10].y=952;
    rows[10].flags=(u8)(2 | (B(MENU_CURRENT)==10));
    rows[10].label=(const char *)(uptr)relocate(menu_label,base);
    rows[10].value=(const char *)(uptr)relocate(s->mode==1 ? menu_on : menu_off,base);
    rows[10].value_font=4;
    callbacks[0]=relocate((const void *)menu_draw_wrapper,base);
    callbacks[1]=0x4d3372680ULL; callbacks[2]=0;
    callbacks[3]=relocate((const void *)menu_initial_draw_wrapper,base);
    callbacks[4]=0x4d3372f50ULL; callbacks[5]=0;
}

#endif
