"""PaddleOCR PP-StructureV3 page extraction, with resumable per-page outputs."""
import argparse
import json
import os
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL_HOME = Path(os.environ.get('LOCALAPPDATA', str(ROOT / '.cache'))) / 'TextbookWorkbook/models'
# Paddle's Windows C++ loader cannot open model paths containing Chinese.
os.environ.setdefault('PADDLE_PDX_CACHE_HOME', str(MODEL_HOME / 'paddlex'))
os.environ.setdefault('HF_HOME', str(ROOT / '.cache/huggingface'))
os.environ.setdefault('MODELSCOPE_CACHE', str(ROOT / '.cache/modelscope'))
os.environ.setdefault('PADDLE_PDX_MODEL_SOURCE', 'huggingface')

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--project')
    parser.add_argument('--limit',type=int)
    parser.add_argument('--device',default='cpu')
    args=parser.parse_args()
    items=json.loads((ROOT/'config/sample-inventory.json').read_text(encoding='utf-8'))
    if args.project:
        items=[x for x in items if x['project']==args.project]
    if args.limit:
        items=items[:args.limit]
    from paddleocr import PPStructureV3
    pipeline=PPStructureV3(
        device=args.device,
        cpu_threads=8,
        enable_mkldnn=False,
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
        use_table_recognition=False,
        use_seal_recognition=False,
        use_chart_recognition=False,
        use_region_detection=False,
        use_formula_recognition=True,
        layout_detection_model_name='PP-DocLayout-M',
        text_detection_model_name='PP-OCRv5_mobile_det',
        text_recognition_model_name='PP-OCRv5_server_rec',
        formula_recognition_model_name='PP-FormulaNet_plus-S',
        formula_recognition_batch_size=1,
    )
    failures=[]
    for item in items:
        dest=ROOT/item['project']/'data/ocr_raw'/item['source_id']/f"p{item['page_number']:04d}"
        done=dest/'completed.json'
        if done.exists():
            print(f'SKIP {dest}',flush=True)
            continue
        dest.mkdir(parents=True,exist_ok=True)
        start=time.monotonic()
        print(f"START {item['project']} {item['source_file']} p{item['page_number']}",flush=True)
        try:
            import numpy as np
            from PIL import Image
            pixels=np.asarray(Image.open(ROOT/item['image']).convert('RGB'))[:,:,::-1].copy()
            for result in pipeline.predict(pixels):
                result.save_to_json(str(dest))
                result.save_to_markdown(str(dest))
            done.write_text(json.dumps({**item,'seconds':round(time.monotonic()-start,2),'status':'unreviewed'},ensure_ascii=False,indent=2),encoding='utf-8')
            print(f'DONE {time.monotonic()-start:.1f}s',flush=True)
        except Exception as exc:
            failures.append({**item,'error':str(exc)})
            print(f'FAILED {exc}',flush=True)
    (ROOT/'.cache/ocr-failures.json').write_text(json.dumps(failures,ensure_ascii=False,indent=2),encoding='utf-8')
    if failures:
        raise SystemExit(f'{len(failures)} pages failed; successful pages are resumable')

if __name__=='__main__':
    main()
