"""Publication must reject absent, pending and changed OCR review evidence."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from audit_ocr_evidence import validate_ocr_evidence


class OcrEvidence(unittest.TestCase):
    def setUp(self):
        self.temp_root = Path(__file__).resolve().parents[1] / '.cache/test-ocr-evidence'
        self.temp_root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=self.temp_root)
        self.addCleanup(self.cleanup)
        self.root = Path(self.temp.name)
        self.book = {'project': '数学分析讲义', 'source_file': 'input/book.pdf',
                     'source_id': 'abc', 'source_sha256': 'a' * 64, 'included_ranges': [[3, 4]],
                     'chapters': [{'chapter': 1, 'physical_start': 3, 'physical_end': 4}]}
        self.reviews = []
        self.report = {'status': 'verified', 'pages': []}
        for page in (3, 4):
            folder = self.folder(page)
            folder.mkdir(parents=True)
            completion = {k: self.book[k] for k in ('project', 'source_file', 'source_sha256')}
            completion['page_number'] = page
            self.write(folder / 'completed.json', completion)
            self.write(folder / 'result.json', {'raw': 'unreviewed'})
            (folder / 'result.md').write_text(f'page {page}', encoding='utf-8')
            digest = hashlib.sha256((folder / 'result.md').read_bytes()).hexdigest()
            self.report['pages'].append({'page_number': page, 'ocr_markdown_sha256': digest})
            self.reviews.append({**completion, 'status': 'reviewed', 'ocr_crosscheck_status': 'verified'})
        self.report_path = self.root / 'qa/ocr-crosscheck-chapter-01.json'
        self.report_path.parent.mkdir()
        self.write(self.report_path, self.report)

    def cleanup(self):
        if not Path(self.temp.name).resolve().is_relative_to(self.temp_root.resolve()):
            raise ValueError('Test cleanup target escaped the test workspace')
        self.temp.cleanup()

    def folder(self, page):
        return self.root / f'数学分析讲义/data/ocr_raw/vl1.6/abc/p{page:04d}'

    def write(self, path, data):
        path.write_text(json.dumps(data), encoding='utf-8')

    def validate(self):
        return validate_ocr_evidence(self.root, [self.book], self.reviews)

    def test_reviewed_evidence_passes_with_legacy_status(self):
        self.reviews[0].pop('ocr_crosscheck_status')
        self.reviews[0]['ocr_cross_check'] = 'complete'
        self.assertEqual(self.validate(), 2)

    def test_changed_ocr_cannot_reuse_review(self):
        (self.folder(3) / 'result.md').write_text('changed', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'changed after proofreading'):
            self.validate()

    def test_pending_page_or_chapter_cannot_pass(self):
        self.reviews[0]['ocr_crosscheck_status'] = 'pending'
        with self.assertRaisesRegex(ValueError, 'not complete'):
            self.validate()
        self.reviews[0]['ocr_crosscheck_status'] = 'verified'
        self.report['status'] = 'pending'
        self.write(self.report_path, self.report)
        with self.assertRaisesRegex(ValueError, 'not verified'):
            self.validate()

    def test_missing_and_duplicate_pages_are_rejected(self):
        for pages in [self.report['pages'][:1], self.report['pages'] + self.report['pages'][:1]]:
            with self.subTest(pages=len(pages)):
                self.write(self.report_path, {**self.report, 'pages': pages})
                with self.assertRaisesRegex(ValueError, 'incomplete or duplicate'):
                    self.validate()

    def test_wrong_source_page_is_rejected(self):
        path = self.folder(3) / 'completed.json'
        record = json.loads(path.read_text())
        record['page_number'] = 4
        self.write(path, record)
        with self.assertRaisesRegex(ValueError, 'different source page'):
            self.validate()

    def test_missing_ocr_artifact_is_rejected(self):
        (self.folder(3) / 'result.json').unlink()
        with self.assertRaisesRegex(ValueError, 'Missing structured'):
            self.validate()

    def test_included_appendix_requires_its_own_verified_report(self):
        self.book['chapters'][0]['physical_end'] = 3
        self.book['appendices'] = [{'chapter': 'A', 'physical_start': 4, 'physical_end': 4}]
        self.write(self.report_path, {**self.report, 'pages': self.report['pages'][:1]})
        appendix_path = self.report_path.with_name('ocr-crosscheck-chapter-A.json')
        appendix = {**self.report, 'pages': self.report['pages'][1:]}
        self.write(appendix_path, {**appendix, 'status': 'pending'})
        with self.assertRaisesRegex(ValueError, 'not verified.*chapter-A'):
            self.validate()
        self.write(appendix_path, appendix)
        self.assertEqual(self.validate(), 2)

    def test_archived_review_preserves_lost_cache_but_rejects_changed_inputs(self):
        source = self.root / self.book['project'] / self.book['source_file']
        source.parent.mkdir()
        source.write_bytes(b'unchanged source')
        source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
        self.book['source_sha256'] = source_hash
        for page in (3, 4):
            completion = self.folder(page) / 'completed.json'
            record = json.loads(completion.read_text())
            self.write(completion, {**record, 'source_sha256': source_hash})
        for name in ('completed.json', 'result.md', 'result.json'):
            (self.folder(4) / name).unlink()
        self.write(self.report_path.with_name('archived-ocr-reviews.json'), {
            'schema_version': 1,
            'chapters': [{
                'project': self.book['project'], 'source_file': self.book['source_file'],
                'source_sha256': source_hash, 'chapter': 1, 'page_count': 2,
                'report_sha256': hashlib.sha256(self.report_path.read_bytes()).hexdigest(),
            }],
        })
        self.assertEqual(self.validate(), 2)
        (self.folder(3) / 'result.md').write_text('changed live OCR', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'OCR evidence changed'):
            self.validate()
        source.write_bytes(b'wrong source')
        with self.assertRaisesRegex(ValueError, 'Archived OCR source changed'):
            self.validate()
        source.write_bytes(b'unchanged source')
        self.write(self.report_path, {**self.report, 'modified': True})
        with self.assertRaisesRegex(ValueError, 'Archived OCR review ledger changed'):
            self.validate()


if __name__ == '__main__':
    unittest.main()
