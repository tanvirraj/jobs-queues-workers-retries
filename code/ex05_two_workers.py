# Exercise 5: Two workers, one job.
# Run two workers at once and watch them fight over the same job.
#
#   python3 ex05_two_workers.py reset
#   python3 ex05_two_workers.py enqueue a@x.com b@x.com c@x.com d@x.com
#   python3 ex05_two_workers.py work naive    (in terminal 1)
#   python3 ex05_two_workers.py work naive    (in terminal 2)
#   cat outbox.txt                            # look for duplicates
#
# Then reset, enqueue again, and use "work atomic" in both terminals.

import json
import os
import sqlite3
import sys
import time

DB = "ex05.db"


def connect():
    db = sqlite3.connect(DB, isolation_level=None, timeout=10)
    db.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id     INTEGER PRIMARY KEY,
            kind   TEXT NOT NULL,
            args   TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'queued',
            worker TEXT
        )""")
    return db


def send_welcome_email(address):
    time.sleep(1)
    with open("outbox.txt", "a") as outbox:
        outbox.write(f"welcome email -> {address}   (worker {os.getpid()})\n")
    print(f"    sent welcome email to {address}")


HANDLERS = {"send_welcome_email": send_welcome_email}


def claim_naive(db):
    # Step 1: look.  Step 2: grab.  Another worker can look in between.
    row = db.execute("SELECT id, kind, args FROM jobs "
                     "WHERE status = 'queued' ORDER BY id LIMIT 1").fetchone()
    if row is None:
        return None
    time.sleep(0.3)  # makes the gap wide enough to see; real gaps are tiny
    db.execute("UPDATE jobs SET status = 'running', worker = ? WHERE id = ?",
               (str(os.getpid()), row[0]))
    return row


def claim_atomic(db):
    # Look and grab in ONE statement. The database runs it as a single
    # indivisible step, so two workers can never both win the same row.
    return db.execute("""
        UPDATE jobs SET status = 'running', worker = ?
        WHERE id = (SELECT id FROM jobs WHERE status = 'queued'
                    ORDER BY id LIMIT 1)
        RETURNING id, kind, args""", (str(os.getpid()),)).fetchone()


def work(db, claim):
    print(f"worker {os.getpid()} using {claim.__name__} (Ctrl-C to stop)")
    while True:
        row = claim(db)
        if row is None:
            time.sleep(0.2)
            continue
        job_id, kind, args = row
        print(f"  job {job_id}: {kind} {args}")
        HANDLERS[kind](**json.loads(args))
        db.execute("UPDATE jobs SET status = 'done' WHERE id = ?", (job_id,))


if __name__ == "__main__":
    db = connect()
    command = sys.argv[1] if len(sys.argv) > 1 else "list"
    if command == "enqueue":
        for address in sys.argv[2:]:
            db.execute("INSERT INTO jobs (kind, args) VALUES (?, ?)",
                       ("send_welcome_email", json.dumps({"address": address})))
        print(f"enqueued {len(sys.argv) - 2} job(s)")
    elif command == "work":
        mode = sys.argv[2] if len(sys.argv) > 2 else "atomic"
        try:
            work(db, claim_naive if mode == "naive" else claim_atomic)
        except KeyboardInterrupt:
            print("\nworker stopped")
    elif command == "reset":
        db.close()
        for name in (DB, "outbox.txt"):
            if os.path.exists(name):
                os.remove(name)
        print("reset")
    else:
        for row in db.execute("SELECT id, args, status, worker FROM jobs"):
            print("  %-3s %-32s %-8s %s" % row)
