from pathlib import Path
from PIL import Image
import numpy as np,json
shot=Image.open('/Users/zhaoxiangting/Desktop/截屏2026-10-19 12.23.53.png').convert('L')
result=[]
for name,yrange in [('opening',range(586,595)),('ordinary',range(620,628))]:
 src=Image.open(Path('work/research/poem-font-audit')/f'{name}-runtime.png').resize((144 if name=='opening' else 196,14),Image.Resampling.NEAREST)
 best=(-1,None)
 for scale in np.arange(1.65,1.91,.005):
  size=(round(src.width*scale),round(src.height*scale))
  for method in [Image.Resampling.BILINEAR,Image.Resampling.NEAREST,Image.Resampling.BICUBIC]:
   z=np.asarray(src.resize(size,method),dtype=float);z-=z.mean();zn=np.linalg.norm(z)
   for y in yrange:
    for x in range(485,497):
     t=np.asarray(shot.crop((x,y,x+size[0],y+size[1])),dtype=float);t-=t.mean();score=np.sum(z*t)/max(1e-10,zn*np.linalg.norm(t))
     if score>best[0]:best=(float(score),dict(x=x,y=y,width=size[0],height=size[1],scale=float(scale),resample=str(method)))
 result.append(dict(name=name,correlation=best[0],**best[1]))
print(json.dumps(result,indent=2))
Path('work/research/poem-font-audit/screenshot-match.json').write_text(json.dumps(result,indent=2)+'\n')
