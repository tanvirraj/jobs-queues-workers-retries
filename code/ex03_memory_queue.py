# Exercise 3: A queue that lives in memory.
# The signup now returns instantly. A background thread does the slow part.
#
#   python3 ex03_memory_queue.py          # waits for the worker to finish
#   python3 ex03_memory_queue.py --quit   # exits early: watch the jobs vanish

import queue
import sys
import threading
import time

jobs = queue.Queue()


def send_welcome_email(address):
    time.sleep(1)
    print(f"    [worker] sent welcome email to {address}")


def worker():
    while True:
        job = jobs.get()          # blocks until a job is available
        send_welcome_email(**job["args"])
        jobs.task_done()          # tell the queue this one is finished


def signup(address):
    started = time.time()
    print(f"creating account for {address}")
    jobs.put({"kind": "send_welcome_email", "args": {"address": address}})
    print(f"  signup finished in {time.time() - started:.3f}s")


# daemon=True means "do not keep the program alive just for this thread"
threading.Thread(target=worker, daemon=True).start()

for address in ["ada@example.com", "alan@example.com", "grace@example.com"]:
    signup(address)

if "--quit" in sys.argv:
    print(f"main program exiting with {jobs.qsize()} job(s) still waiting...")
    sys.exit(0)

jobs.join()                       # wait until every job is task_done()
print("all jobs done")
