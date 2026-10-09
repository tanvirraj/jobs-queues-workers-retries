"""tinyq: a tiny, durable job queue on top of SQLite.

Everything in this file is something you built by hand in exercises 1-8:
jobs as data, a durable queue, atomic claims, leases, retries with
exponential backoff and jitter, a dead-letter state, and a way for a
handler to commit its own database writes in the SAME transaction that
marks the job done.
"""

import json
import random
import sqlite3
import time
import uuid
from contextlib import contextmanager

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id           INTEGER PRIMARY KEY,
    kind         TEXT NOT NULL,
    args         TEXT NOT NULL,
    unique_key   TEXT UNIQUE,                     -- optional enqueue dedup
    status       TEXT NOT NULL DEFAULT 'queued',  -- queued|running|done|dead
    attempts     INTEGER NOT NULL DEFAULT 0,
    run_at       REAL NOT NULL DEFAULT 0,
    locked_by    TEXT,                            -- token of the lease holder
    locked_until REAL,
    last_error   TEXT
);
CREATE INDEX IF NOT EXISTS jobs_ready ON jobs (status, run_at);
"""


class LeaseLost(Exception):
    """Our lease expired and someone else now owns the job. Walk away."""


class Job:
    def __init__(self, queue, job_id, kind, args, attempts, token):
        self.queue = queue
        self.id = job_id
        self.kind = kind
        self.args = args
        self.attempts = attempts
        self.token = token
        self.completed = False

    @contextmanager
    def complete(self):
        """Commit the handler's own writes and 'job done' atomically.

            with job.complete() as db:
                db.execute("UPDATE customers SET points = points + 10 ...")

        Either both happen or neither does. If our lease was stolen while we
        worked, the 'done' update matches no row and everything rolls back.
        """
        db = self.queue.db
        db.execute("BEGIN IMMEDIATE")
        try:
            yield db
            cursor = db.execute(
                "UPDATE jobs SET status = 'done', locked_by = NULL, "
                "locked_until = NULL WHERE id = ? AND locked_by = ?",
                (self.id, self.token))
            if cursor.rowcount != 1:
                raise LeaseLost(f"job {self.id} is no longer ours")
            db.execute("COMMIT")
        except BaseException:
            db.execute("ROLLBACK")
            raise
        self.completed = True


class Queue:
    def __init__(self, path, lease=5.0, max_attempts=10,
                 backoff_base=0.1, backoff_cap=10.0):
        self.db = sqlite3.connect(path, isolation_level=None, timeout=30)
        self.db.execute("PRAGMA journal_mode = WAL")
        self.db.executescript(SCHEMA)
        self.lease = lease
        self.max_attempts = max_attempts
        self.backoff_base = backoff_base
        self.backoff_cap = backoff_cap
        self.handlers = {}

    # --- producer side ------------------------------------------------------

    def handler(self, kind):
        def register(function):
            self.handlers[kind] = function
            return function
        return register

    def enqueue(self, kind, args, unique_key=None, delay=0.0):
        """Returns False if a job with this unique_key already exists."""
        cursor = self.db.execute(
            "INSERT OR IGNORE INTO jobs (kind, args, unique_key, run_at) "
            "VALUES (?, ?, ?, ?)",
            (kind, json.dumps(args), unique_key, time.time() + delay))
        return cursor.rowcount == 1

    # --- consumer side ------------------------------------------------------

    def claim(self):
        token = uuid.uuid4().hex
        now = time.time()
        row = self.db.execute("""
            UPDATE jobs
            SET status = 'running', locked_by = ?, locked_until = ?,
                attempts = attempts + 1
            WHERE id = (
                SELECT id FROM jobs
                WHERE (status = 'queued' AND run_at <= ?)
                   OR (status = 'running' AND locked_until < ?)
                ORDER BY run_at LIMIT 1)
            RETURNING id, kind, args, attempts""",
            (token, now + self.lease, now, now)).fetchone()
        if row is None:
            return None
        job_id, kind, args, attempts = row
        return Job(self, job_id, kind, json.loads(args), attempts, token)

    def backoff(self, attempts):
        delay = min(self.backoff_cap, self.backoff_base * 2 ** (attempts - 1))
        return delay * random.uniform(0.5, 1.0)

    def _fail(self, job, error):
        if job.attempts >= self.max_attempts:
            status, run_at = "dead", 0
        else:
            status, run_at = "queued", time.time() + self.backoff(job.attempts)
        # Only touch the job if we still hold the lease.
        self.db.execute(
            "UPDATE jobs SET status = ?, run_at = ?, last_error = ?, "
            "locked_by = NULL, locked_until = NULL "
            "WHERE id = ? AND locked_by = ?",
            (status, run_at, error, job.id, job.token))

    def work_one(self):
        """Claim and run one job. Returns False if there was nothing to do."""
        job = self.claim()
        if job is None:
            return False
        try:
            self.handlers[job.kind](job)
            if not job.completed:
                with job.complete():
                    pass
        except LeaseLost:
            pass
        except Exception as error:
            self._fail(job, f"{type(error).__name__}: {error}")
        return True

    def unfinished(self):
        return self.db.execute("SELECT count(*) FROM jobs WHERE status IN "
                               "('queued', 'running')").fetchone()[0]

    def work(self, stop_when_idle=False):
        while True:
            if not self.work_one():
                if stop_when_idle and self.unfinished() == 0:
                    return
                time.sleep(0.02)

    def counts(self):
        return dict(self.db.execute(
            "SELECT status, count(*) FROM jobs GROUP BY status").fetchall())
