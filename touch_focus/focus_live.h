/* Session-calibrated, center-target focus guide. All mutation belongs to one
 * UI task. The display worker paints a copied view, never this mutable core. */
#ifndef BF_FOCUS_LIVE_H
#define BF_FOCUS_LIVE_H
#include "focus_capture.h"
#include "focus_guide.h"
#include "focus_phase.h"

#define FOCUS_LIVE_CALIBRATION_SAMPLES 8u
enum FocusLiveCalibration {
    FL_UNCALIBRATED, FL_CALIBRATION_PENDING, FL_CALIBRATING,
    FL_CALIBRATED, FL_CALIBRATION_FAILED
};
struct FocusLivePolicy {
    struct FocusPhaseConfig match;
    uint16_t reserved;
    /* Tolerances are relative to a user-focused reference, in PAS Q8 pixels.
     * They are not lens distance, ring angle, or a depth-of-field certificate.
     * The caller supplies an explicit policy; zero defaults are unusable. */
    uint32_t enter_q8, leave_q8, large_q8;
    uint32_t max_age_ms, confirmation_frames;
    uint32_t calibration_span_q8, calibration_zero_limit_q8;
    uint32_t calibration_spacing_ms, calibration_timeout_ms;
    /* Both fixed horizontal halves must be qualified and agree after their
     * own calibrated zeros are removed. Disagreement is a veto, not a fallback. */
    uint32_t spatial_disagreement_q8;
};
struct FocusLiveView {
    struct FocusGuide guide;
    struct FocusCaptureIdentity identity;
};
struct FocusLive {
    struct FocusGuide *guide;
    struct FocusLivePolicy policy;
    uint32_t enabled, supported, have_identity, calibration, calibration_count;
    uint32_t calibration_epoch, last_request_generation;
    int32_t zero_q8;
    int32_t tile_zero_q8[2];
    struct FocusCaptureIdentity identity;
    uint64_t request_after_ticks, last_sequence, last_acquired_ticks, last_source_epoch;
    uint64_t calibration_start_ticks, calibration_last_ticks;
    int32_t calibration_samples[FOCUS_LIVE_CALIBRATION_SAMPLES][3];
    struct FocusPhaseResult last_match;
    struct FocusPhaseResult last_tiles[2];
    int32_t last_tile_residual_q8[2];
    uint32_t last_spatial_rejection, reserved_match;
    uint64_t last_match_ticks;
    uint32_t last_capture_reason, last_software_checks_passed;
    /* Diagnostic truth remains separate from UI quality/calibration. */
    uint32_t hardware_coherence_unproven, reserved;
    volatile uint32_t view_seq, render_allowed;
    struct FocusLiveView view;
};

/* Pure memory initialization, suitable for relocated resident storage. */
void focus_live_init(struct FocusLive *live,struct FocusGuide *guide,
                     const struct FocusLivePolicy *policy,int enabled);
void focus_live_set_enabled(struct FocusLive *live,int enabled);
/* User action: focus precisely with magnification, return to full view, then
 * request calibration. The next supported full view collects fresh frames. */
void focus_live_calibrate(struct FocusLive *live);
/* UI owner supplies whether its current layout/scene is supported. Returns
 * true when a stock full foreground redraw is needed, including expiry/hide.
 * Never call this from inside an OSD rendering callback. */
int focus_live_poll(struct FocusLive *live,int display_allowed);
/* Only after stock FULL foreground painting, on the borrowed canonical
 * surface. The UI owner must erase/hide through its redraw/drain protocol. */
int focus_live_draw(const struct FocusLive *live,void *surface);
/* Inhibit future paints/measurements before native hook removal. The caller
 * still owns stock repaint + callback barriers; retain resident allocation. */
void focus_live_stop(struct FocusLive *live);
#endif
