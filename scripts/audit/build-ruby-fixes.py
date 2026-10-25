import json,re,collections,difflib
from pathlib import Path
D=Path(__file__).parent
rows=[json.loads(x) for x in Path('work/translation/text.jsonl').read_text().splitlines()]
P=re.compile(r'#RUBS(.*?)#RUBE(.*?)#REND',re.S)
# Explicit decisions for non-phonetic Japanese readings. The remainder of hiragana
# readings are ordinary furigana, and do not carry a second Chinese meaning.
HIRA={
('ここ','セラフ'):'这里',('こちら','僕'):'我这边',('おわり','結末'):'终焉',
('ひと','人間'):'人',('ひと','女'):'人',('ふじむら','タイガー'):'藤村',
('つぶや','術唱'):'低语',('からだ','本能'):'身体',('な','冠'):'名字',('な','命'):'名字',('おのれ','個人'):'自己',('な','銘'):'名字',('な','実'):'名字',
('よぶ','召喚する'):'叫来',('わかれ','挨拶'):'道别',('たたかい','聖杯戦争'):'战斗',('にくしみ','糾弾'):'憎恨',('ほこり','善性'):'骄傲',('ゆめ','記憶'):'梦',('れきし','記録'):'历史',('ほし','天'):'星辰',('むしかご','鐘楼'):'虫笼',('からだ','筐体'):'身体',('こえ','返答'):'声音',('うごき','機能'):'动作',
('せかい','未来'):'世界',('そこ','現在'):'那里',('がくえん','安全地帯'):'学园',('ありす','あたし'):'爱丽丝',('あたし','ありす'):'我',('あい','過食'):'爱',('こえ','批評'):'声音',('げんじつ','結果'):'现实',('こころ','気持ち'):'心',('おもい','怨念'):'思念',('ちから','能力'):'力量',('あかり','太陽'):'光',('とき','瞬間'):'时间',('におい','気配'):'气味',('せんそう','行為'):'战争',('われわれ','人類'):'我们',('ゆめ','理想'):'梦',('もの','存在'):'东西',('みらい','結末'):'未来',('うつくしさ','在り方'):'美丽',('はな','沙羅'):'花',('そこ','地上'):'那里',('あなた','人間'):'你',('ほし','地球'):'星球',('ひと','他人'):'人',('こころ','己'):'心',('すべて','剣'):'一切',('むね','心臓'):'胸膛',('けいけんち','ＥＸＰ'):'经验值',('げんじつ','此処'):'现实',('なまえ','正体'):'名字',('わたし','間桐桜'):'我',('記録','セーブ'):'记录',('ひがし','死角'):'东边',('せかい','聖杯'):'世界',('きせき','故障'):'奇迹',('した','一階'):'楼下',('おじいちゃん','老騎士'):'爷爷',('かれ','ダン'):'他',('ちから','権限'):'力量',('ひと','己'):'人',('こうふく','人生'):'幸福',('まりょく','燃料'):'魔力',('にんげん','自分'):'人',('きせき','聖杯'):'奇迹',('つくりもの','仮想世界'):'虚构之物',('ありす','お友達'):'爱丽丝',('きじゅつ','詠唱'):'记述',('たましい','電脳'):'灵魂',('ありす','子供'):'爱丽丝',('ころして','乗り越え'):'杀死',('よせん','学園生活'):'预选赛',('じぶん','過去'):'自己',('なかみ','願い'):'内在',('ほんね','感情'):'真心话',('なかみ','感情'):'内在',('だんぺん','資料'):'片段',('みたす','理解する'):'填满',('いろ','表情'):'色彩',('なかみ','魂'):'内在',('こころ','なかみ'):'心',('わたし','器'):'我',('こころ','清水'):'心',('きかい','衛星'):'机器',('そら','宙'):'天空',('にんげん','文明'):'人类',('なかみ','自覚'):'内在',('なかみ','意識'):'内在',('なかみ','清水'):'内在',('それ','意思'):'它',('きぼう','気持ち'):'希望',('げんじつ','理性'):'现实',('せんせい','師匠'):'老师',('ころしあい','聖杯戦争'):'厮杀',('い','存在'):'活',('なりたち','理由'):'来历',('あいて','英霊'):'对手',('なかみ','こころ'):'内在',('そこ','淵'):'那里',('あいて','彼女'):'对手',('はじめ','誕生'):'开始',('いのち','使命'):'生命',('ちち','創造者'):'父亲',('いのち','目的'):'生命',('し','領'):'知晓',('こころ','精神'):'心',('いのち','願い'):'生命',('ねがい','感情'):'愿望',
('じしゅきせい','でも'):'自主规制',
}
HIRA.update({('ありす','主人'):'爱丽丝',('あ','仮初'):'那段',('あ','召還'):'那时'})
# Katakana readings that only spell a Japanese name, numeral, or a laugh.
DROP_KATA={'コトミネ','カ','カカ','カカカ','カカカカカ','エイト','ツムカリ','アベ','ネノクニ','カコバナ','Ｔｗｉｃｅ','Ｐｉｅｃｅｍａｎ','ゴキブリ','メガネ','ハナ','アダ'}
# Semantic labels with an established short form. Preserve other translated labels
# when they already convey the second meaning; this avoids rewriting unrelated prose.
UPPER={
'マスター':'御主','トリガー':'触发器','セカンダリトリガー':'次级触发器','プライマリトリガー':'初级触发器','ラスト・トリガー':'最终触发器','ウィザード':'Wizard','ウイザード':'Wizard','ドール':'Doll','タスク':'任务','バイパス':'旁路','エネミー':'Enemy','ノイズ':'噪声','ログアウト':'登出','モラトリアム':'Moratorium','アンチプロテクトコード':'反防护代码','アサシン':'Assassin','ランサー':'Lancer','バーサーカー':'Berserker','アーチャー':'Archer','セイバー':'Saber','サーヴァント':'Servant','アンテナ':'天线','ファイアウォール':'防火墙','アンチウイルス':'杀毒程序','プロテクト':'Protect','プログラム':'程序','ルールブレイク':'破坏规则','ルールブレイカー':'Rule Breaker','ピービング':'Peeping','システムサイド':'系统方','ＮＰＣ':'NPC','セラフ':'SE.RA.PH','ラック':'Luck','アーティファクト':'Artifact','ヘテロクロミア':'异色瞳','マナ':'Mana','マジック':'Magic','エレメント':'EIement','デリート':'删除','ダンジョン':'Dungeon','ハンティング':'狩猎','データ':'数据','ドレスブラスト':'Dress Blast','アンチ・アーティファクト':'Anti-Artifact','マインドブラスト':'Mind Blast','アンチ・マインド':'Anti-Mind','コピー':'复制','マルチクラス':'多重职阶','コマンド':'Command','セブンスヘブン・アートグラフ':'Seventh Heaven Artgraph','ソドム':'索多玛','アイドル':'Idol','モデル':'Model','パートナー':'搭档','クラス':'职阶','リンク':'Link','マーチ・ヘアー':'March Hare','ファーム':'Farm','スクリーン':'Screen','ゴースト':'Ghost','デミエルフ':'半精灵','サーキット':'Circuit','ジャブ':'Jab','マグヌス・オプス':'Magnum Opus','プネウマ':'Pneuma','アーサー':'亚瑟','カタチ':'形态','ルート':'Route','ルール':'Rule','デート':'约会','リベンジ':'Revenge','システム':'系统','アストロジー':'Astrology','ブロック':'Block','ピース':'Piece','アドバイス':'Advice','バカなモノ':'蠢货','アカイア':'阿开亚','ヘヴン':'Heaven','タキトゥス':'塔西佗','アダ':'仇','アタック':'Attack','ケア':'Care','メンタルケア':'Mental Care','イメージ':'Image','エア':'Air','パターン':'Pattern','ソラ':'天空','コレクター':'收藏家','コト':'这件事','フォント':'Font','インヴェーダー':'侵略者','ゴールデンハインド':'Golden Hind','ゴールデン・ハインド':'Golden Hind','トレース':'Trace','ミラクル':'奇迹','ルーチン':'日常程序','ガードドール':'Guard Doll','カソック':'Cassock','パーソナル':'Personal','ジョリーロジャー':'Jolly Roger','フィジカル':'Physical','カード':'Card','アドレス':'Address','ドムス・アウレア':'Domus Aurea','レーダー':'雷达','アラート':'警报','スイッチ':'Switch','コロコロ':'滚来滚去','テーマ':'Theme','アリス':'爱丽丝','フォックスセンス':'狐狸直觉','オーバーキル':'过度杀伤','バルバロイ':'Barbaroi','マーラ':'魔罗','レゾンデートル':'Raison d etre','ブッチギ':'干翻','モンスター':'Monster','オーダー':'Order','サーチアンドデストロイ':'搜索并歼灭','インビジブル・エア':'Invisible Air','リンクアウト':'断开连接','キャストブラスト':'Cast Blast','アンチ・キャスト':'Anti-Cast','ホムンクルス':'Homunculus','ナリ':'模样','ソフト':'软件','バックアップ':'支援','プロセス':'Process','アレ':'那东西','ムーンセル':'Moon Cell','レール':'轨道','コート':'Coat','テクスチャ':'Texture','チート':'作弊','ガウェイン':'高文','イレギュラー':'异常','ディティール':'细节','アクシデント':'事故','マスク':'屏蔽','ゲーム':'Game','モード・オシリス':'Mode Osiris','エーテライト':'Etherlite','オパール':'蛋白石','ファイヤーウォール':'防火墙','サイバーゴースト':'Cyber Ghost','電脳工学':'电脑工程学','タイプ':'Type','アートグラフ':'Artgraph','ヴァジュラ':'金刚杵','セイヴァー':'Saver','インプットしなければ':'输入','コールドスリープ':'冷冻睡眠','フェイト':'Fate','ワンダーランド':'Wonderland','カラダ':'身体','ラグナロク':'Ragnarok','ロール':'Role','ムフロン':'摩弗伦羊','テクスチャー':'Texture','インストール':'Install','バグ':'Bug','サイバースペース':'Cyberspace','モブ':'路人','ガイド':'Guide','バトルログ':'Battle Log','ＣＯＣＨＭＡ':'Chokhmah','コーヒー':'咖啡','メイガス':'Magus','モノ':'东西','メモリー':'Memory','エル・ドラゴ':'EI Drago','アリーナ':'Arena','セーブ':'Save','シリアル':'Serial','ファンタズム':'Phantasm','ＳＥ・ＲＡ・ＰＨ':'SE.RA.PH','ゲームオーバー':'Game Over','アナライズ':'Analyze','オーバースペック':'超出规格','エデン':'Eden','Ｇ':'G','スプーフィング':'Spoofing','レコード':'Record','アトラス':'阿特拉斯','ハーウェイ':'哈维','エンジン':'Engine','イー・バウ':'Yew Bow','プライベート':'Private','ウィルス':'病毒','アイデンティティークライシス':'自我认同危机','タフ':'Tough','ガード':'Guard','ラッキー':'Lucky','ロジックカンサー':'Logic Cancer','アルケミー':'Alchemy','セグメント':'Segment','コード':'Code','デフォルト':'Default','ライブラリ':'Library','パラダイマイザー':'Paradigmizer','モノクローム':'Monochrome','ハッキング':'Hacking','トーン':'Tone','ファイヤウォール':'防火墙','ゲシュタ':'格式塔','ワード':'Word','ストイック':'禁欲','ヒロイック':'英雄','バックドア':'后门','サブタンク':'副油箱','ハッカー':'黑客','モーマンタイ':'冇问题','トランスルーセント':'Translucent','スキル':'Skill','オレ':'我','クイックコード':'Quick Code','スペル':'Spell','コードキャスト':'Code Cast','ファントム':'Phantom','アンチワームコード':'反蠕虫代码','クラッキングコード':'Cracking Code','ドレス':'Dress','スコア':'Score','チャンス':'Chance','ヴォルカヌス':'伏尔甘','エキセントリックな':'古怪','マ':'御','エクィテス':'Equites','ガキ':'小鬼','タイプライター':'Typewriter',
'ガラティーン':'Galatine','エクスカリバー':'Excalibur','ゲイ・ボルク':'Gae Bolg','ゴッド・フォース':'God Force','アンリミテッド・ブレイドワークス':'Unlimited Blade Works','ウエストゥス・ドムス・アウレア':'Aestus Domus Aurea','カズィクル・ベイ':'Kazikli Bey',
}
def norm(s):return re.sub(r'[ \u3000]','',s)
def category(a,b):
 a=norm(a)
 if a and set(a)=={'・'}:return 'emphasis'
 if (a,b) in HIRA:return 'semantic'
 if a in DROP_KATA or (a in {'シリアル','ファンタズム','ファントム'} and re.fullmatch('[Ａ-Ｚａ-ｚA-Za-z．]+',b)) or (a=='セラフ' and b=='ＳＥ．ＲＡ．ＰＨ') or (a=='ＳＥ・ＲＡ・ＰＨ' and b=='セラフ'):return 'reading'
 if a in UPPER or re.search('[ァ-ヺＡ-Ｚａ-ｚA-Za-z]',a):return 'semantic'
 return 'reading'
def upper(a,b,current):
 a=norm(a)
 if category(a,b)=='emphasis':return '・'*max(1,len(re.sub(r'#C\d{9}|#CDEF','',current)))
 if (a,b)==('タイプ','記録'):return '键入'
 return HIRA.get((a,b),UPPER.get(a))
# Main-layer spellings on recurring terminology and several incomplete translations.
BASE={('マスター','ご主人様'):'主人',('マスター','ご主人様っ'):'主人',('マスター','奏者'):'奏者',('トリガー','暗号鍵'):'暗号键',('セカンダリトリガー','第二暗号鍵'):'第二暗号键',('プライマリトリガー','第一暗号鍵'):'第一暗号键',('ウィザード','魔術師'):'魔术师',('ウイザード','魔術師'):'魔术师',('ドール','人形'):'人偶',('タスク','試練'):'试炼',('バイパス','割込回路'):'插入回路',('エネミー','敵性プログラム'):'敌性程序',('ノイズ','残留魔力'):'残留魔力',('モラトリアム','猶予期間'):'猶予期間',('アンチプロテクトコード','抗防御結界術式'):'抗防御结界术式',('マ','ご'):'主',('むしかご','鐘楼'):'钟楼',('し','領'):'统领',('コト','結論'):'结论',('タイプ','記録'):'记录',('記録','セーブ'):'存档',('な','実'):'本质',('な','銘'):'铭',('な','冠'):'冠冕',('おわり','結末'):'结局',('あかり','太陽'):'太阳',('ほし','地球'):'地球',('なかみ','意識'):'意识',('こころ','清水'):'清水',('なかみ','清水'):'清水'}
# Do not introduce traditional Japanese residue in a removed phonetic annotation.
READ_BASE={'蠍':'蝎','滾':'沸腾','滾烫':'沸腾','躊躇':'犹豫','懐疑':'怀疑','遡':'追溯','斃':'毙','慇懃':'殷勤','詫':'道歉','僥幸':'侥幸','儂':'老夫','不加以':'不加以','尾长鸡':'长尾鸡','努努':'万万','刺々':'刺耳'}
# Rows with genuinely missing semantic annotations are rewritten below by hand.
MANUAL={}
def R(u,b):return '#RUBS'+u+'#RUBE'+b+'#REND'
# Review log: all source pairs and every resulting row are exported for reproducibility.
pairs=collections.Counter()
fixes=[]; decisions=[]; pending=[]; mixed=[]
for i,r in enumerate(rows):
 s=r['jp'];z=r.get('zh_cn','');jm=list(P.finditer(s));zm=list(P.finditer(z))
 if not jm and not zm and '#RUB' not in z:continue
 js=[(norm(m[1]),m[2]) for m in jm]
 for a,b in js:pairs[(a,b,category(a,b))]+=1
 cats=[category(a,b) for a,b in js]
 if len(jm)==len(zm):
  # Most entries preserve tag order; mixed entries are printed and checked separately.
  out=[];p=0;reasons=[]
  for j,(m,(a,b)) in enumerate(zip(zm,js)):
   cat=category(a,b);u,v=m[1],m[2]
   out.append(z[p:m.start()]);p=m.end()
   if cat=='reading':
    nv=READ_BASE.get(v,v);out.append(nv);reasons.append('删除普通日文读音，中文正文直接表义')
   else:
    nu=upper(a,b,v)
    if nu is None:nu=u
    nv=BASE.get((a,b),v)
    if (a,b)==('モラトリアム','猶予期間'):nv='宽限期间'
    out.append(R(nu,nv));reasons.append('保留并恢复特殊双意表记' if cat=='semantic' else '保留原文强调点')
  out.append(z[p:]);new=''.join(out)
  if 'semantic' in cats and 'reading' in cats:mixed.append(dict(index=i,id=r['id'],jp=s,old=z,new=new))
 elif not any(c!='reading' for c in cats):
  new=P.sub(lambda m:READ_BASE.get(m[2],m[2]),z);reasons=['删除普通日文读音，中文正文直接表义']
 else:
  new=z;reasons=[];pending.append(dict(index=i,id=r['id'],jp=s,old=z,source=js))
 if new!=z:fixes.append(dict(id=r['id'],zh_cn=new,reason='；'.join(dict.fromkeys(reasons))))
 decisions.append(dict(index=i,id=r['id'],source=[dict(upper=a,base=b,category=category(a,b)) for a,b in js],old=z,new=new))
D.joinpath('ruby-candidate-fixes.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in fixes))
D.joinpath('ruby-pair-decisions.jsonl').write_text(''.join(json.dumps(dict(upper=a,base=b,category=c,count=n),ensure_ascii=False)+'\n' for (a,b,c),n in pairs.items()))
D.joinpath('ruby-mixed-review.json').write_text(json.dumps(mixed,ensure_ascii=False,indent=2))
D.joinpath('ruby-pending.json').write_text(json.dumps(pending,ensure_ascii=False,indent=2))
D.joinpath('ruby-row-audit.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in decisions))
print('pairs',collections.Counter({c:sum(n for (a,b,cat),n in pairs.items() if cat==c) for c in {'reading','semantic','emphasis'}}))
print('fixes',len(fixes),'mixed',len(mixed),'pending',len(pending))
