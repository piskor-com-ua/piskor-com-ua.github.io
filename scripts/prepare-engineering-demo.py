"""Encode reviewed generated demo masters without changing their composition."""
import argparse
import hashlib
import json
from pathlib import Path
from PIL import Image

parser = argparse.ArgumentParser()
parser.add_argument('--source', type=Path, default=Path('output/imagegen/engineering-demo'))
parser.add_argument('--destination', type=Path, default=Path('concept/assets/engineering-demo'))
args = parser.parse_args()
names = ('living-day', 'living-evening', 'living-curtains-closed', 'living-door-open',
         'heating-detail', 'gate-closed', 'gate-open')
args.destination.mkdir(parents=True, exist_ok=True)
report = []
for name in names:
    source = args.source / (name + '.png')
    with Image.open(source) as image:
        if image.size != (1536, 1024):
            raise ValueError('Unexpected demo canvas: ' + str(source))
        image = image.convert('RGB')
        for width in (640, 1440, 1536):
            size = (width, round(width * image.height / image.width))
            rendition = image if image.size == size else image.resize(size, Image.Resampling.LANCZOS)
            target = args.destination / (name + '-' + str(width) + '.webp')
            rendition.save(target, 'WEBP', quality=86, method=6)
            report.append({'file': str(target), 'size': size, 'bytes': target.stat().st_size,
                           'master_sha256': hashlib.sha256(source.read_bytes()).hexdigest()})
(args.source / 'responsive-assets.json').write_text(json.dumps(report, indent=2) + '\n')
print('Prepared', len(report), 'responsive demo assets; no cropping or upscaling')
