import json,re,collections,runpy
from pathlib import Path
D=Path(__file__).parent
ns=runpy.run_path(str(D/'build-ruby-fixes.py'))
R=ns['R'];P=ns['P'];cat=ns['category'];upper=ns['upper']
rows=ns['rows'];orig={r['id']:r['zh_cn'] for r in rows}
fix={r['id']:r for r in [json.loads(x) for x in (D/'ruby-candidate-fixes.jsonl').read_text().splitlines()]}
manual={}
def put(id,z,reason='逐句恢复原文特殊双意上标，并修正对应中文语义及控码结构'):
 manual[id]=dict(id=id,zh_cn=z,reason=reason)
def replace(id,a,b,reason='逐句恢复原文特殊双意上标'):
 z=manual.get(id,{}).get('zh_cn',fix.get(id,{}).get('zh_cn',orig[id]));assert a in z,(id,a,z);put(id,z.replace(a,b),reason)
replace('f268f15ad0404823','防护相对薄弱',R('Protect','防壁')+'相对薄弱')
replace('fbd777027aad7c3d','找回昨天的场子吧！','向昨天的敌人'+R('Revenge','复仇')+'吧！')
replace('e5eb4e47b25418fd','Wizard',R('Wizard','魔术师'))
replace('3b83e2382893541a','偷看',R('Peeping','偷窥'))
put('c39d49bed6189043','……小时候。\n在无人爱我的时候，只有一位'+R('人','女人')+'，\n曾给予我爱。')
replace('e70b2132ed7d5ea0','占星术',R('Astrology','占星术'))
put('b7f2a7e5dd593985','哎呀，是#C255120120'+R('系统方','学生会')+'#CDEF发来的警告吗？\n辛苦你们了。')
put('282a8bb9021ab088','然而，听到那如同'+R('低语','术式吟唱')+'般的声音，\n我的'+R('身体','本能')+'便拒绝再向前迈进一步。')
put('db2f23d5836c04c6','梦见了皇帝吗？\n看来你身为余的'+R('御主','奏者')+'，\n总算有些明白了啊。')
put('229338f0a167953b','你也有父母为你取的'+R('名字','生命')+'吧。\n隐瞒它，不仅会玷污你自己，\n也会玷污你父母的心愿。')
replace('efc819686159a2c3','自己的事',R('自己','个人')+'的事')
replace('5cd7df3e2ebb6ad5','阿开亚',R('阿开亚','希腊'))
put('1b975b01efbb4f0a','不管走到哪里，\n都'+R('・'*10,'无法满足于现在的生活')+'啊。','补全缺失的#REND，并按原句恢复整段强调范围')
replace('5725129750764fbf','虚拟',R('Air','虚拟'))
replace('59b672e5de569447','主人',R('御主','主人'))
replace('06ccfe71e4541831','如果是御主您的吩咐','如果是'+R('御主','主人')+'您的吩咐')
replace('1c2eec6759a53688','主人',R('御主','主人'))
replace('69dccc5c0a57a584','痛快地收拾掉就行','痛快地'+R('干翻','佛耻义理')+'就行')
replace('7ac2a0c60f52296d','怪物',R('Monster','怪物'))
put('99d2acc7c41e9b42',R('触发器','暗号键')+'拿到手了呢。\n我再确认一下，\n'+R('触发器','暗号键')+'都已经集齐了吗？')
put('2b79e9d57dbf69c3','奏者啊……刚才那场战斗已经说明一切了。\n没错，那家伙是#C255120120'+R('Lancer','枪兵')+'#CDEF。\n果然和那个女人预料的一样。','删除原文没有的奏者上标，保留枪兵职阶的双层表记')
put('1bb5480cf7a1b812','他大概是'+R('复制','模造')+'了从者的能力，\n借此取得#C255120120'+R('触发器','暗号键')+'#CDEF吧。')
put('1d0251fe5d7bd95a','#C120200255拉妮#CDEF的身体，\n原来'+R('・'*13,'从一开始就具备这样的功能')+'。','恢复原文整段强调点')
put('27d1f8774c689094','“'+R('那里','地表')+'就是'+R('你们','人类')+'所生活的世界。”')
put('894543c61620affc','如果'+R('御主','主人')+'也想要的话，\n我就把两边都给您剪下来。\n当然，我不会让任何人碰'+R('御主','主人')+'的脖子！')
put('6a806c5f9139dd85','逐渐消失的#C120200255'+R('爱丽丝','主人')+'#CDEF的手，\n被#C255120120'+R('爱丽丝','从者')+'#CDEF紧紧握住。\n她攥着那只手，发出悲痛的呼喊。')
replace('466b27c7bddfd37d','御主',R('御主','主人'))
replace('e44ffb4a615bef95','御主',R('御主','主人'))
replace('23da0d37f1791ed4','魔术师',R('Magus','魔术师'))
replace('224d34514f9df082','传说',R('东西','传说'))
replace('5f3bd6f0941942c4','主人',R('御主','主人'))
replace('5e3279c5b2bcedd0','御主',R('御主','主人'))
replace('eae159870193977e','主人',R('御主','主人'))
replace('7fc759c5764a93e8','御主',R('御主','主人'))
put('b87f550c871a3bf1','没想到从首战开始，\n就要和弗朗西斯·德雷克这样强悍的'+R('Servant','英灵')+'\n交手啊。')
replace('6895f63cd5f45d0a','触发器',R('触发器','暗号键'))
replace('fd36aa0324d7853c','从者',R('Servant','仆从'))
replace('61469fee084dd9f7','结果主人','结果'+R('御主','主人'))
replace('26346119cbd30392','主人',R('御主','主人'))
replace('204429e83ee396a5','主人',R('御主','主人'))
replace('3e737b4530c54a51','我终于也能交到朋友了',R('爱丽丝','我')+'终于也能交到朋友了')
replace('24952f76924ce005','走运',R('Lucky','幸运'))
replace('0b2ae4b2469756d8','爱丽丝',R('爱丽丝','我'))
replace('0fea1fabc6bdd12e','主人',R('御主','主人'))
replace('34d8f9bd75f9846e','从我一直想待在那里的时候起','从'+R('爱丽丝','我')+'一直想待在那里的时候起')
replace('33b8b988c5093591','电脑',R('灵魂','电子脑'))
replace('2f91f13e1b213dcc','主人',R('御主','主人'))
replace('05e4b4829f5b5b6a','万事大吉',R('冇问题','没问题'))
replace('bb26fbc25617d0df','。主人对','。'+R('御主','主人')+'对')
replace('502a3c85ede92643','伟大的作业',R('Magnum Opus','伟大作业'))
replace('0560f8dff4c8cb97',R('那边','他们'),'旁边')
put('75e1a44772d8c679','……不过，曾有过一个成功案例。\n那就是'+R('Wizard','灵子')+'黑客的入侵。')
# The following mismatches already retain every non-phonetic source annotation.
reviewed_unchanged={'46f460736fb1986a','97a7ddf6888fb4d1','77feb91bc8d03259','0d78f56447b0d19b'}
# Mixed-source entries, translated order, malformed ordinary annotations, and prose
# that depended on the translator's redundant upper layer.
put('6b05329273de8c33','我可不能让'+R('御主','主人')+'一直和\n那种蠢货呼吸同一片空气。','按中文语序重新匹配上标，删除普通注音时保留正确的御主表记')
put('782ab97ff4125675','是吧，我亲爱的妻子！\n这位暴食而又拒食的御主，\n这位'+R('・'*11,'只吃自己真心爱着之物')+'的可悲的'+R('人','女人')+'！')
replace('e2c7c2628a23f081',R('Game','游戏'),R('Game','围棋'))
replace('f5a8b36ad0c27fa7','最后的末','最后的末裔')
put('cca459d4cff777bf','升华的灵魂将飞升至天际，\n舍弃作为不完美容器的肉体。\n那作为根基的技艺，便称为“'+R('Magnum Opus','伟大作业')+'”。')
put('c1562afed7b3401d','没错，那位御主就是#C120200255拉妮＝Ⅷ#CDEF。','删除罗马数字的普通读音并修复缺失#REND造成的结构破损')
put('203aff8b11e06af2','之后的发展就和传说一样。\n她出于好奇，转生成了#C120200255藻女#CDEF的模样。','删除人名普通注音，并补回遗失的#CDEF以闭合姓名颜色')
put('6ebd0cb512c539e1','无论如何，这都是最贴切的'+R('名字','冠冕')+'。\n即使余不愿如此，余也只能是余。\n余不允许自己以一个普通人的身份自报名号。')
put('9e0fe5dd3cad653b','英雄越是出名，#C255120120其'+R('名字','本质')+'越为人所知，\n弱点也越容易暴露。#CDEF\n余因此隐瞒了真名。')
put('193466fb685ef5cf','……在'+R('那时','召唤时')+'，')
put('ea94f8e00b866ba2','原来如此……\n是'+R('复制','模仿')+'了从者的'+R('Doll','人偶')+'，是吗。\n情报隐藏得可真彻底。')
put('b3444121c639095f','原来如此……\n是'+R('复制','模仿')+'了从者的'+R('Doll','人偶')+'啊。\n真打算把情报藏得严严实实呢。')
replace('13a7469b025b94c5',R('御','主')+'人',R('御','主'))
# Normal-reading removals sometimes expose an untranslated kanji stem or a
# translation that put the usable Chinese word in the discarded upper layer.
put('1ea119288f803a53','……她笑着这么一说，\n我反而越发坐立不安。','删除普通注音，并把被拆成上下层的中文合成完整词句')
put('fb53a83aeadf2880','好啊，你这家伙，这回绝对把你打成蜂窝！\n这么活蹦乱跳的猎物可不多见！','删除普通注音，保留完整中文用词')
replace('eaf293203c106b7e','优男','俊俏男人')
replace('d7729810813485ac','般地赞余吧','般地赞颂余吧')
exec(D.joinpath('ruby-reading-manual.py').read_text())
# Keep all checked pending rows recorded, including the cases requiring no edit.
pend=json.loads((D/'ruby-pending.json').read_text())
missing={r['id'] for r in pend}-set(manual)-reviewed_unchanged
assert not missing,missing
fix.update(manual)
# Native ruby has fullwidth Latin glyphs. Normalize the small layer to that
# existing alphabet without changing Latin in ordinary body text.
latin_table={ord(c):chr(ord(c)+0xFEE0) for c in 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789.-'}
latin_table[ord(' ')]=chr(0x3000)
for r in rows:
 z=fix.get(r['id'],r)['zh_cn']
 nz=P.sub(lambda m:R(m[1].translate(latin_table),m[2]),z)
 if nz!=z:
  reason=fix.get(r['id'],{}).get('reason','保留原文特殊双意表记')
  fix[r['id']]=dict(id=r['id'],zh_cn=nz,reason=reason+'；小字Latin使用原字库已有的全角字母')
# In ordinary-only rows, no annotation remains; in semantic rows all intended
# annotation fields are explicit in the exported source-pair decision table.
final=[]
for r in rows:
 if r['id'] not in fix:continue
 f=fix[r['id']]
 if f['zh_cn']==orig[r['id']]:continue
 tokens=re.findall(r'#RUBS|#RUBE|#REND',f['zh_cn'])
 assert tokens==['#RUBS','#RUBE','#REND']*(len(tokens)//3),(r['id'],tokens)
 assert not re.search(r'[ぁ-ゖァ-ヺ]',P.sub('',f['zh_cn'])) or re.search(r'[ぁ-ゖァ-ヺ]',P.sub('',orig[r['id']])),r['id']
 final.append(f)
D.joinpath('ruby-fixes.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in final))
print('FINAL',len(final),'manual',len(manual))
print('Remaining identical:',[(r['id'],u,v) for r in final for u,v in P.findall(r['zh_cn']) if u==v])
