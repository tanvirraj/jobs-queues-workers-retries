# Exercise 4: A queue that survives a restart.
# Jobs live in a SQLite file, so they outlive any single process.
#
#   python3 ex04_durable_queue.py enqueue ada@example.com alan@example.com
#   python3 ex04_durable_queue.py list
#   python3 ex04_durable_queue.py work        # Ctrl-C to stop
#   python3 ex04_durable_queue.py reset

import json
import os
import sqlite3
import sys
import time

DB = "ex04.db"


def connect():
    # isolation_level=None: we decide when transactions start and end.
    db = sqlite3.connect(DB, isolation_level=None, timeout=10)
    db.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id     INTEGER PRIMARY KEY,
            kind   TEXT NOT NULL,
            args   TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'queued'   -- queued | running | done
        )""")
    return db


def send_welcome_email(address):
    time.sleep(2)
    with open("outbox.txt", "a") as outbox:
        outbox.write(f"welcome email -> {address}\n")
    print(f"    sent welcome email to {address}")


HANDLERS = {"send_welcome_email": send_welcome_email}


def enqueue(db, kind, **args):
    db.execute("INSERT INTO jobs (kind, args) VALUES (?, ?)",
               (kind, json.dumps(args)))


def work(db):
    print(f"worker {os.getpid()} waiting for jobs (Ctrl-C to stop)")
    while True:
        row = db.execute("SELECT id, kind, args FROM jobs "
                         "WHERE status = 'queued' ORDER BY id LIMIT 1").fetchone()
        if row is None:
            time.sleep(0.5)            # nothing to do; check again soon
            continue
        job_id, kind, args = row
        db.execute("UPDATE jobs SET status = 'running' WHERE id = ?", (job_id,))
        print(f"  job {job_id}: {kind} {args}")
        HANDLERS[kind](**json.loads(args))
        db.execute("UPDATE jobs SET status = 'done' WHERE id = ?", (job_id,))


def show(db):
    for row in db.execute("SELECT id, kind, args, status FROM jobs ORDER BY id"):
        print("  %-3s %-20s %-36s %s" % row)


if __name__ == "__main__":
    db = connect()
    command = sys.argv[1] if len(sys.argv) > 1 else "list"
    if command == "enqueue":
        for address in sys.argv[2:]:
            enqueue(db, "send_welcome_email", address=address)
        print(f"enqueued {len(sys.argv) - 2} job(s)")
    elif command == "work":
        try:
            work(db)
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
