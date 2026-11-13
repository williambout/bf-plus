/* BF 1.04 segment 05: read-only access through the native file-service task.
 * Evidence: decoded-V104/rtos-alt.bin SHA256
 * f747c1350f00526b9c68c65aaef44d6e7b644b0169992342e12f059c42e150dc.
 * Public FS_Open/Read/Close at 313b9e0/313bb50/313baf0 dispatch through
 * 313d350 and wait at 3141040; the stock file loader at 31a0040 uses them.
 * Addresses below include the 0x4d3000000 image base. See the investigation
 * in .touch-focus/doom-research.md for the call chains and host checks.
 *
 * Call only from a task allowed to block, never an ISR or the file-service
 * task itself. Serialize use of each handle. Buffers must remain valid until
 * return. These functions do not mount storage, write files, allocate module
 * memory, validate packages, or publish executable code/cache state.
 *
 * Original instructions were checked with Capstone and exercised in Unicorn
 * with mocked storage/RTOS endpoints. No camera validation was performed.
 * J:\ is a stock firmware path (31a05dc..31a0604); whether a file copied by
 * MTP is visible there in the current USB mode remains unverified.
 */
#ifndef BFPLUS_DOOM_STORAGE_H
#define BFPLUS_DOOM_STORAGE_H
#include <stdint.h>

#define DOOM_PACKAGE_PATH "J:\\DOOM.BFP"

/* Native handles are opaque 64-bit values, not POSIX int descriptors. */
typedef uint64_t DoomFile;

static inline DoomFile doom_file_open(const char *path) {
    if (!path || !*path) return 0;
    /* Mode 0 becomes "r" at 31424a0; the public entry copies the path
     * before the lower wrapper translates its logical drive in place.
     * Native maximum path length is 527 bytes excluding the terminator. */
    return ((DoomFile (*)(const char *, uint32_t))(uintptr_t)
            UINT64_C(0x4d313b9e0))(path,0);
}

/* Return bytes read, 0 at EOF, or -1 on invalid input/native failure.
 * Native FS_Read(handle,buffer,u32 requested,u32 *actual) returns status
 * 0 on success, 4 on EOF/short read, 1 on other failures. Its worker uses
 * a separate u64 count internally; the PUBLIC entry writes only four bytes.
 * A short read is not an exact-read success; the package loader must enforce
 * its declared lengths. Zero-length reads are handled without native I/O. */
static inline int32_t doom_file_read(DoomFile file,void *buffer,uint32_t count) {
    if (!file || count>INT32_MAX || (count && !buffer)) return -1;
    if (!count) return 0;
    uint32_t actual=0;
    uint32_t status=((uint32_t (*)(DoomFile,void *,uint32_t,uint32_t *))
                     (uintptr_t)UINT64_C(0x4d313bb50))(file,buffer,count,&actual);
    if ((status!=0 && status!=4) || actual>count) return -1;
    return (int32_t)actual;
}

static inline void doom_file_close(DoomFile file) {
    /* The public close waits, but does not load the worker's close status
     * before returning. Do not claim that its return register is that status. */
    if (file)
        ((void (*)(DoomFile))(uintptr_t)UINT64_C(0x4d313baf0))(file);
}
#endif
