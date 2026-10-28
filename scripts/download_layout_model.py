"""Fetch the official PP-DocLayoutV3 files into the ASCII PaddleX cache."""
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path

import requests
from download_ocr_runtime import segmented_download

REVISION='241f8bdfc77a7c7bee915a5057aaee58c235a8d3'
REPO='PaddlePaddle/PP-DocLayoutV3'
DEST=Path(os.environ['LOCALAPPDATA'])/'TextbookWorkbook/models/paddlex/official_models/PP-DocLayoutV3'

def main():
    metadata=requests.get(f'https://huggingface.co/api/models/{REPO}/tree/{REVISION}',timeout=30)
    metadata.raise_for_status()
    DEST.mkdir(parents=True,exist_ok=True)
    def one(item):
        target=DEST/item['path']
        url=f"https://huggingface.co/{REPO}/resolve/{REVISION}/{item['path']}"
        if not target.exists() or target.stat().st_size!=item['size']:
            if item['size']>8*1024*1024:
                segmented_download(url,target,target.with_suffix(target.suffix+'.partial'))
            else:
                result=requests.get(url,timeout=60)
                result.raise_for_status()
                target.write_bytes(result.content)
        if target.stat().st_size!=item['size']:
            raise RuntimeError(f'Size mismatch: {target}')
        with target.open('rb') as stream:
            digest=hashlib.file_digest(stream,'sha256').hexdigest()
        if item.get('lfs') and digest!=item['lfs']['oid']:
            raise RuntimeError(f'Official checksum mismatch: {target}')
        return {'file':item['path'],'size':item['size'],'sha256':digest}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        values=list(pool.map(one,metadata.json()))
    (DEST/'download-manifest.json').write_text(json.dumps({'repository':REPO,'revision':REVISION,'files':values},indent=2),encoding='utf-8')
    print('PP-DocLayoutV3 download verified',flush=True)

if __name__=='__main__':
    main()
