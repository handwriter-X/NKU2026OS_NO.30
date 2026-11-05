#include <stdio.h>
#include <string.h>
#include <sbi.h>
#include <dtb.h>
#include <pmm.h>
#include <selftest.h>
#include <trap.h>
#include <clock.h>
#include <intr.h>
/* lab2: 2414067 - original a0/a1 pass through entry.S unchanged. */
int kern_init(uintptr_t hartid, uintptr_t dtb_pa) __attribute__((noreturn));

int kern_init(uintptr_t hartid, uintptr_t dtb_pa) {
    extern char edata[], end[];
    memset(edata, 0, end - edata);

    const char *message = "(THU.CST) os is loading ...\n";
    cprintf("%s\n\n", message);
    dtb_init(hartid,dtb_pa);
    pmm_init();
    run_selftests();
    idt_init();
    /* lab3: 2411520 - install the entry before enabling timer interrupts. */
    clock_init();
    intr_enable();
   while (1)
        ;
}
