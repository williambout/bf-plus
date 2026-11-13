/* BF+ optional Doom package, little endian. No firmware or filesystem calls. */
#ifndef BFPLUS_DOOM_PACKAGE_H
#define BFPLUS_DOOM_PACKAGE_H
#include <stdint.h>
#include <stddef.h>

#define DOOM_PACKAGE_MAGIC UINT64_C(0x314d4f4f44504642) /* BFPDOOM1 */
#define DOOM_PACKAGE_HEADER 128u
#define DOOM_MODULE_MAX (4u*1024u*1024u)
#define DOOM_WAD_MAX (64u*1024u*1024u)
#define DOOM_HEAP_MAX (32u*1024u*1024u)
#define DOOM_STACK_BYTES (256u*1024u)
struct DoomPackage {
    uint64_t magic;
    uint32_t abi, header_bytes, file_bytes, image_bytes, memory_bytes;
    uint32_t entry_offset, reloc_offset, reloc_count, wad_offset, wad_bytes;
    uint32_t heap_bytes, data_start, data_end, crc32;
    uint8_t reserved[64];
};
struct DoomRelocation { uint64_t offset, addend; };
_Static_assert(sizeof(struct DoomPackage)==128,"Doom package ABI");
static inline uint32_t doom_crc32(uint32_t crc,const void *data,size_t size) {
    const uint8_t *p=data;
    for (size_t i=0;i<size;i++) {
        crc^=p[i];
        for (unsigned bit=0;bit<8;bit++)
            crc=(crc>>1)^(0xedb88320u & (0u-(crc&1u)));
    }
    return crc;
}
static inline int doom_package_header(const struct DoomPackage *h) {
    if (!h || h->magic!=DOOM_PACKAGE_MAGIC || h->abi!=1 || h->header_bytes!=128 ||
        h->image_bytes<4 || h->image_bytes>DOOM_MODULE_MAX ||
        h->memory_bytes<h->image_bytes || h->memory_bytes>DOOM_MODULE_MAX ||
        (h->memory_bytes&63) || h->entry_offset>=h->data_start ||
        (h->entry_offset&3) || h->data_start>h->data_end ||
        h->data_end>h->image_bytes || h->data_start<4 ||
        h->reloc_count>16384 || h->reloc_offset!=128+h->image_bytes ||
        (h->reloc_offset&7) || h->wad_bytes<12 || h->wad_bytes>DOOM_WAD_MAX ||
        h->heap_bytes<8u*1024u*1024u || h->heap_bytes>DOOM_HEAP_MAX ||
        (h->heap_bytes&63) ||
        h->wad_offset!=h->reloc_offset+16*h->reloc_count ||
        h->file_bytes!=h->wad_offset+h->wad_bytes) return 0;
    for (unsigned i=0;i<64;i++) if (h->reserved[i]) return 0;
    return 1;
}
/* The image is unreferenced until every relocation and checksum is checked.
 * Sorted, unique, aligned relocations may write only initialized writable
 * module data; their values may refer to code, data, or BSS in this module. */
static inline int doom_package_verify(const uint8_t *file,size_t bytes) {
    if (!file || bytes<128 || ((uintptr_t)file&7u)) return 0;
    const struct DoomPackage *h=(const void *)file;
    if (!doom_package_header(h) || bytes!=h->file_bytes) return 0;
    uint32_t zero=0, crc=doom_crc32(~0u,file,60);
    crc=doom_crc32(crc,&zero,4);
    crc=doom_crc32(crc,file+64,bytes-64);
    if ((crc^~0u)!=h->crc32) return 0;
    const struct DoomRelocation *r=(const void *)(file+h->reloc_offset);
    for (uint32_t i=0;i<h->reloc_count;i++)
        if ((r[i].offset&7u) || r[i].offset<h->data_start ||
            h->data_end<8 || r[i].offset>h->data_end-8 ||
            r[i].addend>=h->memory_bytes || (i && r[i].offset<=r[i-1].offset)) return 0;
    return 1;
}
static inline size_t doom_package_allocation(const struct DoomPackage *h) {
    if (!doom_package_header(h)) return 0;
    return (size_t)4095+h->memory_bytes+((h->file_bytes+63u)&~63u)+
           h->heap_bytes+DOOM_STACK_BYTES;
}
#endif
