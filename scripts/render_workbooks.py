"""Render every output page, plus contact sheets, for visual proofreading."""
import json
from pathlib import Path
import fitz
from PIL import Image,ImageDraw
ROOT=Path(__file__).resolve().parents[1]
for project in ['数学分析讲义','数学分析教程']:
    output=ROOT/project/'qa/rendered'
    output.mkdir(parents=True,exist_ok=True)
    thumbs=[]
    with fitz.open(ROOT/project/'main.pdf') as doc:
        for number,page in enumerate(doc,1):
            image=output/f'page-{number:03d}.png'
            page.get_pixmap(matrix=fitz.Matrix(1.8,1.8),alpha=False).save(image)
            with Image.open(image) as im:
                thumb=im.convert('RGB')
            thumb.thumbnail((350,495))
            tile=Image.new('RGB',(374,530),'#e5e7eb')
            tile.paste(thumb,((374-thumb.width)//2,25))
            ImageDraw.Draw(tile).text((14,8),str(number),fill='black')
            thumbs.append(tile)
        for start in range(0,len(thumbs),6):
            batch=thumbs[start:start+6]
            sheet=Image.new('RGB',(374*3,530*((len(batch)+2)//3)),'white')
            for i,tile in enumerate(batch):sheet.paste(tile,((i%3)*374,(i//3)*530))
            sheet.save(output/f'contact-{start//6+1}.png')
        print(json.dumps({'project':project,'pages':len(doc),'images':str(output)},ensure_ascii=False))
