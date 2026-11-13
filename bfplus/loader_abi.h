/* BF+ segmented RAM loader v1. Shared by the standalone loader and resident.
 * All offsets are little-endian; this header has no installation side effects. */
#ifndef BF_PLUS_LOADER_ABI_H
#define BF_PLUS_LOADER_ABI_H
#include <stdint.h>

#define LOADER_ABI_VERSION 1u
#define LOADER_CONTROL_MAGIC UINT64_C(0x313044414f4c4642) /* BFLOAD01 */
#define LOADER_GUARD_MAGIC UINT64_C(0x3130304452474642)   /* BFGRD001 */
#define LOADER_CONTROL_BYTES 256u
#define LOADER_GUARD_BYTES 256u
#define LOADER_ALIGNMENT 4096u
#define LOADER_TRANSFER_MAX 0x4000u
#define LOADER_MEMORY_MAX 0x10000u
#define LOADER_SCRATCH_MAX 0x1000000u
#define LOADER_PORTRAIT_SCRATCH 0x155000u
#define LOADER_STAGE_OFFSET 0xc000u
#define LOADER_TRANSPORT_BYTES 0x10080u
#define LOADER_RAM_MIN UINT64_C(0x400d20c00)
#define LOADER_RAM_END UINT64_C(0x500000000)
#define LOADER_CALLBACK UINT64_C(0x4d729bd00)
#define LOADER_ORIGINAL UINT64_C(0x4d31254f0)
#define LOADER_L2_SLOT UINT64_C(0x4d71484c8)
#define LOADER_L2_RO UINT64_C(0x4d3200781)

enum LoaderCommand { LOADER_PREPARE=1, LOADER_COMMIT=2, LOADER_REMOVE=3 };
enum LoaderOperation { LOADER_INSTALL_ENTRY=0, LOADER_REMOVE_ENTRY=1 };
enum LoaderPhase {
    LOADER_EMPTY=0, LOADER_PREPARING=1, LOADER_COMMITTING=2,
    LOADER_COMMITTED=3, LOADER_REMOVING=4, LOADER_REMOVED=5, LOADER_FAILED=6
};
enum LoaderResult {
    LOADER_OK=0, LOADER_BAD_ABI=1, LOADER_BAD_EL=2, LOADER_BAD_L2=3,
    LOADER_NOT_IDLE=4, LOADER_BAD_EXTENT=5, LOADER_ALLOC_FAILED=6,
    LOADER_BAD_RANGE=7, LOADER_BAD_GUARD=8, LOADER_BAD_PHASE=9,
    LOADER_BAD_CRC=10, LOADER_ENTRY_FAILED=11, LOADER_BAD_COMMAND=12,
    LOADER_BAD_NONCE=13
};

struct LoaderControl {
    uint64_t magic;                        /* 0 */
    uint32_t abi_version, struct_size;      /* 8,12 */
    uint64_t request_nonce, done;           /* 16,24: done is published last */
    uint32_t command, mode, result, storage_rc; /* 32..44 */
    uint64_t identity_nonce, owner, resident, guard; /* 48..72 */
    uint64_t image_size, memory_size, scratch_size, entry_offset; /* 80..104 */
    uint32_t image_crc32, phase, entry_result, reserved0; /* 112..124 */
    uint64_t el, ctr, mair, tcr;             /* 128..152, observations */
    uint8_t image_sha256[32];               /* 160, identity; not device SHA */
    uint64_t transport_buffer, allocation_size; /* 192,200 */
    uint64_t reserved[6];                   /* 208..255, must be zero */
};

struct LoaderGuard {
    uint64_t magic;
    uint32_t abi_version, phase;
    uint64_t identity_nonce, owner, resident;
    uint64_t image_size, memory_size, scratch_size, entry_offset;
    uint32_t image_crc32, mode;
    uint8_t image_sha256[32];
    uint64_t allocation_size, last_request;
    uint32_t entry_result, reserved[31];
};

/* Return 0 only after successful exact install/remove. Nonzero must leave
 * hooks unchanged. Entry validates its own compiled extents and state, gates
 * idle/L2 again, and performs all hook checks before patch_all publication.
 * It must not retain the control pointer (a temporary loader stack snapshot).
 * identity_nonce identifies the installation; request_nonce changes per command.
 * owner is the allocator result; resident is aligned; scratch is resident+memory_size.
 * Removal must leave queued wrappers safe and retain owner until reboot. */
typedef uint32_t (*LoaderResidentEntry)(uint32_t operation,
                                      const struct LoaderControl *control,
                                      uint64_t ctr);

_Static_assert(sizeof(struct LoaderControl)==256, "loader control ABI");
_Static_assert(sizeof(struct LoaderGuard)==256, "loader guard ABI");
_Static_assert(__builtin_offsetof(struct LoaderControl,done)==24, "completion ABI");
_Static_assert(__builtin_offsetof(struct LoaderControl,image_sha256)==160, "hash ABI");
_Static_assert(__builtin_offsetof(struct LoaderGuard,last_request)==120, "guard ABI");
#endif
