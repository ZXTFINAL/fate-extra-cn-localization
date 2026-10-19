import json
from pathlib import Path
from PIL import ImageFont
base=Path('work/research/ui-localization-audit');tasks=[];results=[]
for letter in ['A','B']:
 tasks += [json.loads(l)for l in (base/f'translation-task-{letter}.jsonl').read_text().splitlines()]
 results += [json.loads(l)for l in (base/f'translation-result-{letter}.jsonl').read_text().splitlines()]
lookup={r['image_id']:r for r in results};entries=[];review=[]
font='/System/Library/Fonts/Hiragino Sans GB.ttc'
for task in tasks:
 if task['kind']!='tutorial':continue
 r=lookup[task['image_id']];title=r['title_zh'];body='\n'.join(r['body_zh'])
 size=14
 while size>11 and max(ImageFont.truetype(font,size,index=2).getlength(l)for l in body.split('\n'))>452:size-=1
 if len(body.split('\n'))>2:raise ValueError(f'too many lines {task["image_id"]}')
 for alias in task['aliases']:
  blocks=[
   {'box':[80,0,300,20],'background':'row_median'},
   {'box':[80,2,300,18],'background':None,'text':title,'size':13,'spacing':0,'align':'center','color':[214,228,255,255]},
   {'box':[0,228,480,44],'background':'row_median'},
   {'box':[14,233,452,38],'background':None,'text':body,'size':size,'spacing':4,'color':[248,248,255,255]},
  ]
  if alias['file'].split('/')[0] in ['tutorial_other_00','tutorial_other_01']:
   # These menu labels were verified visually; leave button icons and English
   # decoration intact. Copy only each bar's empty centre into the old text.
   blocks += [{'box':[168,48,128,14],'background':{'copy_box':[300,48,10,14]},'text':'请选择项目。','size':9,'color':[194,230,255,255]}]
   for y,text in zip([81,96,111,126,141,156],['保存','读取','删除存档','选项设置','重新挑战','返回标题']):
    blocks.append({'box':[102,y,84,12],'background':{'copy_box':[186,y,12,12]},'text':text,'size':9,'color':[240,250,255,255]})
   blocks.append({'box':[88,205,144,15],'background':{'copy_box':[260,205,8,15]},'text':'保存游戏进度。','size':9,'color':[235,235,220,255]})
  entries.append({'file':alias['file'],'index':alias['index'],'image_id':task['image_id'],'source_png':task['png'],'blocks':blocks})
 review.append({'image_id':task['image_id'],'aliases':task['aliases'],'title_zh':title,'body_zh':r['body_zh'],'font_size':size,'notes':r.get('notes'),'screenshot_terms':r.get('screenshot_key_labels',r.get('screenshot_terms',[]))})
(base/'tutorial-text-patches.json').write_text(json.dumps({'entries':entries},ensure_ascii=False,indent=2)+'\n')
(base/'tutorial-translation-review.json').write_text(json.dumps(review,ensure_ascii=False,indent=2)+'\n')
print({'unique_tutorial_images':len(review),'texture_instances':len(entries),'font_sizes':sorted({r['font_size']for r in review})})
