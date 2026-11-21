"""Verify that every included page has the exact OCR evidence a reviewer checked.

This does not perform proofreading or change a review status. It rejects missing,
pending or stale evidence before a whole-book publication package can be prepared.
An archive can preserve completed verification when the raw cache is lost.
"""
from pathlib import Path
import hashlib
import json
import re


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def report_name(project, number):
    label = f'{number:02d}' if isinstance(number, int) else str(number)
    prefix = 'tutorial-' if project == '数学分析教程' else ''
    return f'ocr-crosscheck-{prefix}chapter-{label}.json'


def archived_ocr_pages(root, books=None):
    """Validate surviving review ledgers against a recorded pre-loss audit."""
    root = Path(root)
    archive_path = root / 'qa/archived-ocr-reviews.json'
    if not archive_path.is_file():
        return set()
    if books is None:
        books = read_json(root / 'config/production-books.json')['books']
    archive = read_json(archive_path)
    if archive['schema_version'] != 1:
        raise ValueError('Unsupported OCR review archive version')
    by_source = {(b['project'], b['source_file']): b for b in books}
    checked_sources = set()
    archived = set()
    for entry in archive['chapters']:
        project, source = entry['project'], entry['source_file']
        book = by_source.get((project, source))
        if book is None:
            continue
        number = entry['chapter']
        chapter = next((chapter for chapter in [*book['chapters'], *book.get('appendices', [])]
                        if chapter['chapter'] == number), None)
        if chapter is None:
            continue
        if book['source_sha256'] != entry['source_sha256']:
            raise ValueError(f'Archived OCR source does not match inventory: {source}')
        if (project, source) not in checked_sources:
            source_path = root / project / source
            with source_path.open('rb') as handle:
                actual = hashlib.file_digest(handle, 'sha256').hexdigest()
            if actual != book['source_sha256']:
                raise ValueError(f'Archived OCR source changed: {source}')
            checked_sources.add((project, source))
        path = root / 'qa' / report_name(project, number)
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != entry['report_sha256']:
            raise ValueError(f'Archived OCR review ledger changed: {path.name}')
        report = json.loads(raw.decode('utf-8-sig'))
        rows = report.get('pages', report.get('page_results', []))
        pages = set(range(chapter['physical_start'], chapter['physical_end'] + 1))
        if (entry['page_count'] != len(pages) or report.get('status') != 'verified'
                or len(rows) != len(pages) or {row['page_number'] for row in rows} != pages
                or not all(re.fullmatch(r'[0-9a-f]{64}', markdown_hash(row) or '') for row in rows)):
            raise ValueError(f'Archived OCR review does not cover the full chapter: {path.name}')
        keys = {(project, source, number) for number in pages}
        if archived & keys:
            raise ValueError(f'Duplicate archived OCR coverage: {path.name}')
        archived.update(keys)
    return archived


def markdown_hash(evidence):
    return evidence.get('ocr_markdown_sha256', evidence.get('result_sha256', evidence.get('sha256')))


def validate_ocr_evidence(root, books, page_reviews):
    root = Path(root)
    archived = archived_ocr_pages(root, books)
    reviewed = {(r['project'], r['source_file'], r['page_number']): r for r in page_reviews}
    checked = set()
    for book in books:
        expected = {p for first, last in book['included_ranges'] for p in range(first, last + 1)}
        covered = set()
        for chapter in [*book['chapters'], *book.get('appendices', [])]:
            number = chapter['chapter']
            report_path = root / 'qa' / report_name(book['project'], number)
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
                if key in archived and not any((folder / name).exists() for name in (
                        'completed.json', 'result.json', 'result.md')):
                    checked.add(key)
                    continue
                completion = read_json(folder / 'completed.json')
                if any(completion.get(k) != v for k, v in (
                    ('source_sha256', book['source_sha256']), ('page_number', page),
                    ('source_file', book['source_file']), ('project', book['project']))):
                    raise ValueError(f'OCR evidence belongs to a different source page: {key}')
                if not (folder / 'result.json').is_file():
                    raise ValueError(f'Missing structured OCR result: {key}')
                evidence = by_page[page]
                digest = markdown_hash(evidence)
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
