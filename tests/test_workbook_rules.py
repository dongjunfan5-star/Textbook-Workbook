"""Regression checks for rules that could silently drop or misattribute questions."""
import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from build_workbook import split_units,paginate,problem_tex,chapter_file,chapter_heading

class WorkbookRules(unittest.TestCase):
    def unit(self,count=0,chapter=1):
        return {'chapter':chapter,'kind':'exercise','stem_latex':'共同题干','page_number':28,'source_file':'input/book.pdf','cross_page':True,'review_status':'verified','subquestions':[f'小问 {i}' for i in range(count)]}

    def test_split_keeps_every_part_once_and_first_page(self):
        for count,sizes in [(0,[0]),(3,[3]),(4,[3,1]),(6,[3,3]),(7,[3,3,1]),(10,[3,3,3,1])]:
            with self.subTest(count=count):
                unit=self.unit(count)
                original=copy.deepcopy(unit)
                result=split_units([unit])
                self.assertEqual([len(p['subquestions']) for p in result],sizes)
                self.assertEqual([q for p in result for q in p['subquestions']],unit['subquestions'])
                self.assertTrue(all(p['page_number']==28 and p['stem_latex']=='共同题干' for p in result))
                self.assertEqual(unit,original)

    def test_unreviewed_or_original_number_cannot_publish(self):
        for change in [{'review_status':'unreviewed'},{'original_number':'2.3'},{'page_number':0}]:
            with self.subTest(change=change),self.assertRaises(ValueError):
                split_units([{**self.unit(),**change}])

    def test_final_number_is_shared_by_examples_and_exercises(self):
        result=split_units([{**self.unit(),'kind':'example'},self.unit(4),self.unit(chapter=8)])
        self.assertEqual([p['id'] for p in result],['1.1','1.2','1.3','8.1'])

    def test_pagination_keeps_order_and_separates_long_problem(self):
        rows=split_units([self.unit() for _ in range(7)])
        rows[4]['own_page']=True
        pages=paginate(rows,{p['id']:60 for p in rows},4,700)
        self.assertEqual([[p['id'] for p in page] for page in pages],[['1.1','1.2','1.3','1.4'],['1.5'],['1.6','1.7']])

    def test_height_limit_and_heading_reserve(self):
        rows=split_units([self.unit()])
        for height in [690,650]:
            with self.subTest(height=height),self.assertRaises(ValueError):
                paginate(rows,{'1.1':height},4,700)

    def test_rewrite_label_is_visible(self):
        row=split_units([{**self.unit(),'rewritten':True}])[0]
        self.assertIn('1.1（改写）',problem_tex(row))

    def test_appendix_does_not_collide_with_numbered_chapters(self):
        result=split_units([self.unit(chapter=1),self.unit(4,chapter='A'),self.unit(chapter=10)])
        self.assertEqual([p['id'] for p in result],['1.1','A.1','A.2','10.1'])
        self.assertEqual(chapter_file('A'),'appendix_A.tex')
        self.assertIn(r'\Alph{section}',chapter_heading('A','附录'))
        self.assertIn(r'\arabic{section}',chapter_heading(10,'多重积分'))
        with self.assertRaises(ValueError):chapter_file('../bad')

if __name__=='__main__':
    unittest.main()
