/* BF 1.04 pair-1 receiver adapter. The copied pixels pass bounded software
 * checks; the native IRQ words do not certify hardware frame attribution.
 * UI code must still apply statistical quality, calibration and age gates. */
#ifndef BF_FOCUS_CAPTURE_H
#define BF_FOCUS_CAPTURE_H
#include <stdint.h>

#define FOCUS_CAPTURE_WIDTH 128u
#define FOCUS_CAPTURE_HEIGHT 24u
#define FOCUS_CAPTURE_PIXELS (FOCUS_CAPTURE_WIDTH*FOCUS_CAPTURE_HEIGHT)
#define FOCUS_CAPTURE_GUARD UINT64_C(0xc0dec0de51a7beef)

struct FocusCaptureIdentity {
    uint32_t slot, profile[2]; /* Lens+ identity, not optical calibration. */
};
struct FocusCaptureRequest {
    uint32_t enabled, epoch;
    /* Reject acquisitions that started before this UI request. Never label
     * a cached sensor frame with a newly selected target/calibration. */
    uint64_t after_ticks;
    struct FocusCaptureIdentity identity;
    uint32_t reserved;
};
struct FocusCaptureFrame {
    uint64_t sequence, acquired_ticks, copy_start_ticks, copy_end_ticks;
    uint32_t epoch, software_checks_passed, reason, hardware_coherence_unproven;
    struct FocusCaptureIdentity identity;
    uint32_t wait_results[2], wait_flags[2], lifecycle_continuity_unproven;
    uint64_t guard_before;
    uint8_t pixels[2][FOCUS_CAPTURE_PIXELS];
    uint64_t guard_after;
    uint64_t source_epoch, program_sequence, consume_sequence;
};
enum FocusCaptureRejection {
    FC_TRACK=1, FC_CONFIG=2, FC_IDENTITY=4, FC_WAIT=8, FC_IRQ=16,
    FC_AGE=32, FC_COPY_TIME=64, FC_TORN=128, FC_SCENE=256, FC_REQUEST=512
};
struct FocusCaptureStatus {
    uint32_t version, enabled, published, accepted, rejected, dropped;
    uint32_t last_reason, hardware_coherence_unproven;
    uint64_t last_sequence, last_acquired_ticks, last_copy_ticks;
    uint64_t source_epoch, program_sequence, consume_sequence;
};
extern volatile struct FocusCaptureStatus focus_capture_status;

/* One UI-task writer. The receiver snapshots this before native programming.
 * Disabling prevents new publications; shutdown also invalidates in-flight
 * work. All resident buffers/code remain allocated through hook removal. */
void focus_capture_request(const struct FocusCaptureRequest *request);
void focus_capture_shutdown(void);
/* Table correction is separate from per-frame scene eligibility. Enabling it
 * takes effect only at the next native PAS initialization; disabling/removing
 * hooks likewise needs native reinitialization to reset already loaded tables. */
void focus_sensor_enable_tables(int enabled);

/* One UI-task consumer; a successful acquire owns an immutable slot until
 * release. The producer never writes a held slot and never waits for it.
 * An unclaimed ready frame may be replaced by a newer frame. */
const struct FocusCaptureFrame *focus_capture_acquire(void);
void focus_capture_release(const struct FocusCaptureFrame *frame);

uint64_t focus_sensor_ticks(void); /* native 24 MHz counter */
/* Normal full-view still scene, no electronic contacts, stable Lens+ identity.
 * An unregistered lens is represented by its native slot and zero profile. */
int focus_sensor_context(struct FocusCaptureIdentity *identity);
int focus_capture_same_identity(const struct FocusCaptureIdentity *a,
                                const struct FocusCaptureIdentity *b);
#endif
