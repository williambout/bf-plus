ENTRY(launch)
SECTIONS {
  . = 0;
  __start = .;
  .text : { KEEP(*(.text.launch)) . = 0x100; KEEP(*(.text.entry)) *(.text*) }
  .rodata : { *(.rodata*) }
  . = ALIGN(64);
  .data : { KEEP(*(.data.control)) *(.data*) }
  . = ALIGN(64);
  __image_end = .;
  .bss (NOLOAD) : { *(.bss*) *(COMMON) }
  __end = .;
  /DISCARD/ : { *(.comment*) *(.note*) *(.eh_frame*) }
}
ASSERT(launch == 0, "loader launch moved")
ASSERT(bootstrap == 0x100, "loader bootstrap moved")
ASSERT(__image_end <= 0x4000, "loader exceeds transport staging")
ASSERT(__end == __image_end, "loader requires unstaged BSS")
ASSERT((loader_control & 63) == 0, "loader control alignment")
ASSERT(loader_control >= 0x100 && loader_control + 256 <= __image_end, "loader control extent")
