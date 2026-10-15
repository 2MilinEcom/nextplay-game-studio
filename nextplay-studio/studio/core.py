import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

_UNSET = object()
VIDEO_EXTENSIONS = {'.mp4', '.mov', '.m4v', '.webm', '.mkv'}
DEFAULTS = {'processing_mode': 'local', 'sample_interval': 6, 'max_frames': 24, 'batch_size': 6,
            'max_minutes': 20, 'watch_enabled': True, 'api_auto_refresh': True,
            'api_refresh_minutes': 10, 'live_interval': 5, 'live_batch_frames': 6,
            'live_max_checks': 20, 'vision_model': 'gpt-4.1', 'coach_model': 'gpt-4.1',
            'verify_observations': True, 'max_upload_mb': 2048}


def now():
    return datetime.now(timezone.utc).isoformat()


def ident():
    return uuid.uuid4().hex


def safe_error(exc):
    if isinstance(exc, subprocess.TimeoutExpired):
        return 'Video processing timed out. Try a shorter recording.'
    message = str(exc)[:1200]
    for key in ['OPENAI_API_KEY', 'CLASH_ROYALE_API_KEY']:
        value = os.environ.get(key, '')
        if len(value) > 8:
            message = message.replace(value, '[redacted]')
    message = re.sub(r'\bsk-[\w-]+|\beyJ[\w.-]+', '[redacted]', message)
    return message


def binary(name):
    result = shutil.which(name)
    for candidate in [result, f'/opt/homebrew/bin/{name}', f'/usr/local/bin/{name}']:
        if candidate and Path(candidate).is_file():
            return candidate
    raise ValueError(f'{name} is unavailable. Install FFmpeg before processing recordings.')


def hash_file(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path, value):
    path = Path(path)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding='utf-8')
    os.chmod(temp, 0o600)
    temp.replace(path)


class Store:
    def __init__(self, project, data=None):
        self.project = Path(project).resolve()
        self.data = Path(data or self.project / 'studio-data').resolve()
        self.data.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.data, 0o700)
        for name in ['uploads', 'frames', 'reports', 'logs']:
            (self.data / name).mkdir(exist_ok=True, mode=0o700)
        self.inbox = self.project / 'recordings-inbox'
        self.inbox.mkdir(exist_ok=True, mode=0o700)
        self.db = self.data / 'nextplay.sqlite3'
        self.lock = threading.RLock()
        self.settings_path = self.data / 'settings.json'
        self.settings = dict(DEFAULTS)
        if self.settings_path.exists():
            self.settings.update(json.loads(self.settings_path.read_text()))
        self.save_settings({})
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS jobs (
                  id TEXT PRIMARY KEY, kind TEXT NOT NULL, name TEXT NOT NULL,
                  state TEXT NOT NULL, progress INTEGER DEFAULT 0, message TEXT DEFAULT '',
                  created TEXT NOT NULL, updated TEXT NOT NULL, source TEXT DEFAULT '',
                  sha256 TEXT DEFAULT '', context TEXT DEFAULT '{}', result TEXT DEFAULT '{}',
                  error TEXT DEFAULT '', demo INTEGER DEFAULT 0, cancelled INTEGER DEFAULT 0);
                CREATE INDEX IF NOT EXISTS jobs_state ON jobs(state);
                CREATE INDEX IF NOT EXISTS jobs_sha ON jobs(sha256);
                CREATE TABLE IF NOT EXISTS notes (job_id TEXT PRIMARY KEY, text TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            ''')
            db.execute("UPDATE jobs SET state='interrupted', message='Interrupted by app restart. Retry this review.', updated=? WHERE state IN ('processing','monitoring','uploading')", (now(),))
        os.chmod(self.db, 0o600)
        refresh = self.meta('api_refresh') or {}
        if refresh.get('state') in ['queued', 'running']:
            self.meta('api_refresh', {'state':'failed', 'error':'Interrupted by app restart. Refresh again.', 'time':now()})

    @contextmanager
    def connect(self):
        with self.lock:
            conn = sqlite3.connect(self.db, timeout=15)
            conn.row_factory = sqlite3.Row
            try:
                yield conn
                conn.commit()
            finally:
                conn.close()

    def save_settings(self, updates):
        allowed = set(DEFAULTS)
        if set(updates) - allowed:
            raise ValueError('Unknown setting.')
        ranges = {'sample_interval': (2, 30), 'max_frames': (6, 60), 'batch_size': (2, 8),
                  'max_minutes': (1, 60), 'api_refresh_minutes': (5, 120),
                  'live_interval': (3, 30), 'live_batch_frames': (2, 8),
                  'live_max_checks': (1, 40), 'max_upload_mb': (10, 4096)}
        for key, value in updates.items():
            if key in ranges and (type(value) is not int or not ranges[key][0] <= value <= ranges[key][1]):
                raise ValueError(f'Invalid {key}.')
            if isinstance(DEFAULTS[key], bool) and type(value) is not bool:
                raise ValueError(f'Invalid {key}.')
            if key.endswith('_model') and (not isinstance(value, str) or not re.fullmatch(r'[\w.-]{1,80}', value)):
                raise ValueError('Invalid model name.')
        if updates.get('processing_mode', 'local') not in ('local', 'cloud'):
            raise ValueError('Choose local or cloud processing.')
        self.settings.update(updates)
        # Keep independent verification on; it is part of the evidence contract.
        self.settings['verify_observations'] = True
        write_json(self.settings_path, self.settings)
        return dict(self.settings)

    def create_job(self, kind, name, source='', digest='', context=None, demo=False):
        job_id = ident()
        with self.connect() as db:
            db.execute('INSERT INTO jobs(id,kind,name,state,created,updated,source,sha256,context,demo) VALUES (?,?,?,?,?,?,?,?,?,?)',
                       (job_id, kind, name[:200], 'queued', now(), now(), str(source), digest,
                        json.dumps(context or {}), int(demo)))
        return self.get_job(job_id)

    def update(self, job_id, **values):
        allowed = {'state', 'progress', 'message', 'result', 'error', 'cancelled', 'context', 'source'}
        if not values or set(values) - allowed:
            raise ValueError('Invalid job update.')
        for key in ['result', 'context']:
            if key in values:
                values[key] = json.dumps(values[key])
        values['updated'] = now()
        with self.connect() as db:
            db.execute('UPDATE jobs SET ' + ', '.join(k + '=?' for k in values) + ' WHERE id=?',
                       tuple(values.values()) + (job_id,))

    def decode(self, row, private=False):
        if not row:
            return None
        result = dict(row)
        for key in ['context', 'result']:
            result[key] = json.loads(result[key])
        if not private:
            result.pop('source', None)
        with self.connect() as db:
            note = db.execute('SELECT text FROM notes WHERE job_id=?', (result['id'],)).fetchone()
        result['notes'] = note['text'] if note else ''
        return result

    def get_job(self, job_id, private=False):
        if not re.fullmatch(r'[a-f0-9]{32}', job_id):
            return None
        with self.connect() as db:
            row = db.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
        return self.decode(row, private)

    def jobs(self):
        with self.connect() as db:
            rows = db.execute('SELECT * FROM jobs ORDER BY created DESC LIMIT 100').fetchall()
        return [self.decode(row) for row in rows]

    def duplicate(self, digest):
        with self.connect() as db:
            row = db.execute("SELECT * FROM jobs WHERE sha256=? AND state!='deleted' ORDER BY created DESC LIMIT 1", (digest,)).fetchone()
        return self.decode(row)

    def note(self, job_id, text):
        if not self.get_job(job_id):
            raise ValueError('Review not found.')
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO notes(job_id,text) VALUES (?,?)', (job_id, text[:10000]))

    def meta(self, key, value=_UNSET):
        with self.connect() as db:
            if value is not _UNSET:
                db.execute('INSERT OR REPLACE INTO meta(key,value) VALUES (?,?)', (key, json.dumps(value)))
            row = db.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()
        return json.loads(row['value']) if row else None

    def context(self, battle_time):
        if not battle_time:
            return {}
        path = self.project / 'nextplay-clash-review.json'
        review = json.loads(path.read_text()) if path.exists() else {}
        for battle in review.get('battles', []):
            if battle.get('time') == battle_time:
                return {'link_method': 'user_selected', 'battle': {k: v for k, v in battle.items() if 'elixir' not in k.lower()}}
        raise ValueError('Selected match is unavailable; refresh your API data.')

    def api_summary(self):
        result = {'available': False, 'last_refresh': self.meta('api_refresh'), 'player': {}, 'review': {}}
        for key, filename in [('player', 'player-profile.json'), ('review', 'nextplay-clash-review.json')]:
            path = self.project / filename
            if path.exists():
                try:
                    raw = json.loads(path.read_text())
                    if key == 'player':
                        result[key] = {k: raw.get(k) for k in ['name', 'tag', 'trophies', 'expLevel']}
                    else:
                        def clean(value):
                            if isinstance(value, dict):
                                return {k: clean(v) for k, v in value.items() if 'elixir' not in k.lower()}
                            if isinstance(value, list):
                                return [clean(v) for v in value]
                            return value
                        result[key] = clean(raw)
                        result['available'] = True
                except (ValueError, OSError):
                    pass
        return result
