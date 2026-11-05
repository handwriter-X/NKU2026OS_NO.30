#!/usr/bin/env python3
"""Real 16/32-bit exceptions followed by timer boot-to-shutdown, plus host boundaries."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import socket
import subprocess
from verify_p2 import host_tests


GDB_SCRIPT = r'''
set pagination off
set confirm off
set remotetimeout 10
target remote 127.0.0.1:PORT
hbreak idt_init
continue
finish
python
import gdb, json
inf = gdb.selected_inferior()
def reg(name):
    return int(gdb.parse_and_eval("$" + name)) & ((1 << 64) - 1)
def check(ok, message):
    if not ok:
        raise gdb.GdbError(message)
def breakpoint(symbol):
    return gdb.Breakpoint(symbol, type=gdb.BP_HARDWARE_BREAKPOINT)
gdb.execute("delete breakpoints")
site = reg("pc")
boot_regs = [reg("x%d" % i) for i in range(32)]
boot_status = reg("sstatus")
results = []
cases = [("illegal16", b'\x00\x00', 2),
         ("illegal32", b'\x73\x10\x00\xc0', 2),
         ("breakpoint16", b'\x02\x90', 3),
         ("breakpoint32", b'\x73\x00\x10\x00', 3)]
for name, opcode, cause in cases:
    original = bytes(inf.read_memory(site, len(opcode)))
    inf.write_memory(site, opcode)
    gdb.execute("set $pc = %d" % site)
    for i in range(1, 32):
        if i != 2:
            gdb.execute("set $x%d = %d" % (i, 0x2412267000 + i))
    expected_regs = [reg("x%d" % i) for i in range(32)]
    entry = breakpoint("*trap")
    gdb.execute("continue", to_string=True)
    entry.delete()
    frame = reg("a0")
    before = bytes(inf.read_memory(frame, 36 * 8))
    words = [int.from_bytes(before[8*i:8*i+8], "little") for i in range(36)]
    check(words[:32] == expected_regs, name + " SAVE_ALL registers")
    check(words[33] == site and words[35] == cause, name + " real hardware cause/epc")
    ret = breakpoint("*__trapret")
    gdb.execute("continue", to_string=True)
    ret.delete()
    after = bytes(inf.read_memory(frame, 36 * 8))
    expected = bytearray(before)
    expected[33*8:34*8] = (site + len(opcode)).to_bytes(8, "little")
    check(after == bytes(expected), name + " must change only epc by instruction length")
    resume = breakpoint("*%d" % (site + len(opcode)))
    gdb.execute("continue", to_string=True)
    resume.delete()
    check(reg("pc") == site + len(opcode), name + " sret return address")
    check([reg("x%d" % i) for i in range(32)] == expected_regs, name + " restored registers")
    inf.write_memory(site, original)
    results.append({"case": name, "cause": cause, "epc_increment": len(opcode),
                    "only_epc_changed": True, "returned": True})
    print("P3 CASE PASS: " + name, flush=True)
# Restore the original boot context; now run actual timer interrupts after exceptions.
for i in range(1, 32):
    gdb.execute("set $x%d = %d" % (i, boot_regs[i]))
gdb.execute("set $pc = %d" % site)
gdb.execute("set $sstatus = %d" % boot_status)
shutdown = breakpoint("*sbi_shutdown")
gdb.execute("continue", to_string=True)
check(int(gdb.parse_and_eval("ticks")) == 1000, "shutdown must occur at tick 1000")
shutdown.delete()
print("P3_RESULTS=" + json.dumps(results, sort_keys=True), flush=True)
print("P3 GDB PASS: four real exception returns, then 1000 timer interrupts", flush=True)
end
detach
quit
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--qemu", default="qemu-system-riscv64")
    parser.add_argument("--gdb", default="gdb-multiarch")
    parser.add_argument("--image", default="bin/best_fit/0/ucore.img")
    parser.add_argument("--kernel", default="bin/best_fit/0/kernel")
    parser.add_argument("--memory", default="128M")
    args = parser.parse_args()
    evidence = Path("evidence/p3")
    evidence.mkdir(parents=True, exist_ok=True)
    summary = {"stage": "P3", "passed": False}
    qemu = None
    try:
        hosts = host_tests(evidence, "tools/p3_handler_test.c", ("exceptions",))
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        script = evidence / "verify.gdb"
        script.write_text(GDB_SCRIPT.replace("PORT", str(port)))
        command = [args.qemu, "-machine", "virt", "-m", args.memory, "-nographic", "-bios", "default",
                   "-kernel", args.image, "-S", "-gdb", f"tcp:127.0.0.1:{port}"]
        (evidence / "environment.json").write_text(json.dumps({"qemu_command": command,
            "qemu_version": subprocess.check_output([args.qemu, "--version"], text=True).splitlines()[0],
            "gdb_version": subprocess.check_output([args.gdb, "--version"], text=True).splitlines()[0]}, indent=2) + "\n")
        with (evidence / "qemu.log").open("w") as output:
            qemu = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT)
            with (evidence / "gdb.log").open("w") as gdb_log:
                result = subprocess.run([args.gdb, "-q", "-nx", "-batch", args.kernel, "-x", str(script)],
                                        stdout=gdb_log, stderr=subprocess.STDOUT, timeout=35)
            assert result.returncode == 0, "GDB verification failed; see gdb.log"
            qemu.wait(timeout=5)
        log = (evidence / "qemu.log").read_text()
        gdb_log = (evidence / "gdb.log").read_text()
        assert "P3 GDB PASS:" in gdb_log, "GDB success marker missing"
        assert qemu.returncode == 0, f"QEMU exit={qemu.returncode}"
        assert log.count("Exception type: Illegal instruction") == 2, "illegal output count"
        assert log.count("Exception type: Breakpoint") == 2, "breakpoint output count"
        assert len(re.findall(r"(?m)^Exception epc: 0x[0-9a-f]{16}$", log)) == 4, "exception epc output"
        assert len(re.findall(r"(?m)^100 ticks$", log)) == 10, "timer output count"
        assert "[PANIC]" not in log and "trapframe at " not in log, "unexpected fallback or panic"
        summary.update(passed=True, real_exception_cases=4, host_length_cases=8, host_fallback_causes=15,
                       timer_ticks_at_shutdown=1000, tick_lines=10, qemu_exit=0,
                       source_sha256=hashlib.sha256(Path("kern/trap/trap.c").read_bytes()).hexdigest())
        for output in hosts:
            print(output.strip())
        print("P3 PASS: 4 real exception returns, frame invariants, then 1000 ticks and SBI shutdown")
    except (AssertionError, RuntimeError, subprocess.SubprocessError) as error:
        summary["error"] = str(error)
        print(f"P3 FAIL: {error}")
    finally:
        if qemu is not None and qemu.poll() is None:
            qemu.terminate()
            try:
                qemu.wait(timeout=5)
            except subprocess.TimeoutExpired:
                qemu.kill()
                qemu.wait()
        (evidence / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    if not summary["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
