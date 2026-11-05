#!/usr/bin/env python3
"""P2: behavior with mocked devices, then a real QEMU boot to SBI shutdown."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile


def host_tests(evidence, harness="tools/p2_handler_test.c",
               scenarios=("timer", "independent-count", "non-timer")):
    # Only hardware/console dependencies are mocked; compile actual trap.c and trap.h.
    with tempfile.TemporaryDirectory(prefix="lab3-p2-") as directory:
        fixture = Path(directory)
        (fixture / "defs.h").write_text(
            "#include <stdint.h>\n#include <stddef.h>\ntypedef int bool;\n")
        irq_definitions = "\n".join(line for line in Path("libs/riscv.h").read_text().splitlines()
                                     if re.match(r"#define (IRQ_|CAUSE_)", line))
        (fixture / "riscv.h").write_text(
            irq_definitions + "\n#define write_csr(reg, val) ((void)(val))\n")
        (fixture / "clock.h").write_text(
            "#include <stddef.h>\nextern volatile size_t ticks;\nvoid clock_set_next_event(void);\n")
        (fixture / "sbi.h").write_text("void sbi_shutdown(void);\n")
        # Production cprintf declaration, without replacing the host stdio header.
        (fixture / "console_decl.h").write_text("int cprintf(const char *, ...);\n")
        command = ["cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-Wno-unused-parameter",
                   "-Wno-unused-function", "-include", str(fixture / "console_decl.h"),
                   "-I", str(fixture), "-I", "kern/trap", harness,
                   "-o", str(fixture / "p2-test")]
        build = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        (evidence / "host-build.log").write_text(build.stdout)
        if build.returncode:
            raise RuntimeError(build.stdout)
        outputs = []
        for scenario in scenarios:
            result = subprocess.run([str(fixture / "p2-test"), scenario],
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=5)
            outputs.append(result.stdout)
            if result.returncode:
                (evidence / "host-tests.log").write_text("".join(outputs))
                raise RuntimeError(f"Host scenario failed: {scenario}\n{result.stdout}")
        (evidence / "host-tests.log").write_text("".join(outputs))
        return outputs


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--qemu", default="qemu-system-riscv64")
    parser.add_argument("--image", default="bin/best_fit/0/ucore.img")
    parser.add_argument("--memory", default="128M")
    parser.add_argument("--evidence", default="evidence/p2")
    args = parser.parse_args()
    evidence = Path(args.evidence)
    evidence.mkdir(parents=True, exist_ok=True)
    summary = {"stage": "P2", "passed": False}
    try:
        hosts = host_tests(evidence)
        command = [args.qemu, "-machine", "virt", "-m", args.memory, "-nographic",
                   "-bios", "default", "-kernel", args.image]
        environment = {"qemu_command": command, "host_cc": subprocess.check_output(
            ["cc", "--version"], text=True).splitlines()[0], "qemu_version": subprocess.check_output(
            [args.qemu, "--version"], text=True).splitlines()[0]}
        (evidence / "environment.json").write_text(json.dumps(environment, indent=2) + "\n")
        with (evidence / "qemu.log").open("w") as output:
            try:
                result = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=output,
                                        stderr=subprocess.STDOUT, timeout=25)
            except subprocess.TimeoutExpired:
                raise RuntimeError("QEMU did not shut down within 25 seconds") from None
        log = (evidence / "qemu.log").read_text()
        tick_lines = re.findall(r"(?m)^100 ticks$", log)
        assert result.returncode == 0, f"QEMU exit code {result.returncode}"
        assert len(tick_lines) == 10, f"Expected 10 tick lines; got {len(tick_lines)}"
        assert "LAB2 B SELFTESTS PASSED:" in log, "lab2 baseline selftests did not finish"
        assert log.count("++ setup timer interrupts") == 1, "clock initialization missing/repeated"
        assert "[PANIC]" not in log and "trapframe at " not in log, "unexpected panic/trap"
        sources = ["kern/trap/trap.c", "kern/init/init.c", "libs/sbi.c", "kern/driver/clock.c",
                   "libs/sbi.h", "kern/trap/trap.h", "kern/trap/trapentry.S"]
        summary.update(passed=True, host_scenarios=3, tick_lines=len(tick_lines), qemu_exit=0,
                       source_sha256={name: hashlib.sha256(Path(name).read_bytes()).hexdigest()
                                      for name in sources})
        for output in hosts:
            print(output.strip())
        print("P2 PASS: QEMU printed 10 x 100 ticks and shut down; host behavior checks passed")
    except (AssertionError, RuntimeError, subprocess.SubprocessError) as error:
        summary["error"] = str(error)
        print(f"P2 FAIL: {error}")
    finally:
        (evidence / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    if not summary["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
