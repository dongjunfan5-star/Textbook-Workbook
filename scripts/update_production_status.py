"""Report actual OCR and editorial progress without declaring publication complete."""
import hashlib
import json
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
from audit_ocr_evidence import archived_ocr_pages

ROOT=Path(__file__).resolve().parents[1]
def read(path):return json.loads(path.read_text(encoding='utf-8-sig'))
def write(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

def can_preserve_completion(project, previous, progress, units):
    """Keep an existing acceptance only while its exact reviewed artifacts remain valid."""
    if previous.get('status') != 'complete':
        return False
    try:
        acceptance = read(project/'qa/acceptance-report.json')
        visual_path = project/'qa/visual-review.json'
        visual = read(visual_path)
        curated = read(project/'data/curated.json')
        problems = read(project/'data/problems.json')
        if (acceptance.get('status') != 'passed'
                or acceptance.get('full_book_all_pages_visual_review') != 'passed'
                or visual.get('status') != 'passed' or visual.get('issues')
                or curated.get('status') != 'complete' or problems.get('status') != 'complete'
                or curated.get('units') != units):
            return False
        hashes = {}
        for relative, field in [('main.pdf', 'pdf_sha256'), ('data/curated.json', 'curated_sha256'),
                                ('data/problems.json', 'problems_sha256')]:
            with (project/relative).open('rb') as stream:
                hashes[field] = hashlib.file_digest(stream, 'sha256').hexdigest()
            if hashes[field] != previous.get(field):
                return False
        if (acceptance.get('pdf_sha256') != hashes['pdf_sha256']
                or acceptance.get('curated_sha256') != hashes['curated_sha256']
                or visual.get('pdf_sha256') != hashes['pdf_sha256']
                or acceptance.get('visual_report_sha256') != hashlib.sha256(visual_path.read_bytes()).hexdigest()
                or visual.get('reviewed_pdf_pages') != list(range(1, previous['pdf_pages']+1))
                or problems.get('count') != previous['problem_count']
                or len(problems['problems']) != previous['problem_count']
                or acceptance.get('final_problems') != previous['problem_count']):
            return False
        snapshots = acceptance['chapter_snapshots']
        expected = {row['source_path']: row['sha256'] for row in snapshots}
        actual_files = list((project/'data/chapters').glob('*.reviewed.json'))
        if len(expected) != len(snapshots) or set(expected) != {p.relative_to(project.parent).as_posix() for p in actual_files}:
            return False
        for path in actual_files:
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected[path.relative_to(project.parent).as_posix()]:
                return False
        if any(chapter['ocr_crosscheck_status'] != 'verified' for chapter in progress['chapters_reviewed']):
            return False
        for field in ('planned_source_pages', 'review_complete_pages', 'ocr_required_pages',
                      'ocr_complete_pages', 'source_units_reviewed'):
            if progress[field] != previous.get(field):
                return False
        return True
    except (OSError, ValueError, KeyError, TypeError):
        return False

def main():
    status_path=ROOT/'qa/production-status.json'
    prior=read(status_path) if status_path.is_file() else {}
    previous={p['project']:p for p in prior.get('projects',[])}
    pages=read(ROOT/'config/production-pages.json')
    reviews=read(ROOT/'qa/production-page-reviews.json')
    by_key={(r['project'],r['source_file'],r['page_number']):r for r in reviews}
    for file in sorted((ROOT/'qa').glob('review-*chapter-*.json')):
        for row in read(file):
            key=(row['project'],row['source_file'],row['page_number'])
            if key not in by_key or by_key[key]['status']=='excluded':
                raise ValueError(f'Review outside content inventory: {key}')
            if row['status']!='reviewed' or 'units_count' not in row:
                raise ValueError(f'Unfinished chapter page review: {key}')
            by_key[key]={**by_key[key],**row}
    reviews=list(by_key.values())
    write(ROOT/'qa/production-page-reviews.json',reviews)
    archived=archived_ocr_pages(ROOT)
    completed=[]
    for row in pages:
        folder=ROOT/row['project']/'data/ocr_raw/vl1.6'/row['source_id']/f"p{row['page_number']:04d}"
        done=folder/'completed.json'
        key=(row['project'],row['source_file'],row['page_number'])
        if key in archived:
            completed.append(row)
        elif done.is_file() and (folder/'result.json').is_file():
            if read(done).get('source_sha256')==row['source_sha256']:completed.append(row)
    projects=[]
    for name in dict.fromkeys(r['project'] for r in reviews):
        project=ROOT/name
        chapters=[]
        units=[]
        for file in sorted((project/'data/chapters').glob('*.reviewed.json')):
            data=read(file)
            if data.get('status')!='chapter_reviewed':continue
            if any(u.get('review_status')!='verified' for u in data['units']):
                raise ValueError(f'Unreviewed unit in {file}')
            units.extend(data['units'])
            chapters.append({'chapter':data['chapter'],'units_count':len(data['units']),'file':file.relative_to(ROOT).as_posix(),'ocr_crosscheck_status':data.get('ocr_crosscheck_status','pending')})
        # A chapter file is a whole chapter, so sorting cannot interleave two sources.
        units.sort(key=lambda u:(str(u['chapter']).isalpha(),int(u['chapter']) if str(u['chapter']).isdigit() else str(u['chapter']),u['page_number']))
        own=[r for r in reviews if r['project']==name]
        progress={'project':name,'status':'in_progress','planned_source_pages':len(own),'ocr_required_pages':sum(r['project']==name for r in pages),'ocr_complete_pages':sum(r['project']==name for r in completed),'review_complete_pages':sum(r['status'] in ('reviewed','excluded') for r in own),'content_reviewed_pages':sum(r['status']=='reviewed' for r in own),'source_units_reviewed':len(units),'chapters_reviewed':chapters}
        old=previous.get(name,{})
        if can_preserve_completion(project,old,progress,units):
            progress={**old,**progress,'status':'complete'}
            production_curated=read(project/'data/curated.json')
        else:
            production_curated={'status':'in_progress','chapters':chapters,'units':units}
            if old.get('status')=='complete':
                progress['notice']='已验收的文件、章节、OCR覆盖或验收记录发生变化，须重新验收后才能恢复complete。'
        write(project/'data/production-curated.json',production_curated)
        projects.append(progress)
    overall='complete' if projects and all(p['status']=='complete' for p in projects) else 'in_progress'
    status={'status':overall,'updated_at':datetime.now(timezone.utc).isoformat(),'page_reviews_file':'qa/production-page-reviews.json','planned_source_pages':len(reviews),'ocr_required_pages':len(pages),'ocr_complete_pages':len(completed),'review_complete_pages':sum(p['review_complete_pages'] for p in projects),'projects':projects,'notice':'OCR完成不等于校对完成。各项目独立验收；已完成项目仅在正式PDF、题库、章节快照和验收记录仍匹配时保留complete。整书核验通过前不发布。'}
    write(ROOT/'qa/production-status.json',status)
    print(json.dumps({'ocr':len(completed),'ocr_required':len(pages),'reviewed_content_pages':sum(p['content_reviewed_pages'] for p in projects),'units':sum(p['source_units_reviewed'] for p in projects)},ensure_ascii=False))

if __name__=='__main__':main()
