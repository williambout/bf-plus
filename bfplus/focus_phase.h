/* Original paired-byte-image matcher. A pixel displacement is not calibrated
 * defocus: this module establishes neither optical zero nor near/far sign. */
#ifndef BF_FOCUS_PHASE_H
#define BF_FOCUS_PHASE_H
#include <stdint.h>

struct FocusPhaseConfig {
    uint16_t width, height, stride, max_shift;
    /* Statistical quality gates, all required. Correlation and separation
     * scores are 1..1000. Texture is RMS intensity in 8-bit pixel units. */
    uint16_t min_correlation, min_peak_margin, min_texture_rms;
};
struct FocusPhaseResult {
    int32_t displacement_q8; /* A[x] compared with B[x + displacement/256] */
    uint32_t valid, correlation, peak_margin, texture_rms;
};

/* Input buffers must contain (height-1)*stride + width bytes each, and must
 * belong to the same completed acquisition. This function does not establish
 * ownership/freshness. No default configuration or optical thresholds. */
struct FocusPhaseResult focus_phase_match(const uint8_t *a, const uint8_t *b,
                                          const struct FocusPhaseConfig *config);
#endif
