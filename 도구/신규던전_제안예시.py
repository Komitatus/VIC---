#!/usr/bin/env python3
"""Build the standalone interactive fictional-dungeon proposal."""
import base64
import hashlib
from html import escape
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from balance.proposed_dungeon import calculate

BASE=ROOT/'콘텐츠/명조/신규던전_잔향정제실'
RUN=BASE/'결과/20261118_전체조정_경제영향'
OUT=ROOT/'문서/명조/제안서/신규던전_잔향정제실_인터랙티브.html'
TEMPLATE=Path(__file__).with_name('templates')/'신규던전_제안예시.html'

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def load(p):return json.loads(p.read_text(encoding='utf-8'))
def save(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

def main():
    model=load(BASE/'모델.json')
    for path,digest in model['source_files'].items():assert sha(Path(path))==digest,path
    result=calculate(model);result['input_sha256']=sha(BASE/'모델.json');save(RUN/'계산.json',result)
    icons={r['key']:r for r in load(ROOT/'문서/명조/아이콘_출처.json')['records']}
    text=TEMPLATE.read_text(encoding='utf-8');assets={}
    for token,key in [('XP','item:36000004'),('TUNER','item:36000014'),('COIN','item:2')]:
        r=icons[key];path=ROOT/'문서/명조'/r['document_file'];assert sha(path)==r['sha256']
        assets[key]={'name':r['name'],'sha256':r['sha256'],'object_path':r['object_path']}
        image='<img class="icon" width="46" height="46" src="data:image/png;base64,'+base64.b64encode(path.read_bytes()).decode()+'" alt="'+escape(r['name'])+'">'
        text=text.replace('@@'+token+'_ICON@@',image)
    assert '5000' in icons['item:36000004']['description']
    text=text.replace('@@MODEL@@',json.dumps(model,ensure_ascii=False).replace('<','\\u003c'))
    assert '@@' not in text
    OUT.write_text(text,encoding='utf-8')
    save(RUN/'산출물_명세.json',{'report':str(OUT),'report_sha256':sha(OUT),'model':str(BASE/'모델.json'),'model_sha256':sha(BASE/'모델.json'),'template_sha256':sha(TEMPLATE),'generator_sha256':sha(Path(__file__)),'calculator_sha256':sha(ROOT/'balance/proposed_dungeon.py'),'icons':assets,'fictional':True})
    print(json.dumps({'report':str(OUT),'bytes':OUT.stat().st_size,'weekly_per_user_delta':result['week']['delta']},ensure_ascii=False))

if __name__=='__main__':main()
