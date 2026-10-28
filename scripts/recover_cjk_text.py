"""Recover missing CJK ToUnicode maps in a derived PDF, leaving source untouched.

The textbook uses 256-character GBK subfonts. Infer their GBK block only from
exact glyph-outline matches with local Windows fonts. This is a text-layer
cross-check for the PaddleOCR pipeline, not a proofreading or publication step.
"""
import argparse
import hashlib
import io
import json
from collections import Counter,defaultdict
from pathlib import Path
import fitz
from fontTools.ttLib import TTFont

ROOT=Path(__file__).resolve().parents[1]
def glyph_signature(font,name):
    try:
        points,ends,_=font['glyf'][name].getCoordinates(font['glyf'])
        return (tuple(points),tuple(ends)) if points else None
    except Exception:return None

def gbk_index(character):
    try: b=character.encode('gbk')
    except UnicodeEncodeError:return None
    if len(b)!=2 or not 0x81<=b[0]<=0xfe:return None
    low=b[1]-0x40-(b[1]>=0x80)
    return (b[0]-0x81)*190+low

def from_gbk_index(index):
    high,low=divmod(index,190)
    trail=low+0x40+(low>=63)
    try:return bytes([high+0x81,trail]).decode('gbk')
    except (ValueError,UnicodeDecodeError):return None

def system_lookup(path,collection=False):
    font=TTFont(path,fontNumber=0 if collection else -1)
    result=defaultdict(list)
    for code,name in font.getBestCmap().items():
        index=gbk_index(chr(code))
        if index is not None:
            signature=glyph_signature(font,name)
            if signature:result[signature].append(index)
    return result

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--source',default='数学分析讲义/input/数学分析讲义（第三册）.pdf')
    args=parser.parse_args()
    source=ROOT/args.source
    with source.open('rb') as f:digest=hashlib.file_digest(f,'sha256').hexdigest()
    output=ROOT/'.cache/decoded'/digest[:12]
    output.mkdir(parents=True,exist_ok=True)
    lookups={}
    for family,name in [('SimSun','simsun.ttc'),('SimHei','simhei.ttf'),('KaiTi','simkai.ttf')]:
        path=Path('C:/Windows/Fonts')/name
        if path.is_file():
            lookups[family]=system_lookup(path,name.endswith('.ttc'))
            print(f'Indexed {family}',flush=True)
    doc=fitz.open(source)
    fonts={row[0]:row for page in doc for row in page.get_fonts(full=True) if row[2]=='TrueType'}
    report=[]
    for xref,row in fonts.items():
        family=row[3].split('+')[-1]
        if family not in lookups:continue
        font=TTFont(io.BytesIO(doc.extract_font(xref)[3]))
        byte_map=next((t.cmap for t in font['cmap'].tables if t.platformID==1),None)
        if not byte_map:continue
        anchors=[]
        for code,name in byte_map.items():
            matches=lookups[family].get(glyph_signature(font,name),[])
            if len(matches)==1:anchors.append((code,matches[0]))
        offsets=Counter(index-code for code,index in anchors)
        if not offsets:
            report.append({'xref':xref,'font':row[3],'status':'unresolved','glyphs':len(byte_map)})
            continue
        offset,count=offsets.most_common(1)[0]
        if count!=len(anchors) or offset%256:
            report.append({'xref':xref,'font':row[3],'status':'conflicting_anchors','offsets':dict(offsets)})
            continue
        mappings=[]
        for code in byte_map:
            character=from_gbk_index(code+offset)
            if character:mappings.append((code,character))
        cmap='/CIDInit /ProcSet findresource begin\n12 dict begin\nbegincmap\n/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def\n/CMapName /RecoveredGBK def\n/CMapType 2 def\n1 begincodespacerange\n<00> <FF>\nendcodespacerange\n'
        for start in range(0,len(mappings),100):
            batch=mappings[start:start+100]
            cmap+=f'{len(batch)} beginbfchar\n'+''.join(f'<{code:02X}> <{char.encode("utf-16-be").hex().upper()}>\n' for code,char in batch)+'endbfchar\n'
        cmap+='endcmap\nCMapName currentdict /CMap defineresource pop\nend\nend\n'
        newxref=doc.get_new_xref()
        doc.update_object(newxref,'<< >>')
        doc.update_stream(newxref,cmap.encode('ascii'))
        doc.xref_set_key(xref,'ToUnicode',f'{newxref} 0 R')
        report.append({'xref':xref,'font':row[3],'status':'recovered','anchors':len(anchors),'glyphs':len(mappings),'gbk_block':offset//256})
    derived=output/'text-layer.pdf'
    doc.save(derived,garbage=3,deflate=True)
    doc.close()
    result={'source_file':args.source,'source_sha256':digest,'status':'text_layer_cross_check_only','fonts':report,'counts':dict(Counter(r['status'] for r in report))}
    (output/'recovery.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    with fitz.open(derived) as decoded:
        for n,page in enumerate(decoded,1):
            (output/f'p{n:04d}.txt').write_text(page.get_text(),encoding='utf-8')
            text_dict=page.get_text('dict',flags=fitz.TEXTFLAGS_DICT & ~fitz.TEXT_PRESERVE_IMAGES)
            (output/f'p{n:04d}.json').write_text(json.dumps(text_dict,ensure_ascii=False),encoding='utf-8')
    print(json.dumps(result['counts']))
    print(derived)
if __name__=='__main__':main()
