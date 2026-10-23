import gzip
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen


class PreviewRangeTest(unittest.TestCase):
    def test_video_ranges_head_and_compressed_html(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / '.nojekyll').touch()
            payload = bytes(range(256)) * 100
            (root / 'sample.mp4').write_bytes(payload)
            html = b'<html>Local preview</html>'
            (root / 'index.html').write_bytes(html)
            with socket.socket() as reserved:
                reserved.bind(('127.0.0.1', 0))
                port = reserved.getsockname()[1]
            server = subprocess.Popen([sys.executable, str(Path(__file__).with_name('serve-benchmark.py')),
                                       folder, '--port', str(port)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                origin = f'http://127.0.0.1:{port}'
                for attempt in range(100):
                    try:
                        with urlopen(origin, timeout=1):
                            break
                    except OSError:
                        if attempt == 99:
                            raise
                        time.sleep(.02)
                for byte_range, start, end in [('bytes=20-39', 20, 39), ('bytes=25590-', 25590, 25599),
                                               ('bytes=-10', 25590, 25599), ('bytes=25590-99999', 25590, 25599)]:
                    with urlopen(Request(origin + '/sample.mp4', headers={'Range': byte_range}), timeout=2) as response:
                        self.assertEqual(response.status, 206)
                        self.assertEqual(response.headers['Content-Range'], f'bytes {start}-{end}/{len(payload)}')
                        self.assertEqual(response.read(), payload[start:end + 1])
                with urlopen(Request(origin + '/sample.mp4', method='HEAD'), timeout=2) as response:
                    self.assertEqual(response.headers['Accept-Ranges'], 'bytes')
                    self.assertEqual(int(response.headers['Content-Length']), len(payload))
                    self.assertEqual(response.read(), b'')
                for byte_range in ('bytes=30000-', 'bytes=99-20', 'bytes=-0', 'bytes=0-1,4-5', 'invalid'):
                    with self.assertRaises(HTTPError) as caught:
                        urlopen(Request(origin + '/sample.mp4', headers={'Range': byte_range}), timeout=2)
                    self.assertEqual(caught.exception.code, 416)
                    caught.exception.close()
                with urlopen(Request(origin, headers={'Accept-Encoding': 'gzip'}), timeout=2) as response:
                    self.assertEqual(response.headers['Content-Encoding'], 'gzip')
                    self.assertEqual(gzip.decompress(response.read()), html)
            finally:
                server.terminate()
                server.wait(timeout=5)
