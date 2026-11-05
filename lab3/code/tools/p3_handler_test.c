/* Compile the production exception handler; simulate only its dependencies. */
#include <stdio.h>
#include <stdarg.h>
#include <string.h>
#include <assert.h>
#include <trap.h>
#include <riscv.h>

volatile size_t ticks;
static char output[8192];
static size_t used;
static unsigned dumps;

int cprintf(const char *format, ...) {
    va_list args;
    va_start(args, format);
    int count = vsnprintf(output + used, sizeof(output) - used, format, args);
    va_end(args);
    assert(count >= 0 && (size_t)count < sizeof(output) - used);
    used += (size_t)count;
    if (strcmp(format, "trapframe at %p\n") == 0) ++dumps;
    return count;
}
void clock_set_next_event(void) { assert(!"exception scheduled a timer"); }
void sbi_shutdown(void) { assert(!"exception requested shutdown"); }
void __alltraps(void) {}

#include "../kern/trap/trap.c"

int main(int argc, char **argv) {
    (void)argc;
    (void)argv;
    unsigned checked = 0;
    /* Include a 32-bit prefix at a halfword-aligned (not word-aligned) address. */
    _Alignas(4) uint16_t code[4] = {0, 0, 0xdead, 0xbeef};
    for (uintptr_t cause = 2; cause <= 3; ++cause) {
        for (unsigned low = 0; low < 4; ++low) {
            code[1] = (uint16_t)(0x1000 | low);
            struct trapframe tf;
            memset(&tf, 0x5a, sizeof(tf));
            tf.cause = cause;
            tf.epc = (uintptr_t)&code[1];
            struct trapframe expected = tf;
            expected.epc += low == 3 ? 4 : 2;
            char expected_output[256];
            snprintf(expected_output, sizeof(expected_output),
                     "Exception type: %s\nException epc: 0x%016lx\n",
                     cause == 2 ? "Illegal instruction" : "Breakpoint", (unsigned long)tf.epc);
            used = 0;
            output[0] = 0;
            exception_handler(&tf);
            assert(memcmp(&tf, &expected, sizeof(tf)) == 0);
            assert(strcmp(output, expected_output) == 0 && dumps == 0);
            ++checked;
        }
    }
    const uintptr_t other[] = {0, 1, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 63};
    for (unsigned i = 0; i < sizeof(other) / sizeof(other[0]); ++i) {
        struct trapframe tf;
        memset(&tf, 0x5a, sizeof(tf));
        tf.cause = other[i];
        tf.epc = 1; /* Unreadable instruction pointer: fallback must not fetch it. */
        struct trapframe original = tf;
        used = 0;
        output[0] = 0;
        exception_handler(&tf);
        assert(memcmp(&tf, &original, sizeof(tf)) == 0);
        assert(dumps == i + 1 && strstr(output, "trapframe at "));
        assert(!strstr(output, "Exception type:"));
    }
    assert(ticks == 0);
    printf("P3 HOST PASS: %u length/type cases; %u fallback causes; only epc may change\n",
           checked, dumps);
    return 0;
}
