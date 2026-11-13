/* Original manual-focus guide. No firmware addresses or vendor code.
 * The adapter must supply calibrated, target-specific defocus measurements.
 * See docs/FOCUS-GUIDE.md before connecting this to camera data. */
#ifndef BF_FOCUS_GUIDE_H
#define BF_FOCUS_GUIDE_H
#include <stdint.h>

enum FocusGuideState {
    FG_HIDDEN, FG_UNAVAILABLE, FG_FAR_LARGE, FG_FAR_SMALL,
    FG_IN_FOCUS, FG_NEAR_SMALL, FG_NEAR_LARGE
};

struct FocusGuideConfig {
    /* All thresholds use the adapter's defocus units, never lens-ring degrees.
     * 0 < focus_enter < focus_leave < large_adjustment. */
    uint32_t focus_enter, focus_leave, large_adjustment;
    uint32_t max_age_ms, min_confidence, confirmation_frames;
};

struct FocusGuideSample {
    /* Positive means adjust TOWARD INFINITY; negative means TOWARD CLOSE RANGE.
     * The adapter must establish this sign, scale, timestamp and validity.
     * Confidence is 0..1000. Zero defocus alone is not a valid measurement. */
    int32_t defocus;
    uint32_t confidence, valid, captured_ms, sequence, generation;
};

struct FocusGuide {
    struct FocusGuideConfig config;
    struct FocusGuideSample last;
    uint32_t enabled, manual_focus, magnified, target_id, generation;
    uint32_t have_sample, confirmed;
    uint16_t x, y;
    enum FocusGuideState state;
};

/* Original geometry in the BF's 1024 x 682 logical display space. A renderer
 * converts these abstract colors to its surface format. It must erase the
 * previous overlay before painting a new frame or hiding this one. */
enum FocusGuideColor { FG_GRAY, FG_WHITE, FG_GREEN };
enum FocusGuideShape { FG_RECT, FG_TRIANGLE };
struct FocusGuideMark {
    enum FocusGuideShape shape;
    enum FocusGuideColor color;
    int16_t x[3], y[3]; /* rect: top-left/bottom-right; triangle: three vertices */
};
typedef void (*FocusGuidePaint)(void *context, const struct FocusGuideMark *mark);

void focus_guide_init(struct FocusGuide *guide);
/* There are deliberately no uncalibrated defaults. Reconfiguration, mode
 * changes and target changes advance generation and discard old samples. */
void focus_guide_configure(struct FocusGuide *guide, const struct FocusGuideConfig *config);
void focus_guide_mode(struct FocusGuide *guide, int enabled, int manual_focus, int magnified);
/* Tap/controller/subject selection all use this entry. A target change clears
 * focus confirmation even if its new position happens to be identical. */
void focus_guide_target(struct FocusGuide *guide, int x, int y, uint32_t target_id);
/* Stamp generation when acquisition starts, NEVER when cached data is read.
 * Sequence and captured_ms must advance on each new sensor measurement.
 * Both may wrap at 32 bits; intervals must be less than 2^31.
 * A NULL sample is a clock tick (retain the last indication until it expires).
 * An invalid sample removes guidance immediately. Use one UI-thread owner. */
void focus_guide_update(struct FocusGuide *guide, const struct FocusGuideSample *sample,
                        uint32_t now_ms);
/* Checks expiry even when the producer stops calling update. */
void focus_guide_paint(struct FocusGuide *guide, uint32_t now_ms,
                       FocusGuidePaint paint, void *context);
#endif
