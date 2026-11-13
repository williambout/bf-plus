#include "focus_live.h"
#include "focus_guide_render.h"

#define TICKS_PER_MS UINT64_C(24000)
static uint32_t milliseconds(uint64_t ticks) { return (uint32_t)(ticks/TICKS_PER_MS); }
static void zero(void *out,unsigned n) {
    volatile uint8_t *p=out; for (unsigned i=0;i<n;i++) p[i]=0;
}
static void copy(volatile void *out,const volatile void *in,unsigned n) {
    volatile uint8_t *d=out; const volatile uint8_t *s=in;
    for (unsigned i=0;i<n;i++) d[i]=s[i];
}
static uint32_t magnitude(int32_t x) { return x<0 ? 0u-(uint32_t)x : (uint32_t)x; }
/* Taking an external callback's address can require a GOT in the tiny PIE
 * model. This local thunk keeps the resident image self-relocating. */
static void paint_native(void *surface,const struct FocusGuideMark *mark) {
    focus_guide_native_mark(surface,mark);
}
static int policy_valid(const struct FocusLivePolicy *p) {
    return p->match.width==FOCUS_CAPTURE_WIDTH && p->match.height==FOCUS_CAPTURE_HEIGHT &&
        p->match.stride==FOCUS_CAPTURE_WIDTH && p->match.max_shift==32 &&
        p->match.min_correlation && p->match.min_correlation<=1000 &&
        p->match.min_peak_margin && p->match.min_peak_margin<=1000 &&
        p->match.min_texture_rms && p->match.min_texture_rms<=127 &&
        p->enter_q8 && p->enter_q8<p->leave_q8 && p->leave_q8<p->large_q8 &&
        p->large_q8<=INT32_MAX && p->max_age_ms && p->max_age_ms<=250 &&
        p->confirmation_frames>=2 && p->confirmation_frames<=16 &&
        p->calibration_span_q8 && p->calibration_span_q8<=p->enter_q8 &&
        p->calibration_zero_limit_q8 && p->calibration_zero_limit_q8<=p->match.max_shift*128u &&
        p->calibration_spacing_ms>=30 && p->calibration_spacing_ms<=250 &&
        p->calibration_timeout_ms>=p->calibration_spacing_ms*FOCUS_LIVE_CALIBRATION_SAMPLES &&
        p->calibration_timeout_ms<=10000 &&
        p->spatial_disagreement_q8 && p->spatial_disagreement_q8<=256;
}
static void publish(struct FocusLive *l) {
    l->view_seq++;
    __atomic_thread_fence(__ATOMIC_RELEASE);
    copy(&l->view.guide,l->guide,sizeof(l->view.guide));
    copy(&l->view.identity,&l->identity,sizeof(l->identity));
    __atomic_thread_fence(__ATOMIC_RELEASE);
    l->view_seq++;
}
static void request(struct FocusLive *l,uint64_t now) {
    struct FocusGuide *g=l->guide;
    if (g->generation!=l->last_request_generation || !l->request_after_ticks) {
        l->last_request_generation=g->generation;
        l->request_after_ticks=now;
        l->last_sequence=l->last_acquired_ticks=l->last_source_epoch=0;
    }
    struct FocusCaptureRequest r={
        .enabled=l->enabled && l->supported && policy_valid(&l->policy),
        .epoch=g->generation,.after_ticks=l->request_after_ticks,.identity=l->identity
    };
    focus_capture_request(&r);
}
static void uncalibrate(struct FocusLive *l,uint32_t state) {
    l->calibration=state; l->calibration_count=0;
    l->calibration_start_ticks=l->calibration_last_ticks=0;
    l->zero_q8=0;
    l->tile_zero_q8[0]=l->tile_zero_q8[1]=0;
    focus_guide_configure(l->guide,0);
}
void focus_live_init(struct FocusLive *l,struct FocusGuide *g,
                     const struct FocusLivePolicy *policy,int enabled) {
    zero(l,sizeof(*l)); l->guide=g;
    /* Keep this standalone module independent of an out-of-line libc copy
     * that aggregate assignment may introduce under the size optimizer. */
    if (policy) copy(&l->policy,policy,sizeof(l->policy));
    l->enabled=!!enabled;
    l->hardware_coherence_unproven=1;
    focus_guide_init(g);
    focus_guide_mode(g,l->enabled,0,0);
    publish(l);
}
void focus_live_set_enabled(struct FocusLive *l,int enabled) {
    uint32_t value=!!enabled;
    if (l->enabled==value) return;
    l->enabled=value;
    l->supported=0;
    __atomic_store_n(&l->render_allowed,0,__ATOMIC_RELEASE);
    focus_sensor_enable_tables(value);
    focus_guide_mode(l->guide,value,0,0);
    if (!value && (l->calibration==FL_CALIBRATING || l->calibration==FL_CALIBRATION_PENDING))
        uncalibrate(l,FL_UNCALIBRATED);
    request(l,focus_sensor_ticks()); publish(l);
}
void focus_live_calibrate(struct FocusLive *l) {
    if (!l->enabled || !policy_valid(&l->policy)) return;
    uncalibrate(l,FL_CALIBRATION_PENDING);
    request(l,focus_sensor_ticks()); publish(l);
}
static void calibration_sample(struct FocusLive *l,uint64_t stamp,uint64_t now) {
    int32_t shifts[3]={l->last_match.displacement_q8,
        l->last_tiles[0].displacement_q8,l->last_tiles[1].displacement_q8};
    for (unsigned j=0;j<3;j++) if (magnitude(shifts[j])>l->policy.calibration_zero_limit_q8) {
        l->calibration=FL_CALIBRATION_FAILED; l->calibration_count=0; return;
    }
    if (l->calibration_last_ticks &&
        stamp-l->calibration_last_ticks>l->policy.max_age_ms*TICKS_PER_MS) {
        l->calibration_count=0; l->calibration_last_ticks=0;
    }
    if (l->calibration_last_ticks &&
        stamp-l->calibration_last_ticks < l->policy.calibration_spacing_ms*TICKS_PER_MS) return;
    l->calibration_last_ticks=stamp;
    for (unsigned j=0;j<3;j++) l->calibration_samples[l->calibration_count][j]=shifts[j];
    l->calibration_count++;
    if (l->calibration_count!=FOCUS_LIVE_CALIBRATION_SAMPLES) return;
    /* Eight bounded values; median resists one-sided sample noise. A total
     * spread gate prevents fitting a zero while focus or the subject moves. */
    int32_t zeros[3];
    for (unsigned tile=0;tile<3;tile++) {
        int32_t sorted[FOCUS_LIVE_CALIBRATION_SAMPLES];
        for (unsigned i=0;i<FOCUS_LIVE_CALIBRATION_SAMPLES;i++) {
            int32_t x=l->calibration_samples[i][tile]; unsigned j=i;
            while (j && sorted[j-1]>x) { sorted[j]=sorted[j-1]; j--; }
            sorted[j]=x;
        }
        if ((uint32_t)((int64_t)sorted[7]-sorted[0])>l->policy.calibration_span_q8) {
            l->calibration=FL_CALIBRATION_FAILED; return;
        }
        /* Signed ties round toward zero, matching the C division rule. */
        zeros[tile]=(int32_t)(((int64_t)sorted[3]+sorted[4])/2);
    }
    l->zero_q8=zeros[0]; l->tile_zero_q8[0]=zeros[1]; l->tile_zero_q8[1]=zeros[2];
    l->calibration=FL_CALIBRATED;
    struct FocusGuideConfig c={
        l->policy.enter_q8,l->policy.leave_q8,l->policy.large_q8,
        l->policy.max_age_ms,l->policy.match.min_correlation,l->policy.confirmation_frames
    };
    focus_guide_configure(l->guide,&c);
    /* Calibration frames do not confirm themselves. Flush the acquisition
     * epoch and demand new measurements after the zero was established. */
    request(l,now);
}
static void invalid(struct FocusLive *l,const struct FocusCaptureFrame *f,uint64_t now) {
    struct FocusGuideSample s={.valid=0,.captured_ms=milliseconds(f->acquired_ticks),
        .sequence=(uint32_t)f->sequence,.generation=l->guide->generation};
    focus_guide_update(l->guide,&s,milliseconds(now));
    if (l->calibration==FL_CALIBRATING) {
        l->calibration_count=0; l->calibration_last_ticks=0;
    }
}
static void calibration_deadline(struct FocusLive *l,uint64_t now) {
    if (l->calibration==FL_CALIBRATING &&
        (now<l->calibration_start_ticks ||
         now-l->calibration_start_ticks>l->policy.calibration_timeout_ms*TICKS_PER_MS)) {
        l->calibration=FL_CALIBRATION_FAILED; l->calibration_count=0;
    }
}
int focus_live_poll(struct FocusLive *l,int display_allowed) {
    uint64_t now=focus_sensor_ticks();
    struct FocusGuide *g=l->guide;
    enum FocusGuideState old_state=g->state;
    uint32_t old_calibration=l->calibration, old_generation=g->generation;
    struct FocusCaptureIdentity identity;
    uint32_t supported=!!display_allowed && focus_sensor_context(&identity);
    focus_sensor_enable_tables(l->enabled);
    if (supported) {
        if (l->have_identity && !focus_capture_same_identity(&identity,&l->identity)) {
            /* A changed/deleted profile cannot inherit another lens's zero. */
            uncalibrate(l,FL_UNCALIBRATED);
        }
        l->identity=identity; l->have_identity=1;
    }
    l->supported=supported;
    focus_guide_mode(g,l->enabled,supported,!supported);
    if (!supported && l->calibration==FL_CALIBRATING)
        uncalibrate(l,FL_CALIBRATION_PENDING);
    if (l->enabled && supported && l->calibration==FL_CALIBRATION_PENDING && policy_valid(&l->policy)) {
        l->calibration=FL_CALIBRATING; l->calibration_count=0;
        l->calibration_start_ticks=now; l->calibration_last_ticks=0;
        /* Entering full view changed the core generation above. Explicit
         * calibration from full view changes it in focus_live_calibrate. */
        l->calibration_epoch=g->generation;
    }
    request(l,now);
    __atomic_store_n(&l->render_allowed,l->enabled && supported,__ATOMIC_RELEASE);
    /* Enforce the deadline before a final good frame could finish an expired
     * calibration. A UI stall is not a fresh uninterrupted reference run. */
    calibration_deadline(l,now);
    const struct FocusCaptureFrame *f=focus_capture_acquire();
    int changed=f!=0;
    if (f) {
        l->last_capture_reason=f->reason;
        l->last_software_checks_passed=f->software_checks_passed;
        if (f->epoch==g->generation && f->software_checks_passed==1 && f->source_epoch &&
            l->last_source_epoch && f->source_epoch!=l->last_source_epoch) {
            /* A receiver discontinuity breaks confirmation even if a short
             * stop/restart occurred between UI polls. Flush before accepting
             * another frame; keep a same-profile session zero. */
            if (l->calibration==FL_CALIBRATING) uncalibrate(l,FL_CALIBRATION_PENDING);
            else focus_guide_configure(g,&g->config);
            request(l,now);
        }
        int eligible=l->enabled && supported && policy_valid(&l->policy) &&
            f->software_checks_passed==1 && !f->reason &&
            f->hardware_coherence_unproven==1 &&
            f->lifecycle_continuity_unproven==1 && f->source_epoch &&
            f->program_sequence && f->consume_sequence &&
            f->guard_before==FOCUS_CAPTURE_GUARD && f->guard_after==FOCUS_CAPTURE_GUARD &&
            f->epoch==g->generation && focus_capture_same_identity(&f->identity,&l->identity) &&
            f->sequence>l->last_sequence && f->acquired_ticks>l->last_acquired_ticks &&
            f->acquired_ticks>=l->request_after_ticks && now>=f->acquired_ticks &&
            now-f->acquired_ticks<=l->policy.max_age_ms*TICKS_PER_MS;
        /* Remember every consumed publication within this epoch, including
         * bad frames. A later duplicate cannot become a fresh confirmation. */
        if (f->epoch==g->generation) {
            if (f->sequence>l->last_sequence) l->last_sequence=f->sequence;
            if (f->acquired_ticks>l->last_acquired_ticks) l->last_acquired_ticks=f->acquired_ticks;
        }
        zero(&l->last_match,sizeof(l->last_match));
        zero(l->last_tiles,sizeof(l->last_tiles));
        zero(l->last_tile_residual_q8,sizeof(l->last_tile_residual_q8));
        l->last_spatial_rejection=0;
        uint64_t match_start=now;
        if (eligible) l->last_source_epoch=f->source_epoch;
        if (eligible) {
            l->last_match=focus_phase_match(f->pixels[0],f->pixels[1],&l->policy.match);
            /* Fixed primary A support[32,96) is partitioned into[32,64) and
             * [64,96), with the same24 rows and +/-32 search. Each96-wide
             * outer tile retains both search margins and the original stride.
             * Never move/select tiles to rescue a failed primary match. */
            struct FocusPhaseConfig tile=l->policy.match; tile.width=96;
            for (unsigned j=0;j<2;j++) {
                l->last_tiles[j]=focus_phase_match(f->pixels[0]+j*32,f->pixels[1]+j*32,&tile);
                if (!l->last_tiles[j].valid) l->last_spatial_rejection|=1u<<j;
                else if (l->calibration==FL_CALIBRATED) {
                    int64_t residual=(int64_t)l->last_tiles[j].displacement_q8-l->tile_zero_q8[j];
                    int64_t primary=(int64_t)l->last_match.displacement_q8-l->zero_q8;
                    l->last_tile_residual_q8[j]=(int32_t)residual;
                    int64_t difference=residual-primary;
                    if (difference<0) difference=-difference;
                    if ((uint64_t)difference>l->policy.spatial_disagreement_q8)
                        l->last_spatial_rejection|=4u<<j;
                }
            }
        }
        now=focus_sensor_ticks();
        l->last_match_ticks=now>=match_start ? now-match_start : UINT64_MAX;
        /* Matching time does not refresh capture age. Recheck scene/profile
         * after computation before publishing a new indication. */
        if (now<match_start || now<f->acquired_ticks ||
            now-f->acquired_ticks>l->policy.max_age_ms*TICKS_PER_MS ||
            !focus_sensor_context(&identity) || !focus_capture_same_identity(&identity,&l->identity))
            eligible=0;
        calibration_deadline(l,now);
        if (!eligible || l->last_match.valid!=1 || l->last_spatial_rejection) invalid(l,f,now);
        else if (l->calibration==FL_CALIBRATING && l->calibration_epoch==g->generation) {
            calibration_sample(l,f->acquired_ticks,now);
        } else if (l->calibration==FL_CALIBRATED) {
            /* Observed on hardware: near < focused < far in A/B shift.
             * Negate the residual to mean "adjust toward infinity". */
            int64_t error=(int64_t)l->zero_q8-l->last_match.displacement_q8;
            struct FocusGuideSample sample={
                .defocus=(int32_t)error,
                .confidence=l->last_match.correlation,.valid=1,
                .captured_ms=milliseconds(f->acquired_ticks),
                .sequence=(uint32_t)f->sequence,.generation=f->epoch
            };
            if (error<INT32_MIN || error>INT32_MAX) sample.valid=0;
            focus_guide_update(g,&sample,milliseconds(now));
        }
        focus_capture_release(f);
    }
    focus_guide_update(g,0,milliseconds(now));
    publish(l);
    return changed || g->state!=old_state || l->calibration!=old_calibration || g->generation!=old_generation;
}
int focus_live_draw(const struct FocusLive *l,void *surface) {
    if (!__atomic_load_n(&l->render_allowed,__ATOMIC_ACQUIRE)) return 0;
    uint32_t seq=__atomic_load_n(&l->view_seq,__ATOMIC_ACQUIRE);
    if (seq&1) return 0;
    struct FocusLiveView view;
    copy(&view,&l->view,sizeof(view));
    __atomic_thread_fence(__ATOMIC_ACQUIRE);
    if (seq!=l->view_seq || !__atomic_load_n(&l->render_allowed,__ATOMIC_ACQUIRE)) return 0;
    struct FocusCaptureIdentity identity;
    if (!focus_sensor_context(&identity) || !focus_capture_same_identity(&identity,&view.identity)) return 0;
    focus_guide_paint(&view.guide,milliseconds(focus_sensor_ticks()),paint_native,surface);
    return view.guide.state!=FG_HIDDEN;
}
void focus_live_stop(struct FocusLive *l) {
    __atomic_store_n(&l->render_allowed,0,__ATOMIC_RELEASE);
    l->enabled=0; l->supported=0;
    focus_guide_mode(l->guide,0,0,0);
    focus_capture_shutdown();
    publish(l);
}
