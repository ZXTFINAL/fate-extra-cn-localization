import json
import sys
from pathlib import Path

p = Path('work/translation/review-20261019')
lane = json.loads((p / 'context-lane-3.json').read_text())
base = {r['id']: r for r in map(json.loads, Path(lane['translations']).read_text().splitlines())}
batch = json.loads(Path(sys.argv[1]).read_text())
meta = {}
for shard in lane['shards'][batch['start']:batch['end']]:
    for row in map(json.loads, (p / 'context-shard-plan' / shard['shard']).read_text().splitlines()):
        if row['id'] in shard['target_ids']:
            meta[row['id']] = dict(file=row['file'], text_offset=row['text_offset'], sequence=row['sequence'], shard=shard['shard'])
fix_path = p / 'context-lane-3-fixes.jsonl'
seen = {r['id'] for r in map(json.loads, fix_path.read_text().splitlines())}
out = []
for fix in batch['fixes']:
    ids = [i for i in meta if i.startswith(fix['prefix'])]
    assert len(ids) == 1, fix
    target = ids[0]
    assert target not in seen, target
    zh = fix.get('zh_cn', base[target]['zh_cn'])
    for old, new in fix.get('replace', []):
        assert old in zh, (target, old)
        zh = zh.replace(old, new)
    assert zh.count('#RUBS') == base[target]['zh_cn'].count('#RUBS'), target
    out.append(dict(id=target, zh_cn=zh, reason=fix['reason'], source_ref=meta[target]))
with fix_path.open('a') as stream:
    for row in out:
        stream.write(json.dumps(row, ensure_ascii=False) + '\n')
progress_path = p / 'context-lane-3-progress.json'
progress = json.loads(progress_path.read_text())
shards = lane['shards'][batch['start']:batch['end']]
assert not set(s['shard'] for s in shards) & set(progress['completed_shards'])
new_ids = [i for s in shards for i in s['target_ids']]
progress['reviewed_ids'] = list(dict.fromkeys(progress['reviewed_ids'] + new_ids))
progress['reviewed_count'] = len(progress['reviewed_ids'])
progress['remaining_count'] = lane['target_count'] - progress['reviewed_count']
progress['completed_shards'] += [s['shard'] for s in shards]
progress['batches'].append(dict(shards=[s['shard'] for s in shards], reviewed_count=len(new_ids), method=batch['method']))
progress_path.write_text(json.dumps(progress, ensure_ascii=False, indent=2) + '\n')
print(dict(reviewed=progress['reviewed_count'], fixes=len(seen) + len(out)))
