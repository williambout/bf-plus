ENTRY(launch)
SECTIONS {
  . = 0;
  __start = .;
  .text : { *(.text.launch) . = 0x100; *(.text.entry) KEEP(*(.text.resident_entry)) *(.text*) }
  .rodata : { *(.rodata*) }
  . = ALIGN(64);
  .data : { *(.data*) }
  . = ALIGN(64);
  __image_end = .;
  .bss (NOLOAD) : { __bss_start = .; *(.bss*) *(COMMON) __bss_end = .; }
  . = ALIGN(64);
  __end = .;
  /DISCARD/ : { *(.comment) *(.note*) *(.eh_frame*) }
}
ASSERT(launch == 0, "launcher moved")
ASSERT(bootstrap == 0x100, "bootstrap moved")
ASSERT(__image_end <= 0x10000, "resident initialized image exceeds supported size")
ASSERT(__end <= 0x10000, "resident allocation exceeds supported size")
ASSERT((state & 63) == 0, "state alignment changed")
