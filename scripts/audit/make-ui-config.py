import json,re,sys
from pathlib import Path
from PIL import ImageFont
sys.path.insert(0,'tools')
from fate_extra_texture import Bundle,Texture
BASE=Path('work/research/ui-localization-audit')
records=json.loads((BASE/'all-ui/decode-report.json').read_text())
font='/System/Library/Fonts/Hiragino Sans GB.ttc'
# text, optional preserved left icon width
labels={
'eqp_help_00.tex':('装备',20),'eqp_help_01.tex':('卸下',20),'eqp_help_02.tex':('说明',20),'eqp_help_03.tex':('效果',20),
'eqp_ttl_01.tex':('请选择要更换的装备栏。',16),'eqp_ttl_02.tex':('请选择要更换的装备。',16),
'item_consumption.tex':'消耗MP','shop_cgr_00.tex':'持有数','shop_cgr_01.tex':'持有金',
'shop_cgr_02.tex':('请选择操作。',16),'shop_cgr_03.tex':('请选择要购买的物品。',16),'shop_cgr_04.tex':('请选择要出售的物品。',16),'shop_cgr_11.tex':('请选择物品。',16),
'shop_help_00.tex':('购买',20),'shop_help_01.tex':('取消',20),'shop_help_02.tex':('数量',20),'shop_help_03.tex':('出售',20),
'btl_spt_help.tex':('切换分类',16),'btl_wng_03.tex':'SE.RA.PH警告：禁止御主在竞技场内互相战斗。','btl_wng_04.tex':'SE.RA.PH警告：再过1回合，战斗将强制结束。','btl_wng_05.tex':'SE.RA.PH警告：战斗强制结束。',
'relt_cgr_00.tex':'距离升级还需','relt_cgr_01.tex':'获得经验','relt_cgr_02.tex':'持有金钱','relt_cgr_03.tex':'获得金钱','relt_cgr_04.tex':'获得道具','relt_cgr_07.tex':'御主MP','relt_cgr_08.tex':'从者HP','relt_cgr_09.tex':'从者MP','relt_cgr_10.tex':'技能点数','relt_help_00.tex':('继续',18),
'day_cgr_00.tex':'暗号键取得情况','day_cgr_01.tex':'竞技场探索率','day_cgr_02.tex':'宝箱取得率','day_cgr_03.tex':'情报矩阵取得情况','day_cgr_04.tex':'支线事件情况','tgr_font_00.tex':'获得暗号键',
'day_complete_00.tex':'已取得','day_complete_01.tex':'未取得','day_complete_02.tex':'已完成','day_complete_03.tex':'进行中',
'day_event_00.tex':'寻宝竞赛','day_event_01.tex':'拉妮的占星术','day_event_02.tex':'凶恶异形的真身','day_event_03.tex':'狩猎竞赛','day_event_04.tex':'修复从者魔术回路','day_event_05.tex':'解除赤原礼装封印','day_event_06.tex':'尤里乌斯的突袭',
'day_expected.tex':'目标等级','day_floor_00.tex':'第一层','day_floor_01.tex':'第二层','day_help_00.tex':('查看情报矩阵',20),
'ne_help00.tex':('转换',20),'ne_help01.tex':('删一字',20),'ne_help02.tex':('移一字',34),'ne_tab_font00.tex':'平假名','ne_tab_font01.tex':'片假名',
'ne_title_font00.tex':('请选择性别。',16),'ne_title_font01.tex':('请输入姓名。',16),'ne_title_font02.tex':('请输入昵称。',16),'ne_title_font03.tex':('请确认输入信息。',16),
'ga_cgr_00.tex':'持有SP','ga_help_00.tex':('重置',16),
'pro_day_no00.tex':'决战开始','mtxd_mes_00.tex':'获得敌方从者情报！','mtxd_mes_02.tex':'获得我方从者情报！','main_money.tex':'持有金钱',
'i_mov_help00.tex':('移动',18),'i_mov_help01.tex':('取消',18),'i_mov_title00.tex':('请选择目的地。',16),
'gov_cgr_01.tex':'读取存档','gov_cgr_02.tex':'返回标题','htg_ttl_02.tex':'获得财宝',
'mtx_cgr_00.tex':'能力状态','mtx_cgr_01.tex':'关键词','mtx_cgr_02.tex':'技能','mtx_cgr_03.tex':'详情',
'mtx_help_00.tex':('切换分类',16),'mtx_help_01.tex':('返回',20),'mtx_help_02.tex':('详情',20),'mtx_prf_00.tex':'御主','mtx_prf_01.tex':'真名','mtx_prf_02.tex':'宝具','mtx_prf_03.tex':'关键词',
'mtx_slt_00.tex':'选择从者',
'item_help_00.tex':('说明',20),'item_help_01.tex':('效果',20),'item_ttl_01.tex':('请选择要查看的道具。',16),'item_ttl_02.tex':'道具','item_ttl_03.tex':'礼装',
'opt_cgr_00.tex':'文字速度','opt_cgr_01.tex':'剧情语音','opt_cgr_03.tex':'音效·战斗语音','opt_cgr_04.tex':'镜头操作','opt_cgr_05.tex':'恢复默认设置','opt_cgr_06.tex':'确定',
'opt_help_00.tex':('切换设置',16),'opt_help_01.tex':('调整各项设置。',16),'opt_stg_00.tex':'慢','opt_stg_01.tex':'普通','opt_stg_02.tex':'快','opt_stg_05.tex':'反转','opt_stg_06.tex':'不反转',
'rei_cgr_00.tex':'令咒…','rei_cgr_01.tex':'不使用','rei_cgr_02.tex':'使用',
'stm_cgr_00_00.tex':'保存存档','stm_cgr_00_01.tex':'读取存档','stm_cgr_00_02.tex':'删除存档','stm_cgr_00_03.tex':'选项设置','stm_cgr_00_04.tex':'重新挑战','stm_cgr_00_05.tex':'返回标题','stm_ttl_01.tex':('请选择项目。',16),
'st_cgr_00.tex':'技能点数','st_cgr_01.tex':'经验值','st_cgr_02.tex':'距离升级还需',
'st_help_00.tex':('查看令咒',20),'st_help_01.tex':('已学技能',20),'st_help_02.tex':('能力状态',20),'st_help_03.tex':('切换从者',34),'st_help_04.tex':('切换御主',34),
'adv_mes00.tex':'〈注意〉','adv_mes01.tex':'本作存在通向死路的剧情路线，','adv_mes02.tex':'以及不合常理的选项。','adv_mes03.tex':'建议您准备','adv_mes04.tex':'多个存档。',
}
for i in range(4):labels[f'day_matrix_{i:02d}.tex']=f'对手从者情报0{i+1}'
for prefix in ['ga_st_','mtx_st_','st_abi_']:
 for i,t in enumerate(['筋力','耐久','敏捷','魔力','幸运']):labels[f'{prefix}{i:02d}.tex']=t
classes=['Saber','Rider','Archer','Caster','Berserker','Lancer','Assassin','Human']
for i,t in enumerate(classes,1):labels[f'mtx_cls_{i:02d}.tex']=t
for i,t in enumerate(classes[:7],10):labels[f'mtx_cls_{i:02d}.tex']=t+'?'
labels['mtx_cls_17.tex']='Saver'
for i,t in enumerate(['Saber','Archer','Caster']):labels[f'st_cls_{i:02d}.tex']=t
skills={'a00':'圈境 A','a01':'勇猛 B','a02':'骑乘 B','a03':'神性 B','a04':'咒术 EX','a05':'变化 A+','a06':'变化 A',
'b01':'魔眼 A→C','b02':'对魔力 B','b03':'对魔力 C','b04':'对魔力 D',
'c00':'皇帝特权 EX','c01':'头痛 B','c02':'单独行动 A','c03':'单独行动 C','c04':'心眼（伪） B','c05':'自我改造 A','c06':'战斗续行 A','c07':'破坏工作 A','c08':'气息遮断','c09':'中国武术','c10':'反骨之相 B','c11':'阵地建造 A','c12':'阵地建造 C',
'd00':'战斗续行 A→C','d01':'风暴航海者 A+','d02':'星之开拓者 EX','d03':'无辜的怪物 A','d04':'信仰的加护 A+','d05':'圣者之数字 EX','e00':'原初之一 EX→X','f00':'狂化 A','f01':'狂化 A→C'}
for k,t in skills.items():labels[f'mtx_skill_{k}.tex']=t
entries=[];used_bundles={}
def block(t,w,h,keep=0,preferred=14,align='left',box=None):
 if box is None:box=[keep,0,w-keep,h]
 x,y,ww,hh=box;size=min(preferred,hh)
 while size>7 and max(ImageFont.truetype(font,size,index=2).getlength(l)for l in t.split('\n'))>ww:size-=1
 lines=t.count('\n')+1;spacing=2
 if (size+spacing)*lines-spacing>hh:spacing=0
 size=min(size,hh//lines)
 # Clear all old characters inside the declared text region, then render.
 return [{'box':box,'background':[0,0,0,0]}, {'box':[x,y+max(0,(hh-(size+spacing)*lines+spacing)//2),ww,min(hh,(size+spacing)*lines-spacing)],'background':None,'text':t,'size':size,'spacing':spacing,'color':'palette_ink','align':align}]
for r in records:
 if 'preview'not in r:continue
 name=r['name'];f=r['path'].split('work/extracted/packages/pack/')[-1];w,h=r['width'],r['height'];bs=None
 if f.startswith(('tutorial_','modeselect/','000023_0/interface/staff/','000311_0/interface/staff/')):continue
 if name in labels:
  value=labels[name];text,keep=value if isinstance(value,tuple)else(value,0)
  size=14 if h<=16 else 16 if h<=32 else 20
  if name.startswith('adv_mes'):size=18
  if name.startswith(('mtx_cls_','st_cls_')):size=20
  bs=block(text,w,h,keep,size,align='center' if name.startswith('adv_mes') else 'left')
 elif name in ['btl_spt_00.tex','btl_spt_01.tex','btl_spt_02.tex','are_spt_00.tex','are_spt_01.tex']:
  texts={'btl_spt_00.tex':'技能','btl_spt_01.tex':'代码施放','btl_spt_02.tex':'道具','are_spt_00.tex':'道具','are_spt_01.tex':'代码施放'}
  bs=[{'box':[0,0,w,h],'background':{'clear_rgb':[118,199,216]}}, {'box':[0,6,w,16],'text':texts[name],'size':14,'color':[118,199,216,255],'background':None}]
 elif name=='shop_ttl_00.tex':bs=block('小卖部',w,h,preferred=32,align='center',box=[0,0,102,54])+[{'box':[98,20,50,16],'background':{'copy_box':[98,20,50,16]}}]
 elif name in ['shop_ttl_01.tex','shop_ttl_02.tex']:bs=block('购买'if'01'in name else'出售',w,h,preferred=28,align='center')
 elif name=='day_ttl_00.tex':bs=block('今日成果',w,h,preferred=39,box=[0,0,162,64])
 elif name=='ga_ttl_00.tex':bs=block('灵魂篡改',w,h,preferred=36,align='center')
 elif name=='ga_start_00.tex':bs=[{'box':[0,0,w,h],'background':{'clear_rgb':[255,255,255]}},{'box':[56,9,99,27],'text':'开始篡改','size':18,'align':'center','background':None,'color':'palette_ink'}]
 elif name in ['pro_day_base.tex','pro_day_base2.tex']:
  bs=block('距离决战还有'if name=='pro_day_base.tex'else'校园生活剩余',w,h,preferred=14,box=[0,0,112,18])
 elif name in [f'pro_time_{i:02d}.tex' for i in range(4)]:
  t=['早晨','中午','傍晚','夜晚'][int(name[-6:-4])];bs=block(t,w,h,preferred=19,align='center',box=[0,0,42,24])
 elif name in [f'time_time_{i:02d}.tex'for i in range(4)]:
  t=['早晨','中午','傍晚','决战日'][int(name[-6:-4])];bs=block(t,w,h,preferred=21,align='center')
 elif name=='beg_rem.tex':bs=block('剩余',w,h,preferred=28,box=[0,0,90,h])
 elif name in ['beg_font_l10.tex','beg_font_m01.tex','beg_font_m02.tex','beg_font_m04.tex','beg_font_m06.tex','beg_font_m14.tex']:
  text={'beg_font_l10.tex':'决','beg_font_m01.tex':'战','beg_font_m02.tex':'开','beg_font_m04.tex':'圣','beg_font_m06.tex':'争','beg_font_m14.tex':'胜'}[name]
  bs=block(text,w,h,preferred=34 if w==48 else 30,align='center')
 elif re.match(r'e_hougu_font01_\d\d.tex',name):
  texts=['此身为剑所天成。','血若钢铁，心似琉璃。','纵横无数战场而不败。','未曾一次败退。','亦未曾被人理解。','彼常独立于剑丘之上，\n沉醉于胜利之中。','故其生涯毫无意义。','此身，定为剑所天成。'];t=texts[int(name[-6:-4])];bs=block(t,w,h,preferred=16,align='center')
 elif name in ['slt_text_01.tex','slt_text_02.tex','slt_text_03.tex']:
  i=int(name[-6:-4])-1;t=['身披绯红衣裳的男装少女。\n适合初次游玩的玩家选择。','身披红色外套、神情忧郁的武人。\n适合希望灵活运用多种技能的玩家。','衣着大胆的半兽咒术师。\n适合喜欢挑战逆境的玩家。'][i]
  bs=block(['Saber','Archer','Caster'][i],w,h,preferred=21,box=[0,0,w,28])+block(t,w,h,preferred=14,box=[0,44,w,52])
 elif re.search(r'/dungeon/are_title_\d+\.txb',f) and r['index']in[1,2,3]:
  a=int(re.search(r'are_title_(\d+)',f).group(1));text=('第'+['零','一','二','三','四','五','六','七','零'][a]+'月想海')if r['index']==1 else'第一层'if r['index']==2 else'第二层';bs=block(text,w,h,preferred=30 if r['index']==1 else 20,align='center')
 if bs:
  entries.append({'file':f,'index':r['index'],'source_name':name,'blocks':bs});used_bundles[f]=r['bundle_aliases']
copies=[]
for f,aliases in used_bundles.items():
 targets=[p.split('work/extracted/packages/pack/')[-1]for p in aliases if p!='work/extracted/packages/pack/'+f]
 if targets:copies.append({'source':f,'targets':targets})
config={'entries':entries,'copies':copies}
(BASE/'ui-text-patches.json').write_text(json.dumps(config,ensure_ascii=False,indent=2)+'\n')
print({'canonical_bundles':len(used_bundles),'textures':len(entries),'copied_bundles':sum(len(c['targets'])for c in copies)})
