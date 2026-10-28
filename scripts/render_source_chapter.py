"""Read-only source rendering for chapter-by-chapter editorial review."""
import argparse,json
from pathlib import Path
import fitz
from PIL import Image,ImageDraw
ROOT=Path(__file__).resolve().parents[1]
ap=argparse.ArgumentParser();ap.add_argument('project');ap.add_argument('chapter');args=ap.parse_args()
books=json.loads((ROOT/'config/production-books.json').read_text(encoding='utf-8'))['books']
matches=[(b,c) for b in books if b['project']==args.project for c in b['chapters']+b.get('appendices',[]) if str(c['chapter'])==args.chapter]
if len(matches)!=1:raise ValueError('Chapter not uniquely identified')
book,ch=matches[0]
prefix='tutorial' if args.project=='数学分析教程' else 'lecture'
out=ROOT/'.cache'/f'review-{prefix}{args.chapter.zfill(2)}';out.mkdir(parents=True,exist_ok=True)
first,last=ch['physical_start'],ch['physical_end']
with fitz.open(ROOT/args.project/book['source_file']) as doc:
    for n in range(first,last+1):
        path=out/f'p{n:04d}.png'
        if not path.exists():
            page=doc[n-1];scale=1800/page.rect.width
            page.get_pixmap(matrix=fitz.Matrix(scale,scale),alpha=False).save(path)
for n in range(first,last+1,4):
    sheet=Image.new('RGB',(1800,2520),'#ddd');draw=ImageDraw.Draw(sheet)
    for k,p in enumerate(range(n,min(n+4,last+1))):
        im=Image.open(out/f'p{p:04d}.png').convert('RGB');im.thumbnail((890,1220))
        x=k%2*900;y=k//2*1260
        draw.text((x+10,y+5),f'Physical page {p}',fill='black');sheet.paste(im,(x+(900-im.width)//2,y+30))
    sheet.save(out/f'contact-{n:04d}.jpg',quality=92)
print(json.dumps({'source':book['source_file'],'first':first,'last':last,'output':str(out)},ensure_ascii=False))
