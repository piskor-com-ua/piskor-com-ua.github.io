"""Compare complete public artifacts; ignore only the closing body/html newline."""
from pathlib import Path
import argparse

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('baseline', type=Path)
parser.add_argument('candidate', type=Path)
args = parser.parse_args()

def artifact(root):
    assert root.is_dir(), f'Missing artifact: {root}'
    result = {}
    for path in root.rglob('*'):
        if path.is_file():
            data = path.read_bytes()
            if path.suffix == '.html':
                data = data.replace(b'</body>\n</html>', b'</body></html>')
            result[str(path.relative_to(root))] = data
    assert result, f'Empty artifact: {root}'
    return result

before, after = artifact(args.baseline), artifact(args.candidate)
assert before.keys() == after.keys(), f'Changed routes/assets: {before.keys() ^ after.keys()}'
changed = [name for name in before if before[name] != after[name]]
assert not changed, f'Changed public content: {changed}'
print(f'Parity verified: {len(before)} files; only closing HTML whitespace is normalized')
