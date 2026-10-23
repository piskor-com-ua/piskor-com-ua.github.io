"""Serve an artifact with text compression for repeatable Lighthouse comparisons."""
import argparse
import gzip
import re
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('artifact', type=Path)
parser.add_argument('--port', type=int, default=4173)
parser.add_argument('--compression', choices=('gzip', 'brotli'), default='gzip')
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
        self.range_remaining = None
        path = Path(self.translate_path(self.path))
        if path.is_dir():
            path = path / 'index.html'
        # Native video seeking uses single byte ranges, including on localhost.
        # Keep this out of the compressed text branch: Content-Range describes
        # the original MP4 bytes, not a compressed representation.
        if path.is_file() and path.suffix.lower() in {'.mp4', '.webm', '.mov'}:
            length = path.stat().st_size
            requested = self.headers.get('Range')
            start, end = 0, length - 1
            if requested:
                match = re.fullmatch(r'bytes=(\d*)-(\d*)', requested)
                if match and any(match.groups()):
                    first, last = match.groups()
                    if first:
                        start = int(first)
                        end = min(int(last), length - 1) if last else length - 1
                    else:
                        start = max(0, length - int(last))
                else:
                    start = length
                if start > end or start >= length:
                    self.send_response(416)
                    self.send_header('Content-Range', f'bytes */{length}')
                    self.send_header('Content-Length', '0')
                    self.end_headers()
                    return None
            source = path.open('rb')
            source.seek(start)
            self.range_remaining = end - start + 1
            self.send_response(206 if requested else 200)
            self.send_header('Content-Type', self.guess_type(str(path)))
            self.send_header('Accept-Ranges', 'bytes')
            self.send_header('Content-Length', str(self.range_remaining))
            if requested:
                self.send_header('Content-Range', f'bytes {start}-{end}/{length}')
            self.end_headers()
            return source
        accepted = self.headers.get('Accept-Encoding', '')
        supported = 'gzip' in accepted or args.compression == 'brotli' and 'br' in accepted
        if path.is_file() and path.suffix in {'.html', '.css', '.js', '.json', '.svg', '.txt', '.xml'} and supported:
            if args.compression == 'brotli' and 'br' in accepted:
                import brotli
                payload = brotli.compress(path.read_bytes(), quality=4)
                encoding = 'br'
            else:
                payload = gzip.compress(path.read_bytes(), mtime=0)
                encoding = 'gzip'
            self.send_response(200)
            self.send_header('Content-Type', self.guess_type(str(path)))
            self.send_header('Content-Encoding', encoding)
            self.send_header('Vary', 'Accept-Encoding')
            self.send_header('Content-Length', str(len(payload)))
            self.send_header('Cache-Control', 'max-age=0')
            self.end_headers()
            return BytesIO(payload)
        return super().send_head()

    def copyfile(self, source, destination):
        if self.range_remaining is None:
            return super().copyfile(source, destination)
        remaining = self.range_remaining
        while remaining:
            chunk = source.read(min(65536, remaining))
            if not chunk:
                break
            destination.write(chunk)
            remaining -= len(chunk)

    def log_message(self, *_):
        pass


ThreadingHTTPServer(('127.0.0.1', args.port), Preview).serve_forever()
