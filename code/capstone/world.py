"""The outside world: a flaky mail provider and a flaky bank.

They live in their own database file (world.db) to make the point that we
do NOT control them. We can only send them requests and hope for replies.
Both honour idempotency keys, the way real payment and email APIs do.
"""

import os
import random
import sqlite3

FAIL_BEFORE = 0.15   # request lost on the way in: nothing happened
FAIL_AFTER = 0.15    # reply lost on the way out: it DID happen
USE_KEYS = os.environ.get("TINYQ_NO_KEYS") is None


def connect():
    db = sqlite3.connect("world.db", isolation_level=None, timeout=30)
    db.execute("PRAGMA journal_mode = WAL")
    db.executescript("""
        CREATE TABLE IF NOT EXISTS mail_delivered (
            to_address TEXT NOT NULL, subject TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS bank_accounts (
            name TEXT PRIMARY KEY, balance INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS seen_keys (
            idempotency_key TEXT PRIMARY KEY);
        CREATE TABLE IF NOT EXISTS stats (
            name TEXT PRIMARY KEY, value INTEGER NOT NULL);
    """)
    return db


def _bump(db, name):
    db.execute("INSERT INTO stats VALUES (?, 1) ON CONFLICT (name) "
               "DO UPDATE SET value = value + 1", (name,))


def _call(effect, idempotency_key):
    """Run `effect(db)` once per key, with a flaky network around it."""
    roll = random.random()
    if roll < FAIL_BEFORE:
        raise ConnectionError("request never arrived")
    db = connect()
    if not USE_KEYS:
        idempotency_key = os.urandom(8).hex()   # a key that never repeats
    db.execute("BEGIN IMMEDIATE")
    fresh = db.execute("INSERT OR IGNORE INTO seen_keys VALUES (?)",
                       (idempotency_key,)).rowcount == 1
    if fresh:
        effect(db)
    else:
        _bump(db, "duplicates_absorbed")
    db.execute("COMMIT")
    db.close()
    if roll < FAIL_BEFORE + FAIL_AFTER:
        raise TimeoutError("reply never came back")


def send_email(to, subject, idempotency_key):
    _call(lambda db: db.execute("INSERT INTO mail_delivered VALUES (?, ?)",
                                (to, subject)), idempotency_key)


def charge(account, amount, idempotency_key):
    _call(lambda db: db.execute(
        "UPDATE bank_accounts SET balance = balance - ? WHERE name = ?",
        (amount, account)), idempotency_key)
