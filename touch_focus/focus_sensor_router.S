/* Preserve the native call's LR, SP and receiver x20..x23 before entering C.
 * These context registers are used only at the exact PAS call sites.
 * x18, callee-saved registers and SIMD state are untouched. */
.section .text.focus_sensor_router,"ax"
.global focus_sensor_wrapper
.hidden focus_sensor_wrapper
.hidden focus_sensor_dispatch
focus_sensor_wrapper:
    sub sp, sp, #64
    str x30, [sp]
    add x9, sp, #64
    str x9, [sp, #8]
    stp x20, x21, [sp, #16]
    stp x22, x23, [sp, #32]
    mov x4, sp
    bl focus_sensor_dispatch
    ldr x30, [sp]
    add sp, sp, #64
    ret
