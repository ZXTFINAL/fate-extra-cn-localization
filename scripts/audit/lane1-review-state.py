import json
from pathlib import Path
BASE=Path('work/translation/review-20261019')
LANE=json.loads((BASE/'context-lane-1.json').read_text())
TEXT={d['id']:d for d in map(json.loads,(BASE/'text.context-ruby.jsonl').open())}
PROGRESS=BASE/'context-lane-1-progress.json'
FIXFILE=BASE/'context-lane-1-fixes.jsonl'
state=json.loads(PROGRESS.read_text()) if PROGRESS.exists() else {'target_count':LANE['target_count'],'reviewed_target_ids':[],'reviewed_shards':[],'notes':['人工逐窗读取日文与snapshot译文；不以检索筛选或自动处理冒充已读。']}
fixes=list(map(json.loads,FIXFILE.open())) if FIXFILE.exists() else []
def add(i,zh,reason):
    for s in LANE['shards']:
        if i in s['target_ids']:
            rs=list(map(json.loads,(BASE/'context-shard-plan'/s['shard']).open()))
            r=next(r for r in rs if r['id']==i)
            ref={'file':r['file'],'text_offset':r['text_offset'],'shard':s['shard']}
            break
    else:raise ValueError(i)
    d={'id':i,'zh_cn':zh,'reason':reason,'source_ref':ref}
    existing=next((j for j,x in enumerate(fixes) if x['id']==i),None)
    if existing is None:fixes.append(d)
    else:fixes[existing]=d

def done(shards):
    for name in shards:
        s=next(s for s in LANE['shards'] if s['shard']==name)
        state['reviewed_target_ids']=list(dict.fromkeys(state['reviewed_target_ids']+s['target_ids']))
        state['reviewed_shards']=list(dict.fromkeys(state['reviewed_shards']+[name]))

def save():
    state['reviewed_count']=len(state['reviewed_target_ids'])
    state['remaining_count']=state['target_count']-state['reviewed_count']
    state['fix_count']=len(fixes)
    state['status']='complete' if state['remaining_count']==0 else 'in_progress'
    PROGRESS.write_text(json.dumps(state,ensure_ascii=False,indent=2)+'\n')
    FIXFILE.write_text(''.join(json.dumps(d,ensure_ascii=False)+'\n' for d in fixes))
    print({k:v for k,v in state.items() if k in ['target_count','reviewed_count','remaining_count','fix_count','status']})
