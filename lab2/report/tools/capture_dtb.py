#!/usr/bin/env python3
"""Capture real guest-GDB DTB observations without replacing existing evidence."""
import hashlib
import json
from pathlib import Path
import socket
import subprocess
import time

REPORT = Path(__file__).resolve().parent.parent
CODE = REPORT.parent / 'code'

def capture(memory):
    destination = REPORT / 'evidence' / ('dtb-' + memory)
    destination.mkdir(parents=True, exist_ok=True)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    command = ['qemu-system-riscv64', '-machine', 'virt', '-m', memory,
               '-display', 'none', '-monitor', 'none', '-bios', 'default',
               '-serial', 'file:' + str(destination / 'qemu.log'),
               '-kernel', str(CODE / 'bin/best_fit/0/ucore.img'),
               '-gdb', 'tcp:127.0.0.1:' + str(port), '-S']
    debugger = ['gdb-multiarch', '-q', '-nx', '-batch',
                str(CODE / 'bin/best_fit/0/kernel'),
                '-ex', 'target remote 127.0.0.1:' + str(port),
                '-x', str(REPORT / 'tools/dtb.gdb')]
    proc = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic() + 10
        while True:
            if proc.poll() is not None:
                raise RuntimeError(proc.stderr.read().decode(errors='replace'))
            try:
                with socket.create_connection(('127.0.0.1', port), timeout=.2):
                    break
            except OSError:
                if time.monotonic() > deadline:
                    raise RuntimeError('GDB stub startup timed out')
                time.sleep(.05)
        with (destination / 'gdb.log').open('w', encoding='utf-8') as output:
            subprocess.run(debugger, cwd=CODE, stdout=output, stderr=subprocess.STDOUT,
                           timeout=60, check=True)
        deadline = time.monotonic() + 25
        while True:
            serial = (destination / 'qemu.log').read_text(errors='replace')
            if '[PANIC]' in serial:
                raise RuntimeError('Unexpected guest panic')
            if 'LAB2 B SELFTESTS PASSED: best_fit_pmm_manager' in serial:
                break
            if proc.poll() is not None or time.monotonic() > deadline:
                raise RuntimeError('Selftests did not complete')
            time.sleep(.05)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill(); proc.wait(timeout=5)
        proc.stderr.close()
    trace = (destination / 'gdb.log').read_text()
    if 'LAB2 DTB DEBUG CHECKS PASSED' not in trace:
        raise RuntimeError('Missing DTB completion marker')
    manifest = {'memory':memory,'qemu_command':command,'gdb_command':debugger,
                'sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in (destination/'gdb.log',destination/'qemu.log')}}
    (destination / 'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print('PASS: DTB native parser + GDB + selftests, ' + memory, flush=True)

if __name__ == '__main__':
    subprocess.run(['make','-j2','PMM=best_fit','TEST_CASE=0'],cwd=CODE,check=True)
    for memory in ('64M','128M','256M'):
        capture(memory)
