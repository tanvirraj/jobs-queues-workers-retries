"""A tiny shop built on tinyq.

A signup creates a customer and queues three jobs:
    send_welcome_email   external, made safe with an idempotency key
    charge_signup_fee    external, made safe with an idempotency key
    award_points         internal, made safe by committing with the ack

    python3 shop.py signup ada@example.com
    python3 shop.py work [--chaos 0.1]
    python3 shop.py status
"""

import os
import random
import sys

import tinyq
import world

queue = tinyq.Queue("shop.db", lease=1.0, max_attempts=15, backoff_cap=1.0)
queue.db.execute("CREATE TABLE IF NOT EXISTS customers ("
                 "email TEXT PRIMARY KEY, points INTEGER NOT NULL DEFAULT 0)")

CHAOS = 0.0


def maybe_crash(where):
    """Pull the plug at random, like a deploy, an OOM kill, or a power cut."""
    if random.random() < CHAOS:
        print(f"  [{os.getpid()}] CRASH {where}", flush=True)
        os._exit(1)


def signup(email):
    # The customer row and its jobs commit together, or not at all.
    # (The queue lives in the same database as our data, so this is easy.)
    queue.db.execute("BEGIN IMMEDIATE")
    queue.db.execute("INSERT INTO customers (email) VALUES (?)", (email,))
    for kind in ("send_welcome_email", "charge_signup_fee", "award_points"):
        queue.enqueue(kind, {"email": email}, unique_key=f"{kind}:{email}")
    queue.db.execute("COMMIT")
    w = world.connect()
    w.execute("INSERT OR IGNORE INTO bank_accounts VALUES (?, 100)", (email,))


@queue.handler("send_welcome_email")
def send_welcome_email(job):
    maybe_crash("before sending email")
    world.send_email(job.args["email"], "Welcome!",
                     idempotency_key=f"welcome-email:{job.args['email']}")
    maybe_crash("after sending email, before ack")


@queue.handler("charge_signup_fee")
def charge_signup_fee(job):
    maybe_crash("before charging")
    world.charge(job.args["email"], 5,
                 idempotency_key=f"signup-fee:{job.args['email']}")
    maybe_crash("after charging, before ack")


@queue.handler("award_points")
def award_points(job):
    maybe_crash("before awarding points")
    with job.complete() as db:
        db.execute("UPDATE customers SET points = points + 10 WHERE email = ?",
                   (job.args["email"],))
        maybe_crash("inside the transaction, before commit")


if __name__ == "__main__":
    if "--chaos" in sys.argv:
        CHAOS = float(sys.argv[sys.argv.index("--chaos") + 1])
    command = sys.argv[1] if len(sys.argv) > 1 else "status"
    if command == "signup":
        for email in sys.argv[2:]:
            signup(email)
    elif command == "work":
        queue.work(stop_when_idle=True)
    else:
        print(queue.counts())
