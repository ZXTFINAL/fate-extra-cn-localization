import collections
import hashlib
import json
import re
from pathlib import Path

base = Path('work/translation')
out = base / 'review-20261019' / 'context-shard-plan'
out.mkdir(exist_ok=True)
texts = {d['id']: d for d in map(json.loads, (base / 'text.jsonl').open())}
by_file = collections.defaultdict(list)
all_by_id = collections.defaultdict(list)
for d in map(json.loads, (base / 'refs.jsonl').open()):
    by_file[d['file']].append(d)
    all_by_id[d['id']].append(d)
for rows in by_file.values():
    rows.sort(key=lambda x: x['text_offset'])

def priority(r):
    ks = set(r.get('kinds', []))
    if ks & {'dialogue', 'backlog', 'motion'}:
        p = 0
    elif 'choice' in ks:
        p = 1
    elif 'name_or_location' in ks:
        p = 4
    elif ks & {'misc_prompt', 'popup'}:
        p = 3
    else:
        p = 2
    return p, r['file'], r['text_offset']

owners = {i: min(rows, key=priority) for i, rows in all_by_id.items()}
opening_reviewed = {d['id'] for d in map(json.loads, (base / 'review-20261019/context-opening-ordered.jsonl').open())}
patterns = {
    'ruby_dual_reading': lambda d: '#RUBS' in d['jp'],
    'gender_branch': lambda d: '#[' in d['jp'],
    'implicit_subject': lambda d: bool(re.search('[我你他她]', d['zh_cn'])) and not re.search('私|僕|俺|貴方|貴女|あなた|君|お前|彼|彼女', d['jp']),
    'janai_negative_or_confirmation': lambda d: 'じゃない' in d['jp'],
    'shika_restriction': lambda d: 'しか' in d['jp'],
    'tsukiau_polysemy': lambda d: '付き合' in d['jp'],
    'anomaly_or_memory': lambda d: bool(re.search('違和感|記憶|目眩|名前|消え|同じ', d['jp'])),
}
def flags(i):
    return [name for name, test in patterns.items() if test(texts[i])]

manifest = []
assigned = []
for f, rows in sorted(by_file.items()):
    owned = {i for i, r in owners.items() if r['file'] == f}
    if not owned:
        continue
    # 固定窗口建立在原脚本顺序上；每一处仅第一次作为目标，其他出现仍作为上下文。
    emitted = set()
    for start in range(0, len(rows), 80):
        end = min(start + 80, len(rows))
        target_ids = []
        for r in rows[start:end]:
            i = r['id']
            if i in owned and i not in emitted:
                target_ids.append(i)
                emitted.add(i)
        if not target_ids:
            continue
        first_target = next(j for j in range(start, end) if rows[j]['id'] in target_ids)
        last_target = max(j for j in range(start, end) if rows[j]['id'] in target_ids)
        cstart, cend = max(0, first_target - 8), min(len(rows), last_target + 9)
        number = len(manifest) + 1
        name = f'{number:03d}.jsonl'
        target_set = set(target_ids)
        first_owned = set()
        serial = []
        for sequence in range(cstart, cend):
            r = rows[sequence]
            i = r['id']
            t = texts[i]
            target = i in target_set and i not in first_owned
            if target:
                first_owned.add(i)
            serial.append({'file': f, 'sequence': sequence, 'text_offset': r['text_offset'], 'id': i,
                'is_review_target': target, 'jp': t['jp'], 'zh_cn': t['zh_cn'],
                'kinds': r['kinds'], 'risk_search_flags': flags(i),
                'reviewed_by_opening_pass': i in opening_reviewed})
        (out / name).write_text(''.join(json.dumps(d, ensure_ascii=False) + '\n' for d in serial))
        risk_counts = collections.Counter(flag for i in target_ids for flag in flags(i))
        manifest.append({'shard': name, 'file': f,
            'context_start_offset': rows[cstart]['text_offset'], 'context_end_offset': rows[cend - 1]['text_offset'],
            'target_count': len(target_ids), 'context_rows': len(serial), 'target_ids': target_ids,
            'opening_reviewed_count': len(set(target_ids) & opening_reviewed),
            'risk_search_counts': dict(risk_counts), 'status': 'planned_unreviewed_except_opening_ids'})
        assigned.extend(target_ids)

missing = sorted(set(texts) - set(assigned))
assert not missing, missing
assert len(assigned) == len(set(assigned)) == len(texts)
manifest_obj = {'notice': '这是基于refs文件顺序的全量分片计划，不是全量人工校对完成证明。risk_search仅为检索线索。每个ID只分配一次目标审阅位置；共享文本仍须核对所有使用语境。',
    'text_count': len(texts), 'ref_count': sum(len(x) for x in by_file.values()), 'physical_files': len(by_file),
    'shard_count': len(manifest), 'opening_reviewed_ids': len(opening_reviewed),
    'text_jsonl_sha256_at_generation': hashlib.sha256((base / 'text.jsonl').read_bytes()).hexdigest(),
    'shards': manifest}
(out / 'manifest.json').write_text(json.dumps(manifest_obj, ensure_ascii=False, indent=2) + '\n')
risks = collections.Counter(flag for i in texts for flag in flags(i))
(out / 'risk-search-counts.json').write_text(json.dumps(dict(risks), ensure_ascii=False, indent=2) + '\n')
print(json.dumps({k:v for k,v in manifest_obj.items() if k not in ['shards','notice']}, ensure_ascii=False))
print('risk_search_counts', dict(risks))
