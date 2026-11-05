/* Lab3 support reconstructed from the local lab2026-book; see README.md. */
#include <trap.h>
#include <riscv.h>
#include <stdio.h>
#include <clock.h>
#include <sbi.h>
#include <assert.h>

#define TICK_NUM 100
/* The offline book names this constant but supplies no value: use 10 lines. */
#define SHUTDOWN_AFTER 10

static void print_ticks(void) {
    cprintf("%d ticks\n", TICK_NUM);
#ifdef DEBUG_GRADE
    cprintf("End of Test.\n");
    panic("EOT: kernel seems ok.");
#endif
}

void idt_init(void) {
    extern void __alltraps(void);
    write_csr(sscratch, 0);
    write_csr(stvec, &__alltraps);
}

void print_trapframe(struct trapframe *tf) {
    const uintptr_t *regs = (const uintptr_t *)&tf->gpr;
    cprintf("trapframe at %p\n", tf);
    for (int i = 0; i < 32; ++i)
        cprintf("  x%d 0x%016lx\n", i, (unsigned long)regs[i]);
    cprintf("  status   0x%016lx\n", (unsigned long)tf->status);
    cprintf("  epc      0x%016lx\n", (unsigned long)tf->epc);
    cprintf("  badvaddr 0x%016lx\n", (unsigned long)tf->badvaddr);
    cprintf("  cause    0x%016lx\n", (unsigned long)tf->cause);
}

void interrupt_handler(struct trapframe *tf) {
    /* lab3: 2411520 */
    static size_t printed_lines;
    static bool shutdown_requested;
    uintptr_t cause = (tf->cause << 1) >> 1;
    const char *type;

    switch (cause) {
    case IRQ_S_TIMER:
        clock_set_next_event();
        ++ticks;
        if (ticks % TICK_NUM == 0) {
            print_ticks();
            ++printed_lines;
            if (printed_lines >= SHUTDOWN_AFTER && !shutdown_requested) {
                shutdown_requested = 1;
                sbi_shutdown();
            }
        }
        return;
    case IRQ_U_SOFT:  type = "User software"; break;
    case IRQ_S_SOFT:  type = "Supervisor software"; break;
    case IRQ_H_SOFT:  type = "Hypervisor software"; break;
    case IRQ_M_SOFT:  type = "Machine software"; break;
    case IRQ_U_TIMER: type = "User timer"; break;
    case IRQ_H_TIMER: type = "Hypervisor timer"; break;
    case IRQ_M_TIMER: type = "Machine timer"; break;
    case IRQ_U_EXT:   type = "User external"; break;
    case IRQ_S_EXT:   type = "Supervisor external"; break;
    case IRQ_H_EXT:   type = "Hypervisor external"; break;
    case IRQ_M_EXT:   type = "Machine external"; break;
    case IRQ_COP:     type = "Coprocessor"; break;
    case IRQ_HOST:    type = "Host"; break;
    default:
        print_trapframe(tf);
        return;
    }
    cprintf("%s interrupt (cause=%lu)\n", type, (unsigned long)cause);
}

void exception_handler(struct trapframe *tf) {
    /* lab3: 2412267 */
    const char *type;
    switch (tf->cause) {
    case CAUSE_ILLEGAL_INSTRUCTION:
        type = "Illegal instruction";
        break;
    case CAUSE_BREAKPOINT:
        type = "Breakpoint";
        break;
    default:
        print_trapframe(tf);
        return;
    }

    cprintf("Exception type: %s\n", type);
    cprintf("Exception epc: 0x%016lx\n", (unsigned long)tf->epc);
    uint16_t instruction = *(const volatile uint16_t *)tf->epc;
    tf->epc += (instruction & 3) == 3 ? 4 : 2;
}

static inline void trap_dispatch(struct trapframe *tf) {
    if ((intptr_t)tf->cause < 0) {
        interrupt_handler(tf);
    } else {
        exception_handler(tf);
    }
}

void trap(struct trapframe *tf) { trap_dispatch(tf); }
