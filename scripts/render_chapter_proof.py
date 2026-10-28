"""Render every proof PDF page and labeled four-page contact sheets for visual QA."""
import argparse
from pathlib import Path
import fitz
from PIL import Image,ImageDraw

ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser()
parser.add_argument('pdf')
args=parser.parse_args()
pdf=(ROOT/args.pdf).resolve()
if not pdf.is_relative_to(ROOT):raise ValueError('Proof must be in workspace')
out=pdf.parent/'rendered'
out.mkdir(exist_ok=True)
with fitz.open(pdf) as doc:
    for p in doc:
        p.get_pixmap(matrix=fitz.Matrix(1.5,1.5),alpha=False).save(out/f'page-{p.number+1:04d}.png')
    for start in range(0,len(doc),4):
        canvas=Image.new('RGB',(1600,2280),'#cccccc')
        draw=ImageDraw.Draw(canvas)
        for i in range(start,min(start+4,len(doc))):
            im=Image.open(out/f'page-{i+1:04d}.png').convert('RGB')
            im.thumbnail((790,1100))
            x=(i-start)%2*800;y=(i-start)//2*1140
            draw.text((x+10,y+5),f'PDF page {i+1}',fill='black')
            canvas.paste(im,(x+(800-im.width)//2,y+30))
        canvas.save(out/f'contact-{start+1:04d}.jpg',quality=90)
    print(f'{len(doc)} pages rendered to {out}')
