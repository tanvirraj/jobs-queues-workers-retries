# Exercise 8: Idempotency keys.
# Same flaky bank, same retries. One change: every charge carries a key that
# names *this particular payment*, and the bank refuses to do a key twice.
#
#   python3 ex08_idempotency.py setup
#   python3 ex08_idempotency.py work
#   python3 ex08_idempotency.py report
#
# Then try:  python3 ex08_idempotency.py work --bad-key   (a fresh key per try)

import json
import os
import random
import sqlite3
import sys
import time

DB = "ex08.db"
MAX_ATTEMPTS = 6
BACKOFF_BASE = 0.2     # seconds; real systems use seconds to minutes
BACKOFF_CAP = 5.0
LEASE_SECONDS = 10

rng = random.Random()
BAD_KEY = "--bad-key" in sys.argv


def connect():
    db = sqlite3.connect(DB, isolation_level=None, timeout=10)
    db.executescript("""
        CREATE TABLE IF NOT EXISTS jobs (
            id           INTEGER PRIMARY KEY,
            kind         TEXT NOT NULL,
            args         TEXT NOT NULL,
            status       TEXT NOT NULL DEFAULT 'queued', -- queued|running|done|dead
            attempts     INTEGER NOT NULL DEFAULT 0,
            run_at       REAL NOT NULL DEFAULT 0,        -- not before this time
            locked_until REAL,
            last_error   TEXT
        );
        -- Pretend this table lives inside a bank, far away from us.
        CREATE TABLE IF NOT EXISTS bank_accounts (
            name    TEXT PRIMARY KEY,
            balance INTEGER NOT NULL
        );
        -- The bank remembers every key it has seen, and what it answered.
        CREATE TABLE IF NOT EXISTS bank_requests (
            idempotency_key TEXT PRIMARY KEY,
            response        TEXT NOT NULL
        );""")
    return db


# --- the outside world ------------------------------------------------------

def bank_charge(db, account, amount, idempotency_key):
    roll = rng.random()
    if roll < 0.3:
        # The request never arrived. Nothing happened. Safe to retry.
        raise ConnectionError("could not reach the bank")

    # Inside the bank: check the key and move the money in ONE transaction,
    # so "charged" and "remembered that we charged" can never disagree.
    db.execute("BEGIN IMMEDIATE")
    seen = db.execute("SELECT response FROM bank_requests WHERE idempotency_key = ?",
                      (idempotency_key,)).fetchone()
    if seen is None:
        db.execute("UPDATE bank_accounts SET balance = balance - ? WHERE name = ?",
                   (amount, account))
        db.execute("INSERT INTO bank_requests VALUES (?, 'ok')", (idempotency_key,))
    else:
        print(f"    (bank: I already did {idempotency_key}; not charging again)")
    db.execute("COMMIT")

    if roll < 0.6:
        # The bank DID charge the card, but the reply got lost on the way back.
        # From where we stand, this looks exactly like the failure above.
        raise TimeoutError("no reply from the bank")
    return "ok"


def charge_card(db, account, amount, order_id):
    if BAD_KEY:
        key = f"charge-{order_id}-{time.time()}"   # WRONG: new key every attempt
    else:
        key = f"charge-for-order-{order_id}"        # right: same key every attempt
    bank_charge(db, account, amount, idempotency_key=key)
    print(f"    charged {account} ${amount} for order {order_id}")


HANDLERS = {"charge_card": charge_card}


# --- the queue ---------------------------------------------------------------

def backoff(attempts):
    # 0.2, 0.4, 0.8, 1.6 ... seconds, capped, then "jittered" by up to 50%
    # so that a thousand failed jobs do not all retry at the same instant.
    delay = min(BACKOFF_CAP, BACKOFF_BASE * 2 ** (attempts - 1))
    return delay * rng.uniform(0.5, 1.0)


def claim(db):
    now = time.time()
    return db.execute("""
        UPDATE jobs
        SET status = 'running', locked_until = ?, attempts = attempts + 1
        WHERE id = (
            SELECT id FROM jobs
            WHERE (status = 'queued' AND run_at <= ?)
               OR (status = 'running' AND locked_until < ?)
            ORDER BY run_at LIMIT 1)
        RETURNING id, kind, args, attempts""",
        (now + LEASE_SECONDS, now, now)).fetchone()


def fail(db, job_id, attempts, error):
    if attempts >= MAX_ATTEMPTS:
        db.execute("UPDATE jobs SET status = 'dead', last_error = ? WHERE id = ?",
                   (error, job_id))
        print(f"    gave up after {attempts} attempts -> dead-letter pile")
    else:
        delay = backoff(attempts)
        db.execute("UPDATE jobs SET status = 'queued', run_at = ?, last_error = ? "
                   "WHERE id = ?", (time.time() + delay, error, job_id))
        print(f"    failed ({error}); retry in {delay:.2f}s")


def work(db):
    while True:
        row = claim(db)
        if row is None:
            unfinished = db.execute("SELECT count(*) FROM jobs "
                                    "WHERE status IN ('queued', 'running')").fetchone()[0]
            if unfinished == 0:
                print("no unfinished jobs left; worker exiting")
                return
            time.sleep(0.05)
            continue
        job_id, kind, args, attempts = row
        print(f"  job {job_id} attempt {attempts}: {kind} {args}")
        try:
            HANDLERS[kind](db, **json.loads(args))
        except Exception as error:
            fail(db, job_id, attempts, f"{type(error).__name__}: {error}")
        else:
            db.execute("UPDATE jobs SET status = 'done' WHERE id = ?", (job_id,))


def report(db):
    print("jobs:")
    for row in db.execute("SELECT id, status, attempts, last_error FROM jobs"):
        print("  job %-3s %-6s attempts=%-2s last_error=%s" % row)
    done = db.execute("SELECT count(*) FROM jobs WHERE status = 'done'").fetchone()[0]
    balance = db.execute("SELECT balance FROM bank_accounts "
                         "WHERE name = 'alice'").fetchone()[0]
    print(f"\njobs that succeeded:    {done} x $10")
    print(f"alice should have:      ${100 - 10 * done}")
    print(f"alice actually has:     ${balance}")
    if balance != 100 - 10 * done:
        print(f"alice was overcharged:  ${100 - 10 * done - balance}  <-- duplicates!")


if __name__ == "__main__":
    if "--seed" in sys.argv:
        rng.seed(int(sys.argv[sys.argv.index("--seed") + 1]))
    command = sys.argv[1] if len(sys.argv) > 1 else "report"
    if command == "setup":
        if os.path.exists(DB):
            os.remove(DB)
        db = connect()
        db.execute("INSERT INTO bank_accounts VALUES ('alice', 100)")
        for order_id in range(1, 6):
            db.execute("INSERT INTO jobs (kind, args) VALUES (?, ?)",
                       ("charge_card", json.dumps({"account": "alice", "amount": 10,
                                                    "order_id": order_id})))
        print("alice has $100; queued 5 charges of $10")
    elif command == "work":
        work(connect())
    else:
        report(connect())
