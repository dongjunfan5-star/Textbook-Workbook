"""Resumable page OCR with PaddleOCR-VL 1.6 and a local llama.cpp server.

This stage produces unreviewed evidence, never publication-ready problem data.
The input manifest is the same list of page records used by prepare_sample.py.
"""
import argparse
import hashlib
import importlib.metadata
import json
import os
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL_HOME = Path(os.environ.get('LOCALAPPDATA', str(ROOT/'.cache'))) / 'TextbookWorkbook/models'
os.environ.setdefault('PADDLE_PDX_CACHE_HOME', str(MODEL_HOME/'paddlex'))
os.environ.setdefault('HF_HOME', str(MODEL_HOME/'huggingface'))
os.environ.setdefault('PADDLE_PDX_MODEL_SOURCE', 'huggingface')
os.environ.setdefault('NO_PROXY', 'localhost,127.0.0.1')


def atomic_json(path, value):
    temporary=path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    temporary.replace(path)


def pixels_for(item, width=1800):
    import numpy as np
    from PIL import Image
    image=ROOT/item['image'] if item.get('image') else None
    if image and image.is_file():
        with Image.open(image) as loaded:
            return np.asarray(loaded.convert('RGB'))[:,:,::-1].copy()
    import fitz
    source=ROOT/item['project']/item['source_file']
    with fitz.open(source) as document:
        page=document[item['page_number']-1]
        pix=page.get_pixmap(matrix=fitz.Matrix(width/page.rect.width,width/page.rect.width),alpha=False)
        return np.frombuffer(pix.samples,dtype=np.uint8).reshape(pix.height,pix.width,3)[:,:,::-1].copy()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--inventory',default='config/sample-inventory.json')
    parser.add_argument('--project')
    parser.add_argument('--source-id')
    parser.add_argument('--pages',help='Comma-separated physical PDF page numbers')
    parser.add_argument('--limit',type=int)
    parser.add_argument('--server',default='http://127.0.0.1:8111/v1')
    parser.add_argument('--device',default='cpu')
    parser.add_argument('--concurrency',type=int,default=1)
    parser.add_argument('--output-subdir',default='vl1.6')
    parser.add_argument('--max-consecutive-failures',type=int,default=3)
    args=parser.parse_args()
    if '/' in args.output_subdir or '\\' in args.output_subdir or args.output_subdir in ('.','..'):
        parser.error('output-subdir must be one directory name')
    items=json.loads((ROOT/args.inventory).read_text(encoding='utf-8-sig'))
    if isinstance(items,dict):
        items=items['items']
    if args.project:
        items=[item for item in items if item['project']==args.project]
    if args.source_id:
        items=[item for item in items if item['source_id']==args.source_id]
    if args.pages:
        pages={int(x) for x in args.pages.split(',')}
        items=[item for item in items if item['page_number'] in pages]
    if args.limit:
        items=items[:args.limit]
    sources={}
    remaining=[]
    for item in items:
        source=ROOT/item['project']/item['source_file']
        if source not in sources:
            with source.open('rb') as stream:
                sources[source]=hashlib.file_digest(stream,'sha256').hexdigest()
        if sources[source]!=item['source_sha256']:
            raise ValueError(f'Source checksum changed: {source}')
        dest=ROOT/item['project']/'data/ocr_raw'/args.output_subdir/item['source_id']/f"p{item['page_number']:04d}"
        done=dest/'completed.json'
        if done.is_file():
            record=json.loads(done.read_text(encoding='utf-8'))
            if record.get('source_sha256')==item['source_sha256'] and (dest/'result.json').exists():
                print(f'SKIP {item["source_id"]} p{item["page_number"]}',flush=True)
                continue
        remaining.append((item,dest))
    if not remaining:
        print('No unfinished pages.',flush=True)
        return
    from paddleocr import PaddleOCRVL
    pipeline=PaddleOCRVL(
        pipeline_version='v1.6',device=args.device,cpu_threads=4,enable_mkldnn=False,
        vl_rec_backend='llama-cpp-server',vl_rec_server_url=args.server,
        vl_rec_api_model_name='PaddleOCR-VL-1.6',vl_rec_max_concurrency=args.concurrency,
        use_doc_orientation_classify=False,use_doc_unwarping=False,
        use_chart_recognition=False,
    )
    failures=[]
    failure_streak=0
    versions={name:importlib.metadata.version(name) for name in ('paddleocr','paddlex','paddlepaddle')}
    for count,(item,dest) in enumerate(remaining,1):
        dest.mkdir(parents=True,exist_ok=True)
        started=time.monotonic()
        print(f'START {count}/{len(remaining)} {item["source_id"]} p{item["page_number"]}',flush=True)
        try:
            for result in pipeline.predict(pixels_for(item)):
                result.save_to_json(str(dest/'result.json'))
                result.save_to_markdown(str(dest/'result.md'))
            if not (dest/'result.json').is_file():
                raise RuntimeError('Pipeline returned no result')
            atomic_json(dest/'completed.json',{
                **item,'status':'unreviewed','engine':'PaddleOCR-VL-1.6 / llama.cpp b11829',
                'versions':versions,'seconds':round(time.monotonic()-started,2),
            })
            failure_streak=0
            print(f'DONE {time.monotonic()-started:.2f}s {dest}',flush=True)
        except Exception as error:
            record={**item,'status':'failed','error':str(error)}
            failures.append(record)
            failure_streak+=1
            atomic_json(dest/'failed.json',record)
            print(f'FAILED {error}',flush=True)
            traceback.print_exc()
            if failure_streak>=args.max_consecutive_failures:
                raise SystemExit('Stopped after consecutive failures; inspect the local server and resume this manifest.')
    if failures:
        raise SystemExit(f'{len(failures)} pages failed; successful pages are resumable')


if __name__=='__main__':
    main()
