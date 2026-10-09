"""Chaos test: run workers that randomly die, then audit the books.

    python3 chaos.py                  # idempotency keys ON
    TINYQ_NO_KEYS=1 python3 chaos.py  # keys OFF: watch the audit fail
"""

import os
import subprocess
import sys
import time

CUSTOMERS = 20
WORKERS = 3
CHAOS = "0.1"

for name in ("shop.db", "shop.db-wal", "shop.db-shm",
             "world.db", "world.db-wal", "world.db-shm"):
    if os.path.exists(name):
        os.remove(name)

emails = [f"customer{i:02}@example.com" for i in range(CUSTOMERS)]
subprocess.run([sys.executable, "shop.py", "signup", *emails], check=True)
print(f"signed up {CUSTOMERS} customers -> {CUSTOMERS * 3} jobs queued")
print(f"running {WORKERS} workers that crash at random (chaos={CHAOS})\n")


def spawn():
    return subprocess.Popen([sys.executable, "shop.py", "work", "--chaos", CHAOS])


workers = [spawn() for _ in range(WORKERS)]
crashes = 0
started = time.time()
while workers:
    time.sleep(0.05)
    for worker in list(workers):
        code = worker.poll()
        if code is None:
            continue
        workers.remove(worker)
        if code != 0:            # it crashed: the supervisor starts a new one
            crashes += 1
            workers.append(spawn())

# --- the audit -----------------------------------------------------------------
import sqlite3  # noqa: E402

shop = sqlite3.connect("shop.db")
world = sqlite3.connect("world.db")
counts = dict(shop.execute("SELECT status, count(*) FROM jobs GROUP BY status"))
retried = shop.execute("SELECT count(*) FROM jobs WHERE attempts > 1").fetchone()[0]
absorbed = (world.execute("SELECT value FROM stats WHERE name = "
                          "'duplicates_absorbed'").fetchone() or [0])[0]

problems = []
for email in emails:
    emails_sent = world.execute("SELECT count(*) FROM mail_delivered "
                                "WHERE to_address = ?", (email,)).fetchone()[0]
    balance = world.execute("SELECT balance FROM bank_accounts WHERE name = ?",
                            (email,)).fetchone()[0]
    points = shop.execute("SELECT points FROM customers WHERE email = ?",
                          (email,)).fetchone()[0]
    if emails_sent != 1:
        problems.append(f"{email}: got {emails_sent} welcome emails (want 1)")
    if balance != 95:
        problems.append(f"{email}: balance ${balance} (want $95)")
    if points != 10:
        problems.append(f"{email}: {points} points (want 10)")

print(f"\nfinished in {time.time() - started:.1f}s")
print(f"worker crashes:                 {crashes}")
print(f"jobs by status:                 {counts}")
print(f"jobs that needed >1 attempt:    {retried}")
print(f"duplicates absorbed by keys:    {absorbed}")
print()
if problems:
    print(f"AUDIT FAILED: {len(problems)} problem(s)")
    for problem in problems[:10]:
        print("  " + problem)
else:
    print("AUDIT PASSED: every customer got exactly 1 email, "
          "paid exactly $5, and has exactly 10 points.")
