#include "focus_phase.h"

static uint32_t root(uint64_t value) {
    uint64_t bit=(uint64_t)1<<62, result=0;
    while (bit>value) bit>>=2;
    while (bit) {
        if (value>=result+bit) { value-=result+bit; result=(result>>1)+bit; }
        else result>>=1;
        bit>>=2;
    }
    return (uint32_t)result;
}

struct FocusPhaseResult focus_phase_match(const uint8_t *a, const uint8_t *b,
                                          const struct FocusPhaseConfig *c) {
    struct FocusPhaseResult result={0};
    if (!a || !b || !c || c->width>256 || !c->height || c->height>32 ||
        c->stride<c->width || c->stride>2048 || !c->max_shift || c->max_shift>32 ||
        c->width<2*c->max_shift+16 || !c->min_correlation || c->min_correlation>1000 ||
        !c->min_peak_margin || c->min_peak_margin>1000 ||
        !c->min_texture_rms || c->min_texture_rms>127) return result;
    int limit=c->max_shift, count=c->width-2*limit;
    uint16_t scores[65], texture[65];
    uint32_t best=0, best_index=0, tied=0;
    for (int shift=-limit;shift<=limit;shift++) {
        int64_t cross=0;
        uint64_t aa=0, bb=0;
        for (unsigned y=0;y<c->height;y++) {
            const uint8_t *ar=a+y*c->stride+limit;
            const uint8_t *br=b+y*c->stride+limit+shift;
            uint32_t am=0, bm=0;
            for (int x=0;x<count;x++) { am+=ar[x]; bm+=br[x]; }
            am/=(uint32_t)count; bm/=(uint32_t)count;
            for (int x=0;x<count;x++) {
                int av=(int)ar[x]-(int)am, bv=(int)br[x]-(int)bm;
                cross+=(int64_t)av*bv;
                aa+=(uint32_t)(av*av); bb+=(uint32_t)(bv*bv);
            }
        }
        uint32_t n=(uint32_t)count*c->height;
        uint32_t contrast=root((aa<bb?aa:bb)/n);
        unsigned index=(unsigned)(shift+limit);
        scores[index]=0;
        texture[index]=(uint16_t)contrast;
        if (contrast<c->min_texture_rms || cross<=0) continue;
        /* At most 8192 8-bit products: aa*bb fits in uint64_t. Using row
         * means rejects unrelated DC offsets without floating point/libm. */
        uint32_t divisor=root(aa*bb);
        if (!divisor) continue;
        uint32_t score=(uint32_t)((uint64_t)cross*1000/divisor);
        if (score>1000) score=1000;
        scores[index]=(uint16_t)score;
        if (score>best) { best=score; best_index=index; tied=0; }
        else if (score==best) tied=1;
    }
    result.correlation=best;
    result.texture_rms=texture[best_index];
    /* A boundary peak could lie beyond the search range. Flat/tied peaks
     * cannot provide a unique displacement, even with high correlation. */
    if (tied || !best_index || best_index==(unsigned)(2*limit) || best<c->min_correlation)
        return result;
    uint32_t runner=0;
    for (unsigned i=0;i<=(unsigned)(2*limit);i++) {
        if (i+1>=best_index && i<=best_index+1) continue;
        if (scores[i]>runner) runner=scores[i];
    }
    result.peak_margin=best-runner;
    if (result.peak_margin<c->min_peak_margin) return result;
    int left=scores[best_index-1], right=scores[best_index+1];
    int curvature=2*(int)best-left-right;
    if (curvature<=0) return result;
    int fraction=(right-left)*128/curvature;
    if (fraction>128) fraction=128;
    if (fraction< -128) fraction= -128;
    result.displacement_q8=((int)best_index-limit)*256+fraction;
    result.valid=1;
    return result;
}
