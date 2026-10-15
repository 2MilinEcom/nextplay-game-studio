import argparse
import hmac
import importlib.util
import json
import mimetypes
import os
import re
import secrets
import shutil
import socket
import threading
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse, parse_qs
from .core import Store, VIDEO_EXTENSIONS, binary, ident, safe_error
from .worker import Engine

STATIC = Path(__file__).resolve().parent / 'static'


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, store, engine):
        self.store, self.engine = store, engine
        from live.manager import Manager
        self.player = Manager(STATIC.parent.parent, store.data)
        self.token = secrets.token_urlsafe(32)
        super().__init__(address, Handler)


class Handler(BaseHTTPRequestHandler):
    server_version = 'NextPlay/1.0'
    protocol_version = 'HTTP/1.0'

    def log_message(self, format, *args):
        # Do not log cookies, uploaded names, images, request bodies, or secrets.
        return

    def headers_for(self, kind, length=None, attachment=None):
        self.send_header('Content-Type', kind)
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; media-src 'self' blob:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'self'")
        self.send_header('Permissions-Policy', 'camera=(), microphone=(), display-capture=(self)')
        if length is not None:
            self.send_header('Content-Length', str(length))
        if attachment:
            self.send_header('Content-Disposition', f'attachment; filename="{attachment}"')

    def json(self, value, status=200, cookie=False):
        data = json.dumps(value, ensure_ascii=False).encode()
        self.send_response(status)
        self.headers_for('application/json; charset=utf-8', len(data))
        if cookie:
            self.send_header('Set-Cookie', f'nextplay={self.server.token}; HttpOnly; SameSite=Strict; Path=/')
        self.end_headers()
        self.wfile.write(data)

    def guard(self, mutation=False, public=False):
        port = self.server.server_address[1]
        hosts = {f'127.0.0.1:{port}', f'localhost:{port}'}
        if self.headers.get('Host') not in hosts:
            raise PermissionError('Use the local NextPlay address.')
        origin = self.headers.get('Origin')
        if origin and origin not in {f'http://{h}' for h in hosts}:
            raise PermissionError('Requests must originate from NextPlay on this Mac.')
        if self.headers.get('Sec-Fetch-Site') == 'cross-site':
            raise PermissionError('Cross-site requests are not allowed.')
        if public:
            return
        header = self.headers.get('X-NextPlay-Token', '')
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get('Cookie', ''))
            value = cookie['nextplay'].value if 'nextplay' in cookie else ''
        except Exception:
            value = ''
        supplied = header if mutation else (header or value)
        if not hmac.compare_digest(supplied, self.server.token):
            raise PermissionError('Reload NextPlay to reconnect your local session.')

    def payload(self, maximum=1024 * 1024):
        size = int(self.headers.get('Content-Length', '0'))
        if not 0 <= size <= maximum:
            raise ValueError('Request exceeds the allowed size.')
        body = self.rfile.read(size)
        if len(body) != size:
            raise ValueError('Incomplete request body.')
        return json.loads(body or b'{}')

    def file(self, path, kind=None, attachment=None, ranges=False):
        path = Path(path)
        if not path.is_file() or path.is_symlink():
            return self.json({'error': 'File not found.'}, 404)
        size = path.stat().st_size
        start, end, status = 0, size - 1, 200
        header = self.headers.get('Range') if ranges else None
        if header:
            match = re.fullmatch(r'bytes=(\d*)-(\d*)', header)
            if not match or not any(match.groups()):
                return self.json({'error': 'Invalid byte range.'}, 416)
            if not match[1]:
                start = max(0, size - int(match[2]))
            else:
                start = int(match[1])
                end = min(size - 1, int(match[2])) if match[2] else size - 1
            if start > end or start >= size:
                return self.json({'error': 'Byte range unavailable.'}, 416)
            status = 206
        self.send_response(status)
        self.headers_for(kind or mimetypes.guess_type(path)[0] or 'application/octet-stream', end - start + 1, attachment)
        if ranges:
            self.send_header('Accept-Ranges', 'bytes')
        if status == 206:
            self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
        self.end_headers()
        with path.open('rb') as source:
            source.seek(start)
            left = end - start + 1
            while left > 0:
                chunk = source.read(min(left, 1024 * 256))
                if not chunk:
                    break
                self.wfile.write(chunk)
                left -= len(chunk)

    def do_GET(self):
        try:
            path = unquote(urlparse(self.path).path)
            public = path in ['/', '/index.html', '/app.js', '/style.css', '/api/bootstrap', '/health']
            self.guard(public=public)
            if path == '/health':
                return self.json({'ok': True, 'app': 'NextPlay Studio'})
            if path == '/api/bootstrap':
                return self.json({'token': self.server.token, 'app': 'NextPlay Studio'}, cookie=True)
            if path in ['/', '/index.html', '/app.js', '/style.css']:
                return self.file(STATIC / ('index.html' if path == '/' else path[1:]))
            store = self.server.store
            if path == '/api/player/status':
                return self.json(self.server.player.status())
            if path == '/api/status':
                tools = {}
                for name in ['ffmpeg', 'ffprobe']:
                    try:
                        binary(name)
                        tools[name] = True
                    except ValueError:
                        tools[name] = False
                return self.json({'key_available': bool(os.environ.get('OPENAI_API_KEY')),
                                  'openai_available': bool(importlib.util.find_spec('openai')),
                                  'tools': tools, 'settings': store.settings,
                                  'inbox': str(store.inbox), 'watch_error': store.meta('watch_error'),
                                  'queue_length': self.server.engine.queue.qsize(), 'api': store.api_summary()})
            if path == '/api/jobs':
                return self.json({'jobs': store.jobs()})
            match = re.fullmatch(r'/api/jobs/([a-f0-9]{32})', path)
            if match:
                job = store.get_job(match[1])
                return self.json(job or {'error': 'Review not found.'}, 200 if job else 404)
            match = re.fullmatch(r'/frames/([a-f0-9]{32})/(f\d{4}(?:-overlay)?)\.jpg', path)
            if match:
                job = store.get_job(match[1])
                if not job or job['state'] == 'deleted':
                    return self.json({'error': 'Review not found.'}, 404)
                return self.file(store.data / 'frames' / match[1] / (match[2] + '.jpg'), 'image/jpeg')
            match = re.fullmatch(r'/media/([a-f0-9]{32})', path)
            if match:
                job = store.get_job(match[1], private=True)
                if not job or job['state'] == 'deleted' or job['kind'] != 'video':
                    return self.json({'error': 'Recording unavailable.'}, 404)
                source = Path(job['source'])
                if source.parent != store.data / 'uploads':
                    raise PermissionError('Recording outside local storage.')
                preview = store.data / 'frames' / match[1] / 'preview.mp4'
                return self.file(preview if preview.exists() else source, ranges=True)
            if path == '/reports/api-review.md':
                return self.file(store.project / 'nextplay-clash-ai-review.md', attachment='nextplay-api-review.md')
            match = re.fullmatch(r'/reports/([a-f0-9]{32})\.(json|md)', path)
            if match:
                job = store.get_job(match[1])
                if not job or job['state'] == 'deleted':
                    return self.json({'error': 'Review not found.'}, 404)
                return self.file(store.data / 'reports' / (match[1] + '.' + match[2]), attachment='nextplay-review.' + match[2])
            return self.json({'error': 'Not found.'}, 404)
        except PermissionError as exc:
            self.json({'error': str(exc)}, 403)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as exc:
            self.json({'error': safe_error(exc)}, 400)

    def do_POST(self):
        upload_temp = None
        try:
            self.guard(mutation=True)
            path = urlparse(self.path).path
            store, engine = self.server.store, self.server.engine
            if path == '/api/uploads':
                name = Path(unquote(self.headers.get('X-File-Name', 'recording.mp4'))).name[:200]
                suffix = Path(name).suffix.lower()
                if suffix not in VIDEO_EXTENSIONS:
                    raise ValueError('Choose an MP4, MOV, M4V, WebM, or MKV recording.')
                size = int(self.headers.get('Content-Length', '0'))
                maximum = store.settings['max_upload_mb'] * 1024 * 1024
                if not 0 < size <= maximum:
                    raise ValueError(f'Recording must be under {store.settings["max_upload_mb"]} MB and cannot be empty.')
                if shutil.disk_usage(store.data).free < size + 1024 * 1024 * 1024:
                    raise ValueError('Not enough free disk space to safely review this recording.')
                upload_temp = store.data / 'uploads' / (ident() + '.upload' + suffix)
                self.connection.settimeout(180)
                with upload_temp.open('wb') as target:
                    left = size
                    while left:
                        chunk = self.rfile.read(min(left, 1024 * 1024))
                        if not chunk:
                            raise ValueError('Upload interrupted. Retry your recording.')
                        target.write(chunk)
                        left -= len(chunk)
                job, duplicate = engine.ingest(upload_temp, name, self.headers.get('X-Battle-Time'),
                                                self.headers.get('X-NextPlay-Demo') == 'true', owned=True)
                return self.json({'job': job, 'duplicate': duplicate}, 202)
            if path == '/api/player/start':
                data = self.payload()
                return self.json(self.server.player.start(control=data.get('control') is True))
            if path == '/api/player/stop':
                self.payload()
                return self.json(self.server.player.stop())
            if path == '/api/settings':
                return self.json({'settings': store.save_settings(self.payload())})
            if path == '/api/refresh':
                self.payload()
                return self.json(engine.request_api(), 202)
            if path == '/api/live/start':
                data = self.payload()
                return self.json({'job': engine.begin_live(data.get('battle_time'), demo=data.get('demo') is True)}, 201)
            match = re.fullmatch(r'/api/live/([a-f0-9]{32})/(frame|stop)', path)
            if match:
                if match[2] == 'stop':
                    self.payload()
                    engine.end_live(match[1])
                    return self.json({'stopped': True})
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 4 * 1024 * 1024:
                    raise ValueError('Invalid screenshot size.')
                timestamp = float(self.headers.get('X-Sample-Time', 'nan'))
                return self.json(engine.push_live(match[1], self.rfile.read(size), timestamp))
            match = re.fullmatch(r'/api/jobs/([a-f0-9]{32})/(retry|cancel|notes|delete)', path)
            if match:
                job_id, action = match.groups()
                data = self.payload()
                if action == 'retry':
                    engine.retry(job_id)
                elif action == 'cancel':
                    engine.cancel(job_id)
                elif action == 'notes':
                    if not isinstance(data.get('text'), str):
                        raise ValueError('Notes must be text.')
                    store.note(job_id, data['text'])
                elif action == 'delete':
                    job = store.get_job(job_id, private=True)
                    if not job:
                        raise ValueError('Review not found.')
                    if job['state'] in ['processing', 'monitoring', 'queued']:
                        raise ValueError('Stop or cancel the review before deleting it.')
                    source = Path(job['source']) if job['source'] else None
                    if source and source.parent == store.data / 'uploads':
                        source.unlink(missing_ok=True)
                    shutil.rmtree(store.data / 'frames' / job_id, ignore_errors=True)
                    for ext in ['json', 'md']:
                        (store.data / 'reports' / (job_id + '.' + ext)).unlink(missing_ok=True)
                    store.update(job_id, state='deleted', result={}, context={}, source='', message='Local review deleted.')
                    store.note(job_id, '')
                return self.json({'ok': True, 'job': store.get_job(job_id)})
            self.json({'error': 'Not found.'}, 404)
        except PermissionError as exc:
            self.json({'error': str(exc)}, 403)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as exc:
            self.json({'error': safe_error(exc)}, 400)
        finally:
            if upload_temp:
                upload_temp.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description='NextPlay Studio — local recording and periodic screen coach')
    parser.add_argument('--project', type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument('--data', type=Path)
    parser.add_argument('--port', type=int, default=8777)
    args = parser.parse_args()
    os.umask(0o077)
    store = Store(args.project, args.data)
    engine = Engine(store)
    server = Server(('127.0.0.1', args.port), store, engine)
    print(f'NextPlay Studio ready at http://127.0.0.1:{args.port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        engine.stop.set()
        server.server_close()


if __name__ == '__main__':
    main()
