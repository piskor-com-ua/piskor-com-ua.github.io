"""Serve an artifact with text compression for repeatable Lighthouse comparisons."""
import argparse
import gzip
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('artifact', type=Path)
parser.add_argument('--port', type=int, default=4173)
args = parser.parse_args()
if not (args.artifact / '.nojekyll').is_file():
    parser.error('Serve a built Pages artifact, not source files')


class Preview(SimpleHTTPRequestHandler):
    # Match normal persistent connections; HTTP/1.0 otherwise adds a fresh
    # connection to every resource in Lighthouse's network simulation.
    protocol_version = 'HTTP/1.1'

    def __init__(self, *request_args, **kwargs):
        super().__init__(*request_args, directory=str(args.artifact), **kwargs)

    def send_head(self):
        path = Path(self.translate_path(self.path))
        if path.is_dir():
            path = path / 'index.html'
        if path.is_file() and path.suffix in {'.html', '.css', '.js', '.json', '.svg', '.txt', '.xml'} and 'gzip' in self.headers.get('Accept-Encoding', ''):
            payload = gzip.compress(path.read_bytes(), mtime=0)
            self.send_response(200)
            self.send_header('Content-Type', self.guess_type(str(path)))
            self.send_header('Content-Encoding', 'gzip')
            self.send_header('Vary', 'Accept-Encoding')
            self.send_header('Content-Length', str(len(payload)))
            self.send_header('Cache-Control', 'max-age=0')
            self.end_headers()
            return BytesIO(payload)
        return super().send_head()

    def log_message(self, *_):
        pass


ThreadingHTTPServer(('127.0.0.1', args.port), Preview).serve_forever()
