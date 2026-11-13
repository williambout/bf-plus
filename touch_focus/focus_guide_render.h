/* BF 1.04 OSD mark painter. Call only within an owned DispOSD callback after
 * the stock full foreground repaint. No scheduling, state ownership or hook
 * installation is implied. The caller must handle hide/drain and generations. */
#ifndef BF_FOCUS_GUIDE_RENDER_H
#define BF_FOCUS_GUIDE_RENDER_H
#include "focus_guide.h"

/* Implements FocusGuidePaint using the borrowed native surface as context.
 * Rectangles use exclusive ends. The core's flat-base triangles use inclusive
 * horizontal spans, including their base and single-pixel tip rows. */
void focus_guide_native_mark(void *surface, const struct FocusGuideMark *mark);
#endif
