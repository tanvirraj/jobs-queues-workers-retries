# Exercise 6: When a worker dies holding a job.
# A claimed job carries a lease: "this is mine until <time>". If the worker
# dies, the lease runs out and another worker may take the job.
#
#   python3 ex06_leases.py reset
#   python3 ex06_leases.py enqueue ada@example.com
#   python3 ex06_leases.py work --crash-before-send   # dies before the email
#   python3 ex06_leases.py work                       # picks it up after lease
#   cat outbox.txt                                    # how many emails?
#
# Repeat with --crash-after-send and count again.

import json
import os
import sqlite3
import sys
import time

DB = "ex06.db"
LEASE_SECONDS = 5


def connect():
    db = sqlite3.connect(DB, isolation_level=None, timeout=10)
    db.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id           INTEGER PRIMARY KEY,
            kind         TEXT NOT NULL,
            args         TEXT NOT NULL,
            status       TEXT NOT NULL DEFAULT 'queued',
            locked_until REAL,                -- unix time the lease expires
            attempts     INTEGER NOT NULL DEFAULT 0
        )""")
    return db


def claim(db, lease_seconds):
    now = time.time()
    return db.execute("""
        UPDATE jobs
        SET status = 'running', locked_until = ?, attempts = attempts + 1
        WHERE id = (
            SELECT id FROM jobs
            WHERE status = 'queued'
               OR (status = 'running' AND locked_until < ?)  -- lease expired
            ORDER BY id LIMIT 1)
        RETURNING id, kind, args, attempts""",
        (now + lease_seconds, now)).fetchone()


def send_welcome_email(address, crash=None):
    time.sleep(1)
    if crash == "before":
        print("    *** power cut BEFORE the email was sent ***", flush=True)
        os._exit(1)                       # die instantly, no cleanup at all
    with open("outbox.txt", "a") as outbox:
        outbox.write(f"welcome email -> {address}\n")
    print(f"    sent welcome email to {address}")
    if crash == "after":
        print("    *** power cut AFTER the email was sent ***", flush=True)
        os._exit(1)


def work(db, crash, lease_seconds):
    print(f"worker {os.getpid()} lease={lease_seconds}s (Ctrl-C to stop)", flush=True)
    while True:
        row = claim(db, lease_seconds)
        if row is None:
            time.sleep(0.5)
            continue
        job_id, kind, args, attempts = row
        print(f"  job {job_id} attempt {attempts}: {kind} {args}", flush=True)
        send_welcome_email(**json.loads(args), crash=crash)
        db.execute("UPDATE jobs SET status = 'done', locked_until = NULL "
                   "WHERE id = ?", (job_id,))


def show(db):
    now = time.time()
    for job_id, args, status, locked_until, attempts in db.execute(
            "SELECT id, args, status, locked_until, attempts FROM jobs"):
        lease = ""
        if status == "running":
            left = locked_until - now
            lease = f"lease {left:.1f}s left" if left > 0 else "lease EXPIRED"
        print(f"  {job_id:<3} {args:<32} {status:<8} attempts={attempts} {lease}")


if __name__ == "__main__":
    db = connect()
    command = sys.argv[1] if len(sys.argv) > 1 else "list"
    if command == "enqueue":
        for address in sys.argv[2:]:
            db.execute("INSERT INTO jobs (kind, args) VALUES (?, ?)",
                       ("send_welcome_email", json.dumps({"address": address})))
        print(f"enqueued {len(sys.argv) - 2} job(s)")
    elif command == "work":
        crash = None
        if "--crash-before-send" in sys.argv:
            crash = "before"
        if "--crash-after-send" in sys.argv:
            crash = "after"
        lease = LEASE_SECONDS
        if "--lease" in sys.argv:
            lease = float(sys.argv[sys.argv.index("--lease") + 1])
        try:
            work(db, crash, lease)
        except KeyboardInterrupt:
            print("\nworker stopped")
    elif command == "reset":
        db.close()
        for name in (DB, "outbox.txt"):
            if os.path.exists(name):
                os.remove(name)
        print("reset")
    else:
        show(db)
