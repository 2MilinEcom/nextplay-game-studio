"""Versioned replay observations and conservative deck-specific recommendations.

Coordinates are normalized to the ARENA, not the phone window. A proposed point
is a review aid, never a calibrated tile placement or a command to a device.
"""
import hashlib
import json
import math
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

VERSION = '1.0'
COSTS = {'tesla': 4, 'wall_breakers': 2, 'miner': 3, 'royal_delivery': 3,
         'poison': 4, 'skeletons': 1, 'berserker': 2, 'the_log': 2}


def number(value, low, high, name):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f'Invalid {name}')


def validate(state):
    if state.get('schema_version') != 1 or state.get('app') != 'clash_royale':
        raise ValueError('Only version 1 Clash Royale observations are accepted')
    if state.get('source') not in ('manual_replay', 'synthetic_fixture'):
        raise ValueError('An explicit supported observation source is required')
    if state.get('coordinate_space') != 'arena_normalized':
        raise ValueError('Arena-normalized coordinates required')
    if not isinstance(state.get('evidence_id'), str) or not state['evidence_id'].strip():
        raise ValueError('Evidence reference required')
    number(state.get('observed_ms'), 0, 1e15, 'observed_ms')
    number(state.get('available_ms'), state['observed_ms'], 1e15, 'available_ms')
    number(state.get('confidence'), 0, 1, 'confidence')
    if state.get('phase') not in ('battle', 'menu', 'unknown'):
        raise ValueError('Invalid phase')
    if state.get('elixir') is not None:
        number(state['elixir'], 0, 10, 'displayed own elixir')
    if not isinstance(state.get('hand'), list) or len(state['hand']) > 4:
        raise ValueError('At most four visible hand cards required')
    if len(set(state['hand'])) != len(state['hand']) or any(c not in COSTS for c in state['hand']):
        raise ValueError('Invalid deck card')
    if not isinstance(state.get('threats'), list):
        raise ValueError('Threat list required')
    for threat in state['threats']:
        if threat.get('kind') not in ('balloon', 'ground_tank', 'ground_swarm', 'unknown'):
            raise ValueError('Invalid threat class')
        if threat.get('lane') not in ('left', 'right'):
            raise ValueError('Invalid lane')
        number(threat.get('y'), 0, 1, 'threat position')
        number(threat.get('confidence'), 0, 1, 'threat confidence')
    # No field is allowed to smuggle unobserved hand/elixir or API leak metrics.
    allowed = {'schema_version', 'app', 'source', 'coordinate_space', 'evidence_id',
               'observed_ms', 'available_ms', 'confidence', 'phase', 'elixir', 'hand', 'threats'}
    if set(state) - allowed:
        raise ValueError('Unsupported state fields; hidden information is not accepted')
    return state


def recommend(state, decision_ms):
    validate(state)
    number(decision_ms, state['available_ms'], 1e15, 'decision time')
    result = {'engine_version': VERSION, 'mode': 'offline_review',
              'evidence_id': state['evidence_id'], 'action': None,
              'status': 'withheld', 'reason': '', 'age_ms': decision_ms - state['observed_ms']}
    if state['source'] == 'synthetic_fixture':
        result['fixture'] = True
    if state['phase'] != 'battle':
        result['reason'] = 'No verified battle state'
    elif state['confidence'] < .95:
        result['reason'] = 'State confidence below 0.95'
    elif result['age_ms'] > 500:
        result['reason'] = 'Observation older than 500ms'
    elif state['elixir'] is None:
        result['reason'] = 'Own elixir unreadable'
    else:
        threats = sorted(state['threats'], key=lambda t: t['y'], reverse=True)
        for threat in threats:
            if threat['confidence'] < .95 or threat['y'] < .45:
                continue
            card = {'balloon': 'tesla', 'ground_tank': 'tesla',
                    'ground_swarm': 'royal_delivery'}.get(threat['kind'])
            if card in state['hand'] and state['elixir'] >= COSTS[card]:
                result.update(status='candidate', reason='Review this defensive option; outcome unproven',
                              action={'card': card, 'rule': f'defend_{threat["kind"]}',
                                      'lane': threat['lane'],
                                      'review_region': {'x': .38 if threat['lane'] == 'left' else .62, 'y': .65},
                                      'placement_validated': False})
                break
        if result['action'] is None:
            result['reason'] = 'No supported affordable defense; no speculative action'
    return result


class Journal:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.connect() as db:
            db.executescript('''
              CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY, source TEXT NOT NULL, created_ns INTEGER NOT NULL);
              CREATE TABLE IF NOT EXISTS observations (
                session_id TEXT NOT NULL REFERENCES sessions(id),
                sequence INTEGER NOT NULL, sha256 TEXT NOT NULL, state TEXT NOT NULL,
                decision TEXT NOT NULL, PRIMARY KEY(session_id, sequence));
              CREATE TABLE IF NOT EXISTS labels (
                session_id TEXT NOT NULL, sequence INTEGER NOT NULL,
                card TEXT, reviewer TEXT NOT NULL,
                PRIMARY KEY(session_id, sequence),
                FOREIGN KEY(session_id, sequence) REFERENCES observations(session_id, sequence));
              PRAGMA user_version=1;
            ''')
        self.path.chmod(0o600)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.execute('PRAGMA foreign_keys=ON')
        try:
            with db:
                yield db
        finally:
            db.close()

    def import_session(self, session_id, states):
        if not session_id or len(session_id) > 100 or not states:
            raise ValueError('Session ID and nonempty observations required')
        decisions = []
        previous = -1
        sources = set()
        for state in states:
            validate(state)
            if state['observed_ms'] <= previous:
                raise ValueError('Observation times must increase strictly')
            previous = state['observed_ms']
            sources.add(state['source'])
            decisions.append(recommend(state, state['available_ms']))
        if len(sources) != 1:
            raise ValueError('Synthetic and real observations cannot share a session')
        with self.connect() as db:
            db.execute('INSERT INTO sessions VALUES (?,?,?)', (session_id, sources.pop(), time.time_ns()))
            for i, (state, decision) in enumerate(zip(states, decisions)):
                serialized = json.dumps(state, sort_keys=True, separators=(',', ':'))
                db.execute('INSERT INTO observations VALUES (?,?,?,?,?)',
                           (session_id, i, hashlib.sha256(serialized.encode()).hexdigest(),
                            serialized, json.dumps(decision)))
        return decisions

    def label(self, session_id, sequence, card, reviewer):
        if card is not None and card not in COSTS:
            raise ValueError('Unsupported label card')
        if not reviewer or type(sequence) is not int or sequence < 0:
            raise ValueError('Reviewer and valid sequence required')
        with self.connect() as db:
            db.execute('INSERT INTO labels VALUES (?,?,?,?) ON CONFLICT(session_id,sequence) '
                       'DO UPDATE SET card=excluded.card,reviewer=excluded.reviewer',
                       (session_id, sequence, card, reviewer))

    def report(self, session_id):
        with self.connect() as db:
            session = db.execute('SELECT source FROM sessions WHERE id=?', (session_id,)).fetchone()
            if not session:
                raise ValueError('Unknown session')
            rows = db.execute('SELECT o.state,o.decision,l.card,l.reviewer FROM observations o '
                              'LEFT JOIN labels l USING(session_id,sequence) '
                              'WHERE session_id=? ORDER BY sequence', (session_id,)).fetchall()
        latencies = sorted(json.loads(r[0])['available_ms'] - json.loads(r[0])['observed_ms'] for r in rows)
        labeled = [r for r in rows if r[3] is not None]
        matches = sum((json.loads(r[1])['action'] or {}).get('card') == r[2] for r in labeled)
        return {'session_id': session_id, 'source': session[0], 'observations': len(rows),
                'candidates': sum(json.loads(r[1])['status'] == 'candidate' for r in rows),
                'labeled': len(labeled), 'card_agreement': matches / len(labeled) if labeled else None,
                'observation_delay_p50_ms': latencies[(len(latencies)-1)//2],
                'observation_delay_p95_ms': latencies[math.ceil(.95*len(latencies))-1],
                'live_input_enabled': False, 'readiness': 'not_validated',
                'limitations': ['Card agreement is not move quality or win probability',
                                'No automatic visual recognition, tile calibration or phone input',
                                'Rules are hypotheses requiring human replay labels']}
