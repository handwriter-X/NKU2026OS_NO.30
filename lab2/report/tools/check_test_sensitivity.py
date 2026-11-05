#!/usr/bin/env python3
"""Negative controls in disposable copies; never edit the submitted kernel."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

REPORT=Path(__file__).resolve().parent.parent
CODE=REPORT.parent/'code'
CASES=[
    ('best-fit-becomes-first-fit','kern/mm/best_fit_pmm.c',
     'fit_alloc_pages(n,1)','fit_alloc_pages(n,0)','best_fit',0,
     'selected==(pmm_manager==&best_fit_pmm_manager ? b : a)'),
    ('buddy-counts-request-not-span','kern/mm/buddy_pmm.c',
     'available-=span','available-=n','buddy',0,'nr_free_pages()==total-span'),
    ('slub-keeps-empty-pages','kern/mm/slub.c',
     'if (!s->used) {','if (0 && !s->used) {','best_fit',0,'nr_free_pages()==total'),
    ('wrong-panic-is-not-success','kern/mm/selftest.c',
     'kfree((void *)0x1000);','alloc_pages(0);','best_fit',10,'unexpected panic'),
]

def main():
    output=REPORT/'evidence/test-sensitivity'
    output.mkdir(parents=True,exist_ok=True)
    results=[]
    for name,relative,old,new,backend,case,expected in CASES:
        destination=output/name
        destination.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='lab2-negative-control-') as temporary:
            copy=Path(temporary)/'code'
            shutil.copytree(CODE,copy,ignore=shutil.ignore_patterns('obj','bin','evidence','__pycache__'))
            source=copy/relative
            text=source.read_text()
            if text.count(old)!=1:
                raise RuntimeError('Replacement must identify exactly one site: '+name)
            source.write_text(text.replace(old,new))
            if case:
                command=['python3','-c',
                         'import tools.run_tests as t; t.EVIDENCE.mkdir(parents=True,exist_ok=True); '
                         f't.build({backend!r},{case}); t.run({backend!r},"128M",{case})']
            else:
                command=['python3','tools/run_tests.py','--backend',backend,'--memory','128M']
            result=subprocess.run(command,cwd=copy,capture_output=True,text=True,timeout=120)
            transcript=result.stdout+result.stderr
            (destination/'runner.log').write_text(transcript)
            guest=copy/'evidence/selftest'/f'{backend}-128M-case{case}.log'
            if guest.exists():shutil.copyfile(guest,destination/'guest.log')
            if result.returncode==0 or expected not in transcript:
                raise RuntimeError('Negative control was not rejected for the intended reason: '+name)
            record={'name':name,'temporary_file':relative,'before':old,'after':new,
                    'original_sha256':hashlib.sha256((CODE/relative).read_bytes()).hexdigest(),
                    'backend':backend,'case':case,'runner_exit_code':result.returncode,
                    'expected_failure_observed':expected,'result':'fault detected'}
            (destination/'result.json').write_text(json.dumps(record,indent=2)+'\n')
            results.append(record)
            print('PASS: test rejected injected fault: '+name,flush=True)
    (output/'summary.json').write_text(json.dumps({'complete':True,'count':len(results),
                                                   'results':results},indent=2)+'\n')

if __name__=='__main__':main()
