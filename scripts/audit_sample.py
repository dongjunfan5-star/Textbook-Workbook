"""Check that the sample is traceable, complete, and matches the compiled PDFs."""
import argparse
import hashlib
import json
import re
from pathlib import Path
import fitz
ROOT=Path(__file__).resolve().parents[1]
def read(path):return json.loads(path.read_text(encoding='utf-8'))
def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--require-ocr',action='store_true')
    args=parser.parse_args()
    inventory=read(ROOT/'config/sample-inventory.json')
    hashes={}
    ocr_pages=[]
    for item in inventory:
        source=ROOT/item['project']/item['source_file']
        if source not in hashes:
            with source.open('rb') as f: hashes[source]=hashlib.file_digest(f,'sha256').hexdigest()
        assert hashes[source]==item['source_sha256'],f'Source changed: {source}'
        dest=ROOT/item['project']/'data/ocr_raw'/item['source_id']/f"p{item['page_number']:04d}"
        complete=(dest/'completed.json').is_file()
        if args.require_ocr:
            assert complete,f'OCR incomplete: {dest}'
            assert list(dest.glob('*_res.json')) and list(dest.glob('*.md')),f'OCR output missing: {dest}'
        ocr_pages.append({'project':item['project'],'source_id':item['source_id'],'page_number':item['page_number'],'complete':complete,'seconds':read(dest/'completed.json')['seconds'] if complete else None})
    reports=[]
    for project in ['数学分析讲义','数学分析教程']:
        path=ROOT/project
        problems=read(path/'data/problems.json')['problems']
        build=read(path/'qa/build-report.json')
        assert not build['latex_issues'],f'Unresolved LaTeX warning in {project}'
        ids=[p['id'] for p in problems]
        assert len(ids)==len(set(ids))==build['problem_count']
        with fitz.open(path/'main.pdf') as doc:
            assert len(doc)==1+len(build['page_plan']),'Unexpected pagination'
            for page,plan in zip(list(doc)[1:],build['page_plan']):
                text=re.sub(r'\s+','',page.get_text())
                headings=re.findall(r'(?:例题|习题)(\d+\.\d+)',text)
                assert headings==plan['problems'],f'PDF question order differs: {headings}'
                assert len(headings)<=build['problems_per_page']
                assert '\ufffd' not in text,'Replacement character in PDF text'
            pdf_pages=len(doc)
        for p in problems:
            assert p['review_status']=='verified' and len(p['subquestions'])<=3
            assert p['source_sha256']==hashes[path/p['source_file']]
            assert 'original_number' not in p and 'original_problem_number' not in p
            assert any(row['project']==project and row['source_id']==p['source_id'] and row['page_number']==p['page_number'] for row in inventory)
        reports.append({'project':project,'source_units':build['source_unit_count'],'final_problems':len(problems),'pdf_pages':pdf_pages,'rewritten_problems':[p['id'] for p in problems if p.get('rewritten')],'editorially_corrected_problems':[p['id'] for p in problems if p.get('editorially_corrected')],'cross_page_problems':[p['id'] for p in problems if p.get('cross_page')],'necessary_figures':sum(len(p.get('figures',[])) for p in problems)})
    report={'status':'passed','checks':['source_sha256','final_number_uniqueness','subquestion_limit','first_source_page_in_sample','review_status','pdf_page_count','pdf_problem_order','latex_warnings'],'source_pdf_count':len(hashes),'sample_source_pages':len(inventory),'ocr_complete_pages':sum(p['complete'] for p in ocr_pages),'ocr_pages':ocr_pages,'projects':reports,'limits':['本样本未包含必须保留的题图，配图裁剪尚未做真实题目验收。','本样本包含例题和节末练习；章末习题的完整收录仍需后续整书核查。','verified 表示本轮逐题核对完成，不表示整书或独立复核完成。']}
    (ROOT/'qa').mkdir(exist_ok=True)
    (ROOT/'qa/sample-audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='ocr_pages'},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
