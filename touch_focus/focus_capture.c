#include "focus_capture.h"

typedef uint8_t u8;
typedef uint16_t u16;
typedef uint32_t u32;
typedef uint64_t u64;
typedef uintptr_t uptr;
#define Q(a) (*(volatile u64 *)(uptr)(a))
#define W(a) (*(volatile u32 *)(uptr)(a))
#define B(a) (*(volatile u8 *)(uptr)(a))
#define FC_PENDING UINT64_C(0x4d72faf50)
#define FC_FIRST UINT64_C(0x4d72faf4c)
#define FC_WRITER UINT64_C(0x4d72fb0a8)
#define FC_EVENT UINT64_C(0x4d73014b8)
#define FC_PROGRAM_CALL UINT64_C(0x4d32bf008)
#define FC_GATE_CALL UINT64_C(0x4d32bf194)
#define FC_PAIR_CALL UINT64_C(0x4d32bf1bc)
#define FC_IRQ_CALL UINT64_C(0x4d32ca268)
#define FC_SEND_CALL UINT64_C(0x4d32bf1e0)
/* Central 128x24 subset of the hardware-tested 256x32 crop. Mapping arbitrary
 * UI targets to PAS pixels and calibrating other positions is not implied. */
#define FC_X 693u
#define FC_Y 154u
#define FC_STRIDE 1536u
#define FC_ROI_OFFSET (FC_Y*FC_STRIDE+FC_X)
#define FC_MAX_AGE UINT64_C(2400000) /* 100 ms at nominal 24 MHz */
#define FC_MAX_COPY UINT64_C(240000) /* 10 ms, not a preemption guarantee */

static u32 lens(void) { return ((u32 (*)(void))(uptr)0x4d31d48c0ULL)(); }
#define FOCUS_PAS_EXTERNAL_ROUTER
#include "focus_pas.h"

struct HookContext { u64 lr, sp, descriptor, timing, token, skip; };
struct Writer {
    u8 descriptor[0x58];
    u32 mode, channels;
    u64 stride1, stride2;
    u32 sensor_mode, event_id;
};
struct Irq {
    u32 seq, fault, active, reserved;
    u64 complete[2], errors[2];
};
struct Wait { u64 args[4]; u32 result, output, seen, reserved; };
struct Generation {
    u64 id, program_time, source_epoch;
    u32 valid, program_done, program_result, reserved;
    struct FocusCaptureRequest request;
    u8 metadata[0x158];
    struct Writer writer;
    struct Irq baseline;
};
static struct {
    volatile u32 lock, seq, fault, reserved;
    u64 generation, receiver_sp, source_epoch, consume_sequence, consumed_generation;
    u32 have_consume, floor_valid;
    struct Irq last_consume, consume_floor;
    struct Generation previous, current;
    struct Wait waits[2];
} tracking;
static volatile struct Irq irq_state;
static volatile u32 irq_lock, inflight, stopped, request_seq;
static volatile struct FocusCaptureRequest request;
enum { SLOT_FREE, SLOT_WRITING, SLOT_READY, SLOT_READING };
static struct CaptureSlot {
    volatile u32 state;
    u32 reserved;
    struct FocusCaptureFrame frame;
} slot __attribute__((aligned(64)));
static u64 publication_sequence;
volatile struct FocusCaptureStatus focus_capture_status;
/* Do not consume the native receiver's small stack with forensic snapshots.
 * Only the receiver holding inflight may write this bounded working area. */
static struct {
    struct Generation previous, next;
    struct Wait waits[2];
    struct Writer before, after;
    struct Irq irq_start, irq_end;
    struct Irq consume_floor;
    u64 consume_sequence, consumed_generation;
    u32 floor_valid;
    struct FocusCaptureRequest active, final;
    struct FocusCaptureIdentity identity;
    u8 metadata[0x158];
} work;

static void copy(volatile void *dst, const volatile void *src, u32 n) {
    volatile u8 *d=dst; const volatile u8 *s=src;
    for (u32 i=0;i<n;i++) d[i]=s[i];
}
static void zero(volatile void *dst, u32 n) {
    volatile u8 *p=dst; for (u32 i=0;i<n;i++) p[i]=0;
}
static int same(const volatile void *a,const volatile void *b,u32 n) {
    const volatile u8 *x=a,*y=b;
    for (u32 i=0;i<n;i++) if (x[i]!=y[i]) return 0;
    return 1;
}
static u16 half(const volatile u8 *p) { return (u16)p[0]|((u16)p[1]<<8); }
static u32 word(const volatile u8 *p) { return (u32)half(p)|((u32)half(p+2)<<16); }
static u64 quad(const volatile u8 *p) { return (u64)word(p)|((u64)word(p+4)<<32); }
static void barrier(void) { __asm__ volatile("dmb ish" ::: "memory"); }
/* One exclusive attempt, no spinning or firmware task locks. */
static int claim(volatile u32 *p,u32 expected,u32 value) {
    u32 old,status;
    __asm__ volatile("ldaxr %w0,[%2]\n cmp %w0,%w3\n b.ne 1f\n"
                     "stlxr %w1,%w4,[%2]\n b 2f\n"
                     "1: clrex\n mov %w1,#1\n 2:"
                     : "=&r"(old),"=&r"(status) : "r"(p),"r"(expected),"r"(value)
                     : "cc","memory");
    return status==0;
}
static void release(volatile u32 *p,u32 value) {
    __atomic_store_n(p,value,__ATOMIC_RELEASE);
}
static void fault(void) { release(&tracking.fault,1); }
static int enabled(void) { return !stopped && (request.enabled==1 || inflight); }
static int track_lock(void) {
    if (!claim(&tracking.lock,0,1)) { fault(); return 0; }
    tracking.seq++; barrier(); return 1;
}
static void track_unlock(void) { barrier(); tracking.seq++; release(&tracking.lock,0); }
int focus_capture_same_identity(const struct FocusCaptureIdentity *a,
                                const struct FocusCaptureIdentity *b) {
    return a->slot==b->slot && a->profile[0]==b->profile[0] && a->profile[1]==b->profile[1];
}
static int same_request(const struct FocusCaptureRequest *a,const struct FocusCaptureRequest *b) {
    return a->enabled==b->enabled && a->epoch==b->epoch && a->after_ticks==b->after_ticks &&
        focus_capture_same_identity(&a->identity,&b->identity);
}
static int read_request(struct FocusCaptureRequest *out) {
    u32 seq=__atomic_load_n(&request_seq,__ATOMIC_ACQUIRE);
    if (seq&1) return 0;
    copy(out,&request,sizeof(*out)); barrier();
    return seq==request_seq && !stopped && out->enabled==1 && out->after_ticks;
}
void focus_capture_request(const struct FocusCaptureRequest *r) {
    request_seq++; barrier();
    if (r && !stopped) copy(&request,r,sizeof(request));
    else zero(&request,sizeof(request));
    barrier(); request_seq++;
    focus_capture_status.version=1;
    focus_capture_status.hardware_coherence_unproven=1;
    focus_capture_status.enabled=request.enabled==1 && !stopped;
}
void focus_sensor_enable_tables(int on) { focus_pas.enabled=!!on && !stopped; }
void focus_capture_shutdown(void) {
    release(&stopped,1); focus_sensor_enable_tables(0); fault();
    focus_capture_request(0);
}
uint64_t focus_sensor_ticks(void) { return ((u64 (*)(void))(uptr)0x4d31a5c00ULL)(); }

static int still_scene(void) {
    return W(0x4d70346a0ULL)==2 && W(0x4d70346a4ULL)==12 &&
        Q(0x4d7301c00ULL)==0x4d3398930ULL && Q(0x4d7301c08ULL)==0x4d33988b0ULL &&
        Q(0x4d7301c10ULL)==0x4d3393730ULL && Q(0x4d7301c18ULL)==0x4d33936a0ULL;
}
static void lens_identity(struct FocusCaptureIdentity *id) {
    id->profile[0]=id->profile[1]=0;
    id->slot=((u32 (*)(void))(uptr)0x4d3318480ULL)();
    if (id->slot<10)
        ((void (*)(u32,void *))(uptr)FOCUS_PAS_PROFILE_GETTER)(id->slot,id->profile);
}
static void read_writer(struct Writer *w);
static int writer_valid(const struct Writer *w);
int focus_sensor_context(struct FocusCaptureIdentity *id) {
    if (!id || stopped || !still_scene() || lens()!=0) return 0;
    struct Writer before,after;
    read_writer(&before);
    if (!writer_valid(&before)) return 0;
    struct FocusCaptureIdentity a,b;
    lens_identity(&a); barrier(); lens_identity(&b);
    read_writer(&after);
    if (!same(&before,&after,sizeof(before)) || !focus_capture_same_identity(&a,&b) ||
        !still_scene() || lens()!=0) return 0;
    *id=a; return 1;
}
static int irq_snapshot(struct Irq *out) {
    u32 seq=__atomic_load_n(&irq_state.seq,__ATOMIC_ACQUIRE);
    if (seq&1) return 0;
    copy(out,&irq_state,sizeof(*out)); barrier();
    return seq==irq_state.seq && !out->fault;
}
static int irq_valid(const struct Irq *base,const struct Irq *end) {
    if (base->fault || end->fault || end->active) return 0;
    for (u32 i=0;i<2;i++)
        if (end->errors[i]!=base->errors[i] || end->complete[i]<=base->complete[i]) return 0;
    return 1;
}
static u32 irq_before(u64 p) {
    if (!enabled()) return 0;
    if (!claim(&irq_lock,0,1)) { fault(); return 0; }
    u32 mask=4; /* marker: this callback incremented active */
    irq_state.seq++; barrier();
    if (irq_state.active==UINT32_MAX) irq_state.fault=1;
    else irq_state.active++;
    for (u32 i=0;i<2;i++) {
        u32 bits=W(p+4*i);
        if (bits&1) {
            mask|=1u<<i;
            if (irq_state.complete[i]==UINT64_MAX) irq_state.fault=1;
            else irq_state.complete[i]++;
        }
        if (bits&0x110) {
            if (irq_state.errors[i]==UINT64_MAX) irq_state.fault=1;
            else irq_state.errors[i]++;
        }
    }
    barrier(); irq_state.seq++; release(&irq_lock,0);
    return mask;
}
static void irq_after(u32 mask,u32 result) {
    if (!(mask&4)) return;
    if (!claim(&irq_lock,0,1)) { fault(); return; }
    irq_state.seq++; barrier();
    if (!irq_state.active) irq_state.fault=1;
    else irq_state.active--;
    /* Done bits with a failed native event-set return cannot contribute
     * completion evidence. Taint both overlapping generation intervals. */
    if (result) for (u32 i=0;i<2;i++) if (mask&(1u<<i)) {
        if (irq_state.errors[i]==UINT64_MAX) irq_state.fault=1;
        else irq_state.errors[i]++;
    }
    barrier(); irq_state.seq++; release(&irq_lock,0);
}
static void read_writer(struct Writer *w) {
    copy(w->descriptor,(const void *)(uptr)FC_WRITER,0x58);
    w->mode=W(0x4d70342e4ULL); w->channels=B(0x4d72fba22ULL);
    w->stride1=Q(0x4d72fba28ULL); w->stride2=Q(0x4d72fba30ULL);
    w->sensor_mode=W(0x4d703459cULL); w->event_id=W(FC_EVENT);
}
static int writer_valid(const struct Writer *w) {
    const u8 *d=w->descriptor;
    return word(d+8)==3 && w->mode==3 && w->channels==4 &&
        w->stride1==1536 && w->stride2==512 &&
        half(d+0x30)==1514 && half(d+0x32)==334 &&
        half(d+0x34)==1536 && d[0x38]==14 && d[0x39]==8 &&
        /* All four channels are programmed, although only pair1 is read.
         * Bound the secondary writer too: an unexpected footprint cannot
         * inherit the measured bank-separation contract. */
        half(d+0x40)==504 && half(d+0x42)==334 &&
        half(d+0x44)==512 && d[0x48]==14 && d[0x49]==8 &&
        w->sensor_mode==2;
}
static int tuple_valid(const u8 *tuple) {
    u64 a=quad(tuple), b=quad(tuple+8);
    return b==a+0x7d400 &&
        (a==0x419b58300ULL || a==0x419c52b00ULL ||
         a==0x419d4d300ULL || a==0x419e47b00ULL);
}
static int banks_valid(const u8 *m) {
    return tuple_valid(m+0x138) && tuple_valid(m+0x148) &&
        quad(m+0x138)!=quad(m+0x148);
}
static int source_disjoint(const u8 *previous,const u8 *next) {
    /* Each whitelisted tuple owns two adjacent, fixed-size plane allocations.
     * Neither newly programmed pair may reuse the pending source pair. This
     * checks actual arguments, not an assumption about the modulo4 selector. */
    u64 source=quad(previous+0x138);
    return banks_valid(previous) && banks_valid(next) &&
        source!=quad(next+0x138) && source!=quad(next+0x148);
}
static int metadata_matches(const volatile u8 *a,const volatile u8 *b) {
    /* Native receiver does not write padding bytes 1..3. */
    return a[0]==b[0] && same(a+4,b+4,0x154);
}
static u64 program_before(u64 a,u64 b,const struct HookContext *c) {
    if (!enabled() || !track_lock()) return 0;
    u64 id=0;
    struct FocusCaptureRequest current_request;
    struct FocusCaptureIdentity identity;
    if (!read_request(&current_request)) goto done;
    if (a!=c->sp+0x50 || b!=c->sp+0x60 || !c->descriptor || !c->timing || !c->token) {
        fault(); goto done;
    }
    /* A fault or native reinitialization invalidates the old interval. Start
     * a fresh generation now; only its subsequent fully observed send can pass.
     * Holding the receiver lock prevents clearing a concurrently owned update. */
    u32 bad=__atomic_load_n(&tracking.fault,__ATOMIC_ACQUIRE);
    if (bad) (void)claim(&tracking.fault,1,0);
    copy(&tracking.previous,&tracking.current,sizeof(struct Generation));
    u32 reset=bad || B(FC_FIRST) || !tracking.previous.id || !tracking.previous.program_done ||
        !metadata_matches(tracking.previous.metadata,(const void *)(uptr)FC_PENDING) ||
        !same_request(&tracking.previous.request,&current_request);
    if (reset || !tracking.previous.valid) tracking.previous.valid=0;
    zero(tracking.waits,sizeof(tracking.waits));
    struct Generation *g=&tracking.current;
    zero(g,sizeof(*g));
    if (tracking.generation==UINT64_MAX) { fault(); goto done; }
    id=++tracking.generation; g->id=id; tracking.receiver_sp=c->sp;
    g->request=current_request;
    g->metadata[0]=(u8)c->skip;
    copy(g->metadata+4,(const void *)(uptr)c->token,12);
    copy(g->metadata+0x10,(const void *)(uptr)c->timing,24);
    copy(g->metadata+0x28,(const void *)(uptr)c->descriptor,0x110);
    copy(g->metadata+0x138,(const void *)(uptr)a,16);
    copy(g->metadata+0x148,(const void *)(uptr)b,16);
    read_writer(&g->writer); g->program_time=focus_sensor_ticks();
    if (!reset && !same(&g->writer,&tracking.previous.writer,sizeof(g->writer))) reset=1;
    if (reset) {
        if (tracking.source_epoch==UINT64_MAX) fault();
        else tracking.source_epoch++;
        tracking.previous.valid=0; tracking.have_consume=0;
    }
    g->source_epoch=tracking.source_epoch;
    g->valid=irq_snapshot(&g->baseline) && writer_valid(&g->writer) && banks_valid(g->metadata) &&
        focus_sensor_context(&identity) && focus_capture_same_identity(&identity,&current_request.identity) &&
        quad(g->metadata+0x10)>=current_request.after_ticks;
    if (tracking.previous.id &&
        (g->program_time<=tracking.previous.program_time ||
         quad(g->metadata+0x10)<=quad(tracking.previous.metadata+0x10))) g->valid=0;
done: track_unlock(); return id;
}
static void program_after(u64 id,u32 result) {
    if (!id || !track_lock()) return;
    if (tracking.current.id!=id) fault();
    else { tracking.current.program_result=result; tracking.current.program_done=1; }
    track_unlock();
}
static void observe_wait(u32 index,const struct HookContext *c,const u64 *args,u32 result,u64 id) {
    if (!enabled() || !track_lock()) return;
    /* Hot attachment may begin inside an old frame, before any local program. */
    if (!tracking.generation) goto done;
    struct Wait *w=&tracking.waits[index];
    if (id!=tracking.previous.id || c->sp!=tracking.receiver_sp ||
        args[3]!=c->sp+0x48+index*4 || w->seen || (index && !tracking.waits[0].seen)) {
        fault(); goto done;
    }
    copy(w->args,args,32); w->result=result; w->output=W(args[3]); w->seen=1;
    if (result || (w->output&0x20000000u)) fault();
    /* The real pair wait consumes bits0/1 on success, including skip/stop
     * results. Keep that software consume separate from program/publication.
     * Its return is a boundary, not the exact in-kernel consume instant. */
    if (index && !result && args[0]==W(FC_EVENT) && args[1]==3 && args[2]==0x20 &&
        (w->output&3)==3) {
        copy(&tracking.consume_floor,&tracking.last_consume,sizeof(struct Irq));
        tracking.floor_valid=tracking.have_consume;
        if (tracking.consume_sequence==UINT64_MAX) fault();
        else tracking.consume_sequence++;
        tracking.consumed_generation=id;
        tracking.have_consume=irq_snapshot(&tracking.last_consume);
    }
done: track_unlock();
}
static struct CaptureSlot *write_slot(void) {
    if (claim(&slot.state,SLOT_FREE,SLOT_WRITING) ||
        claim(&slot.state,SLOT_READY,SLOT_WRITING)) return &slot;
    focus_capture_status.dropped++; return 0;
}
const struct FocusCaptureFrame *focus_capture_acquire(void) {
    if (__atomic_load_n(&stopped,__ATOMIC_ACQUIRE)) return 0;
    if (!claim(&slot.state,SLOT_READY,SLOT_READING)) return 0;
    if (__atomic_load_n(&stopped,__ATOMIC_ACQUIRE)) {
        release(&slot.state,SLOT_FREE);
        return 0;
    }
    return &slot.frame;
}
void focus_capture_release(const struct FocusCaptureFrame *frame) {
    /* A reader exclusively owns this state. Releasing cannot depend on a
     * single exclusive-store attempt surviving an interrupt. */
    if (frame==&slot.frame && __atomic_load_n(&slot.state,__ATOMIC_ACQUIRE)==SLOT_READING)
        release(&slot.state,SLOT_FREE);
}
static void capture_send(u64 a,u64 b,u64 c) {
    if (!enabled() || !track_lock()) return;
    if (!tracking.previous.id || !tracking.previous.program_done) { track_unlock(); return; }
    if (!claim(&inflight,0,1)) { fault(); track_unlock(); return; }
    struct CaptureSlot *slot=write_slot();
    if (!slot) { release(&inflight,0); track_unlock(); return; }
    /* The native receiver is single-threaded; seq detects reentry/corruption
     * while the copy runs. Do not hold the observation lock across pixel reads. */
    copy(&work.previous,&tracking.previous,sizeof(work.previous));
    copy(&work.next,&tracking.current,sizeof(work.next));
    copy(work.waits,tracking.waits,sizeof(work.waits));
    copy(&work.consume_floor,&tracking.consume_floor,sizeof(work.consume_floor));
    work.floor_valid=tracking.floor_valid;
    work.consume_sequence=tracking.consume_sequence;
    work.consumed_generation=tracking.consumed_generation;
    track_unlock();
    u32 seq=tracking.seq, reason=0;
    struct FocusCaptureFrame *r=&slot->frame;
    zero(r,(u32)__builtin_offsetof(struct FocusCaptureFrame,pixels));
    const struct Generation *previous=&work.previous, *next=&work.next;
    const struct Wait *waits=work.waits;
    if (publication_sequence==UINT64_MAX) { fault(); reason|=FC_TRACK; }
    else publication_sequence++;
    r->sequence=publication_sequence; r->epoch=previous->request.epoch;
    r->source_epoch=previous->source_epoch;
    r->program_sequence=previous->id; r->consume_sequence=work.consume_sequence;
    r->identity=previous->request.identity;
    r->hardware_coherence_unproven=1;
    r->lifecycle_continuity_unproven=1;
    r->guard_before=r->guard_after=FOCUS_CAPTURE_GUARD;
    r->copy_start_ticks=focus_sensor_ticks();
    if (tracking.fault || !previous->valid || !previous->program_done || previous->program_result ||
        !next->valid || !next->program_done || next->program_result ||
        previous->source_epoch!=next->source_epoch) reason|=FC_TRACK;
    struct Writer *before=&work.before,*after=&work.after;
    struct FocusCaptureIdentity *identity=&work.identity;
    u8 *metadata=work.metadata;
    zero(metadata,sizeof(work.metadata));
    read_writer(before);
    if (!writer_valid(before) || !same(before,&previous->writer,sizeof(*before)) ||
        !same(before,&next->writer,sizeof(*before))) reason|=FC_CONFIG;
    if (a!=FC_PENDING+4 || b!=FC_PENDING || c) reason|=FC_IDENTITY;
    else copy(metadata,(const void *)(uptr)FC_PENDING,sizeof(work.metadata));
    if (metadata[0] || word(metadata+8) || !banks_valid(metadata) ||
        !metadata_matches(metadata,previous->metadata)) reason|=FC_IDENTITY;
    if (!source_disjoint(previous->metadata,next->metadata)) reason|=FC_IDENTITY;
    for (u32 i=0;i<2;i++) {
        r->wait_results[i]=waits[i].result; r->wait_flags[i]=waits[i].output;
        if (waits[i].seen!=1 || waits[i].result || waits[i].args[0]!=before->event_id ||
            waits[i].args[1]!=(i?3:0x20000001u) || waits[i].args[2]!=(i?0x20:1)) reason|=FC_WAIT;
    }
    if (!(waits[0].output&1) || ((waits[0].output|waits[1].output)&0x20000000u) ||
        (waits[1].output&3)!=3) reason|=FC_WAIT;
    if (work.consumed_generation!=previous->id || !work.consume_sequence) reason|=FC_WAIT;
    if (!irq_snapshot(&work.irq_start) || !irq_valid(&previous->baseline,&work.irq_start)) reason|=FC_IRQ;
    /* A completion counted before the preceding successful consume return
     * cannot be credited independently to this overlapping generation. This
     * deliberately rejects some ambiguous but potentially real completions. */
    if (!work.floor_valid || !irq_valid(&work.consume_floor,&work.irq_start)) reason|=FC_IRQ;
    if (!read_request(&work.active) || !same_request(&work.active,&previous->request) ||
        !same_request(&work.active,&next->request)) reason|=FC_REQUEST;
    if (!focus_sensor_context(identity) || !focus_capture_same_identity(identity,&r->identity)) reason|=FC_SCENE;
    u64 stamp=quad(metadata+0x10); r->acquired_ticks=stamp;
    if (!stamp || stamp<previous->request.after_ticks || r->copy_start_ticks<stamp ||
        r->copy_start_ticks-stamp>FC_MAX_AGE || r->copy_start_ticks<previous->program_time ||
        r->copy_start_ticks-previous->program_time>FC_MAX_AGE) reason|=FC_AGE;
    if (!reason) for (u32 plane=0;plane<2;plane++) {
        uptr p=(uptr)quad(metadata+0x138+8*plane)+FC_ROI_OFFSET;
        /* Rounded footprint remains inside each whitelisted 0x7d400 plane.
         * Match the native CPU filter's invalidate-before-read operation. */
        ((void (*)(u64,u32))(uptr)0x4d3074b70ULL)(p&~UINT64_C(63),
            (u32)(p&63)+(FOCUS_CAPTURE_HEIGHT-1)*FC_STRIDE+FOCUS_CAPTURE_WIDTH);
        for (u32 row=0;row<FOCUS_CAPTURE_HEIGHT;row++)
            copy(r->pixels[plane]+row*FOCUS_CAPTURE_WIDTH,
                 (const void *)(p+row*FC_STRIDE),FOCUS_CAPTURE_WIDTH);
    }
    r->copy_end_ticks=focus_sensor_ticks();
    read_writer(after);
    if (!same(before,after,sizeof(*before))) reason|=FC_CONFIG;
    if (!metadata_matches(metadata,(const void *)(uptr)FC_PENDING) || B(FC_FIRST) ||
        tracking.fault || tracking.seq!=seq || (seq&1) || stopped) reason|=FC_TORN;
    if (!read_request(&work.final) || !same_request(&work.final,&previous->request)) reason|=FC_REQUEST;
    if (!focus_sensor_context(identity) || !focus_capture_same_identity(identity,&r->identity)) reason|=FC_SCENE;
    if (!irq_snapshot(&work.irq_end) || !irq_valid(&previous->baseline,&work.irq_end)) reason|=FC_IRQ;
    if (!work.floor_valid || !irq_valid(&work.consume_floor,&work.irq_end)) reason|=FC_IRQ;
    if (tracking.fault || tracking.seq!=seq) reason|=FC_TORN;
    if (r->copy_end_ticks<r->copy_start_ticks || r->copy_end_ticks-r->copy_start_ticks>FC_MAX_COPY) reason|=FC_COPY_TIME;
    if (r->copy_end_ticks<stamp || r->copy_end_ticks-stamp>FC_MAX_AGE) reason|=FC_AGE;
    r->reason=reason; r->software_checks_passed=!reason;
    focus_capture_status.published++;
    if (reason) focus_capture_status.rejected++; else focus_capture_status.accepted++;
    focus_capture_status.last_reason=reason;
    focus_capture_status.last_sequence=r->sequence;
    focus_capture_status.last_acquired_ticks=stamp;
    focus_capture_status.last_copy_ticks=r->copy_end_ticks-r->copy_start_ticks;
    focus_capture_status.source_epoch=r->source_epoch;
    focus_capture_status.program_sequence=r->program_sequence;
    focus_capture_status.consume_sequence=r->consume_sequence;
    /* Owned RAM uses the same virtual mapping for both CPU tasks. Release/
     * acquire publishes all metadata and both planes before a reader claims it.
     * No frame pointer refers to a hardware-owned bank after this point. */
    release(&slot->state,SLOT_READY);
    release(&inflight,0);
}
u64 focus_sensor_dispatch(u64 a,u64 b,u64 c,u64 d,const struct HookContext *ctx) {
    u64 lr=ctx->lr;
    if (lr==FC_PROGRAM_CALL+4) {
        u64 id=program_before(a,b,ctx);
        u64 rc=((u64 (*)(u64,u64,u64,u64))(uptr)0x4d32cb880ULL)(a,b,c,d);
        program_after(id,(u32)rc); return rc;
    }
    if (lr==FC_GATE_CALL+4 || lr==FC_PAIR_CALL+4) {
        u64 id=tracking.previous.id,args[4]={a,b,c,d};
        u64 rc=((u64 (*)(u64,u64,u64,u64))(uptr)0x4d3033810ULL)(a,b,c,d);
        observe_wait(lr==FC_PAIR_CALL+4,ctx,args,(u32)rc,id); return rc;
    }
    if (lr==FC_IRQ_CALL+4) {
        u32 mask=irq_before(a);
        u64 rc=((u64 (*)(u64,u64,u64,u64))(uptr)0x4d32cab80ULL)(a,b,c,d);
        irq_after(mask,(u32)rc); return rc;
    }
    if (lr==FC_SEND_CALL+4) {
        capture_send(a,b,c);
        return ((u64 (*)(u64,u64,u64,u64))(uptr)0x4d32c9d20ULL)(a,b,c,d);
    }
    return focus_pas_explicit((uptr)lr,a,b,c);
}
