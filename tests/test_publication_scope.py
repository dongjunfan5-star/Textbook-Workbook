"""Single-book publication retains every acceptance gate and remote safety check."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import fitz

WORKSPACE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKSPACE / 'scripts'))
import prepare_publication as publication
from build_workbook import split_units

LECTURE = '数学分析讲义'
TUTORIAL = '数学分析教程'


class PublicationScope(unittest.TestCase):
    def setUp(self):
        self.temp_root = WORKSPACE / '.cache/test-publication-scope'
        self.temp_root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=self.temp_root)
        self.root = Path(self.temp.name)
        self.addCleanup(self.cleanup)
        root_patch = patch.object(publication, 'ROOT', self.root)
        root_patch.start()
        self.addCleanup(root_patch.stop)
        for name in publication.ROOT_FILES:
            self.write_text(name, 'fixture\n')
        self.write_text('.gitignore', (WORKSPACE / '.gitignore').read_text(encoding='utf-8'))
        self.books, self.accepted, self.reviews, self.visual = [], [], [], []
        for project in (LECTURE, TUTORIAL):
            self.make_project(project)
        self.accepted[1]['status'] = 'in_progress'
        self.status = {'status': 'in_progress', 'projects': self.accepted,
                       'page_reviews_file': 'qa/production-page-reviews.json',
                       'planned_source_pages': 2, 'review_complete_pages': 2,
                       'ocr_required_pages': 2, 'ocr_complete_pages': 2}
        self.write('qa/production-status.json', self.status)
        self.write('qa/production-page-reviews.json', self.reviews)
        self.write('qa/visual-review.json', {'status': 'pending', 'projects': self.visual})
        self.write('qa/mixed.json', {'changes': [{'project': LECTURE}, {'project': TUTORIAL}]})
        self.write('qa/unowned.json', {'status': 'pending'})
        self.write('config/projects.json', {'projects': [
            {'name': p, 'sources': ['input/book.pdf']} for p in (LECTURE, TUTORIAL)]})
        self.write('config/production-books.json', {'books': self.books})
        self.write('config/production-pages.json', self.reviews)
        self.write('config/sample-pages.json', {'items': [
            {'project': LECTURE, 'page': 1}, {'project': TUTORIAL, 'page': 1}]})
        self.remote = {'repository': 'owner/repo', 'remote_head_sha': 'a' * 40,
                       'remote_tree_sha': 'b' * 40,
                       'reconciliation': {'remote_tutorial_path': publication.OLD_TUTORIAL,
                                          'local_tutorial_path': TUTORIAL},
                       'remote_files': [{'path': path, 'sha': sha, 'mode': '100644'}
                                        for path, sha in publication.OBSOLETE_PLACEHOLDERS.items()]}
        self.write('qa/remote-reconciliation.json', self.remote)

    def cleanup(self):
        if not self.root.resolve().is_relative_to(self.temp_root.resolve()):
            raise ValueError('Test cleanup target escaped the test workspace')
        self.temp.cleanup()

    def write_text(self, relative, value):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding='utf-8')

    def write(self, relative, value):
        self.write_text(relative, json.dumps(value, ensure_ascii=False))

    def pdf(self, relative, text):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        with fitz.open() as document:
            page = document.new_page()
            page.insert_text((40, 40), text, fontname='china-s')
            document.save(path)
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def make_project(self, project):
        source_hash = self.pdf(f'{project}/input/book.pdf', '教材正文')
        pdf_hash = self.pdf(f'{project}/main.pdf', '习题1.1')
        self.write_text(f'{project}/main.tex', 'fixture LaTeX')
        self.write_text(f'{project}/README.md', 'fixture project README')
        unit = {'chapter': 1, 'kind': 'exercise', 'stem_latex': '求证', 'subquestions': [],
                'source_file': 'input/book.pdf', 'source_sha256': source_hash,
                'page_number': 1, 'review_status': 'verified'}
        self.write(f'{project}/data/curated.json', {'status': 'complete', 'units': [unit]})
        self.write(f'{project}/data/problems.json', {'status': 'complete', 'count': 1,
                                                   'problems': split_units([unit])})
        self.write(f'{project}/qa/build-report.json', {'problem_count': 1, 'latex_issues': []})
        book = {'project': project, 'source_file': 'input/book.pdf', 'source_sha256': source_hash,
                'source_id': 'abc', 'pdf_pages': 1, 'included_ranges': [[1, 1]],
                'chapters': [{'chapter': 1, 'physical_start': 1, 'physical_end': 1}]}
        self.books.append(book)
        self.accepted.append({'project': project, 'status': 'complete', 'planned_source_pages': 1,
                              'review_complete_pages': 1, 'ocr_required_pages': 1, 'ocr_complete_pages': 1,
                              'problem_count': 1, 'pdf_sha256': pdf_hash})
        self.visual.append({'project': project, 'status': 'passed', 'pdf_sha256': pdf_hash,
                            'reviewed_pdf_pages': [1], 'issues': []})
        self.reviews.append({'project': project, 'source_file': 'input/book.pdf', 'page_number': 1,
                             'status': 'reviewed', 'units_count': 1, 'ocr_crosscheck_status': 'verified'})
        folder = f'{project}/data/ocr_raw/vl1.6/abc/p0001'
        self.write(f'{folder}/completed.json', {**book, 'page_number': 1})
        self.write(f'{folder}/result.json', {'raw': 'unreviewed'})
        self.write_text(f'{folder}/result.md', 'OCR evidence')
        prefix = 'tutorial-' if project == TUTORIAL else ''
        self.write(f'qa/ocr-crosscheck-{prefix}chapter-01.json', {
            'project': project, 'status': 'verified', 'pages': [
                {'page_number': 1, 'ocr_markdown_sha256': hashlib.sha256(b'OCR evidence').hexdigest()}]})

    def prepare(self, **kwargs):
        return publication.prepare(project=LECTURE, **kwargs)

    def payload(self, manifest, path):
        entry = next(f for f in manifest['files'] if f['path'] == path)
        envelope = publication.read_json(self.root / manifest['package_directory'] / entry['payload'])
        return json.loads(envelope['content'])

    def test_single_project_packaging_is_independent_and_scoped(self):
        original_status = (self.root / 'qa/production-status.json').read_bytes()
        original_config = (self.root / 'config/projects.json').read_bytes()
        # An unfinished other project may even lack a usable local source PDF.
        (self.root / TUTORIAL / 'input/book.pdf').unlink()
        manifest = self.prepare()
        paths = {f['path'] for f in manifest['files']}
        self.assertTrue(manifest['ready_for_full_publication'])
        self.assertEqual(manifest['scope'], 'selected_project')
        self.assertEqual(manifest['proposed_obsolete_placeholder_deletions'], [])
        self.assertIn(f'{LECTURE}/README.md', paths)
        self.assertIn('qa/ocr-crosscheck-chapter-01.json', paths)
        self.assertFalse(any(p.startswith(TUTORIAL + '/') or 'tutorial-' in p for p in paths))
        self.assertTrue({'qa/mixed.json', 'qa/unowned.json'}.isdisjoint(paths))
        self.assertIn('qa/remote-reconciliation.json', paths)
        for entry in manifest['files']:
            if entry['path'].startswith('qa/'):
                self.assertNotIn(TUTORIAL, publication.project_references(self.payload(manifest, entry['path'])))
        accepted = self.payload(manifest, 'qa/production-status.json')
        self.assertEqual(accepted['status'], 'complete')
        self.assertEqual(accepted['planned_source_pages'], 1)
        self.assertEqual([p['project'] for p in accepted['projects']], [LECTURE])
        self.assertEqual(len(self.payload(manifest, 'qa/production-page-reviews.json')), 1)
        self.assertEqual(len(self.payload(manifest, 'config/projects.json')['projects']), 1)
        self.assertEqual(len(self.payload(manifest, 'config/production-books.json')['books']), 1)
        self.assertEqual([r['project'] for r in self.payload(manifest, 'config/production-pages.json')], [LECTURE])
        self.assertEqual([r['project'] for r in self.payload(manifest, 'config/sample-pages.json')['items']], [LECTURE])
        self.assertEqual((self.root / 'qa/production-status.json').read_bytes(), original_status)
        self.assertEqual((self.root / 'config/projects.json').read_bytes(), original_config)

    def test_default_requires_all_projects_and_totals(self):
        with self.assertRaisesRegex(ValueError, 'status is not complete'):
            publication.prepare()
        self.status['status'] = 'complete'
        self.write('qa/production-status.json', self.status)
        with self.assertRaisesRegex(ValueError, 'Project is not complete'):
            publication.prepare()
        self.accepted[1]['status'] = 'complete'
        self.status['ocr_complete_pages'] = 1
        self.write('qa/production-status.json', self.status)
        with self.assertRaisesRegex(ValueError, 'Incorrect total OCR'):
            publication.prepare()
        self.status['ocr_complete_pages'] = 2
        self.write('qa/production-status.json', self.status)
        self.write('qa/visual-review.json', {'status': 'passed', 'projects': self.visual})
        manifest = publication.prepare()
        self.assertEqual(manifest['scope'], 'all_projects')
        self.assertEqual(len(manifest['projects']), 2)
        self.assertEqual(len(manifest['proposed_obsolete_placeholder_deletions']), 4)

    def test_missing_duplicate_or_incomplete_acceptance_is_refused(self):
        for entries in [self.accepted[1:], self.accepted + self.accepted[:1],
                        [{**self.accepted[0], 'status': 'in_progress'}, self.accepted[1]]]:
            with self.subTest(entries=entries):
                self.write('qa/production-status.json', {**self.status, 'projects': entries})
                with self.assertRaises(ValueError):
                    self.prepare()

    def test_missing_page_pending_ocr_and_changed_evidence_are_refused(self):
        for records in [self.reviews[1:],
                        [{**self.reviews[0], 'ocr_crosscheck_status': 'pending'}, self.reviews[1]]]:
            with self.subTest(records=records):
                self.write('qa/production-page-reviews.json', records)
                with self.assertRaises(ValueError):
                    self.prepare()
        self.write('qa/production-page-reviews.json', self.reviews)
        self.write_text(f'{LECTURE}/data/ocr_raw/vl1.6/abc/p0001/result.md', 'changed')
        with self.assertRaisesRegex(ValueError, 'changed after proofreading'):
            self.prepare()

    def test_incomplete_visual_review_and_stale_pdf_are_refused(self):
        for changes in [{'reviewed_pdf_pages': []}, {'pdf_sha256': '0' * 64}, {'status': 'pending'}]:
            with self.subTest(changes=changes):
                self.write('qa/visual-review.json', {'status': 'passed', 'projects': [
                    {**self.visual[0], **changes}, self.visual[1]]})
                with self.assertRaises(ValueError):
                    self.prepare()

    def test_preview_is_not_publishable_and_unknown_project_is_rejected(self):
        self.assertFalse(self.prepare(preview=True)['ready_for_full_publication'])
        with self.assertRaisesRegex(ValueError, 'Unknown publication project'):
            publication.prepare(project='../other')

    def test_remote_deletion_is_fixed_to_known_unchanged_tutorial_placeholders(self):
        remote = copy.deepcopy(self.remote)
        remote['remote_files'].append({'path': publication.OLD_TUTORIAL + '/new-work.tex',
                                       'mode': '100644', 'sha': 'c' * 40})
        planned = publication.obsolete_placeholder_deletions(remote, [TUTORIAL])
        self.assertEqual({d['path'] for d in planned}, set(publication.OBSOLETE_PLACEHOLDERS))
        remote['remote_files'][0]['sha'] = 'd' * 40
        self.assertEqual(publication.obsolete_placeholder_deletions(remote, [LECTURE]), [])
        with self.assertRaisesRegex(ValueError, 'Remote placeholder changed'):
            publication.obsolete_placeholder_deletions(remote, [TUTORIAL])
        remote = copy.deepcopy(self.remote)
        remote['reconciliation']['remote_tutorial_path'] = 'unrelated-directory'
        with self.assertRaisesRegex(ValueError, 'Unexpected tutorial migration'):
            publication.obsolete_placeholder_deletions(remote, [TUTORIAL])

    def test_gitignore_credentials_and_readme_allowlist(self):
        paths = ['credentials/auth.json', f'{LECTURE}/credentials/auth.json', f'{LECTURE}/README.md']
        for path in paths:
            self.write_text(path, 'fixture')
        output = self.root / '.cache/ignore-test'
        output.mkdir(parents=True)
        self.assertEqual(publication.git_ignored(paths, output), set(paths[:2]))
        self.assertFalse(publication.allowed(paths[0], [LECTURE], set()))
        self.assertTrue(publication.allowed(paths[-1], [LECTURE], set()))


if __name__ == '__main__':
    unittest.main()
