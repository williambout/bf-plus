/* Render the actual guide core to SVG with synthetic measurements. No USB. */
#include <stdio.h>
#include "../bfplus/focus_guide.h"

static void paint(void *context, const struct FocusGuideMark *m) {
    (void)context;
    const char *colors[]={"#9299a2","#f2f4f7","#55db88"};
    if (m->shape==FG_RECT) {
        printf("<rect x=\"%d\" y=\"%d\" width=\"%d\" height=\"%d\" fill=\"%s\"/>\n",
               m->x[0],m->y[0],m->x[1]-m->x[0],m->y[1]-m->y[0],colors[m->color]);
    } else {
        printf("<polygon points=\"%d,%d %d,%d %d,%d\" fill=\"%s\"/>\n",
               m->x[0],m->y[0],m->x[1],m->y[1],m->x[2],m->y[2],colors[m->color]);
    }
}

int main(void) {
    const char *labels[]={"Toward infinity","Toward infinity","In focus",
                          "Toward close range","Toward close range","Unavailable"};
    const char *amounts[]={"Large adjustment","Small adjustment","Confirmed",
                           "Small adjustment","Large adjustment","No valid measurement"};
    const int errors[]={100,20,0,-20,-100,0};
    /* Test units only. These are NOT optical calibration for a Sigma lens. */
    const struct FocusGuideConfig config={10,16,80,200,800,3};
    puts("<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"1100\" height=\"264\" viewBox=\"0 0 1100 264\" role=\"img\" aria-labelledby=\"title desc\">");
    puts("<title id=\"title\">BF focus guide: synthetic state preview</title>");
    puts("<desc id=\"desc\">Six states rendered by the C guide. White separated pointers indicate near or far adjustment, green aligned pointers indicate confirmed focus, and gray dots indicate missing information. Camera integration is incomplete.</desc>");
    puts("<rect width=\"1100\" height=\"264\" rx=\"12\" fill=\"#181c21\"/>");
    puts("<g font-family=\"system-ui, sans-serif\" fill=\"#f2f4f7\">");
    puts("<text x=\"22\" y=\"30\" font-size=\"17\">Focus guide</text>");
    puts("<text x=\"22\" y=\"52\" fill=\"#9299a2\" font-size=\"12\">Synthetic measurements · on-camera integration incomplete</text>");
    for (unsigned i=0;i<6;i++) {
        struct FocusGuide guide;
        focus_guide_init(&guide);
        focus_guide_configure(&guide,&config);
        focus_guide_mode(&guide,1,1,0);
        focus_guide_target(&guide,90,100,0);
        for (unsigned sequence=1;sequence<=3;sequence++) {
            struct FocusGuideSample sample={errors[i],900,i!=5,sequence*20,sequence,guide.generation};
            focus_guide_update(&guide,&sample,sequence*20);
        }
        printf("<g transform=\"translate(%u 70)\">\n",10+i*180);
        focus_guide_paint(&guide,60,paint,0);
        printf("<text x=\"90\" y=\"150\" text-anchor=\"middle\" font-size=\"13\">%s</text>\n",labels[i]);
        printf("<text x=\"90\" y=\"169\" text-anchor=\"middle\" font-size=\"11\" fill=\"#9299a2\">%s</text>\n",amounts[i]);
        puts("</g>");
    }
    puts("</g></svg>");
    return 0;
}
