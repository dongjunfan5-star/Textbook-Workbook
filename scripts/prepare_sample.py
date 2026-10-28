"""Render selected source pages without changing the source PDFs."""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def main():
    import fitz
    parser = argparse.ArgumentParser()
    parser.add_argument('--manifest', default='config/sample-pages.json')
    parser.add_argument('--width', type=int, default=1800)
    args = parser.parse_args()
    manifest = json.loads((ROOT / args.manifest).read_text(encoding='utf-8'))
    inventory = []
    for item in manifest['items']:
        project = ROOT / item['project']
        source = project / item['source_file']
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        source_id = digest[:12]
        image_dir = project / 'data/page_images' / source_id
        image_dir.mkdir(parents=True, exist_ok=True)
        with fitz.open(source) as doc:
            for number in item['pages']:
                page = doc[number-1]
                path = image_dir / f'p{number:04d}.png'
                page.get_pixmap(matrix=fitz.Matrix(args.width/page.rect.width,args.width/page.rect.width), alpha=False).save(path)
                # Text layer helps audit; OCR remains the selected extraction route.
                (image_dir / f'p{number:04d}.txt').write_text(page.get_text(), encoding='utf-8')
                inventory.append({**{k:v for k,v in item.items() if k!='pages'}, 'source_sha256':digest,'source_id':source_id,'page_number':number,'image':path.relative_to(ROOT).as_posix()})
        print(item['project'], source.name, item['pages'], flush=True)
    destination = ROOT / 'config/sample-inventory.json'
    destination.write_text(json.dumps(inventory,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(f'Rendered {len(inventory)} source pages')

if __name__ == '__main__':
    main()
