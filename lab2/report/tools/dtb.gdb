set pagination off
set confirm off
set architecture riscv:rv64
python
import gdb
MASK = (1 << 64) - 1
OFFSET = 0xffffffff40000000
def val(expr):
    return int(gdb.parse_and_eval(expr)) & MASK
def stop(expr):
    gdb.execute('thbreak ' + expr)
    gdb.execute('continue')
def check(ok, message):
    if not ok:
        raise gdb.GdbError(message)
    print('PASS: ' + message)

print('\n=== 1. Firmware parameters at physical kernel entry ===')
stop('*0x80200000')
dtb_pa = val('$a1')
gdb.execute('info registers pc a0 a1 satp')
check(val('$satp') == 0, 'physical entry is Bare')

print('\n=== 2. dtb_init after paging and BSS clearing ===')
stop('dtb_init')
gdb.execute('info args')
gdb.execute('info registers pc satp')
check(val('dtb_pa') == dtb_pa, 'DTB physical argument preserved')
check(val('$satp') >> 60 == 8, 'DTB parser executes under Sv39')
dtb_va = (dtb_pa + OFFSET) & MASK
print('DTB_PA=0x%x DTB_KVA=0x%x' % (dtb_pa, dtb_va))
gdb.execute('x/40bx 0x%x' % dtb_va)

print('\n=== 3. Native parser arguments and independent FDT inspection ===')
stop('dtb_parse')
gdb.execute('info args')
check(val('(unsigned long)blob') == dtb_va, 'parser reads the high direct-map address')
inferior = gdb.selected_inferior()
header = bytes(inferior.read_memory(dtb_va, 40))
fields = [int.from_bytes(header[i:i+4], 'big') for i in range(0, 40, 4)]
magic,total,so,to,ro,version,last,bootcpu,ts,ss = fields
print('FDT magic=0x%x totalsize=%d version=%d last_comp_version=%d' % (magic,total,version,last))
print('offsets: struct=0x%x strings=0x%x reservations=0x%x sizes: struct=%d strings=%d' % (so,to,ro,ss,ts))
check(magic == 0xd00dfeed and 40 <= total <= val('available'), 'FDT header and parser bound agree')
data = bytes(inferior.read_memory(dtb_va, total))
def be32(pos): return int.from_bytes(data[pos:pos+4], 'big')
def align4(pos): return (pos + 3) & ~3
pos = so
stack = []
found = []
while pos < so + ss:
    token = be32(pos); pos += 4
    if token == 1:
        end = data.index(b'\0', pos)
        name = data[pos:end].decode()
        parent = stack[-1] if stack else {'ac':2,'sc':1}
        stack.append({'name':name,'ac':2,'sc':1,'pac':parent['ac'],'psc':parent['sc']})
        pos = align4(end + 1)
    elif token == 2:
        stack.pop()
    elif token == 3:
        length, nameoff = be32(pos), be32(pos+4); pos += 8
        nameend = data.index(b'\0', to+nameoff)
        name = data[to+nameoff:nameend].decode()
        node = stack[-1]
        if name == '#address-cells': node['ac'] = be32(pos)
        if name == '#size-cells': node['sc'] = be32(pos)
        if (node['name']=='memory' or node['name'].startswith('memory@')) and name == 'reg':
            ac,sc=node['pac'],node['psc']
            print('memory node=%s parent address-cells=%d size-cells=%d reg_length=%d' % (node['name'],ac,sc,length))
            print('reg bytes=' + data[pos:pos+length].hex(' '))
            step=(ac+sc)*4
            for at in range(pos,pos+length,step):
                base=int.from_bytes(data[at:at+ac*4],'big')
                size=int.from_bytes(data[at+ac*4:at+step],'big')
                found.append((base,size))
                print('decoded RAM base=0x%x size=0x%x (%d MiB) end=0x%x' % (base,size,size>>20,base+size))
        pos = align4(pos+length)
    elif token == 4:
        pass
    elif token == 9:
        break
    else:
        raise gdb.GdbError('Unexpected FDT token')
check(len(found)==1, 'observed one QEMU RAM bank')
out_addr = val('(unsigned long)out')
gdb.execute('finish')
check(val('$a0') == 0, 'native dtb_parse returned success')
parsed = gdb.parse_and_eval('*(struct memory_info *)0x%x' % out_addr)
native_base,native_size=int(parsed['base']),int(parsed['size'])
print('native result base=0x%x size=0x%x' % (native_base,native_size))
check((native_base,native_size)==found[0], 'native parser agrees with independently decoded reg')

print('\n=== 4. PMM layout after page_init ===')
stop('run_selftests')
gdb.execute('p/x nbase')
gdb.execute('p/x npage')
gdb.execute('p sizeof(struct Page)')
gdb.execute('p/x pages')
gdb.execute('p/x free_begin')
gdb.execute('p/x managed_end')
expected_end = min(native_base+native_size,0x88000000) & ~4095
check(val('managed_end')==expected_end, 'managed_end=min(detected_end,PHYSTOP), page aligned')
count=val('npage')-val('nbase')
desc_pa=val('(unsigned long)pages')-OFFSET
desc_end=desc_pa+count*val('sizeof(struct Page)')
check(val('free_begin') >= desc_end, 'descriptor storage excluded from free range')
print('DETECTED_MiB=%d MANAGED_MiB=%d DESCRIPTORS=%d FREE_PAGES=%d' % (native_size>>20,(expected_end-native_base)>>20,count,(expected_end-val('free_begin'))//4096))
print('LAB2 DTB DEBUG CHECKS PASSED')
gdb.execute('delete breakpoints')
end
detach
quit
