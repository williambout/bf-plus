/* SPDX-License-Identifier: GPL-2.0-or-later
 * A small nonlocal return boundary for Doom's exit/error callbacks.
 * Never cross a host frame: setjmp and longjmp are entirely inside entry(). */
#ifdef __APPLE__
#define SYM(x) _##x
#else
#define SYM(x) x
#endif
.text
.p2align 2
.globl SYM(bfdoom_setjmp)
.globl SYM(bfdoom_longjmp)
#ifndef __APPLE__
.hidden bfdoom_setjmp
.hidden bfdoom_longjmp
#endif
#if defined(__aarch64__)
SYM(bfdoom_setjmp):
    stp x19, x20, [x0, #0]
    stp x21, x22, [x0, #16]
    stp x23, x24, [x0, #32]
    stp x25, x26, [x0, #48]
    stp x27, x28, [x0, #64]
    stp x29, x30, [x0, #80]
    mov x1, sp
    str x1, [x0, #96]
#ifndef BFDOOM_GENERAL_REGS
    stp d8, d9, [x0, #112]
    stp d10, d11, [x0, #128]
    stp d12, d13, [x0, #144]
    stp d14, d15, [x0, #160]
#endif
    mov w0, #0
    ret
SYM(bfdoom_longjmp):
    ldp x19, x20, [x0, #0]
    ldp x21, x22, [x0, #16]
    ldp x23, x24, [x0, #32]
    ldp x25, x26, [x0, #48]
    ldp x27, x28, [x0, #64]
    ldp x29, x30, [x0, #80]
    ldr x1, [x0, #96]
    mov sp, x1
#ifndef BFDOOM_GENERAL_REGS
    ldp d8, d9, [x0, #112]
    ldp d10, d11, [x0, #128]
    ldp d12, d13, [x0, #144]
    ldp d14, d15, [x0, #160]
#endif
    mov w0, #1
    ret
#elif defined(__x86_64__)
SYM(bfdoom_setjmp):
    movq %rbx, 0(%rdi)
    movq %rbp, 8(%rdi)
    movq %r12, 16(%rdi)
    movq %r13, 24(%rdi)
    movq %r14, 32(%rdi)
    movq %r15, 40(%rdi)
    leaq 8(%rsp), %rax
    movq %rax, 48(%rdi)
    movq (%rsp), %rax
    movq %rax, 56(%rdi)
    xorl %eax, %eax
    ret
SYM(bfdoom_longjmp):
    movq 0(%rdi), %rbx
    movq 8(%rdi), %rbp
    movq 16(%rdi), %r12
    movq 24(%rdi), %r13
    movq 32(%rdi), %r14
    movq 40(%rdi), %r15
    movq 48(%rdi), %rsp
    movl $1, %eax
    jmp *56(%rdi)
#else
#error "Nonlocal return is implemented for AArch64 and x86-64 only"
#endif
#ifndef __APPLE__
.section .note.GNU-stack,"",@progbits
#endif
