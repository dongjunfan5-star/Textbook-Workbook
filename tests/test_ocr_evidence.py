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


if __name__ == '__main__':
    unittest.main()
