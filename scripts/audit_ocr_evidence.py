"""Verify that every included page has the exact OCR evidence a reviewer checked.

This does not perform proofreading or change a review status. It rejects missing,
pending or stale evidence before a whole-book publication package can be prepared.
"""
from pathlib import Path
import hashlib
import json


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def validate_ocr_evidence(root, books, page_reviews):
    root = Path(root)
    reviewed = {(r['project'], r['source_file'], r['page_number']): r for r in page_reviews}
    checked = set()
    for book in books:
        expected = {p for first, last in book['included_ranges'] for p in range(first, last + 1)}
        covered = set()
        for chapter in book['chapters']:
            number = chapter['chapter']
            label = f'{number:02d}' if isinstance(number, int) else str(number)
            prefix = 'tutorial-' if book['project'] == '数学分析教程' else ''
            report_path = root / 'qa' / f'ocr-crosscheck-{prefix}chapter-{label}.json'
            report = read_json(report_path)
            if report.get('status') != 'verified':
                raise ValueError(f'OCR crosscheck is not verified: {report_path.name}')
            rows = report.get('pages', report.get('page_results', []))
            by_page = {row['page_number']: row for row in rows}
            chapter_pages = set(range(chapter['physical_start'], chapter['physical_end'] + 1))
            if len(by_page) != len(rows) or set(by_page) != chapter_pages or covered & chapter_pages:
                raise ValueError(f'OCR crosscheck has incomplete or duplicate pages: {report_path.name}')
            covered.update(chapter_pages)
            for page in sorted(chapter_pages):
                key = (book['project'], book['source_file'], page)
                review = reviewed.get(key, {})
                state = review.get('ocr_crosscheck_status', review.get('ocr_cross_check'))
                if review.get('status') != 'reviewed' or state not in {'verified', 'complete'}:
                    raise ValueError(f'Page OCR review is not complete: {key}')
                folder = root / book['project'] / 'data/ocr_raw/vl1.6' / book['source_id'] / f'p{page:04d}'
                completion = read_json(folder / 'completed.json')
                if any(completion.get(k) != v for k, v in (
                    ('source_sha256', book['source_sha256']), ('page_number', page),
                    ('source_file', book['source_file']), ('project', book['project']))):
                    raise ValueError(f'OCR evidence belongs to a different source page: {key}')
                if not (folder / 'result.json').is_file():
                    raise ValueError(f'Missing structured OCR result: {key}')
                evidence = by_page[page]
                digest = evidence.get('ocr_markdown_sha256', evidence.get('result_sha256', evidence.get('sha256')))
                current = hashlib.sha256((folder / 'result.md').read_bytes()).hexdigest()
                if digest != current:
                    raise ValueError(f'OCR evidence changed after proofreading: {key}')
                structured = evidence.get('structured_result_sha256')
                if structured and structured != hashlib.sha256((folder / 'result.json').read_bytes()).hexdigest():
                    raise ValueError(f'Structured OCR evidence changed after proofreading: {key}')
                checked.add(key)
        if covered != expected:
            raise ValueError(f'Chapter OCR coverage differs from source inventory: {book["source_file"]}')
    return len(checked)
