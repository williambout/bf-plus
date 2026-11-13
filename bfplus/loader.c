/* Original standalone BF 1.04 segmented RAM loader. No resident hooks here. */
#include "loader_abi.h"
typedef uint8_t u8;
typedef uint32_t u32;
typedef uint64_t u64;
#define Q(a) (*(volatile u64 *)(uintptr_t)(a))
#define W(a) (*(volatile u32 *)(uintptr_t)(a))

volatile struct LoaderControl loader_control
    __attribute__((section(".data.control"), aligned(64))) = {0};
extern u8 __start[] __attribute__((visibility("hidden")));

void *memcpy(void *out, const void *in, __SIZE_TYPE__ n) {
    volatile u8 *d=out;
    const volatile u8 *s=in;
    for (__SIZE_TYPE__ i=0;i<n;i++) d[i]=s[i];
    return out;
}
void *memset(void *out, int value, __SIZE_TYPE__ n) {
    volatile u8 *d=out;
    for (__SIZE_TYPE__ i=0;i<n;i++) d[i]=(u8)value;
    return out;
}

static void publish(u64 first, u64 end, u64 ctr, int code) {
    u64 step=4ULL<<((ctr>>16)&15);
    for (u64 p=first&~(step-1);p<end;p+=step)
        __asm__ volatile("dc cvac, %0" :: "r"(p) : "memory");
    __asm__ volatile("dsb ish" ::: "memory");
    if (code) {
        step=4ULL<<(ctr&15);
        for (u64 p=first&~(step-1);p<end;p+=step)
            __asm__ volatile("ic ivau, %0" :: "r"(p) : "memory");
        __asm__ volatile("dsb ish\n isb" ::: "memory");
    }
}
static int idle(void) {
    return W(0x4d70346a0ULL)==2 && W(0x4d70346a4ULL)==12 &&
        Q(0x4d7301c00ULL)==0x4d3398930ULL && Q(0x4d7301c08ULL)==0x4d33988b0ULL &&
        Q(0x4d7301c10ULL)==0x4d3393730ULL && Q(0x4d7301c18ULL)==0x4d33936a0ULL;
}
static int overlaps(u64 a, u64 end, u64 b, u64 b_end) { return a<b_end && b<end; }
static int extents(const struct LoaderControl *c) {
    return c->image_size>=4 && c->image_size<=c->memory_size &&
        c->memory_size<=LOADER_MEMORY_MAX && !(c->memory_size&63) &&
        c->scratch_size<=LOADER_SCRATCH_MAX && !(c->scratch_size&63) &&
        !(c->entry_offset&3) && c->entry_offset<=c->image_size-4 && c->mode<=1;
}
static int transport(const struct LoaderControl *c) {
    u64 b=c->transport_buffer;
    return b>=LOADER_RAM_MIN && b<=LOADER_RAM_END-LOADER_TRANSPORT_BYTES &&
        !(b&4095) && b+LOADER_STAGE_OFFSET==(u64)(uintptr_t)__start &&
        Q(0x4d72c2230ULL)==b;
}
static int allocation(const struct LoaderControl *c) {
    /* Bounds make every later addition/subtraction non-wrapping. Guard writes
     * never precede owner, and the allocator's whole region must be disjoint
     * from executing transport storage and known RTOS code/static data. */
    u64 n=LOADER_GUARD_BYTES+4095+c->memory_size+c->scratch_size;
    if (c->allocation_size!=n || c->owner<LOADER_RAM_MIN ||
        c->owner>LOADER_RAM_END-n) return 0;
    u64 base=(c->owner+LOADER_GUARD_BYTES+4095)&~4095ULL;
    if (c->resident!=base || c->guard!=base-LOADER_GUARD_BYTES ||
        base+c->memory_size+c->scratch_size>c->owner+n) return 0;
    return !overlaps(c->owner,c->owner+n,c->transport_buffer,
                     c->transport_buffer+LOADER_TRANSPORT_BYTES) &&
        !overlaps(c->owner,c->owner+n,0x4d3000000ULL,0x4d7400000ULL);
}
static u32 crc32_image(u64 base, u64 size) {
    const volatile u8 *p=(const volatile u8 *)(uintptr_t)base;
    u32 crc=~0u;
    for (u64 i=0;i<size;i++) {
        crc^=p[i];
        for (u32 bit=0;bit<8;bit++) crc=(crc>>1)^(0xedb88320u & (0u-(crc&1)));
    }
    return ~crc;
}
static int identity(const struct LoaderControl *c, const volatile struct LoaderGuard *g) {
    if (g->magic!=LOADER_GUARD_MAGIC || g->abi_version!=LOADER_ABI_VERSION ||
        g->identity_nonce!=c->identity_nonce || g->owner!=c->owner ||
        g->resident!=c->resident || g->image_size!=c->image_size ||
        g->memory_size!=c->memory_size || g->scratch_size!=c->scratch_size ||
        g->entry_offset!=c->entry_offset || g->image_crc32!=c->image_crc32 ||
        g->mode!=c->mode || g->allocation_size!=c->allocation_size) return 0;
    for (u32 i=0;i<32;i++) if (g->image_sha256[i]!=c->image_sha256[i]) return 0;
    for (u32 i=0;i<31;i++) if (g->reserved[i]) return 0;
    return 1;
}
static void phase(struct LoaderControl *c, volatile struct LoaderGuard *g, u32 value) {
    c->phase=value;
    g->phase=value;
    g->entry_result=c->entry_result;
    publish(c->guard,c->guard+LOADER_GUARD_BYTES,c->ctr,0);
}
static u32 prepare(struct LoaderControl *c) {
    if (c->owner || c->resident || c->guard || c->allocation_size || c->phase ||
        c->identity_nonce!=c->request_nonce) return LOADER_BAD_GUARD;
    u64 owner=0;
    u64 n=LOADER_GUARD_BYTES+4095+c->memory_size+c->scratch_size;
    u32 ok=((u32 (*)(u64,u64,u32,u32,u64 *,int))(uintptr_t)0x4d330c850ULL)(
        n,0x400000000ULL,0,0,&owner,100);
    if (!(ok&255) || !owner) return LOADER_ALLOC_FAILED;
    /* Invalid allocator returns are reported, never dereferenced or freed. */
    c->owner=owner;
    c->allocation_size=n;
    if (owner>LOADER_RAM_END-n || owner<LOADER_RAM_MIN) return LOADER_BAD_RANGE;
    c->resident=(owner+LOADER_GUARD_BYTES+4095)&~4095ULL;
    c->guard=c->resident-LOADER_GUARD_BYTES;
    if (!allocation(c)) return LOADER_BAD_RANGE;
    struct LoaderGuard g={0};
    g.magic=LOADER_GUARD_MAGIC; g.abi_version=LOADER_ABI_VERSION;
    g.phase=LOADER_PREPARING; g.identity_nonce=c->identity_nonce;
    g.owner=owner; g.resident=c->resident;
    g.image_size=c->image_size; g.memory_size=c->memory_size;
    g.scratch_size=c->scratch_size; g.entry_offset=c->entry_offset;
    g.image_crc32=c->image_crc32; g.mode=c->mode;
    for (u32 i=0;i<32;i++) g.image_sha256[i]=c->image_sha256[i];
    g.allocation_size=n; g.last_request=c->request_nonce;
    memcpy((void *)(uintptr_t)c->guard,&g,sizeof(g));
    c->phase=LOADER_PREPARING;
    publish(c->guard,c->guard+sizeof(g),c->ctr,0);
    return LOADER_OK;
}
static u32 resident_command(struct LoaderControl *c) {
    if (!allocation(c)) return LOADER_BAD_RANGE;
    volatile struct LoaderGuard *g=(volatile struct LoaderGuard *)(uintptr_t)c->guard;
    if (!identity(c,g)) return LOADER_BAD_GUARD;
    if (c->request_nonce==g->last_request || c->request_nonce==c->identity_nonce)
        return LOADER_BAD_NONCE;
    u32 installing=c->command==LOADER_COMMIT;
    u32 required=installing ? LOADER_PREPARING : LOADER_COMMITTED;
    if (c->phase!=required || g->phase!=required || g->entry_result) return LOADER_BAD_PHASE;
    g->last_request=c->request_nonce;
    phase(c,g,installing ? LOADER_COMMITTING : LOADER_REMOVING);
    if (installing) {
        if (crc32_image(c->resident,c->image_size)!=c->image_crc32) {
            phase(c,g,LOADER_FAILED); return LOADER_BAD_CRC;
        }
        memset((void *)(uintptr_t)(c->resident+c->image_size),0,
               c->memory_size-c->image_size);
    }
    publish(c->resident,c->resident+c->memory_size,c->ctr,1);
    /* CRC/cache work can take time. The resident must repeat these checks
     * atomically with its exact hook validation immediately before patching. */
    if (Q(LOADER_L2_SLOT)!=LOADER_L2_RO) {
        phase(c,g,LOADER_FAILED); return LOADER_BAD_L2;
    }
    if (!idle()) { phase(c,g,LOADER_FAILED); return LOADER_NOT_IDLE; }
    LoaderResidentEntry entry=(LoaderResidentEntry)(uintptr_t)(c->resident+c->entry_offset);
    c->entry_result=entry(installing ? LOADER_INSTALL_ENTRY : LOADER_REMOVE_ENTRY,c,c->ctr);
    phase(c,g,c->entry_result ? LOADER_FAILED : installing ? LOADER_COMMITTED : LOADER_REMOVED);
    return c->entry_result ? LOADER_ENTRY_FAILED : LOADER_OK;
}

/* The existing byte-identical launch.S publishes the staging window and jumps
 * here at +0x100. Restore the writer callback BEFORE consulting host control. */
__attribute__((section(".text.entry"), minsize))
u32 bootstrap(u32 block, u32 count, void *buffer) {
    Q(LOADER_CALLBACK)=LOADER_ORIGINAL;
    __asm__ volatile("dsb ish" ::: "memory");
    struct LoaderControl c;
    memcpy(&c,(const void *)&loader_control,sizeof(c));
    __asm__ volatile("mrs %0, CurrentEL\n mrs %1, ctr_el0" : "=r"(c.el),"=r"(c.ctr));
    c.mair=c.tcr=0; c.result=LOADER_BAD_ABI; c.entry_result=0;
    if (c.magic!=LOADER_CONTROL_MAGIC || c.abi_version!=LOADER_ABI_VERSION ||
        c.struct_size!=sizeof(c) || c.reserved0) goto finish;
    for (u32 i=0;i<6;i++) if (c.reserved[i]) goto finish;
    c.result=LOADER_BAD_NONCE;
    if (!c.request_nonce || !c.identity_nonce || c.done) goto finish;
    c.result=LOADER_BAD_EL;
    if (c.el!=4) goto finish;
    __asm__ volatile("mrs %0, mair_el1\n mrs %1, tcr_el1" : "=r"(c.mair),"=r"(c.tcr));
    c.result=LOADER_BAD_L2;
    if (Q(LOADER_L2_SLOT)!=LOADER_L2_RO) goto finish;
    c.result=LOADER_NOT_IDLE;
    if (!idle()) goto finish;
    c.result=LOADER_BAD_EXTENT;
    if (!extents(&c)) goto finish;
    c.result=LOADER_BAD_RANGE;
    if (!transport(&c)) goto finish;
    c.result=LOADER_BAD_COMMAND;
    if (c.command==LOADER_PREPARE) c.result=prepare(&c);
    else if (c.command==LOADER_COMMIT || c.command==LOADER_REMOVE) c.result=resident_command(&c);
finish:
    c.storage_rc=((u32 (*)(u32,u32,void *))(uintptr_t)LOADER_ORIGINAL)(block,count,buffer);
    c.done=0;
    memcpy((void *)&loader_control,&c,sizeof(c));
    if (c.el==4) publish((u64)(uintptr_t)&loader_control,
                         (u64)(uintptr_t)&loader_control+sizeof(c),c.ctr,0);
    __asm__ volatile("dsb ish" ::: "memory");
    loader_control.done=c.request_nonce;
    if (c.el==4) publish((u64)(uintptr_t)&loader_control.done,
                         (u64)(uintptr_t)&loader_control.done+8,c.ctr,0);
    return c.storage_rc;
}
