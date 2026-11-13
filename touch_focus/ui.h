/* BF 1.04 OSD transactions. The worker owns canonical pixels; UI input
 * consumes geometry published after the native bank-selection boundary. */
#ifndef BF_UI_H
#define BF_UI_H

static struct {
    struct GlobalOrientationPlane plane[2];
    volatile u32 requested, displayed, published_owned, epoch, input_ready;
    u32 frame_raw, frame_owned, frame_ok, last_owned;
    u32 seeded[2];
    uptr last_foreground;
    u64 redraw[3];
    u32 initialized, frame_mask, row_token, row_ok;
    volatile u32 removing;
    uptr painter, row_handler;
    /* Keep the exported lifecycle prefix stable. These fields belong to the
     * display worker, except force_native which is used by the UI-task drain. */
    uptr native_draw[2];
    struct UIImageAnchors anchors;
    u32 prepared, split, capture_plane, consumed;
    u32 blocked, job_ok, lost_anchors;
    volatile u32 force_native;
    u32 frame_epoch, frame_depth, frame_pending, frame_replace;
    uptr retry_switch;
    u32 retry_count;
    struct GlobalOrientationSurface drawing_surface[2];
    u32 private_token, settings_token;
    /* A partial live-view child can reconstruct only a still-live full root.
     * Native hierarchy slots survive pops, so bytes alone are not a lifetime. */
    volatile u32 base_family, switching;
    u32 base_candidate, preserve_base, base_owner, candidate_owner, handoff_base;
    u64 base_slots[8];
    struct UIImageProfileStyle profile_style, profile_staged;
    u32 profile_family, profile_staged_family, rebuilding;
    u32 retain_child, child_clean, child_base, child_owner;
} ui;

static void ui_poll(void);
static u32 ui_transition_pending(void) {
    return W(MENU_PENDING)!=12 || W(0x4d703469cULL)!=12;
}
static u32 ui_base_slots_match(u32 family) {
    static const u32 root[4]={0x338e070,0x338cfe0,0x338cef0,0x338e060};
    static const u32 full[5][4]={
        {0x3398930,0x33988b0,0x3393730,0x33936a0},
        {0x3392c30,0x3392bb0,0x338ebd0,0x338eb40},
        {0x33d16e0,0x33d1640,0x33cd6a0,0x33cd820},
        {0x33d3f60,0x33d3340,0x33d29d0,0x33d3a70},
        {0x33a2680,0x33a2560,0x33a1f90,0x33a2660}
    };
    if (family!=1 && family!=2 && (family<8 || family>10)) return 0;
    u32 index=family>=8 ? family-6 : family-1;
    for (u32 i=0;i<4;i++)
        if (Q(0x4d7301be0ULL+8*i)!=0x4d0000000ULL+root[i] ||
            Q(0x4d7301c00ULL+8*i)!=0x4d0000000ULL+full[index][i]) return 0;
    return 1;
}
static void ui_base_forget(void) {
    __atomic_store_n(&ui.base_family,0,__ATOMIC_RELEASE);
    ui.base_candidate=ui.base_owner=ui.candidate_owner=0;
}
static u32 ui_base_valid(void) {
    u32 family=__atomic_load_n(&ui.base_family,__ATOMIC_ACQUIRE);
    if (!family || (ui.switching && !ui.preserve_base) ||
        W(0x4d7034698ULL)!=1 || W(MENU_DEPTH)<2 || W(MENU_DEPTH)>11 ||
        !ui_base_slots_match(ui.base_owner)) return 0;
    for (u32 i=0;i<8;i++)
        if (ui.base_slots[i]!=Q(0x4d7301be0ULL+8*i)) return 0;
    return family;
}
static u32 ui_inherited_base(u32 owner) {
    if (owner!=9 && owner!=10) return 0;
    if (ui.base_owner==owner && ui_base_valid()) return ui.base_family;
    /* The root dispatcher replaces slot2 during a pop to slot1. A bounded
     * handoff is valid only in that worker, under the SAME root descriptor,
     * after it has copied the exact new partial-scene descriptor. */
    if (!ui.switching || !ui.handoff_base || !ui_base_slots_match(owner)) return 0;
    for (u32 i=0;i<4;i++)
        if (ui.base_slots[i]!=Q(0x4d7301be0ULL+8*i)) return 0;
    return ui.handoff_base;
}
static void ui_base_capture(u32 family) {
    if (!ui_base_slots_match(family)) return;
    u32 base=(family==9 || family==10) ? ui_inherited_base(family) : family;
    if (!base) return;
    /* The native worker copies slot2 before calling its initializer, but
     * publishes depth afterwards. Commit only after that worker returns. */
    if (ui.switching) { ui.base_candidate=base; ui.candidate_owner=family; return; }
    if (ui_transition_pending() || W(0x4d7034698ULL)!=1 ||
        W(MENU_DEPTH)<2 || W(MENU_DEPTH)>11) return;
    for (u32 i=0;i<8;i++) ui.base_slots[i]=Q(0x4d7301be0ULL+8*i);
    ui.base_owner=family;
    __atomic_store_n(&ui.base_family,base,__ATOMIC_RELEASE);
}
static u32 ui_child_descriptor(uptr slot) {
    static const u32 fields[4]={0x33d4b10,0x33d48d0,0x33d4240,0x33d4af0};
    for (u32 i=0;i<4;i++) if (Q(slot+8*i)!=0x4d0000000ULL+fields[i]) return 0;
    return 1;
}
static u32 ui_child_valid(void) {
    return ui.child_clean && ui_base_valid()==ui.child_base &&
           ui.base_owner==ui.child_owner && ui_child_descriptor(0x4d7301c20ULL) &&
           ((ui.switching && ui.retain_child) ||
            (!ui.switching && W(MENU_DEPTH)>=3 && W(MENU_DEPTH)<=11));
}
static u32 ui_owned_scene(uptr callback) {
    if (callback==(uptr)menu_draw_wrapper || callback==(uptr)menu_initial_draw_wrapper) return 1;
    if (callback==(uptr)menu_submenu_draw_wrapper) return 2;
    if (callback==(uptr)menu_picker_draw_wrapper || callback==(uptr)menu_picker_initial_draw_wrapper) return 3;
    return 0;
}
static uptr ui_scene(uptr callback) {
    u32 owned=ui_owned_scene(callback);
    uptr rows=native_touch_rows_handler_for_draw(callback);
    uptr compact=ui_compact_scene(callback);
    uptr private_list=native_touch_private_list_handler_for_draw(callback);
    uptr settings_list=native_touch_settings_list_handler_for_draw(callback);
    u32 family=ui_image_anchors_family_for_draw(callback);
    u32 playback=ui_image_profiles_ui_for_draw(callback,0);
    return owned ? owned : rows ? rows : compact ? compact : private_list ? private_list :
           settings_list ? settings_list : family ? 0x100+family :
           playback ? 0x200+playback : callback;
}
static void ui_cancel(void) {
    ui.input_ready=0;
    ui.epoch++;
    menu_touch.moved |= menu_touch.active;
    menu_touch.active=0;
    native_touch_menu_reset();
    native_touch_rows_reset();
    native_touch_private_list_reset();
    native_touch_settings_list_reset();
}
static u32 ui_noop_foreground(void *s,const void *p,u32 n) { (void)s;(void)p;(void)n; return 0; }
static u32 ui_noop_background(void *s,const void *p,u32 n) { (void)s;(void)p;(void)n; return 0; }
static u32 ui_owned_input_ready(void) {
    return !ui.initialized || (__atomic_load_n(&ui.input_ready,__ATOMIC_ACQUIRE) && !ui.removing);
}
static u32 ui_menu_poll(void) {
    if (!ui.initialized) return 0;
    ui_poll(); return 1;
}
static u32 ui_map_packet(u8 out[20],const void *packet) {
    if (!__atomic_load_n(&ui.input_ready,__ATOMIC_ACQUIRE) || ui.removing || (ui.published_owned && ui.displayed)) {
        for (u32 i=0;i<20;i++) out[i]=((const u8 *)packet)[i];
        for (u32 i=0;i<12;i++) out[i]=255;
        return 0;
    }
    return global_orientation_ui_packet(out,packet,ui.displayed,GLOBAL_ORIENTATION_FIT_TRANSPARENT);
}
static void ui_owned_packet(u8 out[20],const void *packet) {
    if (ui.initialized && !ui.published_owned) { ui_map_packet(out,packet); return; }
    for (u32 i=0;i<20;i++) out[i]=((const u8 *)packet)[i];
}

/* Native painters normally receive persistent worker descriptors. Keep that
 * lifetime while using the compositor's local copy for post-draw validation.
 * Captures observe the exact persistent descriptor handed to the painter. */
static u32 ui_canonical_draw(void *surface,const void *params,u32 len) {
    struct GlobalOrientationSurface *native=&ui.drawing_surface[ui.capture_plane];
    *native=*(struct GlobalOrientationSurface *)surface;
    if (ui.row_handler) ui.row_token=native_touch_rows_begin(ui.row_handler,native,ui.epoch);
    if (!ui.capture_plane) {
        uptr handler=native_touch_private_list_handler_for_draw(ui.painter);
        if (handler) ui.private_token=native_touch_private_list_begin(handler,native,ui.epoch);
        handler=native_touch_settings_list_handler_for_draw(ui.painter);
        if (handler) ui.settings_token=native_touch_settings_list_begin(handler,native,ui.epoch);
    }
    u32 capture=ui.split && ui_image_anchors_begin(&ui.anchors,native,ui.capture_plane,ui.epoch);
    if (ui.split && !capture) { ui.job_ok=0; return 0; }
    if (!ui.rebuilding && ui.capture_plane==1 &&
        ui_image_anchors_family_for_draw(ui.painter)==9)
        ui_image_profiles_style_begin(&ui.profile_staged,ui.painter);
    u32 result=((GlobalOrientationDraw)ui.painter)(native,params,len);
    if (capture) ui_image_anchors_end(&ui.anchors,1);
    *(struct GlobalOrientationSurface *)surface=*native;
    return result;
}
static void ui_frame_begin(void) {
    if (ui.row_token) native_touch_rows_end(ui.row_token,0);
    if (ui.private_token) native_touch_private_list_end(ui.private_token,0);
    if (ui.settings_token) native_touch_settings_list_end(ui.settings_token,0);
    ui.private_token=ui.settings_token=0;
    ui.row_token=ui.row_ok=ui.frame_mask=ui.frame_ok=0;
    ui.frame_raw=ui.displayed; ui.frame_owned=ui.published_owned;
    ui.prepared=ui.split=ui.consumed=0; ui.job_ok=1;
    ui.profile_staged=ui.profile_style;
    ui.profile_staged_family=ui.profile_family;
    ui.frame_epoch=ui.epoch; ui.frame_depth=W(MENU_DEPTH);
    ui.frame_pending=W(MENU_PENDING); ui.frame_replace=W(0x4d703469cULL);
}

static u32 ui_is_noop(uptr fn,u32 bg) {
    return fn==(uptr)(bg ? ui_noop_background : ui_noop_foreground);
}
static void ui_note_foreground(uptr fn) {
    if (!fn || ui_is_noop(fn,0)) return;
    uptr scene=ui_scene(fn);
    if (ui.last_foreground!=scene) { ui_cancel(); ui.last_foreground=scene; }
    ui.last_owned=ui_owned_scene(fn);
}
/* Initial and incremental root callbacks share one canonical scene. A single
 * plane update can retain the other plane's known callback from that family. */
static u32 ui_root_pair(uint64_t out[3]) {
    u32 f=ui_image_anchors_family_for_draw(ui.native_draw[0]);
    if (!f || f!=ui_image_anchors_family_for_draw(ui.native_draw[1])) return 0;
    for (u32 i=0;i<sizeof(ui_anchor_pairs)/sizeof(ui_anchor_pairs[0]);i++)
        if (ui_anchor_pairs[i].family==f) {
            out[0]=ui_anchor_pairs[i].foreground; out[1]=ui_anchor_pairs[i].background;
            out[2]=0; return f;
        }
    return 0;
}
static u32 ui_rebuild_pair(const uint64_t pair[3],u32 split) {
    u32 family=ui_image_anchors_family_for_draw(pair[0]);
    u32 inherited=ui_image_profiles_base_mask(family);
    u32 base=inherited ? ui_inherited_base(family) : 0;
    if (inherited && (!split || !ui_image_profiles_accepts_base(family,base))) return 0;
    if (split) ui_image_anchors_start_rebuild(&ui.anchors);
    ui.split=split;
    u32 length;
    const void *params=ui_image_profiles_rebuild_params(family,&length);
    ui.rebuilding=1;
    for (u32 bg=0;bg<2;bg++) {
        if (!global_orientation_reset(&ui.plane[bg])) { ui.rebuilding=0; return 0; }
        ui.seeded[bg]=1; ui.capture_plane=bg; ui.row_handler=0;
        for (u32 i=0;i<4;i++) {
            struct UIImageProfileStep step={pair[bg],params,length,family};
            if (inherited) {
                if (!ui_image_profiles_rebuild_step(family,base,bg,i,&step)) break;
            } else if (i) break;
            ui.painter=step.fn; ui.anchors.capture_family=step.family;
            menu_capture=1;
            int ok=global_orientation_draw_canonical(&ui.plane[bg],ui_canonical_draw,step.params,step.length,0);
            menu_capture=0; ui.anchors.capture_family=0;
            if (ok!=1 || !ui.job_ok) { ui.rebuilding=0; return 0; }
        }
    }
    ui.rebuilding=0;
    return !split || ui_image_anchors_commit_rebuild(&ui.anchors,ui.epoch,1);
}
static void ui_consumed_initial(const uint64_t pair[3],uptr fg,uptr bg,u32 inherited) {
    if (fg && !ui_is_noop(fg,0) && (!inherited || fg==pair[0])) ui.consumed|=1;
    if (bg && !ui_is_noop(bg,1) && (!inherited || bg==pair[1])) ui.consumed|=2;
}
/* Called after dequeue, before either native callback. Both initial painters
 * run on clean backing before any bank is presented. Never acquire from pixels
 * containing a previously painted image anchor. */
static void ui_prepare_job(uptr fg,uptr bg) {
    ui.prepared=1;
    ui_note_foreground(fg);
    ui.frame_epoch=ui.epoch; ui.frame_depth=W(MENU_DEPTH);
    ui.frame_pending=W(MENU_PENDING); ui.frame_replace=W(0x4d703469cULL);
    if (fg && !ui_is_noop(fg,0)) ui.native_draw[0]=fg;
    if (bg && !ui_is_noop(bg,1)) ui.native_draw[1]=bg;
    uint64_t full[3];
    u32 family=ui_root_pair(full);
    u32 inherited=ui_image_profiles_base_mask(family);
    u32 base=inherited ? ui_inherited_base(family) : 0;
    u32 child=family==11;
    if (!child && !(ui.switching && ui.retain_child && family==ui.child_owner))
        ui.child_clean=0;
    if (!child) {
        ui.profile_staged_family=family;
        if (family!=ui.profile_family) ui.profile_staged=(struct UIImageProfileStyle){0};
    }
    /* A real initial BG job resets its style even when a normalized rebuild
     * consumes that callback, including resuming from the retained child. */
    if (family==9 && bg==0x4d33d3200ULL)
        ui_image_profiles_style_begin(&ui.profile_staged,bg);
    if (fg && !ui_is_noop(fg,0) && !family && !ui.last_owned &&
        !native_touch_rows_handler_for_draw(fg) && !ui_compact_scene(fg) &&
        !native_touch_private_list_handler_for_draw(fg) &&
        !native_touch_settings_list_handler_for_draw(fg)) {
        ui_base_forget(); ui.handoff_base=0;
    }
    u32 raw=ui_is_noop(fg,0) ? ui.requested : ui.displayed;
    u32 had_split=ui.anchors.family!=0;
    if ((!family && (ui_image_anchors_family_for_draw(ui.native_draw[0]) ||
                    ui_image_anchors_family_for_draw(ui.native_draw[1]))) ||
        (!family && (ui_image_anchors_unsplit_draw(ui.native_draw[0]) ||
                     ui_image_anchors_unsplit_draw(ui.native_draw[1])))) ui.blocked=1;
    else if (family || ui.last_owned || native_touch_rows_handler_for_draw(fg) || ui_compact_scene(fg) ||
             native_touch_private_list_handler_for_draw(fg) || native_touch_settings_list_handler_for_draw(fg) ||
             (!ui.lost_anchors && (ui_image_profiles_ui_for_draw(fg,0) ||
                                   ui_image_profiles_ui_for_draw(bg,1) ||
                                   (fg && !ui_is_noop(fg,0)) ||
                                   (bg && !ui_is_noop(bg,1)))))
        ui.blocked=0;
    if (inherited && !ui_image_profiles_accepts_base(family,base)) ui.blocked=1;
    if (child && !ui_child_valid()) ui.blocked=1;
    if (ui.force_native || ui.removing || ui.blocked ||
        (family && ui_transition_pending())) raw=0;
    if (had_split && (!family || (!raw && !inherited && !child && !ui.retain_child))) {
        ui.split=0;
        /* Scene transitions normally drain synchronously before the hierarchy
         * changes. An unexpected callback must never replay an old root over
         * a new scene: require a known full rebuild or native command0. */
        if (!family) ui.lost_anchors=1;
        else {
            if (!ui_rebuild_pair(full,0)) { ui.job_ok=0; ui.lost_anchors=1; }
            else ui.lost_anchors=0;
            if (fg && !ui_is_noop(fg,0)) ui.consumed|=1;
            if (bg && !ui_is_noop(bg,1)) ui.consumed|=2;
        }
        ui_image_anchors_reset(&ui.anchors);
        /* A partial, unclassified overlay inherits image-bearing backing.
         * Hold native geometry until a known scene supersedes it. */
        if (!family) ui.blocked=1;
        raw=0;
    }
    if (family && !inherited && !child && !ui.retain_child && ui.lost_anchors && !raw && ui.job_ok) {
        if (!ui_rebuild_pair(full,0)) ui.job_ok=0;
        else {
            ui.lost_anchors=0;
            if (fg && !ui_is_noop(fg,0)) ui.consumed|=1;
            if (bg && !ui_is_noop(bg,1)) ui.consumed|=2;
        }
    }
    if (family && (raw || inherited || child || ui.retain_child) && !ui.blocked) {
        ui_image_anchors_select(&ui.anchors,full[0],full[1],ui.epoch,
                               !raw && ui.retain_child && !inherited && !child ? 1 : raw);
        ui.anchors.raw=raw;
        ui.anchors.inherited_base=child ? ui.child_base : base;
        ui.anchors.inherited_owner=child ? ui.child_owner : family;
        ui.anchors.style=&ui.profile_staged;
        ui.split=1;
        if (child && ui_child_valid() && ui.plane[0].ready && ui.plane[1].ready) {
            /* This lease came from a clean parent drain. The native child
             * initializer runs exactly once on those retained pixels; there
             * is deliberately no replay of its stateful full-mask painter. */
            ui.anchors.clean=ui.anchors.captured=3;
            ui.anchors.failed=ui.anchors.rebuilding=0;
        }
        if (!ui_image_anchors_ready(&ui.anchors,ui.epoch) ||
            !ui.plane[0].ready || !ui.plane[1].ready) {
            if (child || !ui_rebuild_pair(full,1)) ui.job_ok=0;
            else ui.lost_anchors=0;
            /* The full initial pair already reflects the native root state.
             * Do not execute its incremental painters a second time. */
            ui_consumed_initial(full,fg,bg,inherited);
        }
    }
    ui.frame_raw=raw; ui.frame_owned=ui.last_owned;
    if (ui.lost_anchors) ui.job_ok=0;
    if (!ui.job_ok || raw!=ui.displayed || ui.frame_owned!=ui.published_owned)
        ui.input_ready=0;
}
static void ui_complete(void) {
    /* Finish a fresh capture before retagging orientation. Reorient cannot
     * take the capture gate, and must never invalidate this new scene's rows. */
    if (ui.frame_epoch!=ui.epoch || ui.frame_depth!=W(MENU_DEPTH) ||
        ui.frame_pending!=W(MENU_PENDING) || ui.frame_replace!=W(0x4d703469cULL)) {
        ui.job_ok=0; ui.input_ready=0;
    }
    u32 captured=ui.row_ok && ui.job_ok;
    if (ui.row_token) native_touch_rows_end(ui.row_token,captured);
    if (ui.private_token) native_touch_private_list_end(ui.private_token,captured);
    if (ui.settings_token) native_touch_settings_list_end(ui.settings_token,captured);
    ui.row_token=ui.private_token=ui.settings_token=0;
    if (ui.frame_mask==3 && ui.frame_ok==3 && ui.job_ok &&
        (!ui.split || ui_image_anchors_ready(&ui.anchors,ui.epoch))) {
        u32 raw=ui.frame_raw, owned=ui.frame_owned;
        if (ui.displayed!=raw || ui.published_owned!=owned) {
            ui.input_ready=0;
            ui.epoch++;
            menu_touch.moved |= menu_touch.active;
            menu_touch.active=0;
            native_touch_menu_reset();
            /* Canonical row geometry survives an orientation-only no-op;
             * cancel the gesture and retag its verified targets atomically. */
            native_touch_rows_reorient(ui.epoch);
            native_touch_private_list_reorient(ui.epoch);
            native_touch_settings_list_reorient(ui.epoch);
        }
        menu_orientation.displayed=owned ? raw : 0;
        __asm__ volatile("dmb ish" ::: "memory");
        ui.displayed=raw; ui.published_owned=owned;
        if (ui.split) ui.anchors.epoch=ui.epoch;
        ui.profile_style=ui.profile_staged;
        ui.profile_family=ui.profile_staged_family;
        u32 family=ui_image_anchors_family_for_draw(ui.native_draw[0]);
        if (family && family==ui_image_anchors_family_for_draw(ui.native_draw[1]))
            ui_base_capture(family);
        __atomic_store_n(&ui.input_ready,1,__ATOMIC_RELEASE);
    } else if (!ui.job_ok || ui.frame_ok!=ui.frame_mask || ui.frame_raw!=ui.displayed ||
               ui.frame_owned!=ui.published_owned) ui.input_ready=0;
    ui.row_ok=ui.frame_mask=ui.frame_ok=0;
    ui.prepared=0;
}

static u32 ui_draw(void *surface,const void *params,u32 len,uptr original,u32 background) {
    GlobalOrientationDraw draw=(GlobalOrientationDraw)original;
    if (state.mode==2) return draw(surface,params,len);
    if (!ui.frame_mask && !ui.prepared) ui_frame_begin();
    if (!ui.prepared) ui_prepare_job(background ? 0 : original,background ? original : 0);
    u32 bit=1u<<background;
    ui.frame_mask |= bit; ui.frame_ok &= ~bit;
    struct GlobalOrientationPlane *plane=&ui.plane[background];
    struct GlobalOrientationSurface *physical=surface;
    if (!plane->ready) {
        /* A transformed bank is never a valid source for re-seeding. */
        if (ui.seeded[background] || !global_orientation_seed(plane,physical)) {
            ui.input_ready=0; return draw(surface,params,len);
        }
        ui.seeded[background]=1;
    }
    u32 noop=ui_is_noop(original,background);
    if (!background) {
        ui_note_foreground(original);
        if (ui.frame_raw!=ui.displayed || ui.frame_owned!=ui.published_owned) ui.input_ready=0;
    }
    if (!noop) ui.native_draw[background]=original;
    u32 result=0;
    ui.painter=(ui.consumed&bit) ? (uptr)(background ? ui_noop_background : ui_noop_foreground) : original;
    ui.capture_plane=background;
    ui.row_handler=background || noop ? 0 : native_touch_rows_handler_for_draw(original);
    menu_capture=1;
    int canonical=global_orientation_draw_canonical(plane,ui_canonical_draw,params,len,&result);
    menu_capture=0; ui.row_handler=0;
    if (canonical<=0 || !ui.job_ok || (ui.split && !ui_image_anchors_ready(&ui.anchors,ui.epoch))) {
        ui.input_ready=0; ui.job_ok=0; return result;
    }
    u32 raw=ui.frame_raw, owned=ui.frame_owned;
    int presented=0;
    if (raw && owned && global_orientation_destination(plane,physical)) {
        if (!background) {
            u32 old=menu_orientation.displayed;
            menu_orientation.wanted=raw;
            presented=menu_portrait(surface,owned-1);
            menu_orientation.displayed=old;
            /* Text/surface rejection uses the same fitted native canvas and
             * matching inverse as other menus, retaining the requested angle. */
            if (!presented) { ui.frame_owned=owned=0; ui.input_ready=0; }
        } else if (!(ui.frame_mask&1) || (ui.frame_ok&1)) {
            orientation_background(surface); presented=1;
        }
    }
    if (!presented && ui.split) {
        if (!raw && background && (ui.anchors.family==9 ||
            (ui.anchors.family==11 && ui.anchors.inherited_owner==9)))
            presented=global_orientation_present(plane,physical,0,GLOBAL_ORIENTATION_FIT_TRANSPARENT) &&
                      ui_image_anchors_identity_bg(&ui.anchors,physical,ui.epoch);
        else presented=global_orientation_destination(plane,physical) &&
                global_orientation_clear(physical,background) &&
                ui_image_anchors_paint(&ui.anchors,physical,background,ui.epoch) &&
                global_orientation_present(plane,physical,raw,GLOBAL_ORIENTATION_FIT_OVER);
    } else if (!presented)
        presented=global_orientation_present(plane,physical,raw,GLOBAL_ORIENTATION_FIT_TRANSPARENT);
    if (presented) ui.frame_ok |= bit;
    else ui.input_ready=0;
    if (!background) ui.row_ok=(u32)presented;
    return result;
}

static void ui_poll(void) {
    if (state.mode==2 || ui_transition_pending()) return;
    u32 raw=(ui.removing || ui.force_native || ui.blocked) ? 0 : menu_orientation_current();
    if (ui.lost_anchors) return;
    if (raw==ui.displayed && ui.input_ready) return;
    ui.requested=raw; menu_orientation.wanted=raw;
    ((void (*)(const u64 *,const void *,u32))(uptr)0x4d3322d90ULL)(ui.redraw,0,0);
}

/* Only native UI-icon hit tests are inverse-mapped. Image-space AF, image
 * dragging, playback pan and native original Event packets remain physical. */
static u32 ui_rect_hit(const void *packet,u32 x,u32 y,u32 w,u32 h) {
    u8 mapped[20];
    if (!packet || !ui_map_packet(mapped,packet)) return 0;
    return ((u32 (*)(const void *,u32,u32,u32,u32))(uptr)0x4d33235e0ULL)(mapped,x,y,w,h);
}
static u32 ui_input(struct Event *event,uptr original) {
    if (state.mode!=2 && ntr_family(original)>=0)
        return native_touch_rows_input(event,original,ui.epoch);
    if (state.mode!=2 && original==NPL_INPUT)
        return native_touch_private_list_input(event,original,ui.epoch);
    if (state.mode!=2 && original==NATIVE_TOUCH_SETTINGS_LIST_INPUT)
        return native_touch_settings_list_input(event,original,ui.epoch);
    return stock(event,original);
}

static u32 ui_switch(void *next) {
    if (state.mode!=2) {
        u32 before_base=ui_base_valid();
        ui.retain_child=before_base && W(MENU_DEPTH)==2 && W(MENU_PENDING)==3 &&
                        W(0x4d703469cULL)==12 && ui_child_descriptor(0x4d7301d40ULL) &&
                        ui_image_anchors_family_for_draw(ui.native_draw[0])==ui.base_owner &&
                        ui_image_anchors_family_for_draw(ui.native_draw[1])==ui.base_owner;
        if (ui_transition_pending() && (ui.anchors.family || ui.displayed || ui.lost_anchors || ui.retain_child)) {
            /* The queue call waits for the display completion semaphore.
             * Keep the old hierarchy if that display restoration fails. */
            ui.force_native=1; ui.requested=0;
            ((void (*)(const u64 *,const void *,u32))(uptr)0x4d3322d90ULL)(ui.redraw,0,0);
            ui.force_native=0;
            if (ui.displayed || !ui.input_ready || ui.frame_mask || ui.lost_anchors) {
                ui.input_ready=0; ui.retry_switch=(uptr)next;
                return 0;
            }
        }
        ui.retry_switch=0; ui.retry_count=0;
        u32 target=W(MENU_PENDING);
        u32 base=ui_base_valid();
        ui.child_clean=ui.retain_child && base && ui_image_anchors_ready(&ui.anchors,ui.epoch);
        if (ui.child_clean) { ui.child_base=base; ui.child_owner=ui.base_owner; }
        u32 replacement=W(0x4d703469cULL)==1 && target==12;
        for (u32 i=0;i<4;i++)
            if (Q(0x4d7301d40ULL+8*i)!=ui.base_slots[i]) replacement=0;
        ui.handoff_base=base && ((W(0x4d703469cULL)==12 && target==1) || replacement) ? base : 0;
        ui.preserve_base=base && W(0x4d703469cULL)==12 &&
                         (target==12 || (target>2 && target<12));
        if (!ui.preserve_base) ui_base_forget();
        ui.base_candidate=ui.candidate_owner=0;
        ui.switching=1;
        ui_cancel(); ui.last_foreground=0;
        if (ui_transition_pending()) {
            ui.native_draw[0]=ui.native_draw[1]=0;
            ui.blocked=0;
        }
    }
    u32 result=((u32 (*)(void *))(uptr)0x4d3323ca0ULL)(next);
    if (state.mode!=2) {
        u32 candidate=ui.base_candidate, owner=ui.candidate_owner;
        ui.switching=0; ui.preserve_base=0;
        ui.base_candidate=ui.candidate_owner=0;
        if (ui.base_family && !ui_base_valid()) ui_base_forget();
        if (candidate && !ui_transition_pending() && W(0x4d7034698ULL)==1 &&
            W(MENU_DEPTH)>=2 && W(MENU_DEPTH)<=11 && ui_base_slots_match(owner)) {
            for (u32 i=0;i<8;i++) ui.base_slots[i]=Q(0x4d7301be0ULL+8*i);
            ui.base_owner=owner;
            __atomic_store_n(&ui.base_family,candidate,__ATOMIC_RELEASE);
        }
        ui.handoff_base=0;
        ui.retain_child=0;
        if (ui.child_clean && !ui_child_valid()) ui.child_clean=0;
    }
    return result;
}

static u32 ui_anchor_call(uptr target,void *surface,const void *arg1,u32 arg2,u32 arg3) {
    u32 result, family=ui.anchors.capture_family ? ui.anchors.capture_family : ui.anchors.family;
    u32 canonical=state.mode!=2 && surface==&ui.drawing_surface[ui.capture_plane];
    u32 alpha=target==0x4d332a8c0ULL || target==0x4d332aba0ULL;
    if (canonical && ui.capture_plane==1 && !ui.rebuilding &&
        ui_image_anchors_family_for_draw(ui.painter)==9) {
        if (alpha && !ui_image_profiles_capture_alpha(&ui.profile_staged,target,arg1,arg2,arg3))
            ui.job_ok=0;
        if (target==0x4d3368760ULL)
            ui_image_profiles_style_level(&ui.profile_staged,arg2);
    }
    if (canonical && ui.anchors.capturing && !ui.anchors.failed &&
        surface==ui.anchors.canonical &&
        ui_image_profiles_defer_alpha(family,target,surface,arg1,arg2,arg3,&result)) return result;
    if (state.mode!=2 && ui_image_anchors_defer(&ui.anchors,target,surface,arg1,arg2,&result))
        return result;
    if (canonical && alpha && ui_image_anchors_family_for_draw(ui.painter)==9)
        return ui_image_profiles_alpha_original(target,surface,arg1,arg2,arg3);
    return ((u32 (*)(void *,const void *,u32,u32))target)(surface,arg1,arg2,arg3);
}

/* Exact LR selection preserves the island's original no-argument getter for
 * unrelated callers. x4=FG function, x3=BG function or original Event handler. */
u64 ui_bridge(uptr a,uptr b,uptr c,uptr d,uptr e) {
    uptr caller=(uptr)__builtin_return_address(0);
    if (caller==0x4d31ad2a8ULL || caller==0x4d31ad5d0ULL)
        return ui_draw((void *)a,(const void *)b,(u32)c,e,0);
    if (caller==0x4d31ad310ULL || caller==0x4d31ad638ULL)
        return ui_draw((void *)a,(const void *)b,(u32)c,d,1);
    if (caller==0x4d31ad3f8ULL) {
        u32 result=((u32 (*)(u32))(uptr)0x4d321d770ULL)((u32)a);
        if (state.mode!=2) ui_complete();
        return result;
    }
    if (caller==0x4d31accf0ULL) {
        int result=((int (*)(u32,void *))(uptr)0x4d3033a50ULL)((u32)a,(void *)b);
        if (result>0 && state.mode!=2) {
            ui_frame_begin();
            u32 cmd=menu_read16((const u8 *)b+8);
            if (cmd==0 || cmd==7) ui_cancel();
            if (cmd==1 && result>=40 && menu_read16((const u8 *)b+10)>=24)
                ui_prepare_job(Q(b+16),Q(b+24));
        }
        return (u32)result;
    }
    if (caller==0x4d31ad200ULL) {
        /* Successful command0 has cleared/reinitialized both native planes.
         * Command7 never enters here: its retained canonical pixels survive. */
        if (state.mode!=2) {
            ui.plane[0].ready=ui.plane[1].ready=0;
            ui.seeded[0]=ui.seeded[1]=0;
            ui.displayed=menu_orientation.displayed=0;
            ui.published_owned=ui.last_owned=0; ui.last_foreground=0;
            ui.native_draw[0]=ui.native_draw[1]=0;
            ui.blocked=ui.lost_anchors=0;
            ui_base_forget();
            ui.handoff_base=0;
            ui.child_clean=0;
            ui_image_anchors_reset(&ui.anchors);
        }
        return ((u32 (*)(u32,u32))(uptr)0x4d3033950ULL)((u32)a,(u32)b);
    }
    if (caller==0x4d3323ac4ULL) {
        /* tk_rcv_mbf's timeout is normalized to E_TMOUT=-50 by the stock
         * adapter. Poll in this UI task without fabricating input messages. */
        for (;;) {
            if (state.mode==2)
                return ((u32 (*)(u32,void *))(uptr)0x4d3033a50ULL)((u32)a,(void *)b);
            int result=((int (*)(u32,void *,int))(uptr)0x4d3033ab0ULL)((u32)a,(void *)b,100);
            if (result!=-50) return (u32)result;
            /* Retry at most twice while idle. The original hierarchy call on
             * a later real event starts a fresh bounded attempt. next points
             * to this UI task's persistent handler pair, never a draw stack. */
            if (ui.retry_switch && ui.retry_count<2) {
                ui.retry_count++;
                ui_switch((void *)ui.retry_switch);
            }
            ui_poll();
        }
    }
    if (caller==0x4d3323a78ULL) {
        ui.retry_count=0;
        return ui_switch((void *)a);
    }
    if (caller==0x4d33232fcULL) return ui_input((struct Event *)a,d);
    if (caller==0x4d3367780ULL || caller==0x4d33677ecULL || caller==0x4d336783cULL)
        return ui_rect_hit((const void *)a,(u32)b,(u32)c,(u32)d,(u32)e);
#define UI_ROW_MATCH(address) if (caller==(address)+4) { \
        native_touch_rows_observe(ui.row_token,(const void *)a,(const void *)b); \
        native_touch_private_list_observe(ui.private_token,(const void *)a,(const void *)b); \
        return ((u32 (*)(void *,const void *))(uptr)0x4d3363df0ULL)((void *)a,(const void *)b); }
    UI_ROW_CALLS(UI_ROW_MATCH)
#undef UI_ROW_MATCH
    if (caller==0x4d337d290ULL) {
        native_touch_settings_list_observe_copy(ui.settings_token,(const void *)a,(const void *)b,c);
        return ((u64 (*)(void *,const void *,u64))(uptr)0x4d3007fc0ULL)((void *)a,(const void *)b,c);
    }
#define UI_ANCHOR_MATCH(address,target) if (caller==(address)+4) { \
        return ui_anchor_call(target,(void *)a,(const void *)b,(u32)c,(u32)d); }
    UI_IMAGE_ANCHORS_BL_HOOKS(UI_ANCHOR_MATCH)
    UI_IMAGE_ANCHORS_EXTRA_BL_HOOKS(UI_ANCHOR_MATCH)
#undef UI_ANCHOR_MATCH
    if (caller==0x4d3323ab0ULL) {
        u32 result=((u32 (*)(void))(uptr)0x4d3323c50ULL)();
        ui_poll(); return result;
    }
    return ((u32 (*)(void))(uptr)0x4d33175f0ULL)();
}

static void ui_initialize(uptr base) {
#define UI_EXPORT_OFFSET(name,field) __asm__(".global " #name "\n.set " #name ", %c0" :: "i"(__builtin_offsetof(__typeof__(ui),field)))
    UI_EXPORT_OFFSET(__ui_removing_offset,removing);
    UI_EXPORT_OFFSET(__ui_ready_offset,input_ready);
    UI_EXPORT_OFFSET(__ui_displayed_offset,displayed);
    UI_EXPORT_OFFSET(__ui_frame_offset,frame_mask);
    UI_EXPORT_OFFSET(__ui_anchors_offset,anchors);
    UI_EXPORT_OFFSET(__ui_blocked_offset,blocked);
    UI_EXPORT_OFFSET(__ui_lost_anchors_offset,lost_anchors);
    UI_EXPORT_OFFSET(__ui_base_family_offset,base_family);
    UI_EXPORT_OFFSET(__ui_base_slots_offset,base_slots);
    UI_EXPORT_OFFSET(__ui_switching_offset,switching);
    UI_EXPORT_OFFSET(__ui_base_candidate_offset,base_candidate);
    UI_EXPORT_OFFSET(__ui_base_owner_offset,base_owner);
    UI_EXPORT_OFFSET(__ui_handoff_base_offset,handoff_base);
    UI_EXPORT_OFFSET(__ui_profile_style_offset,profile_style);
    UI_EXPORT_OFFSET(__ui_profile_staged_offset,profile_staged);
    UI_EXPORT_OFFSET(__ui_child_clean_offset,child_clean);
    UI_EXPORT_OFFSET(__ui_retain_child_offset,retain_child);
#undef UI_EXPORT_OFFSET
    __typeof__(ui) *s=(void *)(uptr)relocate(&ui,base);
    uptr scratch=base+(uptr)__end-(uptr)__start+ORIENTATION_BYTES;
    global_orientation_bind(&s->plane[0],0,(void *)scratch,GLOBAL_ORIENTATION_FG_BYTES);
    global_orientation_bind(&s->plane[1],1,(void *)(scratch+GLOBAL_ORIENTATION_FG_BYTES),GLOBAL_ORIENTATION_BG_BYTES);
    s->redraw[0]=relocate((const void *)ui_noop_foreground,base);
    s->redraw[1]=relocate((const void *)ui_noop_background,base);
    /* A first idle poll has no scene provenance. It may seed landscape, but
     * must not rotate a native bank that could already contain image anchors.
     * A real classified pair (or a real UI-only draw) releases this hold. */
    s->blocked=1;
    s->initialized=1;
}
#endif
