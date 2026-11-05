#!/usr/bin/env python3
"""Render editable diagrams and clearly attributed real-log figures for report.md."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import textwrap

from PIL import Image, ImageDraw, ImageFont

REPORT=Path(__file__).resolve().parent.parent
IMAGES=REPORT/'images'
CODE=REPORT.parent/'code'
FONT=Path('C:/Windows/Fonts/msyh.ttc')
MONO=Path('C:/Windows/Fonts/consola.ttf')

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def relative(path):return str(path.relative_to(REPORT.parent)).replace('\\','/')
def log_rows(path, predicate):
    return [(number,line.expandtabs(4)) for number,line in enumerate(path.read_text(encoding='utf-8').splitlines(),1)
            if predicate(line)]

def panel(name,title,sections,manifest):
    title_font=ImageFont.truetype(str(FONT),30)
    note_font=ImageFont.truetype(str(FONT),17)
    code_font=ImageFont.truetype(str(MONO),18)
    rows=[]
    sources=[]
    for label,path,lines in sections:
        rows.append(('section',label))
        rows.append(('source',relative(path)))
        digest=sha(path)
        rows.append(('source','SHA256: '+digest))
        sources.append({'path':relative(path),'sha256':digest,
                        'selected_line_numbers':[n for n,_ in lines if n is not None]})
        previous=None
        for number,line in lines:
            if number is not None and previous is not None and number>previous+1:
                rows.append(('code','       ... [omitted source lines] ...'))
            prefix=('%4d | '%number) if number is not None else '     '
            wrapped=textwrap.wrap(line,width=101,replace_whitespace=False,drop_whitespace=False) or ['']
            for index,part in enumerate(wrapped):
                rows.append(('code',(prefix if index==0 else '     | ')+part))
            previous=number
        rows.append(('gap',''))
    width=1280
    height=145+sum(36 if kind=='section' else 27 if kind=='code' else 24 if kind=='source' else 16 for kind,_ in rows)+35
    image=Image.new('RGB',(width,height),'#f4f7fa')
    draw=ImageDraw.Draw(image)
    draw.rectangle((0,0,width,112),fill='#16324b')
    draw.text((30,18),title,font=title_font,fill='white')
    draw.text((31,65),'真实日志 / JSON 的摘录排版图；非现场终端截图。省略行明确标示，完整来源见下方及图片清单。',font=note_font,fill='#d9e8f4')
    y=132
    for kind,line in rows:
        if kind=='section':
            draw.text((30,y),line,font=ImageFont.truetype(str(FONT),22),fill='#16324b');y+=36
        elif kind=='source':
            draw.text((30,y),line,font=code_font,fill='#526879');y+=24
        elif kind=='code':
            color='#176142' if 'PASS' in line or 'fault detected' in line else '#9a3425' if 'PANIC' in line else '#25394a'
            draw.text((30,y),line,font=code_font,fill=color);y+=27
        else:y+=16
    destination=IMAGES/name
    image.save(destination)
    manifest.append({'image':relative(destination),'type':'attributed log/JSON figure, not terminal screenshot',
                     'width':width,'height':height,'sha256':sha(destination),'sources':sources})

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--diagram-renderer',type=Path,
                        help='Optional path to diagram-generator/scripts/render_diagram.py; defaults to local dot')
    args=parser.parse_args()
    if not FONT.exists() or not MONO.exists():
        raise RuntimeError('This renderer uses the Windows Microsoft YaHei and Consolas fonts')
    manifest=[]
    for source in sorted(IMAGES.glob('*.dot')):
        destination=source.with_suffix('.png')
        if args.diagram_renderer:
            command=['python',str(args.diagram_renderer),str(source),'--format','png','--out',str(destination)]
        else:
            dot=shutil.which('dot')
            if not dot:raise RuntimeError('Graphviz dot is required to render the editable DOT diagrams')
            command=[dot,'-Tpng',str(source),'-o',str(destination)]
        subprocess.run(command,check=True)
        with Image.open(destination) as image:dimensions=image.size
        manifest.append({'image':relative(destination),'type':'source-based schematic, not runtime evidence',
                         'width':dimensions[0],'height':dimensions[1],'sha256':sha(destination),
                         'sources':[{'path':relative(source),'sha256':sha(source)}]})

    dtb=REPORT/'evidence/dtb-128M/gdb.log'
    chosen=log_rows(dtb,lambda s:any(x in s for x in (
        'DTB_PA=','0xffffffffc70000','FDT magic=','offsets:','memory node=',
        'reg bytes=','decoded RAM','Value returned','native result',
        'native dtb_parse','native parser agrees','DETECTED_MiB=','LAB2 DTB')))
    panel('07-dtb-debug.png','DTB 实测：从启动参数、原始字节到内核解析结果',[
        ('Best-Fit / 128 MiB：GDB 真实观测',dtb,chosen)],manifest)

    sections=[]
    for memory in ('64M','128M','256M'):
        path=REPORT/('evidence/dtb-'+memory+'/qemu.log')
        sections.append(('QEMU -m '+memory,path,log_rows(path,lambda s:s.startswith(('DTB:','MANAGED:','LAYOUT:','FREE:')))))
    panel('08-dtb-capacities.png','容量对比：发现的 RAM 与允许管理的 RAM',sections,manifest)

    path=REPORT/'evidence/dtb-128M/qemu.log'
    panel('09-normal-selftest.png','正常运行：内存布局、分页状态与分配器 / SLUB 自测',[
        ('Best-Fit / 128 MiB：本次 DTB 调试后继续执行',path,log_rows(path,lambda s:s.startswith((
            '(THU.CST)','DTB:','memory management:','MANAGED:','LAYOUT:','FREE:',
            'satp ','SELFTEST:','[PASS]','LAB2 B'))))],manifest)

    path=CODE/'evidence/selftest/summary-all.json'
    pmm=json.loads(path.read_text())
    positives=[r for r in pmm['results'] if r['case']==0]
    negatives=[r for r in pmm['results'] if r['case']!=0]
    rows=[(None,'self_written=%s complete=%s total=%d normal=%d expected_rejection=%d'%(
        pmm['self_written'],pmm['complete'],len(pmm['results']),len(positives),len(negatives)))]
    rows += [(None,'%-10s %-5s case=0  %s'%(r['backend'],r['memory'],r['result'])) for r in positives]
    bootpath=CODE/'evidence/integration/summary.json'
    boot=json.loads(bootpath.read_text())
    bootrows=[(None,'self_written=%s complete=%s boot_cases=%d'%(boot['self_written'],boot['complete'],len(boot['boot_gdb_results'])))]
    bootrows += [(None,'%-10s %-5s %s'%(r['backend'],r['memory'],r['result'])) for r in boot['boot_gdb_results']]
    panel('10-regression-matrix.png','已有证据集：35 个功能场景与 9 个启动 GDB 场景',[
        ('读取已有 JSON；不表示本次重新执行全部矩阵',path,rows),('启动 GDB 矩阵',bootpath,bootrows)],manifest)

    path=REPORT/'evidence/test-sensitivity/summary.json'
    sensitivity=json.loads(path.read_text())
    sections=[]
    for result in sensitivity['results']:
        guest=REPORT/'evidence/test-sensitivity'/result['name']/'guest.log'
        rows=[(None,'runner exit code=%d; result=%s'%(result['runner_exit_code'],result['result']))]
        rows += log_rows(guest,lambda s:s.startswith(('[PANIC]','[EXPECT PANIC]')))
        sections.append((result['name'],guest,rows))
    panel('11-test-sensitivity.png','反向验证：四类错误副本均被原测试拒绝',sections,manifest)
    manifest[-1]['sources'].append({'path':relative(path),'sha256':sha(path),
                                    'purpose':'runner exit codes and fault-detection results'})
    (IMAGES/'image-manifest.json').write_text(json.dumps({'description':'All new figures and their exact sources',
        'figures':manifest},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('Rendered %d figures with source manifest'%len(manifest))

if __name__=='__main__':main()
