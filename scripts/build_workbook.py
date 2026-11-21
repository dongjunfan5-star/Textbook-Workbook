"""Validate reviewed units, split subquestions, typeset and compile twice."""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
import os
import re
import shutil
import subprocess
from collections import defaultdict
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def split_units(units, limit=3):
    if limit < 1:
        raise ValueError('Subquestion limit must be positive')
    problems=[]
    counters=defaultdict(int)
    for unit in units:
        if unit.get('review_status')!='verified':
            raise ValueError('Unreviewed material cannot be published')
        if 'original_number' in unit or 'original_problem_number' in unit:
            raise ValueError('Original problem numbering is not retained')
        if not unit.get('stem_latex') or not isinstance(unit.get('page_number'),int) or unit['page_number']<1:
            raise ValueError('Missing stem or first physical source page')
        parts=unit.get('subquestions',[])
        groups=[parts[i:i+limit] for i in range(0,len(parts),limit)] if parts else [[]]
        for group in groups:
            problem=copy.deepcopy(unit)
            counters[unit['chapter']]+=1
            problem['id']=f"{unit['chapter']}.{counters[unit['chapter']]}"
            problem['subquestions']=group
            problems.append(problem)
    return problems

def tex_escape(value):
    return ''.join({'\\':r'\textbackslash{}','&':r'\&','%':r'\%','$':r'\$','#':r'\#','_':r'\_','{':r'\{','}':r'\}'}.get(c,c) for c in value)

def chapter_file(chapter):
    if isinstance(chapter,int) and chapter>0:
        return f'chapter_{chapter:02d}.tex'
    if isinstance(chapter,str) and re.fullmatch('[A-Z]',chapter):
        return f'appendix_{chapter}.tex'
    raise ValueError('Invalid chapter identifier')

def chapter_heading(chapter,title):
    chapter_file(chapter)
    if isinstance(chapter,int):
        return rf'\renewcommand{{\thesection}}{{\arabic{{section}}}}\renewcommand{{\theHsection}}{{chapter.\arabic{{section}}}}\setcounter{{section}}{{{chapter-1}}}\section{{{tex_escape(title)}}}'+'\n'
    return rf'\renewcommand{{\thesection}}{{\Alph{{section}}}}\renewcommand{{\theHsection}}{{appendix.\Alph{{section}}}}\setcounter{{section}}{{{ord(chapter)-ord("A")}}}\section{{{tex_escape(title)}}}'+'\n'

def problem_tex(problem):
    kind='例题' if problem['kind']=='example' else '习题'
    text=rf'\ProblemHeading{{{kind}}}{{{problem["id"]}}}'+'\n'+problem['stem_latex']+'\n'
    if problem.get('rewritten') or problem.get('editorially_corrected'):
        label='、'.join(x for flag,x in [('rewritten','改写'),('editorially_corrected','校订')] if problem.get(flag))
        text=text.replace(r'\ProblemHeading{'+kind+'}{'+problem['id']+'}',r'\ProblemHeading{'+kind+'}{'+problem['id']+'（'+label+'）}',1)
    for i,part in enumerate(problem.get('subquestions',[]),1):
        text+=rf'\SubQ{{{i}}}{{{part}}}'+'\n'
    for figure in problem.get('figures',[]):
        # Figure names are assigned from the final problem number.
        text+=r'\begin{center}\includegraphics[width='+str(figure.get('width_fraction',0.5))+r'\linewidth]{'+figure['path']+r'}\end{center}'+'\n'
    return text

def find_xelatex(explicit=None):
    candidates=[explicit,os.environ.get('XELATEX'),shutil.which('xelatex'),str(Path(os.environ.get('LOCALAPPDATA',''))/'TextbookWorkbook/texlive/bin/windows/xelatex.exe')]
    for path in candidates:
        if path and Path(path).is_file():
            return str(Path(path).resolve())
    raise FileNotFoundError('XeLaTeX not found; set XELATEX or pass --xelatex')

def compile_tex(exe,project,name,output_dir=None):
    command=[exe,'-no-shell-escape','-interaction=nonstopmode','-halt-on-error','-file-line-error']
    if output_dir:
        command+=['-output-directory='+str(output_dir)]
    command.append(name)
    result=subprocess.run(command,cwd=project,capture_output=True,text=True,encoding='utf-8',errors='replace')
    if result.returncode:
        raise RuntimeError(result.stdout[-10000:]+'\n'+result.stderr[-2000:])
    return result.stdout


def compile_stable(exe,project,name='main.tex',max_passes=5):
    """Compile at least twice, including a further pass when the TOC grows."""
    stem=Path(name).stem
    def auxiliary_state():
        return tuple((project/(stem+suffix)).read_bytes() if (project/(stem+suffix)).is_file() else None
                     for suffix in ('.aux','.toc','.out'))
    previous=auxiliary_state()
    for passes in range(1,max_passes+1):
        compile_tex(exe,project,name)
        current=auxiliary_state()
        if passes>=2 and current==previous:
            return passes
        previous=current
    raise RuntimeError(f'LaTeX references did not stabilize after {max_passes} passes: {name}')

def paginate(problems,heights,per_page,textheight):
    if per_page < 1:
        raise ValueError('Problems per page must be positive')
    pages=[]
    page=[]
    available=textheight-55 # first-page chapter heading reserve
    for problem in problems:
        height=heights[problem['id']]
        if height>textheight-12:
            raise ValueError(f"Problem {problem['id']} exceeds one page; editorial split needed")
        long=problem.get('own_page',False) or height>textheight/per_page
        required=sum(heights[p['id']] for p in page)+height+22*len(page)
        if page and (long or len(page)>=per_page or required>available):
            pages.append(page);page=[];available=textheight
        if not page and height>available:
            raise ValueError(f"Problem {problem['id']} leaves no space for the chapter heading")
        page.append(problem)
        if long:
            pages.append(page);page=[];available=textheight
    if page:
        pages.append(page)
    return pages

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('project')
    parser.add_argument('--config',default='config/projects.json',help='Project settings file relative to workspace')
    parser.add_argument('--xelatex')
    parser.add_argument('--curated',help='Reviewed JSON path relative to workspace; defaults to project/data/curated.json')
    parser.add_argument('--output-dir',help='Separate workspace directory for a chapter proof')
    args=parser.parse_args()
    config=json.loads((ROOT/args.config).read_text(encoding='utf-8'))
    settings=next((item for item in config['projects'] if item['name']==args.project),None)
    if settings is None:
        parser.error(f'Unknown project: {args.project}')
    source_project=(ROOT/args.project).resolve()
    if source_project.parent!=ROOT:
        parser.error('Project must be a directory directly under the workspace')
    project=(ROOT/args.output_dir).resolve() if args.output_dir else source_project
    if not project.is_relative_to(ROOT):
        raise ValueError('Output must stay inside the workspace')
    data_path=ROOT/args.curated if args.curated else source_project/'data/curated.json'
    data=json.loads(data_path.read_text(encoding='utf-8'))
    status=data.get('status')
    if status not in ('sample','chapter_reviewed','complete'):
        raise ValueError('Unsupported editorial state')
    if status=='chapter_reviewed' and not args.output_dir:
        raise ValueError('Chapter proofs require a separate output directory')
    project.mkdir(parents=True,exist_ok=True)
    (project/'data').mkdir(exist_ok=True)
    units=data['units']
    problems=split_units(units)
    if not problems:
        raise ValueError('No reviewed problems')
    per_page=settings['problems_per_page']
    configured_sources={(source_project/path).resolve() for path in settings.get('sources',[])}
    input_dir=(source_project/'input').resolve()
    source_hashes={}
    for p in problems:
        source=(source_project/p['source_file']).resolve()
        if (not source.is_relative_to(source_project) or not source.is_file()
                or (source not in configured_sources and not source.is_relative_to(input_dir))):
            raise ValueError('Source must be an existing PDF in the project input directory or listed in project settings')
        if source not in source_hashes:
            with source.open('rb') as stream:
                source_hashes[source]=hashlib.file_digest(stream,'sha256').hexdigest()
        if p.get('source_sha256')!=source_hashes[source]:
            raise ValueError('Source PDF changed since proofreading: '+str(source))
        if p.get('screenshot'):
            raise ValueError('Do not duplicate a text problem as a screenshot')
        if p.get('figures'):
            import fitz
            (project/'figures').mkdir(exist_ok=True)
            for i,fig in enumerate(p['figures'],1):
                dest=project/'figures'/f"fig_{p['id'].replace('.','_')}_{i}.png"
                if 'crop' not in fig:
                    raise ValueError('Necessary figures require a reviewed crop')
                with fitz.open(source) as doc:
                    doc[fig.get('page_number',p['page_number'])-1].get_pixmap(matrix=fitz.Matrix(3,3),clip=fitz.Rect(fig['crop']),alpha=False).save(dest)
                fig['path']=dest.relative_to(project).as_posix()
    build=project/'build';build.mkdir(exist_ok=True)
    (project/'chapters').mkdir(exist_ok=True)
    preamble=(ROOT/'templates/preamble.tex').read_text(encoding='utf-8')
    exe=find_xelatex(args.xelatex)
    measure=preamble+r'\newwrite\sizes\immediate\openout\sizes=measure.sizes\begin{document}'+'\n'
    measure+=r'\immediate\write\sizes{TEXTHEIGHT=\the\textheight}'+'\n'
    for p in problems:
        measure+=r'\setbox0=\vbox{\hsize=\textwidth '+problem_tex(p)+r'}'+'\n'
        measure+=r'\immediate\write\sizes{'+p['id']+r'=\the\dimexpr\ht0+\dp0\relax}'+'\n'
    measure+=r'\immediate\closeout\sizes\end{document}'
    (build/'measure.tex').write_text(measure,encoding='utf-8')
    compile_tex(exe,project,'build/measure.tex','build')
    sizes=dict(re.findall(r'([A-Z\d]+\.\d+|TEXTHEIGHT)=([\d.]+)pt',(build/'measure.sizes').read_text()))
    heights={k:float(v) for k,v in sizes.items() if k!='TEXTHEIGHT'}
    textheight=float(sizes['TEXTHEIGHT'])
    chapters=defaultdict(list)
    for p in problems:
        chapters[p['chapter']].append(p)
    main=preamble+'\n'+r'\begin{document}\thispagestyle{empty}'+'\n'
    subtitle={'sample':'首轮校对小样','chapter_reviewed':'章节校对稿','complete':'完整题集'}[status]
    main+=r'\begin{center}{\LARGE\bfseries '+tex_escape(args.project)+r'做题本}\par\vspace{6mm}{\large '+subtitle+r'}\end{center}'+'\n'
    if status=='complete':
        main+=f'本题集收录 {len(units)} 道原题，按最多三个小问一组拆分为 {len(problems)} 道题。\n\n'
    else:
        main+=f'本{subtitle}收录 {len(units)} 道选定原题，按最多三个小问一组拆分为 {len(problems)} 道题。仅用于核对内容与版式，不代表整书完成。\n\n'
    main+=f'常规页面每页 {per_page} 题，长题单独成页。正文只显示本做题本题号；题目来源另附校对记录。\n\n'
    main+='标注“改写”的例题由说明性内容改为提问；标注“校订”的题目补足了数学条件，详情见校对记录。\n\n'
    main+='仅限非商业性使用。教材原文与配图的权利归原权利人。\n'+r'\tableofcontents\clearpage'+'\n'
    page_plan=[]
    for ch,items in chapters.items():
        title=items[0]['chapter_title']
        pages=paginate(items,heights,per_page,textheight)
        text=chapter_heading(ch,title)
        for pi,page in enumerate(pages):
            for p in page:
                text+=r'\noindent\begin{minipage}{\textwidth}'+problem_tex(p)+r'\end{minipage}\par\vfill'+'\n'
            if pi<len(pages)-1:
                text+=r'\newpage'+'\n'
            page_plan.append({'chapter':ch,'problems':[p['id'] for p in page],'content_height_pt':round(sum(heights[p['id']] for p in page),2)})
        file=chapter_file(ch)
        (project/'chapters'/file).write_text(text,encoding='utf-8')
        main+=rf'\input{{chapters/{file}}}\clearpage'+'\n'
    main+=r'\end{document}'+'\n'
    (project/'main.tex').write_text(main,encoding='utf-8')
    (project/'data/problems.json').write_text(json.dumps({'status':status,'count':len(problems),'problems':problems},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    tex_passes=compile_stable(exe,project)
    log=(project/'main.log').read_text(encoding='utf-8',errors='replace')
    issues=[line for line in log.splitlines() if any(x in line for x in ('Overfull','Missing character','Undefined control'))]
    report={'source_unit_count':len(units),'problem_count':len(problems),'problems_per_page':per_page,'page_plan':page_plan,'latex_issues':issues,'tex_passes':tex_passes,'references_stable':True}
    (project/'qa').mkdir(exist_ok=True)
    (project/'qa/build-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    if issues:
        raise SystemExit('PDF built, but layout warnings need review: '+str(issues))
    print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=='__main__':
    main()
