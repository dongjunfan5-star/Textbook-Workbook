"""Download pinned official OCR runtime assets; never touches textbook inputs."""
import concurrent.futures
import hashlib
import json
import os
import time
import zipfile
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
MODEL_HOME = Path(os.environ['LOCALAPPDATA']) / 'TextbookWorkbook/models/paddleocr-vl-1.6'
ASSETS = [
    ('https://github.com/ggml-org/llama.cpp/releases/download/b11829/llama-b11829-bin-win-cuda-12.4-x64.zip', ROOT/'.tools/llama-b11829-cuda.zip'),
    ('https://github.com/ggml-org/llama.cpp/releases/download/b11829/cudart-llama-bin-win-cuda-12.4-x64.zip', ROOT/'.tools/llama-cudart-12.4.zip'),
    ('https://huggingface.co/PaddlePaddle/PaddleOCR-VL-1.6-GGUF/resolve/511b096/PaddleOCR-VL-1.6-GGUF.gguf', MODEL_HOME/'PaddleOCR-VL-1.6-GGUF.gguf'),
    ('https://huggingface.co/PaddlePaddle/PaddleOCR-VL-1.6-GGUF/resolve/511b096/PaddleOCR-VL-1.6-GGUF-mmproj.gguf', MODEL_HOME/'PaddleOCR-VL-1.6-GGUF-mmproj.gguf'),
]
EXPECTED_SHA256 = {
    'PaddleOCR-VL-1.6-GGUF.gguf':'f3ae46ec885050acf4b3d31944431e1fd90d50664fb09126af4a3c050ba14ee8',
    'PaddleOCR-VL-1.6-GGUF-mmproj.gguf':'204d757d7610d9b3faab10d506d69e5b244e32bf765e2bab2d0167e65e0a058a',
    'llama-b11829-cuda.zip':'fe65d813d828eb3af2016e0c28ccb14ea12ae7be153e28d1b5044b29b8481def',
    'llama-cudart-12.4.zip':'8c79a9b226de4b3cacfd1f83d24f962d0773be79f1e7b75c6af4ded7e32ae1d6',
}

def download(asset):
    url, target = asset
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(target.suffix+'.partial')
    if target.exists():
        return {'url':url, 'path':str(target), 'bytes':target.stat().st_size, 'sha256':hashlib.file_digest(target.open('rb'),'sha256').hexdigest()}
    if target.suffix=='.gguf' or 'llama-b11829' in target.name:
        return segmented_download(url,target,partial)
    for attempt in range(5):
        try:
            offset=partial.stat().st_size if partial.exists() else 0
            response=requests.get(url,stream=True,timeout=(30,60),headers={'Range':f'bytes={offset}-'} if offset else {})
            response.raise_for_status()
            resume=response.status_code==206 and offset>0
            with partial.open('ab' if resume else 'wb') as stream:
                last=time.monotonic()
                for chunk in response.iter_content(1024*1024):
                    stream.write(chunk)
                    if time.monotonic()-last>20:
                        print(f'DOWNLOAD {target.name} {stream.tell()/1e6:.0f} MB',flush=True)
                        last=time.monotonic()
            partial.replace(target)
            return {'url':url,'path':str(target),'bytes':target.stat().st_size,'sha256':hashlib.file_digest(target.open('rb'),'sha256').hexdigest()}
        except Exception as error:
            print(f'RETRY {target.name} {attempt+1}: {error}',flush=True)
            if attempt==4:
                raise
    raise RuntimeError('unreachable')

def segmented_download(url,target,partial):
    response=requests.get(url,headers={'Range':'bytes=0-0'},timeout=(30,60))
    response.raise_for_status()
    if response.status_code!=206:
        raise RuntimeError('Server does not support partial downloads')
    total=int(response.headers['Content-Range'].split('/')[-1])
    offset=partial.stat().st_size if partial.exists() else 0
    # Bound segments explicitly; never trust a successful but full-body response.
    segment_size=8*1024*1024
    ranges=[(start,min(start+segment_size,total)-1) for start in range(offset,total,segment_size)]
    def segment(bounds):
        start,end=bounds
        path=partial.with_suffix(partial.suffix+f'.{start}-{end}')
        expected=end-start+1
        if path.exists() and path.stat().st_size==expected:
            return path
        for attempt in range(5):
            try:
                r=requests.get(url,headers={'Range':f'bytes={start}-{end}'},timeout=(30,90))
                r.raise_for_status()
                if r.status_code!=206 or len(r.content)!=expected or r.headers.get('Content-Range')!=f'bytes {start}-{end}/{total}':
                    raise RuntimeError('Unexpected partial response')
                path.write_bytes(r.content)
                print(f'SEGMENT {target.name} {end/total:.0%}',flush=True)
                return path
            except Exception as exc:
                print(f'SEGMENT RETRY {target.name} {start}: {exc}',flush=True)
                if attempt==4:
                    raise
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as executor:
        pieces=list(executor.map(segment,ranges))
    with partial.open('ab') as stream:
        for piece in pieces:
            stream.write(piece.read_bytes())
    if partial.stat().st_size!=total:
        raise RuntimeError('Download size mismatch')
    partial.replace(target)
    digest=hashlib.file_digest(target.open('rb'),'sha256').hexdigest()
    if target.name in EXPECTED_SHA256 and digest!=EXPECTED_SHA256[target.name]:
        raise RuntimeError(f'Official model checksum mismatch: {target.name}')
    return {'url':url,'path':str(target),'bytes':total,'sha256':digest}

if __name__=='__main__':
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        results=list(executor.map(download,ASSETS))
    for result in results:
        name=Path(result['path']).name
        if result['sha256']!=EXPECTED_SHA256[name]:
            raise RuntimeError(f'Official release checksum mismatch: {name}')
    out=ROOT/'.tools/llama-b11829'
    out.mkdir(parents=True,exist_ok=True)
    for _,path in ASSETS[:2]:
        with zipfile.ZipFile(path) as archive:
            for name in archive.namelist():
                resolved=(out/name).resolve()
                if not resolved.is_relative_to(out.resolve()):
                    raise ValueError(f'Unsafe ZIP path: {name}')
            archive.extractall(out)
    (ROOT/'.tools/ocr-runtime-manifest.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
    print(json.dumps(results,indent=2),flush=True)
