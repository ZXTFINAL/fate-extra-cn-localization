import json,sys
from pathlib import Path
D=Path(__file__).parent
plan=json.load(open(D/'context-lane-2.json'))
base={r['id']:r for r in map(json.loads,(D/'text.context-ruby.jsonl').read_text().splitlines())}
byshard={x['shard']:x['target_ids'] for x in plan['shards']}
cmd=sys.argv[1]
if cmd=='read':
 for name in sys.argv[2:]:
  name=name if '.' in name else name.zfill(3)+'.jsonl'
  rs=[json.loads(s) for s in (D/'context-shard-plan'/name).read_text().splitlines()]
  ts=set(byshard[name]); inds=[i for i,r in enumerate(rs) if r['id'] in ts]; wanted=set()
  for i in inds:wanted.update(range(max(0,i-2),min(len(rs),i+3)))
  print('\nSHARD',name,'file',rs[0]['file'],'targets',len(ts))
  last=-2
  for i in sorted(wanted):
   if i!=last+1:print('...')
   r=rs[i];last=i
   print(('*' if r['id'] in ts else '-')+str(r['sequence']),r['id'],r['jp'].replace('\n',' / '),'→',base[r['id']]['zh_cn'].replace('\n',' / '))
elif cmd=='commit':
 # Invoked only after the corresponding text was actually read by the reviewer.
 names=[n if '.' in n else n.zfill(3)+'.jsonl' for n in sys.argv[2:]]
 pth=D/'context-lane-2-progress.json';p=json.load(open(pth)) if pth.exists() else dict(target_count=plan['target_count'],reviewed_ids=[],completed_shards=[],batches=[],status='in_progress')
 for n in names:
  assert n in byshard
  if n not in p['completed_shards']:p['completed_shards'].append(n)
  p['reviewed_ids']=list(dict.fromkeys(p['reviewed_ids']+byshard[n]))
 p['reviewed_count']=len(p['reviewed_ids']);p['remaining_count']=p['target_count']-p['reviewed_count'];p['batches'].append(dict(shards=names,reviewed_count=sum(len(byshard[n]) for n in names),method='Direct model reading of full Japanese/Chinese target text with adjacent script context; current context-ruby baseline.'))
 p['status']='complete' if p['remaining_count']==0 else 'in_progress';pth.write_text(json.dumps(p,ensure_ascii=False,indent=2));print(p['reviewed_count'],p['remaining_count'])
elif cmd=='fix':
 incoming=json.load(sys.stdin);pth=D/'context-lane-2-fixes.jsonl';old=[json.loads(s) for s in pth.read_text().splitlines()] if pth.exists() else [];mapping={r['id']:r for r in old}
 for f in incoming:
  assert f['id'] in plan['target_ids']
  refs=[]
  for sp in plan['shards']:
   if f['id'] not in sp['target_ids']:continue
   for r in map(json.loads,(D/'context-shard-plan'/sp['shard']).read_text().splitlines()):
    if r['id']==f['id']:refs.append(dict(file=r['file'],text_offset=r['text_offset'],sequence=r['sequence'],shard=sp['shard']))
  assert refs
  f['source_ref']=refs[0];mapping[f['id']]=f
 pth.write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in mapping.values()));print('fixes',len(mapping))
