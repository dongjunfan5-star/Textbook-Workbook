"""Exercise the actual PDF TOC after it grows beyond one page."""
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from build_workbook import chapter_heading,compile_stable,find_xelatex


class PdfNavigation(unittest.TestCase):
    def test_multipage_toc_and_appendix_destinations(self):
        try:
            exe=find_xelatex()
        except FileNotFoundError:
            self.skipTest('XeLaTeX is required for the PDF navigation regression')
        import fitz
        parent=ROOT/'.cache/test-pdf-navigation'
        parent.mkdir(parents=True,exist_ok=True)
        folder=Path(tempfile.mkdtemp(dir=parent))
        try:
            source=(r'\documentclass{article}'
                    r'\usepackage[paperwidth=150mm,paperheight=130mm,margin=18mm]{geometry}'
                    r'\usepackage{hyperref}\begin{document}\tableofcontents\clearpage')
            chapters=[*range(1,19),'A']
            for chapter in chapters:
                label=f'C{chapter:02d}' if isinstance(chapter,int) else 'APPENDIX'
                source+=chapter_heading(chapter,label)+f'PROBE-{label}'+r'\clearpage'
            source+=r'\end{document}'
            (folder/'main.tex').write_text(source,encoding='utf-8')
            passes=compile_stable(exe,folder)
            self.assertGreaterEqual(passes,3)
            with fitz.open(folder/'main.pdf') as pdf:
                destinations={}
                for page_number,page in enumerate(pdf,1):
                    for label in re.findall(r'PROBE-(C\d{2}|APPENDIX)',page.get_text()):
                        destinations[label]=page_number
                self.assertEqual(len(destinations),19)
                first_body=destinations['C01']
                self.assertGreater(first_body,2)
                toc_text=''.join(pdf[i].get_text() for i in range(first_body-1))
                # The PDF text must show the final page number, not just the .toc file.
                compact=re.sub(r'[\s.]+','',toc_text)
                for chapter in chapters:
                    label=f'C{chapter:02d}' if isinstance(chapter,int) else 'APPENDIX'
                    self.assertIn(f'{chapter}{label}{destinations[label]}',compact)
                bookmarks=pdf.get_toc()
                self.assertEqual(len(bookmarks),19)
                for _,title,page_number in bookmarks:
                    label=title.split()[-1]
                    self.assertEqual(page_number,destinations[label])
                links=[link for i in range(first_body-1) for link in pdf[i].get_links()
                       if link.get('kind') in (fitz.LINK_GOTO,fitz.LINK_NAMED) and link.get('page',-1)>=0]
                self.assertEqual(sorted({link['page']+1 for link in links}),sorted(destinations.values()))
        finally:
            if folder.resolve().is_relative_to(parent.resolve()):
                shutil.rmtree(folder)


if __name__=='__main__':
    unittest.main()
