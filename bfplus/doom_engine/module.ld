/* No firmware addresses. All virtual addresses are offsets from load base. */
ENTRY(bfdoom_entry)
PHDRS {
    text PT_LOAD FLAGS(5);
    ro PT_LOAD FLAGS(4);
    rw PT_LOAD FLAGS(6);
    dynamic PT_DYNAMIC FLAGS(6);
}
SECTIONS {
    . = 0;
    .text : { *(.text .text.*) } :text
    . = ALIGN(4096);
    .rodata : { *(.rodata .rodata.*) } :ro
    .dynsym : { *(.dynsym) } :ro
    .gnu.hash : { *(.gnu.hash) } :ro
    .hash : { *(.hash) } :ro
    .dynstr : { *(.dynstr) } :ro
    .rela.dyn : { *(.rela.dyn) } :ro
    . = ALIGN(4096);
    .data : { *(.data .data.*) } :rw
    bfdoom_state : {
        __start_bfdoom_state = .;
        *(bfdoom_state)
        __stop_bfdoom_state = .;
    } :rw
    .got : { *(.got .got.*) } :rw
    .dynamic : { *(.dynamic) } :rw :dynamic
    .bss (NOLOAD) : { *(.bss .bss.* COMMON) } :rw
    __bfdoom_end = .;
    /DISCARD/ : { *(.comment .note.* .eh_frame .eh_frame_hdr) }
}
