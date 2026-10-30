"""Small transactional stores. Every record belongs to an isolated laboratory run."""
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import time
import uuid

SCHEMA = '''
CREATE TABLE IF NOT EXISTS faults(run TEXT, name TEXT, enabled INTEGER, PRIMARY KEY(run,name));
CREATE TABLE IF NOT EXISTS payments(run TEXT, key TEXT, amount INTEGER, qty INTEGER, created REAL, PRIMARY KEY(run,key));
CREATE TABLE IF NOT EXISTS inventory(run TEXT PRIMARY KEY, stock INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS reservations(id TEXT PRIMARY KEY, run TEXT, key TEXT, qty INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS reservations_run ON reservations(run,key);
CREATE TABLE IF NOT EXISTS intents(run TEXT, key TEXT, qty INTEGER, amount INTEGER, PRIMARY KEY(run,key));
CREATE TABLE IF NOT EXISTS orders(run TEXT, key TEXT, qty INTEGER, amount INTEGER, created REAL, PRIMARY KEY(run,key));
CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT, run TEXT, at REAL, service TEXT, kind TEXT, trace TEXT, data TEXT);
CREATE INDEX IF NOT EXISTS events_run ON events(run,seq);
CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, scenario TEXT, mode TEXT, status TEXT, created REAL, updated REAL, report TEXT);
'''


class Store:
    def __init__(self, path):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def connect(self, write=False):
        c = sqlite3.connect(self.path, timeout=15)
        c.row_factory = sqlite3.Row
        c.execute('PRAGMA journal_mode=WAL')
        try:
            if write:
                c.execute('BEGIN IMMEDIATE')
            yield c
            c.commit()
        except BaseException:
            c.rollback()
            raise
        finally:
            c.close()

    def log(self, run, service, kind, data, trace=''):
        with self.connect(write=True) as c:
            c.execute('INSERT INTO events(run,at,service,kind,trace,data) VALUES(?,?,?,?,?,?)',
                      (run,time.time(),service,kind,trace,json.dumps(data)))

    def fault(self, run, name):
        with self.connect() as c:
            row = c.execute('SELECT enabled FROM faults WHERE run=? AND name=?',(run,name)).fetchone()
            return bool(row and row['enabled'])

    def set_fault(self, run, name, enabled):
        with self.connect(write=True) as c:
            c.execute('INSERT INTO faults VALUES(?,?,?) ON CONFLICT(run,name) DO UPDATE SET enabled=excluded.enabled',
                      (run,name,int(enabled)))
        self.log(run,'control','fault.changed',{'fault':name,'enabled':enabled})

    def events(self, run, after=0, limit=500):
        with self.connect() as c:
            rows = c.execute('SELECT * FROM events WHERE run=? AND seq>? ORDER BY seq LIMIT ?',
                             (run,after,limit)).fetchall()
        return [{**dict(r),'data':json.loads(r['data'])} for r in rows]

    def rows(self, table, run):
        if table not in {'payments','reservations','intents','orders','inventory'}:
            raise ValueError('Unsupported table')
        with self.connect() as c:
            return [dict(r) for r in c.execute(f'SELECT * FROM {table} WHERE run=?',(run,))]

    def create_run(self, scenario, mode):
        run = uuid.uuid4().hex
        now = time.time()
        with self.connect(write=True) as c:
            c.execute('INSERT INTO runs VALUES(?,?,?,?,?,?,?)',(run,scenario,mode,'queued',now,now,None))
        return run

    def update_run(self, run, status, report=None):
        with self.connect(write=True) as c:
            c.execute('UPDATE runs SET status=?,updated=?,report=? WHERE id=?',
                      (status,time.time(),json.dumps(report) if report is not None else None,run))

    def get_run(self, run):
        with self.connect() as c:
            row = c.execute('SELECT * FROM runs WHERE id=?',(run,)).fetchone()
        if not row:
            return None
        result = dict(row)
        result['report'] = json.loads(result['report']) if result['report'] else None
        return result

    def runs(self):
        with self.connect() as c:
            return [dict(r) for r in c.execute('SELECT id,scenario,mode,status,created,updated FROM runs ORDER BY created DESC LIMIT 50')]
