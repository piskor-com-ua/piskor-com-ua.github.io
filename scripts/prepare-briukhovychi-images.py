"""Extract selected original renders, never PDF sheets, for the portfolio."""
import argparse
import subprocess
import tempfile
from pathlib import Path
from PIL import Image

parser = argparse.ArgumentParser()
parser.add_argument('pdf', type=Path)
args = parser.parse_args()
selection = {
    'living': (7, 0), 'living-detail': (7, 3),
    'kitchen': (10, 1), 'terrace': (64, 4),
    'bedroom': (18, 0), 'study': (22, 0),
    'stairs': (58, 0), 'entrance': (2, 0),
    'perimeter': (64, 2), 'garden': (64, 5), 'gate': (64, 0),
}
out = Path('concept/assets/portfolio/briukhovychi-house')
out.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory(prefix='piskor-renders-') as temp:
    for page in sorted({p for p, _ in selection.values()}):
        subprocess.run(['pdfimages', '-f', str(page), '-l', str(page), '-j',
                        str(args.pdf), f'{temp}/page-{page}'], check=True)
    for name, (page, index) in selection.items():
        sources = list(Path(temp).glob(f'page-{page}-{index:03d}.*'))
        assert len(sources) == 1, sources
        with Image.open(sources[0]) as source:
            original = source.convert('RGB')
            for bound in (640, 1440, 2200):
                image = original.copy()
                image.thumbnail((bound, bound * 2), Image.Resampling.LANCZOS)
                image.save(out / f'{name}-{bound}.webp', quality=86, method=6)
            print(name, original.size)
