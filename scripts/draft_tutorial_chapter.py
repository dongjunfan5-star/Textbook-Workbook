"""Collect OCR question candidates for editorial review; never mark them verified."""
import argparse,json,re
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def split_parts(text):
    matches=list(re.finditer(r'(?m)^\s*[（(](\d+)[）)]\s*',text))
    if not matches:return text.strip(),[]
    if [int(m[1]) for m in matches]!=list(range(1,len(matches)+1)):
        return text.strip(),[]
    return text[:matches[0].start()].strip(),[text[m.end():matches[i+1].start() if i+1<len(matches) else None].strip() for i,m in enumerate(matches)]

def math_format(text):
    text=re.sub(r'\$\$(.*?)\$\$',lambda m:r'\['+m[1].strip()+r'\]',text,flags=re.S)
    return text.strip()

def main():
    ap=argparse.ArgumentParser();ap.add_argument('chapter');ap.add_argument('--allow-partial',action='store_true');args=ap.parse_args()
    inventory=json.loads((ROOT/'config/production-books.json').read_text(encoding='utf-8'))
    selection=[]
    for book in inventory['books']:
        if book['project']!='数学分析教程':continue
        for chapter in book['chapters']+book.get('appendices',[]):
            if str(chapter['chapter'])==args.chapter:selection.append((book,chapter))
    if len(selection)!=1:raise ValueError('Chapter must be unique')
    book,chapter=selection[0]
    units=[]; current=None; in_exercises=False; missing=[]; blocks=[]
    def finish():
        nonlocal current
        if current:
            raw='\n\n'.join(current.pop('chunks'))
            stem,parts=split_parts(raw)
            current.update(stem_latex=math_format(stem),subquestions=[math_format(x) for x in parts])
            units.append(current);current=None
    def begin(page,kind,mark,body):
        nonlocal current
        finish()
        current={k:book[k] for k in ('source_file','source_id','source_sha256')}
        current.update(chapter=chapter['chapter'],chapter_title=chapter['title'],page_number=page,source_end_page=page,kind=kind,candidate_marker=mark,review_status='unreviewed',figures=[],chunks=[body] if body else [])
    for page in range(chapter['physical_start'],chapter['physical_end']+1):
        file=ROOT/book['project']/'data/ocr_raw/vl1.6'/book['source_id']/f'p{page:04d}'/'result.md'
        if not file.exists():
            missing.append(page);finish();in_exercises=False;continue
        for block in re.split(r'\n\s*\n',file.read_text(encoding='utf-8')):
            block=block.strip();clean=re.sub(r'^#+\s*','',block).strip()
            blocks.append({'page':page,'text':block})
            if re.match(r'^(?:练习题?|习题|问题)\s*\d',clean):
                finish();in_exercises=True;continue
            if re.match(r'^\d+\.[\d.]+\s+[^$\\]',clean) and (block.startswith('#') or len(clean)<65):
                finish();in_exercises=False;continue
            example=re.match(r'^例\s*(\d+)\s*[.．、:：]?\s*(.*)',clean,flags=re.S)
            if example:
                in_exercises=False;begin(page,'example','example '+example[1],example[2]);continue
            if not in_exercises and re.match(r'^(?:证明|解答?|证|说明)\s*[：:]?\s*',clean):
                finish();continue
            if in_exercises:
                question=re.match(r'^(\d+)\s*[.．、]\s*(.*)',clean,flags=re.S)
                if question:begin(page,'exercise','exercise '+question[1],question[2]);continue
            if current:
                current['chunks'].append(block)
                current['source_end_page']=page
        # Retain current question over a physical page boundary.
    finish()
    out=ROOT/'.cache/candidates/tutorial';out.mkdir(parents=True,exist_ok=True)
    payload={'status':'unreviewed','chapter':chapter['chapter'],'missing_pages':missing,'warning':'Regex candidates may include solutions, omit tasks or have wrong boundaries/formulas. Require page-by-page visual review.','units':units}
    (out/f'chapter_{args.chapter}.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (out/f'chapter_{args.chapter}.blocks.json').write_text(json.dumps(blocks,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'candidates':len(units),'missing_pages':missing}))
    if missing and not args.allow_partial:raise SystemExit('Partial OCR; candidates remain incomplete')

if __name__=='__main__':main()
