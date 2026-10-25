#!/usr/bin/env python3
"""Install the CN font/UI add-on without replacing an existing HD art pack.

Merges only the matching hash fragment and copies CN_HD/. Preserves the
existing hash algorithm, scenes and options. Creates a timestamped ini backup.
No emulator is started or controlled.
"""
from __future__ import annotations
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import shutil

BEGIN='# BEGIN FATE EXTRA CN HD v1.2'
END='# END FATE EXTRA CN HD v1.2'


def install(pack: Path, target: Path):
    game=pack/'NPJH50247' if (pack/'NPJH50247').is_dir() else pack
    target.mkdir(parents=True,exist_ok=True)
    ini=target/'textures.ini';before=ini.read_bytes() if ini.exists() else None
    text=before.decode('utf-8-sig') if before else (game/'textures.ini').read_text()
    options=re.search(r'(?ims)^\[options\]\s*$(.*?)(?=^\[|\Z)',text)
    algorithm=re.search(r'(?im)^\s*hash\s*=\s*(\w+)',options[1]) if options else None
    algorithm=algorithm[1].lower() if algorithm else 'quick'
    if algorithm not in ['xxh64','quick']:
        raise ValueError(f'existing pack uses unsupported hash {algorithm!r}; no files changed')
    fragment=(game/f'textures-{algorithm}.ini').read_text()
    mapping=re.findall(r'(?im)^([0-9a-f]{24})\s*=\s*(CN_HD/[^\r\n]+)',fragment)
    if not mapping or len(dict(mapping))!=len(mapping):raise ValueError('invalid or duplicate CN mappings')
    for _,name in mapping:
        path=(game/name).resolve()
        if not path.is_relative_to(game.resolve()) or not path.is_file():raise ValueError(f'missing pack image {name}')
    text=re.sub(r'(?ms)^'+re.escape(BEGIN)+r'\n.*?^'+re.escape(END)+r'\n?','',text)
    ours={key for key,_ in mapping};lines=[];removed=0
    for line in text.splitlines():
        match=re.match(r'^\s*([0-9a-fA-F]{24})\s*=',line)
        if match and match[1].lower() in ours:
            removed+=1;continue
        lines.append(line)
    text='\n'.join(lines)+'\n'
    section=re.search(r'(?im)^\[hashes\]\s*$',text)
    if not section: text+='\n[hashes]\n';section=re.search(r'(?im)^\[hashes\]\s*$',text)
    block='\n'+BEGIN+'\n'+'\n'.join(f'{k} = {v}' for k,v in mapping)+'\n'+END+'\n'
    text=text[:section.end()]+block+text[section.end():]
    if before:
        backup=target/f'textures.ini.before-cn-hd-{datetime.now():%Y%m%d-%H%M%S}.bak'
        backup.write_bytes(before)
    else:backup=None
    shutil.copytree(game/'CN_HD',target/'CN_HD',dirs_exist_ok=True)
    temp=ini.with_suffix('.ini.cn-hd-tmp');temp.write_text(text,encoding='utf-8');temp.replace(ini)
    # Check installed mapping bytes and all required images after the write.
    installed=ini.read_text();missing=[]
    for key,name in mapping:
        if f'{key} = {name}' not in installed or not (target/name).is_file():missing.append(key)
    if missing:raise ValueError(f'installation readback failed: {missing[:3]}')
    report={'target':str(target),'hash':algorithm,'mappings':len(mapping),'replaced_matching_keys':removed,
            'backup':str(backup) if backup else None,'ini_sha256':hashlib.sha256(ini.read_bytes()).hexdigest(),
            'runtime_test':'not run; restart PPSSPP to reload the pack'}
    (target/'CN_HD/install-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    return report


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--pack',type=Path,default=Path(__file__).resolve().parent,help='Unpacked add-on directory containing NPJH50247')
    ap.add_argument('--target',type=Path,required=True,help='Existing PSP/TEXTURES/NPJH50247 folder')
    args=ap.parse_args();print(json.dumps(install(args.pack,args.target),ensure_ascii=False,indent=2))

if __name__=='__main__':main()
