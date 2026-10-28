"""Prepare an explicit publication package without writing to GitHub or root .git.

Publication requires completed curated data and a completed production audit.
--project limits both acceptance and publication to one configured project.
--sample-preview generates a clearly labelled local preview only.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = {'.gitignore', 'README.md', 'LICENSE.md', '制作要求.txt',
              'requirements.txt', 'requirements-lock.txt', 'requirements-gpu-lock.txt',
              'requirements-vl.txt'}
SOURCE_DIRS = {'config': {'.json'}, 'scripts': {'.py','.ps1'}, 'templates': {'.tex'},
               'tests': {'.py'}, 'qa': {'.json', '.md'}}
FORBIDDEN_PARTS = {'.git', '.cache', '.tools', '.ssh', 'secrets', 'credentials',
                   'venv', 'env', 'models', 'model_cache', 'official_models',
                   '.paddlex', '.paddle', '.paddleocr', '.huggingface', '.modelscope',
                   'ocr_raw', 'page_images', 'rendered', 'rendered_pages',
                   'build', '__pycache__', '.pytest_cache', 'tmp', 'temp'}
FORBIDDEN_SUFFIXES = {'.pem', '.key', '.pfx', '.p12', '.pdparams', '.pdmodel',
                      '.pdiparams', '.safetensors', '.onnx', '.pt', '.pth', '.ckpt', '.gguf'}
BINARY_SUFFIXES = {'.pdf', '.png', '.jpg', '.jpeg'}
SECRET_PATTERNS = [
    re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    re.compile(r'\bgh[pousr]_[A-Za-z0-9]{30,}\b'),
    re.compile(r'\bgithub_pat_[A-Za-z0-9_]{30,}\b'),
    re.compile(r'\bAKIA[0-9A-Z]{16}\b'),
]
TUTORIAL_PROJECT = '数学分析教程'
OLD_TUTORIAL = '数学分析教程（史济怀著）'
OBSOLETE_PLACEHOLDERS = {
    f'{OLD_TUTORIAL}/chapters/.gitkeep': 'e69de29bb2d1d6434b8b29ae775ad8c2e48c5391',
    f'{OLD_TUTORIAL}/figures/.gitkeep': 'e69de29bb2d1d6434b8b29ae775ad8c2e48c5391',
    f'{OLD_TUTORIAL}/input/.gitkeep': 'e69de29bb2d1d6434b8b29ae775ad8c2e48c5391',
    f'{OLD_TUTORIAL}/main.tex': 'cfb783cf3ddcc52720ab3d5fe84c7fb07f468e4b',
}


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def safe_path(relative):
    """Reject traversal, symlinks, Windows junctions and paths outside ROOT."""
    rel = PurePosixPath(relative)
    if rel.is_absolute() or not rel.parts or any(p in {'', '.', '..'} or ':' in p or '\\' in p for p in rel.parts):
        raise ValueError(f'Unsafe publication path: {relative}')
    path = ROOT.joinpath(*rel.parts)
    for parent in (path, *path.parents):
        if parent == ROOT:
            break
        if parent.is_symlink() or getattr(parent, 'is_junction', lambda: False)():
            raise ValueError(f'Linked paths cannot be published: {relative}')
    if not path.resolve().is_relative_to(ROOT):
        raise ValueError(f'Path escapes workspace: {relative}')
    return path


def forbidden(relative):
    path = PurePosixPath(relative)
    parts = [part.lower() for part in path.parts]
    name = path.name.lower()
    if any(p in FORBIDDEN_PARTS or p.startswith('.venv') for p in parts):
        return True
    if name.startswith(('.env', 'id_rsa', 'id_ed25519')) or name == 'config.local.json':
        return name != '.env.example'
    if any(word in name for word in ('credential', 'secret', 'token-cache')):
        return True
    if path.suffix.lower() in FORBIDDEN_SUFFIXES:
        return True
    return 'input' in parts and name != '.gitkeep'


def allowed(relative, projects, figure_paths):
    if forbidden(relative):
        return False
    path = PurePosixPath(relative)
    parts = path.parts
    if relative in ROOT_FILES:
        return True
    if len(parts) == 2 and parts[0] in SOURCE_DIRS:
        return path.suffix.lower() in SOURCE_DIRS[parts[0]]
    if parts[0] not in projects:
        return False
    tail = '/'.join(parts[1:])
    if tail in {'README.md', 'main.tex', 'main.pdf', 'data/curated.json', 'data/problems.json',
                'chapters/.gitkeep', 'figures/.gitkeep', 'input/.gitkeep'}:
        return True
    if len(parts) == 3 and parts[1] == 'chapters' and path.suffix == '.tex':
        return True
    if len(parts) == 3 and parts[1] == 'qa' and path.suffix in {'.json', '.md'}:
        return True
    return relative in figure_paths and bool(re.fullmatch(r'fig_(?:\d+|[A-Z])_\d+(?:_\d+)?\.(?:png|jpe?g|pdf|svg)', path.name))


def candidates(projects):
    """Walk only allowed source folders, never recursively traverse environments."""
    found = set(ROOT_FILES)
    for folder in SOURCE_DIRS:
        found.update(p.relative_to(ROOT).as_posix() for p in (ROOT / folder).glob('*') if p.is_file())
    for project in projects:
        folder = ROOT / project
        for name in ('README.md', 'main.tex', 'main.pdf', 'data/curated.json', 'data/problems.json', 'input/.gitkeep'):
            found.add(f'{project}/{name}')
        for name in ('chapters', 'figures', 'qa'):
            found.update(p.relative_to(ROOT).as_posix() for p in (folder / name).glob('*') if p.is_file())
    return sorted(p for p in found if safe_path(p).is_file())


def git_ignored(paths, output):
    """Use the repository .gitignore with an isolated local index, never root .git."""
    git = shutil.which('git')
    if not git:
        raise RuntimeError('Git is required to validate .gitignore before packaging.')
    git_dir = output / 'ignore-check.git'
    if not git_dir.resolve().is_relative_to(ROOT / '.cache'):
        raise ValueError('Ignore-check repository must remain under .cache.')
    env = os.environ.copy()
    for key in list(env):
        if key.startswith('GIT_'):
            env.pop(key)
    env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT='0')
    if not git_dir.exists():
        subprocess.run([git, 'init', '--bare', str(git_dir)], check=True, capture_output=True, env=env)
    cmd = [git, '--git-dir=' + str(git_dir), '--work-tree=' + str(ROOT),
           '-c', 'core.excludesFile=' + os.devnull, 'check-ignore', '--no-index', '-z', '--stdin']
    result = subprocess.run(cmd, input=('\0'.join(paths) + '\0').encode('utf-8'),
                            capture_output=True, cwd=ROOT, env=env)
    if result.returncode not in (0, 1):
        raise RuntimeError(result.stderr.decode('utf-8', errors='replace'))
    return set(result.stdout.decode('utf-8').rstrip('\0').split('\0')) - {''}


def validate_projects(projects, preview, all_projects=True):
    import fitz
    from build_workbook import split_units

    production = ROOT / 'qa/production-status.json'
    status = read_json(production) if production.exists() else {}
    if not preview:
        validate_production_coverage(status, projects, all_projects=all_projects)
    visual = read_json(ROOT / 'qa/visual-review.json')
    if all_projects and visual.get('status') != 'passed':
        raise ValueError('Visual review is not passed.')
    summaries, figures = [], set()
    for project in projects:
        curated_bytes = (ROOT / project / 'data/curated.json').read_bytes()
        problem_bytes = (ROOT / project / 'data/problems.json').read_bytes()
        curated = json.loads(curated_bytes)
        data = json.loads(problem_bytes)
        build = read_json(ROOT / project / 'qa/build-report.json')
        if not preview and (curated.get('status') != 'complete' or data.get('status') != 'complete'):
            raise ValueError(f'Full publication refused: {project} data status is not complete.')
        problems = data['problems']
        expected = split_units(curated['units'])
        if not problems or len(problems) != data['count'] or len(problems) != build['problem_count']:
            raise ValueError(f'Problem count mismatch: {project}')
        if [p['id'] for p in problems] != [p['id'] for p in expected] or len(expected) != len(problems):
            raise ValueError(f'Problem numbering mismatch: {project}')
        for p, source in zip(problems, expected):
            for field in ('stem_latex', 'subquestions', 'source_file', 'source_sha256', 'page_number', 'review_status'):
                if p.get(field) != source.get(field):
                    raise ValueError(f'Stale built problem {project}/{p["id"]}: {field}')
            if p.get('review_status') != 'verified' or len(p.get('subquestions', [])) > 3:
                raise ValueError(f'Unreviewed or unsplit problem: {project}/{p["id"]}')
            for figure in p.get('figures', []):
                relative = f'{project}/{figure["path"]}'
                if not safe_path(relative).is_file():
                    raise ValueError(f'Missing approved figure: {relative}')
                figures.add(relative)
        if build.get('latex_issues'):
            raise ValueError(f'Unresolved LaTeX issues: {project}')
        pdf = (ROOT / project / 'main.pdf').read_bytes()
        pdf_hash = sha256(pdf)
        reviews = [p for p in visual['projects'] if p['project'] == project]
        if len(reviews) != 1:
            raise ValueError(f'Expected exactly one visual review: {project}')
        review = reviews[0]
        if review.get('status', visual.get('status')) != 'passed':
            raise ValueError(f'Visual review is not passed: {project}')
        if review.get('pdf_sha256') != pdf_hash or review.get('issues'):
            raise ValueError(f'Visual review does not match current PDF: {project}')
        with fitz.open(stream=pdf, filetype='pdf') as document:
            if review.get('reviewed_pdf_pages') != list(range(1, len(document) + 1)):
                raise ValueError(f'Incomplete visual review: {project}')
            headings = re.findall(r'(?:例题|习题)((?:\d+|[A-Z])\.\d+)', re.sub(r'\s+', '', ''.join(p.get_text() for p in document)))
            if headings != [p['id'] for p in problems]:
                raise ValueError(f'PDF problem order mismatch: {project}')
            pages = len(document)
        if not preview:
            acceptance = next(p for p in status['projects'] if p['project'] == project)
            if acceptance.get('problem_count') != len(problems) or acceptance.get('pdf_sha256') != pdf_hash:
                raise ValueError(f'Production acceptance does not match current deliverables: {project}')
            source_units = {}
            for unit in curated['units']:
                key = (unit['source_file'], unit['page_number'])
                source_units[key] = source_units.get(key, 0) + 1
            for row in read_json(safe_path(status['page_reviews_file'])):
                if row['project'] != project:
                    continue
                actual = source_units.get((row['source_file'], row['page_number']), 0)
                if row['status'] == 'excluded' and actual or row['status'] == 'reviewed' and row['units_count'] != actual:
                    raise ValueError(f'Page review source-unit count differs: {project}/{row["page_number"]}')
        summaries.append({'project': project, 'status': data['status'], 'problem_count': len(problems),
                          'pdf_pages': pages, 'pdf_sha256': pdf_hash,
                          'curated_sha256': sha256(curated_bytes), 'problems_sha256': sha256(problem_bytes)})
    return summaries, figures


def validate_production_coverage(status, projects, all_projects=True):
    """Require explicit review or reasoned exclusion for every physical source page."""
    import fitz

    if all_projects and status.get('status') != 'complete':
        raise ValueError('Full publication refused: qa/production-status.json status is not complete.')
    accepted = status.get('projects', [])
    if not all_projects:
        accepted = [p for p in accepted if p.get('project') in projects]
    if sorted(p.get('project', '') for p in accepted) != sorted(projects):
        raise ValueError('Production status must contain each configured project exactly once.')
    reviews_file = status.get('page_reviews_file', '')
    if not re.fullmatch(r'qa/[^/]+\.json', reviews_file):
        raise ValueError('Production page_reviews_file must be a JSON file directly under qa/.')
    records = read_json(safe_path(reviews_file))
    if not isinstance(records, list):
        raise ValueError('Page reviews must be an array.')
    if not all_projects:
        records = [r for r in records if r.get('project') in projects]
    reviewed = set()
    for row in records:
        key = (row.get('project'), row.get('source_file'), row.get('page_number'))
        if key in reviewed or row.get('status') not in {'reviewed', 'excluded'}:
            raise ValueError(f'Duplicate or incomplete page review: {key}')
        if row['status'] == 'excluded' and not str(row.get('reason', '')).strip():
            raise ValueError(f'Excluded page needs an explicit reason: {key}')
        if row['status'] == 'reviewed':
            if not isinstance(row.get('units_count'), int) or row['units_count'] < 0:
                raise ValueError(f'Reviewed page needs a source-unit count: {key}')
            if row['units_count'] == 0 and not str(row.get('reason', '')).strip():
                raise ValueError(f'Page without source units needs a reason: {key}')
        reviewed.add(key)
    expected = set()
    counts = {}
    config = read_json(ROOT / 'config/projects.json')
    configured = config['projects'] if all_projects else [p for p in config['projects'] if p['name'] in projects]
    if sorted(p['name'] for p in configured) != sorted(projects):
        raise ValueError('Publication projects do not match the configured scope.')
    for project in configured:
        count = 0
        for source in project['sources']:
            with fitz.open(safe_path(project['name'] + '/' + source)) as document:
                expected.update((project['name'], source, n) for n in range(1, len(document) + 1))
                count += len(document)
        counts[project['name']] = count
    if reviewed != expected:
        raise ValueError(f'Incomplete source review coverage: missing={len(expected-reviewed)}, unexpected={len(reviewed-expected)}')
    inventory = read_json(ROOT / 'config/production-books.json')
    books = inventory['books'] if all_projects else [b for b in inventory['books'] if b['project'] in projects]
    ocr_required = {name: 0 for name in projects}
    inventory_sources = set()
    for book in books:
        identity = (book['project'], book['source_file'])
        if identity in inventory_sources:
            raise ValueError(f'Duplicate production source: {identity}')
        inventory_sources.add(identity)
        included = set()
        for first, last in book['included_ranges']:
            covered = set(range(first, last + 1))
            if first > last or included & covered:
                raise ValueError(f'Invalid or repeated production page range: {identity}')
            included.update(covered)
        if not included or min(included) < 1 or max(included) > book['pdf_pages']:
            raise ValueError(f'Out-of-range production pages: {identity}')
        with safe_path(book['project'] + '/' + book['source_file']).open('rb') as handle:
            if hashlib.file_digest(handle, 'sha256').hexdigest() != book['source_sha256']:
                raise ValueError(f'Source PDF changed: {identity}')
        ocr_required[book['project']] += len(included)
    if inventory_sources != {(p['name'], source) for p in configured for source in p['sources']}:
        raise ValueError('Production inventory does not match configured source PDFs.')
    from audit_ocr_evidence import validate_ocr_evidence
    if validate_ocr_evidence(ROOT, books, records) != sum(ocr_required.values()):
        raise ValueError('OCR proofreading evidence does not cover every included page.')
    for project in accepted:
        if project.get('status') != 'complete':
            raise ValueError(f'Project is not complete: {project.get("project")}')
        for field in ('planned_source_pages', 'review_complete_pages'):
            if project.get(field) != counts[project['project']]:
                raise ValueError(f'Incorrect completed page count: {project["project"]}/{field}')
        required = ocr_required[project['project']]
        completed = project.get('ocr_complete_pages', -1)
        if project.get('ocr_required_pages') != required or not required <= completed <= counts[project['project']]:
            raise ValueError(f'Incomplete OCR coverage: {project["project"]}')
    if all_projects:
        for field in ('planned_source_pages', 'review_complete_pages'):
            if status.get(field) != sum(counts.values()):
                raise ValueError(f'Incorrect total completed page count: {field}')
        if status.get('ocr_required_pages') != sum(ocr_required.values()) or status.get('ocr_complete_pages') != sum(p['ocr_complete_pages'] for p in accepted):
            raise ValueError('Incorrect total OCR page count.')


def project_references(value):
    """Read explicit ownership in QA, without inferring it from file names."""
    if isinstance(value, list):
        return set().union(*(project_references(v) for v in value))
    if isinstance(value, dict):
        names = {value['project']} if isinstance(value.get('project'), str) else set()
        return names | set().union(*(project_references(v) for v in value.values()))
    return set()


def scoped_shared_files(projects):
    """Project shared audit/configuration payloads without editing local records.

    Unowned or mixed QA files are excluded by default. The three core audit
    records have explicit projections; no other mixed report is copied whole.
    """
    selected = set(projects)
    status = read_json(ROOT / 'qa/production-status.json')
    page_file = status['page_reviews_file']
    if not re.fullmatch(r'qa/[^/]+\.json', page_file):
        raise ValueError('Production page_reviews_file must be a JSON file directly under qa/.')
    accepted = [p for p in status['projects'] if p['project'] in selected]
    scoped_status = {key: status[key] for key in ('schema_version', 'updated_at', 'page_reviews_file') if key in status}
    scoped_status.update(projects=accepted, publication_scope=projects,
                         status='complete' if all(p.get('status') == 'complete' for p in accepted) else 'in_progress',
                         notice='This published audit covers only the listed projects; local records for other projects are retained separately.')
    for key in ('planned_source_pages', 'ocr_required_pages', 'ocr_complete_pages', 'review_complete_pages'):
        scoped_status[key] = sum(p.get(key, 0) for p in accepted)
    visual = read_json(ROOT / 'qa/visual-review.json')
    reviews = [p for p in visual['projects'] if p['project'] in selected]
    scoped_visual = {key: visual[key] for key in ('schema_version', 'method') if key in visual}
    scoped_visual.update(projects=reviews, publication_scope=projects,
                         status='passed' if all(p.get('status', visual.get('status')) == 'passed' for p in reviews) else 'pending')
    config = read_json(ROOT / 'config/projects.json')
    config['projects'] = [p for p in config['projects'] if p['name'] in selected]
    inventory = read_json(ROOT / 'config/production-books.json')
    books = [b for b in inventory['books'] if b['project'] in selected]
    scoped_inventory = {key: inventory[key] for key in ('schema_version', 'inventory_date', 'page_convention', 'verification') if key in inventory}
    total = sum(b['pdf_pages'] for b in books)
    included = sum(last - first + 1 for b in books for first, last in b['included_ranges'])
    scoped_inventory.update(scope=projects, books=books, total_source_pages=total,
                            included_pages=included, excluded_pages=total-included)
    overrides = {
        'qa/production-status.json': scoped_status,
        page_file: [r for r in read_json(safe_path(page_file)) if r['project'] in selected],
        'qa/visual-review.json': scoped_visual,
        'config/projects.json': config,
        'config/production-books.json': scoped_inventory,
    }
    for relative in ('config/production-pages.json', 'config/production-pages-priority.json',
                     'config/sample-inventory.json'):
        if safe_path(relative).exists():
            records = read_json(safe_path(relative))
            if not isinstance(records, list) or any(not isinstance(r, dict) or 'project' not in r for r in records):
                raise ValueError(f'Expected project-owned inventory rows: {relative}')
            overrides[relative] = [r for r in records if r['project'] in selected]
    sample_file = 'config/sample-pages.json'
    if safe_path(sample_file).exists():
        sample = read_json(safe_path(sample_file))
        overrides[sample_file] = {'description': 'Sample pages for the published projects only.',
                                  'items': [r for r in sample['items'] if r['project'] in selected]}
    # This is a remote-tree snapshot and publication procedure, not textbook QA.
    # Retain it so the published preparer can run; it still requires a fresh
    # remote read before mutation and never deletes an unselected project.
    eligible = set(overrides) | {'qa/production-status.schema.json', 'qa/remote-reconciliation.json'}
    for path in (ROOT / 'qa').glob('*.json'):
        relative = path.relative_to(ROOT).as_posix()
        if relative in eligible or forbidden(relative):
            continue
        owners = project_references(read_json(path))
        if owners and owners <= selected:
            eligible.add(relative)
    return {path: (json.dumps(data, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
            for path, data in overrides.items()}, eligible


def obsolete_placeholder_deletions(remote, projects):
    """Only migrate the four immutable known placeholders with the tutorial."""
    if TUTORIAL_PROJECT not in projects:
        return []
    reconciliation = remote['reconciliation']
    if (reconciliation.get('remote_tutorial_path') != OLD_TUTORIAL or
            reconciliation.get('local_tutorial_path') != TUTORIAL_PROJECT):
        raise ValueError('Unexpected tutorial migration paths; preserve remote files.')
    deletions, seen = [], set()
    for entry in remote['remote_files']:
        path = entry['path']
        if path not in OBSOLETE_PLACEHOLDERS:
            continue
        expected = OBSOLETE_PLACEHOLDERS[path]
        if path in seen or entry.get('sha') != expected or entry.get('mode') != '100644':
            raise ValueError(f'Remote placeholder changed; preserve and reconcile before publishing: {path}')
        seen.add(path)
        deletions.append({'path': path, 'expected_blob_sha': expected})
    return deletions


def prepare(preview=False, project=None):
    selected_project = project
    config = read_json(ROOT / 'config/projects.json')
    projects = [p['name'] for p in config['projects']]
    if len(set(projects)) != len(projects) or any(len(PurePosixPath(p).parts) != 1 or forbidden(p) for p in projects):
        raise ValueError('Project names must be unique direct workspace folder names.')
    if selected_project is not None:
        if selected_project not in projects:
            raise ValueError(f'Unknown publication project: {selected_project}')
        projects = [selected_project]
    for project in projects:
        safe_path(project)
    summaries, figures = validate_projects(projects, preview, all_projects=selected_project is None)
    overrides, shared = scoped_shared_files(projects) if selected_project is not None else ({}, None)
    output = ROOT / '.cache/publication'
    if selected_project is not None:
        output = output / ('project-' + selected_project)
    output.mkdir(parents=True, exist_ok=True)
    blobs = output / 'blobs'
    blobs.mkdir(exist_ok=True)
    paths = candidates(projects)
    ignored = git_ignored(paths, output)
    selected, excluded = [], []
    for relative in paths:
        if shared is not None and PurePosixPath(relative).parts[0] in {'qa', 'config'} and relative not in shared:
            excluded.append({'path': relative, 'reason': 'outside_project_scope'})
            continue
        if not allowed(relative, projects, figures) or relative in ignored:
            excluded.append({'path': relative, 'reason': 'gitignore' if relative in ignored else 'not_allowlisted'})
            continue
        data = overrides[relative] if relative in overrides else safe_path(relative).read_bytes()
        if len(data) >= 100 * 1024 * 1024:
            raise ValueError(f'File exceeds GitHub regular blob size: {relative}')
        encoding = 'base64' if PurePosixPath(relative).suffix.lower() in BINARY_SUFFIXES else 'utf-8'
        if encoding == 'utf-8':
            content = data.decode('utf-8')
            if any(pattern.search(content) for pattern in SECRET_PATTERNS):
                raise ValueError(f'Possible credential material in: {relative}')
        else:
            content = base64.b64encode(data).decode('ascii')
        digest = sha256(data)
        git_sha = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
        blob_file = blobs / (digest + '.json')
        blob_file.write_text(json.dumps({'encoding': encoding, 'content': content}, ensure_ascii=False) + '\n', encoding='utf-8')
        selected.append({'path': relative, 'mode': '100644', 'size': len(data), 'sha256': digest,
                         'git_blob_sha': git_sha, 'encoding': encoding,
                         'payload': blob_file.relative_to(output).as_posix()})
    selected_paths = {entry['path'] for entry in selected}
    required = ROOT_FILES | set(overrides) | {f'{p}/{name}' for p in projects for name in ('main.pdf', 'main.tex', 'data/curated.json', 'data/problems.json')}
    missing = required - selected_paths
    if missing or figures - selected_paths:
        raise ValueError(f'Required deliverables excluded or missing: {sorted(missing | (figures - selected_paths))}')
    for project in summaries:
        for name, field in [('main.pdf', 'pdf_sha256'), ('data/curated.json', 'curated_sha256'), ('data/problems.json', 'problems_sha256')]:
            entry = next(f for f in selected if f['path'] == project['project'] + '/' + name)
            if entry['sha256'] != project[field]:
                raise ValueError('Deliverables changed while preparing the package; rerun validation.')
    remote = read_json(ROOT / 'qa/remote-reconciliation.json')
    deletions = obsolete_placeholder_deletions(remote, projects)
    manifest = {'schema_version': 1, 'mode': 'sample-preview' if preview else 'complete',
                'ready_for_full_publication': not preview, 'remote_writes_performed': False,
                'scope': 'all_projects' if selected_project is None else 'selected_project',
                'package_directory': output.relative_to(ROOT).as_posix(),
                'projected_shared_files': sorted(overrides),
                'repository': remote['repository'], 'base_head_sha': remote['remote_head_sha'],
                'base_tree_sha': remote['remote_tree_sha'], 'remote_must_be_refreshed_before_publish': True,
                'projects': summaries, 'files': selected, 'excluded_candidates': excluded,
                'proposed_obsolete_placeholder_deletions': deletions,
                'notice': 'Local review package only. Only listed payloads belong to this manifest; ignore stale payloads from earlier runs. Re-read remote main before any publication.'}
    (output / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    rows = ['# 发布内容包', '', '模式：' + manifest['mode'], '',
            '本程序没有提交或推送。整书发布前必须重新读取远程分支并复核清单。', '',
            '| 路径 | 字节数 | 编码 | SHA-256 |', '| --- | ---: | --- | --- |']
    rows += [f'| {f["path"]} | {f["size"]} | {f["encoding"]} | {f["sha256"]} |' for f in selected]
    (output / 'REVIEW.md').write_text('\n'.join(rows) + '\n', encoding='utf-8')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sample-preview', action='store_true', help='Prepare a local sample preview; never mark it ready for full publication.')
    parser.add_argument('--project', help='Publish only this configured project; require its complete acceptance and leave other projects untouched.')
    args = parser.parse_args()
    try:
        manifest = prepare(args.sample_preview, args.project)
    except (ValueError, OSError, KeyError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps({'mode': manifest['mode'], 'files': len(manifest['files']),
                      'ready_for_full_publication': manifest['ready_for_full_publication'],
                      'manifest': manifest['package_directory'] + '/manifest.json'}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
