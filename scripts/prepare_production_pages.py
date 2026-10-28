"""Expand the verified book inventory into resumable OCR and review manifests."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def main():
    inventory=json.loads((ROOT/'config/production-books.json').read_text(encoding='utf-8'))
    pages=[]
    reviews=[]
    old_file=ROOT/'qa/production-page-reviews.json'
    old=json.loads(old_file.read_text(encoding='utf-8')) if old_file.exists() else []
    existing={(p['project'],p['source_file'],p['page_number']):p for p in old}
    for book in inventory['books']:
        included={p for first,last in book['included_ranges'] for p in range(first,last+1)}
        excluded={p:r['reason'] for r in book['excluded_ranges'] for p in range(r['physical_start'],r['physical_end']+1)}
        if included & excluded.keys() or included | excluded.keys() != set(range(1,book['pdf_pages']+1)):
            raise ValueError('Every source page must be classified exactly once')
        for p in range(1,book['pdf_pages']+1):
            row={k:book[k] for k in ('project','source_file','source_id','source_sha256')}
            row['page_number']=p
            key=(row['project'],row['source_file'],p)
            if p in included:
                chapters=book['chapters']+book.get('appendices',[])
                chapter=next(c for c in chapters if c['physical_start']<=p<=c['physical_end'])
                row.update(chapter=chapter['chapter'],chapter_title=chapter['title'])
                pages.append(row)
                reviews.append(existing.get(key,{**row,'status':'pending'}))
            else:
                reviews.append({**row,'status':'excluded','reason':excluded[p]})
    (ROOT/'config/production-pages.json').write_text(json.dumps(pages,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    old_file.write_text(json.dumps(reviews,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(f'{len(pages)} OCR pages; {len(reviews)-len(pages)} excluded pages')

if __name__=='__main__':main()
