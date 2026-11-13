/* Fixed entry code for subsequent uploads at the same staging address.
 * x0/x1/x2 and the caller's return address retain the storage callback ABI.
 * The C bootstrap is always at +0x100, so this prefix never depends on its size.
 * First execution still uses the camera's established RAM-loader path. */
.section .text.launch,"ax"
.global launch
.hidden launch
.hidden bootstrap
launch:
    adr x9, launch
    add x10, x9, #4, lsl #12
    mrs x11, ctr_el0
    ubfx x11, x11, #16, #4
    mov x12, #4
    lsl x11, x12, x11
1:
    dc cvac, x9
    add x9, x9, x11
    cmp x9, x10
    b.lo 1b
    dsb ish
    ic ialluis
    dsb ish
    isb
    b bootstrap
