"""Progress refreshes must preserve valid releases and invalidate changed content."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import update_production_status as progress


class ProductionStatus(unittest.TestCase):
    def setUp(self):
        self.cache = Path(__file__).resolve().parents[1] / '.cache/test-production-status'
        self.cache.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=self.cache)
        self.addCleanup(self.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / '数学分析讲义'
        self.unit = {'chapter': 1, 'page_number': 1, 'review_status': 'verified', 'stem_latex': '题目'}
        self.chapter = self.project / 'data/chapters/chapter_01.reviewed.json'
        self.write(self.chapter, {'status': 'chapter_reviewed', 'chapter': 1,
                                 'ocr_crosscheck_status': 'verified', 'units': [self.unit]})
        self.write(self.project / 'data/curated.json', {'status': 'complete', 'units': [self.unit]})
        self.write(self.project / 'data/problems.json', {'status': 'complete', 'count': 1, 'problems': [self.unit]})
        (self.project / 'main.pdf').write_bytes(b'reviewed PDF fixture')
        self.previous = {'project': '数学分析讲义', 'status': 'complete', 'pdf_pages': 2,
                         'problem_count': 1, 'planned_source_pages': 1, 'review_complete_pages': 1,
                         'ocr_required_pages': 1, 'ocr_complete_pages': 1, 'source_units_reviewed': 1}
        for relative, field in [('main.pdf', 'pdf_sha256'), ('data/curated.json', 'curated_sha256'),
                                ('data/problems.json', 'problems_sha256')]:
            self.previous[field] = self.sha(self.project / relative)
        visual = {'status': 'passed', 'pdf_sha256': self.previous['pdf_sha256'],
                  'issues': [], 'reviewed_pdf_pages': [1, 2]}
        self.write(self.project / 'qa/visual-review.json', visual)
        self.acceptance = {'status': 'passed', 'full_book_all_pages_visual_review': 'passed',
                           'pdf_sha256': self.previous['pdf_sha256'], 'curated_sha256': self.previous['curated_sha256'],
                           'visual_report_sha256': self.sha(self.project / 'qa/visual-review.json'),
                           'final_problems': 1, 'chapter_snapshots': [
                               {'source_path': self.chapter.relative_to(self.root).as_posix(), 'sha256': self.sha(self.chapter)}]}
        self.write(self.project / 'qa/acceptance-report.json', self.acceptance)
        self.current = {**self.previous, 'status': 'in_progress',
                        'chapters_reviewed': [{'chapter': 1, 'ocr_crosscheck_status': 'verified'}]}

    def cleanup(self):
        if not Path(self.temp.name).resolve().is_relative_to(self.cache.resolve()):
            raise ValueError('Test cleanup escaped the workspace')
        self.temp.cleanup()

    @staticmethod
    def sha(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    @staticmethod
    def write(path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')

    def valid(self):
        return progress.can_preserve_completion(self.project, self.previous, self.current, [self.unit])

    def test_reviewed_release_is_preserved_during_other_project_progress(self):
        source = {'project': '数学分析讲义', 'source_file': 'input/book.pdf', 'source_id': 'lecture',
                  'source_sha256': 'a' * 64, 'page_number': 1}
        tutorial = {**source, 'project': '数学分析教程', 'source_id': 'tutorial'}
        self.write(self.root / 'config/production-pages.json', [source, tutorial])
        self.write(self.root / 'qa/production-page-reviews.json', [
            {**source, 'status': 'reviewed', 'units_count': 1},
            {**tutorial, 'status': 'reviewed', 'units_count': 0, 'reason': '理论页'}])
        self.write(self.root / 'qa/production-status.json', {'status': 'in_progress', 'projects': [self.previous]})
        folder = self.project / 'data/ocr_raw/vl1.6/lecture/p0001'
        self.write(folder / 'completed.json', source)
        self.write(folder / 'result.json', {})
        (self.root / '数学分析教程/data').mkdir(parents=True)
        with patch.object(progress, 'ROOT', self.root), contextlib.redirect_stdout(io.StringIO()):
            progress.main()
        result = progress.read(self.root / 'qa/production-status.json')
        self.assertEqual(result['status'], 'in_progress')
        self.assertEqual([r['status'] for r in result['projects']], ['complete', 'in_progress'])
        self.assertEqual(result['projects'][0]['pdf_sha256'], self.previous['pdf_sha256'])
        self.assertEqual(progress.read(self.project / 'data/production-curated.json')['status'], 'complete')

    def test_changed_formal_artifact_or_chapter_invalidates_release(self):
        self.assertTrue(self.valid())
        for relative in ['main.pdf', 'data/curated.json', 'data/problems.json', 'data/chapters/chapter_01.reviewed.json']:
            with self.subTest(relative=relative):
                path = self.project / relative
                original = path.read_bytes()
                path.write_bytes(original + b' ')
                self.assertFalse(self.valid())
                path.write_bytes(original)
        self.assertTrue(self.valid())

    def test_missing_or_new_chapter_invalidates_release(self):
        original = self.chapter.read_bytes()
        self.chapter.unlink()
        self.assertFalse(self.valid())
        self.chapter.write_bytes(original)
        self.write(self.chapter.with_name('chapter_02.reviewed.json'), {})
        self.assertFalse(self.valid())

    def test_failed_acceptance_or_changed_visual_evidence_invalidates_release(self):
        failed = {**self.acceptance, 'status': 'pending'}
        self.write(self.project / 'qa/acceptance-report.json', failed)
        self.assertFalse(self.valid())
        self.write(self.project / 'qa/acceptance-report.json', self.acceptance)
        self.write(self.project / 'qa/visual-review.json', {'status': 'passed', 'reviewed_pdf_pages': [1]})
        self.assertFalse(self.valid())

    def test_incomplete_ocr_or_content_progress_invalidates_release(self):
        for field in ['ocr_complete_pages', 'review_complete_pages', 'source_units_reviewed']:
            with self.subTest(field=field):
                old = self.current[field]
                self.current[field] = 0
                self.assertFalse(self.valid())
                self.current[field] = old
        self.current['chapters_reviewed'][0]['ocr_crosscheck_status'] = 'pending'
        self.assertFalse(self.valid())


if __name__ == '__main__':
    unittest.main()
