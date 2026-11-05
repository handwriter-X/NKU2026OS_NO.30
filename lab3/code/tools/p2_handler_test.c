/* Host-side behavioral checks; includes the unchanged production trap.c. */
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <assert.h>
#include <trap.h>
#include <riscv.h>

volatile size_t ticks;
static unsigned scheduled, lines, shutdowns, frame_dumps;
static size_t ticks_before;
static char events[32], output[8192];
static size_t event_len, output_len;

static void event(char value) {
    assert(event_len + 1 < sizeof(events));
    events[event_len++] = value;
    events[event_len] = 0;
}

int cprintf(const char *format, ...) {
    va_list args;
    va_start(args, format);
    int count = vsnprintf(output + output_len, sizeof(output) - output_len, format, args);
    va_end(args);
    assert(count >= 0 && (size_t)count < sizeof(output) - output_len);
    output_len += (size_t)count;
    if (strcmp(format, "%d ticks\n") == 0) {
        assert(ticks % 100 == 0);
        ++lines;
        event('P');
    }
    if (strcmp(format, "trapframe at %p\n") == 0) ++frame_dumps;
    return count;
}

void clock_set_next_event(void) {
    assert(ticks == ticks_before);  /* Schedule before incrementing ticks. */
    ++scheduled;
    event('E');
}

void sbi_shutdown(void) {
    assert(lines >= 10);
    assert(event_len && events[event_len - 1] == 'P');
    ++shutdowns;
    event('S');
    /* Deliberately return, to verify that shutdown is requested only once. */
}

void __alltraps(void) {}

#include "../kern/trap/trap.c"

static void invoke(uintptr_t cause) {
    struct trapframe tf;
    memset(&tf, 0x5a, sizeof(tf));
    tf.cause = ((uintptr_t)1 << (sizeof(uintptr_t) * 8 - 1)) | cause;
    struct trapframe original = tf;
    ticks_before = ticks;
    event_len = output_len = 0;
    events[0] = output[0] = 0;
    interrupt_handler(&tf);
    assert(memcmp(&tf, &original, sizeof(tf)) == 0);
}

int main(int argc, char **argv) {
    assert(argc == 2);
    if (strcmp(argv[1], "timer") == 0) {
        for (unsigned i = 1; i <= 1100; ++i) {
            invoke(IRQ_S_TIMER);
            assert(ticks == i && scheduled == i && lines == i / 100);
            assert(shutdowns == (i >= 1000));
            const char *expected = i == 1000 ? "EPS" : i % 100 == 0 ? "EP" : "E";
            assert(strcmp(events, expected) == 0);
            assert(strcmp(output, i % 100 == 0 ? "100 ticks\n" : "") == 0);
        }
        assert(frame_dumps == 0);
    } else if (strcmp(argv[1], "independent-count") == 0) {
        for (unsigned i = 1; i <= 11; ++i) {
            ticks = 999;  /* High absolute tick count must not cause early shutdown. */
            invoke(IRQ_S_TIMER);
            assert(ticks == 1000 && lines == i && scheduled == i);
            assert(shutdowns == (i >= 10));
            assert(strcmp(events, i == 10 ? "EPS" : "EP") == 0);
        }
    } else if (strcmp(argv[1], "non-timer") == 0) {
        static const char *names[] = {
            "User software", "Supervisor software", "Hypervisor software", "Machine software",
            "User timer", NULL, "Hypervisor timer", "Machine timer",
            "User external", "Supervisor external", "Hypervisor external", "Machine external",
            "Coprocessor", "Host"
        };
        ticks = 99;
        for (unsigned i = 0; i < sizeof(names) / sizeof(names[0]); ++i) {
            if (i == IRQ_S_TIMER) continue;
            invoke(i);
            char expected[128];
            snprintf(expected, sizeof(expected), "%s interrupt (cause=%u)\n", names[i], i);
            assert(strcmp(output, expected) == 0);
            assert(ticks == 99 && !scheduled && !lines && !shutdowns && !frame_dumps);
        }
        const uintptr_t unknown[] = {14, 63, ((uintptr_t)-1) >> 1};
        for (unsigned i = 0; i < sizeof(unknown) / sizeof(unknown[0]); ++i) {
            invoke(unknown[i]);
            assert(frame_dumps == i + 1 && strstr(output, "trapframe at "));
            assert(strstr(output, "status") && strstr(output, "epc") && strstr(output, "cause"));
            assert(ticks == 99 && !scheduled && !lines && !shutdowns);
        }
    } else {
        return 2;
    }
    printf("P2 HOST PASS: %s; schedule=%u lines=%u shutdown=%u frames=%u\n",
           argv[1], scheduled, lines, shutdowns, frame_dumps);
    return 0;
}
