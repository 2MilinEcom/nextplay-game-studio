import base64
import json
import math
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from .core import VIDEO_EXTENSIONS, hash_file, ident, now, safe_error, write_json
from .video import extract, normalize_jpeg, browser_preview
from .coach import Model, observe, make_coaching, finish_report


class Cancelled(Exception):
    pass


class Engine:
    def __init__(self, store, model_factory=Model, start=True):
        self.store = store
        self.model_factory = model_factory
        self.queue = queue.Queue()
        self.live_queue = queue.Queue()
        self.stop = threading.Event()
        self.live = {}
        self.live_lock = threading.RLock()
        self.api_lock = threading.Lock()
        self.watch_stable = {}
        if start:
            for job in store.jobs():
                if job['state'] == 'queued':
                    self.queue.put(('video', job['id']))
            threading.Thread(target=self.work, daemon=True, name='nextplay-review').start()
            threading.Thread(target=self.work, args=(self.live_queue,), daemon=True, name='nextplay-screen').start()
            threading.Thread(target=self.watch, daemon=True, name='nextplay-inbox').start()
            if store.settings['api_auto_refresh']:
                self.request_api()

    def check(self, job_id):
        job = self.store.get_job(job_id)
        if not job or job['cancelled'] or job['state'] in ['deleted', 'cancelled']:
            raise Cancelled()

    def ingest(self, path, name=None, battle_time=None, demo=False, owned=False):
        path = Path(path)
        if path.suffix.lower() not in VIDEO_EXTENSIONS:
            raise ValueError('Supported recordings: MP4, MOV, M4V, WebM, MKV.')
        if path.is_symlink() or not path.is_file():
            raise ValueError('Recording must be a regular file.')
        if path.stat().st_size > self.store.settings['max_upload_mb'] * 1024 * 1024:
            raise ValueError('Recording exceeds the configured upload size limit.')
        if shutil.disk_usage(self.store.data).free < path.stat().st_size + 1024 * 1024 * 1024:
            raise ValueError('Not enough free disk space to review this recording.')
        context = self.store.context(battle_time)
        if len([j for j in self.store.jobs() if j['state'] in ['queued', 'processing']]) >= 10:
            raise ValueError('Review queue is full. Wait for current reviews to finish.')
        digest = hash_file(path)
        duplicate = self.store.duplicate(digest)
        if duplicate:
            if owned:
                path.unlink(missing_ok=True)
            return duplicate, True
        target = self.store.data / 'uploads' / (ident() + path.suffix.lower())
        if owned:
            path.replace(target)
        else:
            shutil.copyfile(path, target)
        target.chmod(0o600)
        demo = demo or (name or path.name).startswith('NEXTPLAY_SYSTEM_TEST_')
        job = self.store.create_job('video', name or path.name, target, digest, context, demo)
        self.queue.put(('video', job['id']))
        return job, False

    def retry(self, job_id):
        job = self.store.get_job(job_id, private=True)
        if not job or job['state'] not in ['failed', 'interrupted', 'cancelled']:
            raise ValueError('Only failed, interrupted, or cancelled reviews can be retried.')
        if job['kind'] != 'video' or not Path(job['source']).is_file():
            raise ValueError('Live sessions cannot resume after restart. Start a new screen session.')
        self.store.update(job_id, state='queued', cancelled=0, error='', progress=0, message='Queued for retry.')
        self.queue.put(('video', job_id))

    def cancel(self, job_id):
        job = self.store.get_job(job_id)
        if not job:
            raise ValueError('Review not found.')
        if job['kind'] == 'live':
            self.end_live(job_id)
        else:
            self.store.update(job_id, cancelled=1, state='cancelled', message='Cancelled. Any current request may finish; no further calls will be made.')

    def work(self, work_queue=None):
        work_queue = work_queue or self.queue
        while not self.stop.is_set():
            try:
                kind, payload = work_queue.get(timeout=1)
            except queue.Empty:
                continue
            try:
                if kind == 'video':
                    self.review_video(payload)
                elif kind == 'live':
                    self.review_live(payload)
                elif kind == 'api':
                    self.refresh_api(payload)
            except Cancelled:
                job_id = payload if isinstance(payload, str) else payload[0]
                if kind != 'api' and self.store.get_job(job_id)['state'] != 'deleted':
                    self.store.update(job_id, state='cancelled', message='Cancelled; no report published.')
            except Exception as exc:
                message = safe_error(exc)
                if kind == 'api':
                    self.store.meta('api_refresh', {'state': 'failed', 'error': message, 'time': now()})
                else:
                    job_id = payload if isinstance(payload, str) else payload[0]
                    if self.store.get_job(job_id)['state'] != 'deleted':
                        self.store.update(job_id, state='failed', error=message, message='Review needs attention.')
                    with self.live_lock:
                        if job_id in self.live:
                            self.live[job_id]['closed'] = True
            finally:
                work_queue.task_done()

    def review_video(self, job_id):
        self.check(job_id)
        job = self.store.get_job(job_id, private=True)
        if job['state'] not in ['queued', 'processing']:
            return
        settings = dict(self.store.settings)
        if settings['processing_mode'] == 'local':
            from .local import scan
            self.store.update(job_id, state='processing', progress=1, message='Starting local recording scan.')
            report = scan(self.store, job, settings, lambda: self.check(job_id),
                          lambda pct, msg: self.store.update(job_id, progress=pct, message=msg))
            self.check(job_id)
            self.store.update(job_id, state='completed', progress=100, message='Local review ready — no API calls.', result=report)
            return
        self.store.update(job_id, state='processing', progress=3, message='Reading the recording and sampling frames.')
        info, frames = extract(job['source'], self.store.data / 'frames' / job_id, settings,
                               lambda: self.check(job_id),
                               lambda pct: self.store.update(job_id, progress=3 + round(pct * .22)))
        self.check(job_id)
        self.store.update(job_id, progress=25, message='Preparing local video playback.')
        browser_preview(job['source'], self.store.data / 'frames' / job_id, info)
        self.check(job_id)
        model = self.model_factory()
        observations, unknowns, withheld, qualities = [], [], [], []
        batches = [frames[i:i + settings['batch_size']] for i in range(0, len(frames), settings['batch_size'])]
        for i, batch in enumerate(batches):
            self.check(job_id)
            self.store.update(job_id, progress=25 + round(i / len(batches) * 60),
                              message=f'Checking screenshot evidence, group {i + 1} of {len(batches)}.')
            result = observe(batch, model, settings, f'b{i:02d}')
            self.check(job_id)
            observations.extend(result['observations'])
            withheld.extend(result['withheld'])
            unknowns.extend(result['unknowns'])
            qualities.append(result['quality'])
        self.store.update(job_id, progress=90, message='Turning accepted evidence into a measurable practice plan.')
        self.check(job_id)
        coaching = make_coaching(observations, model, settings, job['context'])
        self.check(job_id)
        info['qualities'] = qualities
        report = finish_report(self.store, job, frames, info, observations, unknowns, withheld, coaching, model, settings)
        self.store.update(job_id, state='completed', progress=100, message='Review ready.', result=report)

    def begin_live(self, battle_time=None, demo=False):
        if self.store.settings['processing_mode'] == 'local':
            raise ValueError('Local mode currently supports recordings. Upload your Clash Royale recording; paid screen analysis is disabled.')
        with self.live_lock:
            active = [x for x in self.live.values() if not x['closed']]
            if active:
                raise ValueError('A screen session is already running. Stop it before starting another.')
            job = self.store.create_job('live', ('System screen test · ' if demo else 'Screen session · ') + now()[:16], context=self.store.context(battle_time), demo=demo)
            settings = dict(self.store.settings)
            self.live[job['id']] = {'frames': [], 'pending': [], 'checks': 0, 'closed': False,
                                    'busy': False, 'last_at': 0, 'started': time.monotonic(), 'last_received': time.monotonic(),
                                    'observations': [], 'unknowns': [], 'withheld': [], 'model': self.model_factory(), 'settings': settings}
            self.store.update(job['id'], state='monitoring', message='Sharing selected window. Waiting for screenshot samples.')
            return self.store.get_job(job['id'])

    def push_live(self, job_id, data, timestamp):
        if not isinstance(timestamp, (int, float)) or not math.isfinite(timestamp) or timestamp < 0 or timestamp > 7200:
            raise ValueError('Invalid screen sample time.')
        with self.live_lock:
            session = self.live.get(job_id)
            if not session or session['closed']:
                raise ValueError('This screen session has stopped.')
            settings = session['settings']
            session['last_received'] = time.monotonic()
            if session['busy']:
                return {'accepted': False, 'reason': 'Current batch is still being checked.', 'checks': session['checks']}
            count = len(session['frames'])
            if count and timestamp < session['last_at'] + settings['live_interval'] * .75:
                return {'accepted': False, 'reason': 'Sampling interval has not elapsed.'}
            if len(data) > 4 * 1024 * 1024 or not data.startswith(b'\xff\xd8'):
                raise ValueError('Expected a JPEG screenshot under 4 MB.')
            directory = self.store.data / 'frames' / job_id
            directory.mkdir(exist_ok=True, mode=0o700)
            frame_id = f'f{count:04d}'
            raw = directory / f'{frame_id}.incoming.jpg'
            target = directory / f'{frame_id}.jpg'
            raw.write_bytes(data)
            try:
                normalize_jpeg(raw, target)
            finally:
                raw.unlink(missing_ok=True)
            frame = {'id': frame_id, 'time_seconds': round(timestamp, 3), 'path': str(target), 'sha256': hash_file(target)}
            session['frames'].append(frame)
            session['pending'].append(frame)
            session['last_at'] = timestamp
            session['last_received'] = time.monotonic()
            self.store.update(job_id, message=f"Saved {len(session['frames'])} screen samples; {session['checks']} checks completed.")
            if len(session['pending']) >= settings['live_batch_frames']:
                self.enqueue_live(job_id, session)
            return {'accepted': True, 'frame_id': frame_id, 'checks': session['checks'], 'limit': settings['live_max_checks']}

    def enqueue_live(self, job_id, session):
        if session['busy'] or not session['pending']:
            return
        if session['checks'] >= session['settings']['live_max_checks']:
            session['closed'] = True
            return
        batch = list(session['pending'])
        session['pending'].clear()
        session['busy'] = True
        self.live_queue.put(('live', (job_id, batch)))

    def end_live(self, job_id):
        with self.live_lock:
            session = self.live.get(job_id)
            if not session:
                raise ValueError('Screen session not found.')
            session['closed'] = True
            if not session['busy'] and session['pending']:
                self.enqueue_live(job_id, session)
            elif not session['busy']:
                if not session['frames']:
                    self.store.update(job_id, state='cancelled', progress=0, message='Screen session stopped before any screenshots were captured.')
                else:
                    self.store.update(job_id, state='completed', progress=100, message='Screen sharing stopped. Saved observations remain available.')
            else:
                self.store.update(job_id, message='Screen sharing stopped. Finishing the accepted screenshot batch.')

    def review_live(self, payload):
        job_id, frames = payload
        with self.live_lock:
            session = self.live.get(job_id)
        if not session:
            return
        job = self.store.get_job(job_id, private=True)
        if job['state'] == 'deleted':
            return
        model, settings = session['model'], session['settings']
        result = observe(frames, model, settings, f"check{session['checks']:03d}")
        session['observations'].extend(result['observations'])
        session['unknowns'].extend(result['unknowns'])
        session['withheld'].extend(result['withheld'])
        coaching = make_coaching(session['observations'][-16:], model, settings, job['context'])
        with self.live_lock:
            session['checks'] += 1
            session['busy'] = False
            if session['checks'] >= settings['live_max_checks']:
                session['closed'] = True
            info = {'duration_seconds': frames[-1]['time_seconds'], 'sampled_frames': len(session['frames']),
                    'sampling_gap_seconds': max((b['time_seconds'] - a['time_seconds'] for a,b in zip(session['frames'],session['frames'][1:])), default=0),
                    'checks_completed': session['checks'], 'checks_limit': settings['live_max_checks'],
                    'timestamp_basis': 'Elapsed screen-session sample time. Periodic asynchronous analysis, not instantaneous play-by-play.'}
            report = finish_report(self.store, job, session['frames'], info, session['observations'], session['unknowns'],
                                   session['withheld'], coaching, model, settings)
            state = 'completed' if session['closed'] else 'monitoring'
            self.store.update(job_id, state=state, progress=round(session['checks'] / settings['live_max_checks'] * 100),
                              message='Screen session stopped; review saved.' if session['closed'] else f"Check {session['checks']} ready; continuing periodic screen analysis.", result=report)

    def request_api(self):
        current = self.store.meta('api_refresh') or {}
        if current.get('state') in ['queued', 'running']:
            return current
        value = {'state': 'queued', 'time': now()}
        self.store.meta('api_refresh', value)
        self.queue.put(('api', None))
        return value

    def refresh_api(self, _):
        self.store.meta('api_refresh', {'state': 'running', 'time': now()})
        env = dict(os.environ, NEXTPLAY_PYTHON=sys.executable)
        review = self.store.project / 'nextplay-clash-review.json'
        coaching = self.store.project / 'nextplay-clash-ai-review.json'
        def run(script):
            path = self.store.project / script
            if not path.exists():
                raise ValueError('The existing Clash pipeline is missing ' + script)
            result = subprocess.run([sys.executable, str(path)], cwd=self.store.project, env=env,
                                    capture_output=True, text=True, timeout=180)
            if result.returncode:
                combined = result.stdout + result.stderr
                status = next((line.strip() for line in combined.splitlines() if 'HTTP ERROR' in line or 'NEXTPLAY ERROR:' in line or 'Missing CLASH_' in line), '')
                if '403' in status:
                    raise ValueError('Clash API returned HTTP 403. Check the existing Clash key allowed IP address in the developer portal.')
                raise ValueError('API refresh failed. ' + safe_error(status or 'Check the existing key, network, and pipeline dependencies.'))
        run('test_clash_api.py')
        run('nextplay-clash-v2.py')
        current_digest = hash_file(review)
        previous_digest = None
        if coaching.exists():
            try:
                previous_digest = json.loads(coaching.read_text()).get('metadata', {}).get('deterministic_sha256')
            except (OSError, ValueError):
                pass
        changed = previous_digest != current_digest
        if changed and self.store.settings['processing_mode'] == 'cloud':
            run('nextplay-clash-ai.py')
        self.store.meta('api_refresh', {'state': 'completed', 'time': now(), 'new_coaching': changed and self.store.settings['processing_mode'] == 'cloud',
                                       'review_sha256': current_digest})

    def watch(self):
        last_api = time.monotonic()
        seen = self.store.meta('watch_seen') or {}
        while not self.stop.wait(3):
            try:
                # Abandoned browser sessions do not keep sending frames or spending calls.
                with self.live_lock:
                    stale = [k for k,v in self.live.items() if not v['closed'] and time.monotonic() - v['last_received'] > 90]
                for job_id in stale:
                    self.end_live(job_id)
                if self.store.settings['watch_enabled']:
                    for path in self.store.inbox.iterdir():
                        if path.is_symlink() or not path.is_file() or path.suffix.lower() not in VIDEO_EXTENSIONS:
                            continue
                        stat = path.stat()
                        signature = f'{stat.st_size}:{stat.st_mtime_ns}'
                        if seen.get(path.name) == signature:
                            continue
                        old = self.watch_stable.get(path.name)
                        if old and old[0] == signature and time.monotonic() - old[1] >= 6 and time.time() - stat.st_mtime >= 5:
                            try:
                                self.ingest(path)
                                self.store.meta('watch_error', None)
                            except Exception as exc:
                                self.store.meta('watch_error', {'time': now(), 'name': path.name, 'error': safe_error(exc)})
                            seen[path.name] = signature
                            self.store.meta('watch_seen', seen)
                        elif not old or old[0] != signature:
                            self.watch_stable[path.name] = (signature, time.monotonic())
                minutes = self.store.settings['api_refresh_minutes']
                if self.store.settings['api_auto_refresh'] and time.monotonic() - last_api >= minutes * 60:
                    self.request_api()
                    last_api = time.monotonic()
            except Exception as exc:
                self.store.meta('watch_error', {'time': now(), 'error': safe_error(exc)})
