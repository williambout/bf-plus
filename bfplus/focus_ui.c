#include "focus_ui.h"

static uint64_t token(uint32_t epoch) { return (UINT64_C(1)<<32)|epoch; }
static int scene(struct FocusUi *u,struct FocusUiScene *out) {
    return u && u->live && u->services.scene && u->services.submit &&
        u->services.scene(u->services.context,out)==1;
}
static int same_underlay(const struct FocusUi *u,const struct FocusUiScene *s) {
    return s->normal_still==1 && s->foreground==FOCUS_UI_FULL_FOREGROUND &&
        s->displayed_orientation==0 && s->epoch==u->owned_epoch;
}
static int eligible(const struct FocusUiScene *s) {
    return s->normal_still==1 && s->foreground==FOCUS_UI_FULL_FOREGROUND &&
        !s->camera_orientation && !s->displayed_orientation &&
        !s->transition_pending && s->presentable==1 && !s->removing;
}
static void inhibit(struct FocusUi *u) {
    __atomic_store_n(&u->paint_token,0,__ATOMIC_RELEASE);
    if (!u->stopping) focus_live_poll(u->live,0);
}
static int receipt(const struct FocusUi *u,uint32_t before) {
    uint32_t sequence=__atomic_load_n(&u->stock_sequence,__ATOMIC_ACQUIRE);
    return sequence!=before &&
        __atomic_load_n(&u->stock_epoch,__ATOMIC_RELAXED)==u->owned_epoch;
}
/* A single full callback clears the entire canonical foreground. The second
 * submission cannot be dequeued until the first job's dirty-bank copy ends.
 * Native completion alone precedes that copy and is insufficient for leave. */
static int retire(struct FocusUi *u) {
    inhibit(u);
    if (!u->owns_pixels) return 1;
    struct FocusUiScene before,after;
    if (!scene(u,&before) || !same_underlay(u,&before)) {
        u->last_result=FOCUS_UI_LOST_SCENE;
        return 0;
    }
    uint32_t sequence=__atomic_load_n(&u->stock_sequence,__ATOMIC_ACQUIRE);
    if (u->services.submit(u->services.context,FOCUS_UI_REDRAW)!=1 || !receipt(u,sequence)) {
        u->last_result=FOCUS_UI_RETRY;
        return 0;
    }
    /* Inhibition stays in force across both jobs. No late queued focus draw
     * can add pixels between the clearing callback and this barrier. */
    if (u->services.submit(u->services.context,FOCUS_UI_BARRIER)!=1) {
        u->last_result=FOCUS_UI_RETRY;
        return 0;
    }
    if (!scene(u,&after) || !same_underlay(u,&after)) {
        u->last_result=FOCUS_UI_LOST_SCENE;
        return 0;
    }
    if (after.presentable!=1 || !receipt(u,sequence)) {
        u->last_result=FOCUS_UI_RETRY;
        return 0;
    }
    u->owns_pixels=0;
    return 1;
}
void focus_ui_init(struct FocusUi *u,struct FocusLive *live,
                   const struct FocusUiServices *services) {
    volatile uint8_t *p=(volatile uint8_t *)u;
    for (unsigned i=0;i<sizeof(*u);i++) p[i]=0;
    u->live=live;
    if (services) u->services=*services;
}
int focus_ui_quiesce(struct FocusUi *u) {
    if (!u || !u->live) return 0;
    if (!retire(u)) return 0;
    u->last_result=u->stopped ? FOCUS_UI_STOPPED : FOCUS_UI_IDLE;
    return 1;
}
enum FocusUiResult focus_ui_poll(struct FocusUi *u,int display_allowed) {
    if (!u || !u->live) return FOCUS_UI_RETRY;
    if (u->stopping) {
        if (!focus_ui_stop(u)) return (enum FocusUiResult)u->last_result;
        return FOCUS_UI_STOPPED;
    }
    struct FocusUiScene s;
    int have_scene=scene(u,&s);
    if (have_scene && s.removing) {
        if (!focus_ui_stop(u)) return (enum FocusUiResult)u->last_result;
        return FOCUS_UI_STOPPED;
    }
    if (!have_scene || !display_allowed || !eligible(&s) || !u->live->enabled) {
        if (!retire(u)) return (enum FocusUiResult)u->last_result;
        u->last_result=FOCUS_UI_IDLE;
        return FOCUS_UI_IDLE;
    }
    if (u->owns_pixels && !same_underlay(u,&s)) {
        /* A missed pre-transition drain cannot be repaired by repainting the
         * old still screen over a new owner. Require caller recovery. */
        inhibit(u); u->last_result=FOCUS_UI_LOST_SCENE;
        return FOCUS_UI_LOST_SCENE;
    }
    int changed=focus_live_poll(u->live,1);
    if (!u->owns_pixels) {
        u->owns_pixels=1; u->owned_epoch=s.epoch;
        changed=1;
    }
    __atomic_store_n(&u->paint_token,token(s.epoch),__ATOMIC_RELEASE);
    if (!changed && !u->redraw_pending) {
        u->last_result=FOCUS_UI_IDLE;
        return FOCUS_UI_IDLE;
    }
    u->redraw_pending=1;
    uint32_t sequence=__atomic_load_n(&u->stock_sequence,__ATOMIC_ACQUIRE);
    int submitted=u->services.submit(u->services.context,FOCUS_UI_REDRAW)==1;
    struct FocusUiScene after;
    if (!submitted || !receipt(u,sequence) || !scene(u,&after) ||
        !same_underlay(u,&after) || !eligible(&after)) {
        inhibit(u);
        u->last_result=FOCUS_UI_RETRY;
        return FOCUS_UI_RETRY;
    }
    u->redraw_pending=0;
    u->last_result=FOCUS_UI_UPDATED;
    return FOCUS_UI_UPDATED;
}
void focus_ui_set_enabled(struct FocusUi *u,int enabled) {
    if (!u || !u->live || u->stopping) return;
    /* Inhibit before changing the runtime; OFF still owes underlay erasure. */
    if (!enabled) __atomic_store_n(&u->paint_token,0,__ATOMIC_RELEASE);
    focus_live_set_enabled(u->live,enabled);
    u->redraw_pending=1;
}
void focus_ui_calibrate(struct FocusUi *u) {
    if (!u || !u->live || u->stopping) return;
    focus_live_calibrate(u->live);
    u->redraw_pending=1;
}
int focus_ui_after_stock(struct FocusUi *u,const struct FocusUiScene *job,void *surface) {
    if (!u || !u->live || !job || job->foreground!=FOCUS_UI_FULL_FOREGROUND ||
        job->normal_still!=1 || job->displayed_orientation) return 0;
    int painted=0;
    if (eligible(job) && __atomic_load_n(&u->paint_token,__ATOMIC_ACQUIRE)==token(job->epoch))
        painted=focus_live_draw(u->live,surface);
    __atomic_store_n(&u->stock_epoch,job->epoch,__ATOMIC_RELAXED);
    __atomic_add_fetch(&u->stock_sequence,1,__ATOMIC_RELEASE);
    return painted;
}
int focus_ui_stop(struct FocusUi *u) {
    if (!u || !u->live) return 0;
    if (u->stopped) return 1;
    __atomic_store_n(&u->paint_token,0,__ATOMIC_RELEASE);
    if (!u->stopping) {
        u->stopping=1;
        focus_live_stop(u->live);
    }
    if (!retire(u)) return 0;
    u->stopped=1; u->last_result=FOCUS_UI_STOPPED;
    return 1;
}
