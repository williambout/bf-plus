/* Focus-owned display lifecycle. The global UI compositor supplies checked
 * queue services; this module never submits from an OSD callback. */
#ifndef BF_FOCUS_UI_H
#define BF_FOCUS_UI_H
#include "focus_live.h"

#define FOCUS_UI_FULL_FOREGROUND UINT64_C(0x4d3394c90)

struct FocusUiScene {
    uint64_t foreground;
    uint32_t epoch;
    /* Current hierarchy, independently of a pending transition request. */
    uint32_t normal_still;
    uint32_t camera_orientation, displayed_orientation;
    uint32_t transition_pending, presentable, removing;
};
enum FocusUiJob { FOCUS_UI_REDRAW, FOCUS_UI_BARRIER };
struct FocusUiServices {
    void *context;
    /* A consistent snapshot of the compositor and current scene. */
    int (*scene)(void *context,struct FocusUiScene *out);
    /* UI task only. REDRAW uses the persistent triple
     * {0x4d3394c90,0,0}; BARRIER uses {0,0,0}, both with NULL data/zero
     * length. Return 1 only for a checked native completion. The foreground
     * callback must call focus_ui_after_stock, including while inhibited.
     * Do not emulate BARRIER with an orientation no-op: its purpose is to
     * wait beyond the preceding job's completion-before-dirty-copy boundary.
     * Descriptors and callbacks remain resident through hook removal. */
    int (*submit)(void *context,enum FocusUiJob job);
};
enum FocusUiResult {
    FOCUS_UI_IDLE, FOCUS_UI_UPDATED, FOCUS_UI_RETRY, FOCUS_UI_LOST_SCENE,
    FOCUS_UI_STOPPED
};
struct FocusUi {
    struct FocusLive *live;
    struct FocusUiServices services;
    /* UI-task fields. Owning an epoch conservatively means a queued worker
     * may have painted, even if no foreground receipt has arrived yet. */
    uint32_t owns_pixels, owned_epoch, redraw_pending, stopping, stopped;
    uint32_t last_result;
    /* UI task publishes this one atomic paint permission. Worker receipts
     * are separate: the worker never changes the live core or UI ownership. */
    volatile uint64_t paint_token;
    volatile uint32_t stock_sequence, stock_epoch;
};

/* Pure memory work. Supply already-relocated live/service/context pointers. */
void focus_ui_init(struct FocusUi *ui,struct FocusLive *live,
                   const struct FocusUiServices *services);
/* UI task only, before the compositor's orientation/no-op polling. A caller
 * that knows its layout is unsupported passes display_allowed=0. A snapshot
 * with removing set enters the terminal stop/drain path in this UI task. */
enum FocusUiResult focus_ui_poll(struct FocusUi *ui,int display_allowed);
/* Call BEFORE changing hierarchy, orientation, callback family or canonical
 * backing. False retains the old scene and keeps paint/acquisition inhibited.
 * Retry on a later UI event, never in an unbounded loop. */
int focus_ui_quiesce(struct FocusUi *ui);
/* OFF/ON/Calibrate menu actions; repaint/erasure occurs on the next UI poll. */
void focus_ui_set_enabled(struct FocusUi *ui,int enabled);
void focus_ui_calibrate(struct FocusUi *ui);
/* Worker only, immediately after the exact full stock foreground callback,
 * before composition/presentation. Pass that job's scene snapshot. Other
 * callbacks and backgrounds do not establish an erasure receipt. */
int focus_ui_after_stock(struct FocusUi *ui,const struct FocusUiScene *job,
                        void *surface);
/* Removal calls this in the UI task and restores hooks only after true.
 * A failed drain remains stopped/inhibited and may be retried. */
int focus_ui_stop(struct FocusUi *ui);
#endif
