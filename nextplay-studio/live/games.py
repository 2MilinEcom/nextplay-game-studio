"""Versioned per-game experience; records evidence, never auto-claims learning."""
import json,sqlite3,time,uuid
from pathlib import Path

class Games:
    def __init__(self,path):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.db() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS games(id TEXT PRIMARY KEY,policy TEXT,source TEXT,started REAL,ended REAL,outcome TEXT);
            CREATE TABLE IF NOT EXISTS events(game_id TEXT,sequence INTEGER,kind TEXT,payload TEXT,PRIMARY KEY(game_id,sequence));''')
    def db(self):return sqlite3.connect(self.path)
    def start(self,policy,source):
        if source not in ['practice','replay','live']:raise ValueError('Explicit source required')
        identifier=uuid.uuid4().hex
        with self.db() as db:db.execute('INSERT INTO games VALUES(?,?,?,?,?,?)',(identifier,policy,source,time.time(),None,None))
        return identifier
    def record(self,identifier,kind,payload):
        if kind not in ['observation','decision','input','outcome','verified_label']:raise ValueError('Invalid event')
        with self.db() as db:
            game=db.execute('SELECT ended FROM games WHERE id=?',(identifier,)).fetchone()
            if not game or game[0] is not None:raise ValueError('No active game')
            sequence=db.execute('SELECT COUNT(*) FROM events WHERE game_id=?',(identifier,)).fetchone()[0]
            db.execute('INSERT INTO events VALUES(?,?,?,?)',(identifier,sequence,kind,json.dumps(payload)))
    def finish(self,identifier,outcome):
        if outcome not in ['win','loss','draw','unknown','disconnected']:raise ValueError('Invalid outcome')
        with self.db() as db:
            updated=db.execute('UPDATE games SET ended=?,outcome=? WHERE id=? AND ended IS NULL',(time.time(),outcome,identifier)).rowcount
            if updated!=1:raise ValueError('No active game')
    def report(self):
        with self.db() as db:
            rows=db.execute('SELECT policy,source,COUNT(*),SUM(outcome="win") FROM games WHERE ended IS NOT NULL GROUP BY policy,source').fetchall()
        return {'versions':[{'policy':p,'source':s,'games':n,'wins':w} for p,s,n,w in rows],
            'automatic_training':False,'automatic_promotion':False,
            'meaning':'Logs support labeled training and version comparisons; wins alone do not prove move quality or improvement.'}
