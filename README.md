# Jobs, Queues, Workers, and Retries

### Doing work later, doing it reliably, and (almost) never doing it twice

*A hands-on guide in ten chapters and nine exercises. It assumes you know nothing about the topic and a little Python.*

> **Read the interactive version online: https://tanvirraj.github.io/jobs-queues-workers-retries/** (or open [`guide.html`](./guide.html) locally in a browser). It has the same text, plus simulations you can poke at: a live queue with workers you can kill, a race condition you can step through, a crash-timing explorer, and a payment simulator. (It is generated from this file: after editing, run `python3 tools/build.py`, which needs [pandoc](https://pandoc.org).)

---

## Table of Contents

0. [How to Use This Guide](#0-how-to-use-this-guide)
1. [The Waiter Who Cooks](#1-the-waiter-who-cooks)
2. [The Job: Work Written Down](#2-the-job-work-written-down)
3. [The Queue: Where Work Waits](#3-the-queue-where-work-waits)
4. [The Worker: Where Work Happens](#4-the-worker-where-work-happens)
5. [When Workers Die: Leases](#5-when-workers-die-leases)
6. [Retry: Trying Again, Politely](#6-retry-trying-again-politely)
7. [The Tricky Question: Did It Happen?](#7-the-tricky-question-did-it-happen)
8. [Idempotency: Making Repeats Harmless](#8-idempotency-making-repeats-harmless)
9. [Capstone: tinyq and the Chaos Monkey](#9-capstone-tinyq-and-the-chaos-monkey)
10. [The Real World](#10-the-real-world)
11. [Glossary](#glossary)

---

## 0. How to Use This Guide

This guide teaches four ideas. A **job** is a message describing work to do. A **queue** is where that message waits until it can be processed. A **worker** is running code that takes a job and performs the work. A **retry** is another attempt after a failure. The first three ideas are simple and you will understand them within an hour. The fourth one hides a question that has troubled engineers for decades: *if I do this work again, could I end up doing it twice?* Most of this guide is about that question, because that is where real systems break and where real money goes missing.

You will not learn this by reading. You will learn it by building a small job queue from nothing, breaking it on purpose, and fixing it, one exercise at a time. Each exercise follows the same pattern, borrowed from Zed Shaw's *Learn Code the Hard Way* books, and the pattern matters more than it looks.

First, **type the code in yourself**. Do not copy and paste. The code is in the `code/` folder so you can check your work, but your fingers need to write it. Typing makes you read every line, and you will make small mistakes that teach you more than the code does. Second, **run it and compare with "What You Should See"**. If your output differs, find out why before going on. That difference is the lesson. Third, **do the Study Drills**. They ask you to change the code and predict what happens. Fourth, **Break It**. Each exercise has a section where you deliberately make the system fail. Engineers who have only seen a system work do not understand it. Engineers who have seen it fail in five different ways do.

Between exercises you will find **Pause and Check** boxes. They are questions, and the answers are folded away. Answer in your head, or better on paper, before you look. If you got one wrong, reread the section above it. Nothing later will make sense if an earlier layer is shaky. We build this like a staircase, and each step stands on the one below it.

You need Python 3.10 or newer and a terminal. Everything uses Python's standard library, including SQLite, which ships with Python. There is nothing to install.

```
code/
├── ex01_slow_signup.py      Chapter 1   the problem
├── ex02_jobs.py             Chapter 2   jobs are data
├── ex03_memory_queue.py     Chapter 3   a queue in memory
├── ex04_durable_queue.py    Chapter 3-4 a queue on disk, a worker loop
├── ex05_two_workers.py      Chapter 4   a race between workers
├── ex06_leases.py           Chapter 5   crashes and leases
├── ex07_retries.py          Chapter 6-7 retries, and the money goes missing
├── ex08_idempotency.py      Chapter 8   idempotency keys
└── capstone/                Chapter 9   everything together, under fire
    ├── tinyq.py
    ├── world.py
    ├── shop.py
    └── chaos.py
```

Before we write any code, here is the whole map. Do not worry if it means little yet. By the end of the guide you will be able to draw it from memory, and explain what goes wrong at every arrow.

```
                         THE WHOLE STORY ON ONE PAGE

   ┌──────────┐   enqueue    ┌─────────────────────────┐    claim    ┌──────────┐
   │ Producer │ ───────────▶ │          QUEUE          │ ──────────▶ │  Worker  │
   │ (web app)│   a JOB      │  ┌───┐┌───┐┌───┐┌───┐   │   a JOB     │ (process)│
   └──────────┘              │  │ J ││ J ││ J ││ J │   │             └────┬─────┘
                             │  └───┘└───┘└───┘└───┘   │                  │ do the work
                             └───────────▲─────────────┘                  ▼
                                         │                         ┌─────────────┐
                                         │    ack ("done!")        │ The World:  │
                                         └──────────────────────── │ email, bank,│
                                         │                         │ database... │
                                         │    fail → RETRY later   └─────────────┘
                                         └──────────────────────────────┘

        The hard part lives in the gap between "do the work" and "ack".
```

---

## 1. The Waiter Who Cooks

Imagine a restaurant with one employee. You walk in, sit down, and order a burger. The waiter writes nothing down. They walk to the kitchen, cook your burger for twelve minutes, bring it to you, and only then go to greet the family that has been standing at the door all this time. This restaurant has a clear problem, and you can see it instantly: the person *taking* the order is also the person *doing* the order, so nobody else can be served while the work happens.

Real restaurants solve this with a piece of paper. The waiter writes your order on a ticket, clips it to a rail above the kitchen, and goes straight back to the dining room. A cook takes the ticket off the rail when they are free. The waiter and the cook never wait for each other. If ten tables order at once, the rail fills up with tickets, the cooks work through them as fast as they can, and nobody standing at the door is ignored.

```
   THE WAITER WHO COOKS                       THE TICKET RAIL

   guest ─▶ waiter ─▶ (cooks 12 min)          guest ─▶ waiter ─▶ [ticket]─┐
             │                                          │                 │
             └─▶ next guest waits 12 min                └─▶ next guest    ▼
                                                            served   ┌──────────┐
                                                            NOW      │ rail:    │
                                                                     │ ▯ ▯ ▯ ▯  │
                                                                     └────┬─────┘
                                                                          ▼
                                                                    cook takes one
```

Hold onto this picture, because this whole guide is that ticket rail. The ticket is the **job**. The rail is the **queue**. The cook is the **worker**. When a cook burns a burger and makes it again, that is a **retry**. And when a ticket accidentally gets cooked twice, so a table receives two burgers and is billed for both, that is the **duplicate** problem we will spend half this guide on.

Web applications have exactly this problem. When someone signs up for your website, you might need to create their account, send a welcome email, resize their profile photo, and notify your sales team. Creating the account takes a few milliseconds. Sending the email means talking to an email provider over the internet, which might take two seconds, or thirty, or fail entirely. If your web server does all of that while the user stares at a spinning wheel, you have built the waiter who cooks.

### Exercise 1: The Waiter Who Cooks

Type this into `ex01_slow_signup.py`:

```python
# Exercise 1: The waiter who cooks.
# A signup that does ALL of its work while the user waits.

import time


def send_welcome_email(address):
    time.sleep(2)  # pretend the mail server is slow today
    print(f"    sent welcome email to {address}")


def signup(address):
    started = time.time()
    print(f"creating account for {address}")
    send_welcome_email(address)  # the user is staring at a spinner here
    print(f"  signup finished in {time.time() - started:.1f}s")


for address in ["ada@example.com", "alan@example.com", "grace@example.com"]:
    signup(address)
```

#### What You Should See

```
$ python3 ex01_slow_signup.py
creating account for ada@example.com
    sent welcome email to ada@example.com
  signup finished in 2.0s
creating account for alan@example.com
    sent welcome email to alan@example.com
  signup finished in 2.0s
creating account for grace@example.com
    sent welcome email to grace@example.com
  signup finished in 2.0s
```

Each signup takes two full seconds, and the second user cannot even start until the first one finishes. Three users take six seconds. A thousand users arriving in the same minute would wait over half an hour.

#### Study Drills

Change the sleep to `time.sleep(30)`, which is roughly what happens when an email provider is having a bad day, and imagine you are the user. Then add a line in `send_welcome_email` that does `raise ConnectionError("mail server down")` and run it again. Notice that the *signup itself* now crashes, even though creating the account worked fine. A slow, unreliable thing that the user does not care about right now has taken down a fast, reliable thing that they do care about. That coupling is the real problem.

<!-- widget:waiter -->

> **Pause and Check 1.1.** In the restaurant analogy, what are the two different jobs the waiter was doing, and which one does the guest actually need to wait for?
>
> <details><summary>Answer</summary>
>
> The waiter was *taking the order* and *cooking the order*. The guest needs to wait for the order to be taken (they want to know it was received), but they do not need to stand there watching it be cooked. In a web app, the user needs to know "your account was created", but they do not need to wait while the welcome email travels across the internet. Splitting "accept the request" from "do the slow work" is the entire motivation for job queues.
> </details>

---

## 2. The Job: Work Written Down

The restaurant's breakthrough was not hiring a cook. It was the *ticket*. Before the ticket existed, the order lived only in the waiter's head, and the only way to get it to the kitchen was for the waiter to walk there and do it themselves. Once the order was written down, it became a *thing* that could be handed over, set aside, read by someone else, and acted on later.

That is what a job is. **A job is a message describing work to do.** It is not the work itself. It is a description of the work, written in a form that something else can read later and act upon. This distinction feels pedantic at first, so let us make it concrete.

When you call `send_welcome_email("ada@example.com")` in Python, the work happens *right now*, *in this process*, and when it is done it is gone. There is no object you can point at and say "that is the email-sending". A function call is an action, like speaking a word out loud. A job is more like writing the word on paper. Here is the same intent, written down:

```json
{ "kind": "send_welcome_email", "args": { "address": "ada@example.com" } }
```

This is just data. It is not alive. It does not do anything. But because it is just data, you can do things with it that you cannot do with a function call. You can save it to a file. You can send it to another computer. You can keep it for a week and run it on Tuesday. You can look at a list of a thousand of them and count how many are about emails. You can run it, see it fail, and run the exact same description again.

```
     AN ACTION (function call)                 A MESSAGE (job)

     send_welcome_email("ada@…")              {"kind": "send_welcome_email",
            │                                  "args": {"address": "ada@…"}}
            ▼                                          │
     happens NOW, HERE,                        can be stored, copied, sent,
     then it's gone                            inspected, delayed, retried
```

Of course, a description is useless if no one knows how to carry it out. The cook needs to know what "burger, no onions" means. In code, we keep a table that maps each kind of job to the function that knows how to do it. Those functions are called **handlers**. The job says *what*. The handler knows *how*.

### Exercise 2: Jobs Are Data

Type this into `ex02_jobs.py`:

```python
# Exercise 2: A job is a message, not an action.
# We split "what to do" (data) from "how to do it" (code).

import json
import time


# --- the "how": ordinary functions, called handlers -------------------------

def send_welcome_email(address):
    time.sleep(0.5)
    print(f"    sent welcome email to {address}")


def resize_photo(path, width):
    time.sleep(0.5)
    print(f"    resized {path} to {width}px wide")


HANDLERS = {
    "send_welcome_email": send_welcome_email,
    "resize_photo": resize_photo,
}


# --- the "what": a job is just a dictionary --------------------------------

def make_job(kind, **args):
    return {"kind": kind, "args": args}


def run(job):
    handler = HANDLERS[job["kind"]]
    handler(**job["args"])


job = make_job("send_welcome_email", address="ada@example.com")
print("the job as a Python dict:  ", job)

# Because a job is plain data, we can turn it into text...
text = json.dumps(job)
print("the job as text on the wire:", text)

# ...store it, send it to another computer, keep it for a week, and later
# turn it back into data and run it. Nothing about it is "alive".
again = json.loads(text)
print("running it:")
run(again)

run(make_job("resize_photo", path="cat.jpg", width=200))
```

#### What You Should See

```
$ python3 ex02_jobs.py
the job as a Python dict:   {'kind': 'send_welcome_email', 'args': {'address': 'ada@example.com'}}
the job as text on the wire: {"kind": "send_welcome_email", "args": {"address": "ada@example.com"}}
running it:
    sent welcome email to ada@example.com
    resized cat.jpg to 200px wide
```

The interesting line is the middle one. The job became a string of text. Text can go anywhere: into a file, into a database, across a network. Then `json.loads` turned it back into data and we ran it. In between, the job was completely inert. That inertness is the superpower.

#### What Makes a Good Job

Now that you know a job is a written description, you can ask what makes a *good* one, the same way a restaurant learns what makes a good ticket. Three rules cover most of it.

A good job carries **references, not snapshots**. Write `{"user_id": 42}`, not a copy of the entire user record. The job might sit in the queue for minutes, and by the time a worker reads it the user may have changed their email address. If the job carries an ID, the worker looks up the current address when it runs. A ticket that says "table 7" is better than a ticket with a drawing of the people at table 7.

A good job is **self-contained**. Everything the worker needs to know must be in the message, or reachable from it through a lookup. The worker is a different process, possibly on a different computer, possibly started next week. It shares no memory with the code that created the job. It cannot ask "what did you mean?"

A good job is **small and boring**. Plain strings and numbers that serialize cleanly to JSON. Not open file handles, not database connections, not Python objects that only make sense inside the process that made them. A ticket is a few words on paper, not the ingredients.

There is a fourth property, the most important of all, but you are not ready for it yet. It concerns what happens if the same job is carried out twice. We will come back to it in Chapter 8 with a name: *idempotency*.

<!-- widget:job-anatomy -->

> **Pause and Check 2.1.** A colleague writes a job like this: `{"kind": "charge_card", "args": {"card": <a live connection object to the payment provider>, "amount": 10}}`. Name two things wrong with it.
>
> <details><summary>Answer</summary>
>
> First, a live connection object cannot be turned into text, so the job cannot be stored or sent to another process. It is not really a message at all. Second, even if it could be serialized, the connection would be meaningless in a different process or after a delay. The job should carry plain data that lets the worker *re-create* what it needs: something like `{"customer_id": 42, "amount_cents": 1000, "order_id": 9001}`. (You will see in Chapter 8 why that `order_id` is far more important than it looks.)
> </details>

> **Pause and Check 2.2.** Why is it better for a job to say `{"user_id": 42}` than to include the user's email address directly?
>
> <details><summary>Answer</summary>
>
> Because time passes between writing the job and running it. If the user changes their email address in the meantime, a job carrying the old address would send to the wrong place. Carrying an ID means the worker always fetches the *current* truth at the moment it does the work. (There are exceptions. Sometimes you deliberately want a snapshot, like "the price at the moment they clicked Buy". The point is to choose consciously.)
> </details>

---

## 3. The Queue: Where Work Waits

We have tickets. Now we need a rail to clip them to. **A queue is where a job waits until it can be processed.** The word "queue" means a line of people, and the default behaviour is the same: first in, first out. The job that arrived first is handed out first.

```
                      A QUEUE (first in, first out)

   enqueue ──▶ ┌────┬────┬────┬────┬────┐ ──▶ dequeue
   (back)      │ J5 │ J4 │ J3 │ J2 │ J1 │     (front)
               └────┴────┴────┴────┴────┘
                newest               oldest: next to be worked on
```

The queue does something subtle and powerful. It **decouples** the producer, the code that creates jobs, from the consumer, the code that does them. The waiter no longer needs to know which cook will make the burger, or when, or whether the cooks are busy. The waiter's only responsibility is to clip the ticket on the rail. Everything after that is someone else's problem.

Decoupling buys you three things, and it is worth naming each one, because they are the reasons companies adopt queues.

The first is **speed for the user**. The producer finishes as soon as the job is written down. The user is told "done" in milliseconds.

The second is **absorbing bursts**. Suppose a hundred people sign up in the same second because your app was mentioned on television, but you can only send ten emails per second. Without a queue, ninety requests fail or time out. With a queue, all hundred jobs are written down instantly, and the workers drain the backlog over the next ten seconds. The queue acts like a reservoir behind a dam. Water arrives in floods, and leaves at a steady rate.

```
   jobs arriving per second              jobs processed per second
   (bursty)                              (steady)

   100 │    █                            100 │
       │    █                                │
    50 │    █                             50 │
       │    █        █                       │
    10 │ ▁  █  ▁  ▁  █  ▁                 10 │ ▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆
       └──────────────────▶ time             └──────────────────────▶ time
                     ╲                       ╱
                      ╲   ┌─────────────┐   ╱
                       ╲─▶│ the queue   │──╱    the queue absorbs the
                          │ fills, then │       difference, like a reservoir
                          │ drains      │
                          └─────────────┘
```

The third is **isolating failure**. If the email provider goes down for ten minutes, the email jobs simply wait in the queue. Signups keep working. When the provider comes back, the workers catch up. The slow, unreliable part of your system can no longer take down the fast, reliable part. That was the exact problem you created in Exercise 1's study drills.

### Exercise 3: A Queue in Memory

Python's standard library already has a queue, `queue.Queue`, designed for passing work between threads in the same program. Let us use it to move the email sending off to a background thread. Type this into `ex03_memory_queue.py`:

```python
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
```

#### What You Should See

```
$ python3 ex03_memory_queue.py
creating account for ada@example.com
  signup finished in 0.000s
creating account for alan@example.com
  signup finished in 0.000s
creating account for grace@example.com
  signup finished in 0.000s
    [worker] sent welcome email to ada@example.com
    [worker] sent welcome email to alan@example.com
    [worker] sent welcome email to grace@example.com
all jobs done
```

Look at the timings. Every signup now finishes in under a millisecond. The emails still take a second each, but nobody is waiting for them. The waiter has stopped cooking.

#### Break It

Now run it with `--quit`, which simulates the program stopping, whether from a deploy, a crash, or someone pressing Ctrl-C:

```
$ python3 ex03_memory_queue.py --quit
creating account for ada@example.com
  signup finished in 0.000s
creating account for alan@example.com
  signup finished in 0.000s
creating account for grace@example.com
  signup finished in 0.000s
main program exiting with 3 job(s) still waiting...
```

(You may see 2 instead of 3, if the worker grabbed the first job before the program quit. Either way, no emails went out.)

Three users were told "your account is ready". None of them will ever get the welcome email, and no record exists anywhere that they should have. The jobs lived in the program's memory, and memory is erased when a program ends. This is like a restaurant whose ticket rail is made of soap bubbles. It works beautifully until someone opens a door.

### Durability: Writing the Tickets in Ink

The fix is to keep the queue somewhere that survives a restart: on disk. A queue that survives crashes is called **durable**. Dedicated systems like RabbitMQ and Amazon SQS exist for this, but you already have a durable store sitting in Python's standard library: SQLite, a complete database in a single file. A queue is just a table where each row is a job.

```
   jobs table (in ex04.db, a file on disk)

   ┌────┬─────────────────────┬──────────────────────────────┬─────────┐
   │ id │ kind                │ args                         │ status  │
   ├────┼─────────────────────┼──────────────────────────────┼─────────┤
   │  1 │ send_welcome_email  │ {"address":"ada@example.com"}│ done    │
   │  2 │ send_welcome_email  │ {"address":"alan@example…"}  │ running │
   │  3 │ send_welcome_email  │ {"address":"grace@exampl…"}  │ queued  │
   └────┴─────────────────────┴──────────────────────────────┴─────────┘

   Each job moves through a tiny state machine:

        queued ───claim───▶ running ───finish───▶ done
```

The `status` column is the important addition. In the in-memory queue, a job that was taken out of the queue simply vanished from it. In our table, a job is never deleted; it moves from `queued` to `running` to `done`. That gives us a record of where every job is in its life. The next exercise builds this queue, and the worker that consumes it, so it belongs to the next chapter.

> **Pause and Check 3.1.** A friend says "a queue just makes things slower, because the work still has to happen eventually". Are they right?
>
> <details><summary>Answer</summary>
>
> Partly. The *total* amount of work does not shrink, and each individual job may actually finish a little later than it would have if done immediately. But a queue changes *who waits* and *what fails together*. The user no longer waits for slow work, bursts are smoothed out instead of rejected, and a failure in the slow work no longer breaks the fast path. Queues trade latency of background work for responsiveness and resilience of the foreground.
> </details>

> **Pause and Check 3.2.** In Exercise 3 the queue was in memory. List the everyday events that would destroy the jobs waiting in it.
>
> <details><summary>Answer</summary>
>
> Anything that ends the process: deploying a new version of the code, the server rebooting, the process running out of memory and being killed by the operating system, an unhandled exception in the main thread, someone pressing Ctrl-C, the machine losing power. In production, at least one of these happens every single day. That is why real job queues are durable.
> </details>

---

## 4. The Worker: Where Work Happens

**A worker is running code that takes a job and performs the work.** Notice the word *running*. A handler is a function sitting in a file, like a recipe in a cookbook. A worker is a live process executing a loop, like a cook standing in the kitchen. The cook uses recipes. The worker uses handlers.

Every worker in the world, from a forty-line Python script to the systems at the largest tech companies, runs some version of the same loop:

```
                       THE WORKER LOOP

               ┌──────────────────────────────────┐
               │                                  │
               ▼                                  │
        ┌─────────────┐   nothing?   ┌────────┐   │
        │ 1. CLAIM a  │ ───────────▶ │ sleep  │ ──┘
        │    job      │              └────────┘
        └──────┬──────┘
               │ got one
               ▼
        ┌─────────────┐
        │ 2. DO the   │   (call the handler: send the email,
        │    work     │    charge the card, resize the photo)
        └──────┬──────┘
               ▼
        ┌─────────────┐
        │ 3. ACK: mark│   ("acknowledge": tell the queue
        │    it done  │    this job is finished)
        └──────┬──────┘
               │
               └──────────────▶ back to 1
```

Claim, do, acknowledge, repeat. Memorize this. Every hard problem in this guide happens at one of these three steps, or in the gaps between them.

### Exercise 4: A Durable Queue and a Worker

Type this into `ex04_durable_queue.py`. It is longer than the previous ones, but most of it is the small command-line interface at the bottom.

```python
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
```

Our "email" is a line appended to a file called `outbox.txt`. That is deliberate. It is a side effect you can see and count, which will matter enormously later.

#### What You Should See

This exercise uses two terminal windows. That is the point: the producer and the worker are separate programs that never talk to each other directly. They only share the queue.

In the first terminal, enqueue two jobs *without any worker running*, and look at the queue:

```
$ python3 ex04_durable_queue.py enqueue ada@example.com alan@example.com
enqueued 2 job(s)
$ python3 ex04_durable_queue.py list
  1   send_welcome_email   {"address": "ada@example.com"}       queued
  2   send_welcome_email   {"address": "alan@example.com"}      queued
```

The program that enqueued the jobs has *exited*. The jobs are still there, written in ink. Now, in the second terminal, start a worker:

```
$ python3 ex04_durable_queue.py work
worker 846 waiting for jobs (Ctrl-C to stop)
  job 1: send_welcome_email {"address": "ada@example.com"}
    sent welcome email to ada@example.com
  job 2: send_welcome_email {"address": "alan@example.com"}
    sent welcome email to alan@example.com
```

Leave the worker running and go back to the first terminal. Enqueue another address and watch it appear in the worker's window a moment later. Then list the queue and look at the outbox:

```
$ python3 ex04_durable_queue.py list
  1   send_welcome_email   {"address": "ada@example.com"}       done
  2   send_welcome_email   {"address": "alan@example.com"}      done
$ cat outbox.txt
welcome email -> ada@example.com
welcome email -> alan@example.com
```

#### Break It

Enqueue one more job. Start the worker, and press Ctrl-C *while it is in the middle of sending*, during the two-second sleep. Then list the queue.

```
$ python3 ex04_durable_queue.py enqueue grace@example.com
$ python3 ex04_durable_queue.py work
worker 854 waiting for jobs (Ctrl-C to stop)
  job 3: send_welcome_email {"address": "grace@example.com"}
^C
worker stopped
$ python3 ex04_durable_queue.py list
  1   send_welcome_email   {"address": "ada@example.com"}       done
  2   send_welcome_email   {"address": "alan@example.com"}      done
  3   send_welcome_email   {"address": "grace@example.com"}     running
```

Job 3 says `running`. But nothing is running it. The worker that claimed it is gone. Start the worker again, and it will ignore job 3 forever, because it only looks for `queued` jobs. Grace will never get her email. This is better than Exercise 3, because at least there is a *record* of the problem. A human could find it. But it is not yet a system that heals itself. Remember this stuck job; Chapter 5 is about it.

### Many Workers, and a Race

One worker processes one job at a time. If each email takes two seconds, one worker can send thirty emails a minute. If you need three hundred a minute, the solution is to run ten workers. This is one of the most beautiful properties of the queue design: **you scale by adding workers**, and the producer does not need to change at all. The restaurant hires more cooks; the waiters keep clipping tickets to the same rail.

```
                                ┌──────────┐
                           ┌───▶│ worker A │
   ┌───────────────────┐   │    └──────────┘
   │ queue: J5 J4 J3 … │───┼───▶│ worker B │
   └───────────────────┘   │    └──────────┘
                           └───▶│ worker C │
                                └──────────┘
```

But there is a trap in our worker loop, and it is the first truly subtle bug in this guide. Look at how our worker claims a job. It does it in two steps. First it *looks*: `SELECT ... WHERE status = 'queued' LIMIT 1`. Then it *grabs*: `UPDATE ... SET status = 'running'`. Between those two steps, another worker can look at the same table and see the same job still marked `queued`.

Picture two cooks who both glance at the rail at the same instant, both see the burger ticket at the front, and both turn around to start cooking it before either one has taken the ticket off the rail. Table 7 gets two burgers.

```
   time ──────────────────────────────────────────────────────────▶

   Worker A:  SELECT → "job 1 is queued"        UPDATE job 1 → running   send email
   Worker B:        SELECT → "job 1 is queued"        UPDATE job 1 → running   send email
                          ▲
                          └── both saw it queued. Both think it is theirs.
                              Ada gets TWO welcome emails.
```

This is called a **race condition**: the result depends on the precise timing of two things racing each other. The pattern of looking at something and then acting on what you saw, when the world can change in between, is so common that it has its own name: **check-then-act**. It is one of the most frequent bugs in all of software.

### Exercise 5: Two Workers, One Job

In this exercise we will create the race on purpose, watch it happen, and fix it. Type in `ex05_two_workers.py`. It has two different claim functions so you can compare them.

```python
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
```

The `time.sleep(0.3)` in `claim_naive` is a magnifying glass. In real systems the gap between the SELECT and the UPDATE is a fraction of a millisecond, so the race happens rarely, perhaps once in ten thousand jobs. Rare bugs are the worst kind: they slip through every test and then appear in production on a busy Monday. The sleep makes the gap wide enough that the race happens every time, so you can see it.

#### What You Should See

Reset, enqueue four jobs, and start `work naive` in two terminals at nearly the same time. Wait a few seconds, stop both, and sort the outbox:

```
$ sort outbox.txt
welcome email -> a@x.com   (worker 989)
welcome email -> a@x.com   (worker 990)
welcome email -> b@x.com   (worker 989)
welcome email -> b@x.com   (worker 990)
welcome email -> c@x.com   (worker 989)
welcome email -> c@x.com   (worker 990)
welcome email -> d@x.com   (worker 989)
welcome email -> d@x.com   (worker 990)
```

Every single customer received two emails, one from each worker. Now reset, enqueue the same four jobs, and use `work atomic` in both terminals:

```
$ sort outbox.txt
welcome email -> a@x.com   (worker 1014)
welcome email -> b@x.com   (worker 1013)
welcome email -> c@x.com   (worker 1013)
welcome email -> d@x.com   (worker 1014)
```

Exactly one email each, and the work was split between the two workers. That is what we want.

#### Why the Atomic Version Works

`claim_atomic` folds "look" and "grab" into a single SQL statement. The database guarantees that a single statement is **atomic**: it happens completely or not at all, and no other writer can slip in halfway through. The word comes from the Greek *atomos*, "uncuttable". In SQLite, only one writer can hold the write lock at a time, so the second worker's UPDATE waits until the first one has finished, and by then job 1 is already `running` and no longer matches `WHERE status = 'queued'`. The second worker gets job 2 instead.

```
   time ───────────────────────────────────────────────────────▶

   Worker A:  [ UPDATE…WHERE queued → got job 1 ]
   Worker B:                    (waits for lock) [ UPDATE…WHERE queued → got job 2 ]
                                                   ▲
                                                   job 1 is already 'running',
                                                   so B's WHERE skips it
```

In a restaurant, this is the rule that you must *physically take the ticket off the rail* before you start cooking. Glancing at it is not enough. The act of taking it is what makes it yours, and only one hand can hold a ticket. In PostgreSQL, the same trick is usually written `SELECT ... FOR UPDATE SKIP LOCKED`, which lets many workers claim different rows at once without waiting on each other. In dedicated queue systems like RabbitMQ or SQS, the queue server does the claiming for you, and handing a message to one consumer hides it from the others.

<!-- widget:race -->

> **Pause and Check 4.1.** Without looking back, name the three steps of the worker loop, and say which step the race condition in Exercise 5 lived in.
>
> <details><summary>Answer</summary>
>
> Claim, do, ack. The race lived in *claim*: because claiming was split into a separate look and grab, two workers could both claim the same job.
> </details>

> **Pause and Check 4.2.** The race in `claim_naive` only happened because of the `sleep(0.3)`. Without it, the gap is microseconds. A teammate argues "so the naive version is fine in practice". What do you say?
>
> <details><summary>Answer</summary>
>
> A microsecond gap is still a gap. With many workers and millions of jobs, two workers *will* eventually hit it at the same time, and when they do the result is a duplicate email or, worse, a duplicate payment. The bug will be rare, impossible to reproduce on demand, and expensive. A correct design makes the bad outcome *impossible*, not just unlikely. The sleep only made an existing bug visible; it did not create it.
> </details>

---

## 5. When Workers Die: Leases

Remember Grace? In Exercise 4 you killed a worker in the middle of a job, and her job was left saying `running` forever, with nobody running it. Our atomic claim fixed duplicate claims, but it did nothing for this. In fact the two problems pull in opposite directions. To prevent duplicates, we made sure that once a job is claimed, nobody else can touch it. But if the claimer dies, "nobody else can touch it" means it is stuck forever.

Workers die all the time. You deploy a new version of your code and the old workers are stopped. The operating system kills a worker for using too much memory. A server loses power. A cloud provider reclaims a machine. In a system with a hundred workers, some worker is dying almost every hour. So the question is not whether a worker will die holding a job, but what happens to the job when it does.

Here is the difficulty. From the outside, a dead worker and a slow worker look identical. Both are silent. If a job has been `running` for ten minutes, the queue cannot tell whether the worker is still bravely sending a very large email, or whether it died nine minutes ago. There is no reliable way to tell the difference across a network. This is not a limitation of our code; it is a fundamental property of distributed systems.

### The Lease

The standard answer is a **lease**: a claim that expires. When a worker claims a job, it does not take it forever. It takes it *until a deadline*, say five minutes from now. If the worker finishes and acks before the deadline, all is well. If the deadline passes and the job is still `running`, the queue assumes the worker is dead and lets someone else claim the job.

Think of a library book. You do not own it; you borrow it until a due date. If you vanish and never return it, the library does not wait forever. After the due date, they consider it lost and get another copy for the next reader. Or think of a hotel room key card that stops working at noon on checkout day, whether or not you remembered to leave.

```
                         A JOB WITH A LEASE

   claim at 12:00, lease = 5 min
   ├───────────────── lease held by worker A ─────────────────┤
   12:00                                                     12:05
     │                                                         │
     │  Case 1: A acks at 12:02          ──▶ done. Lease irrelevant.
     │
     │  Case 2: A crashes at 12:01  ✝    ··· silence ···       │
     │                                                         ▼
     │                                          lease expires. Worker B
     │                                          may claim the job. ✓
```

Amazon SQS calls this the *visibility timeout*: a message handed to a consumer becomes invisible to other consumers for a while, and reappears if it is not deleted in time. Other systems call it a lock timeout, a reservation, or an ack deadline. The name changes; the idea is the same.

<!-- widget:lease-sim -->

### Exercise 6: Crashes and Leases

Type in `ex06_leases.py`. The claim query has grown a second condition: it will take a job that is `queued`, *or* a job that is `running` but whose lease has expired. The worker also has two ways to "pull the plug" on itself, using `os._exit(1)`, which kills the process instantly with no cleanup, like a power cut.

```python
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
```

#### What You Should See

First, crash the worker *before* it sends the email. Then look at the queue twice, once immediately and once after five seconds:

```
$ python3 ex06_leases.py reset
$ python3 ex06_leases.py enqueue ada@example.com
$ python3 ex06_leases.py work --crash-before-send
worker 1077 lease=5s (Ctrl-C to stop)
  job 1 attempt 1: send_welcome_email {"address": "ada@example.com"}
    *** power cut BEFORE the email was sent ***
$ python3 ex06_leases.py list
  1   {"address": "ada@example.com"}   running  attempts=1 lease 3.9s left
$ sleep 5; python3 ex06_leases.py list
  1   {"address": "ada@example.com"}   running  attempts=1 lease EXPIRED
```

Now start a healthy worker. It sees the expired lease and takes over the job:

```
$ python3 ex06_leases.py work
worker 1078 lease=5s (Ctrl-C to stop)
  job 1 attempt 2: send_welcome_email {"address": "ada@example.com"}
    sent welcome email to ada@example.com
^C
$ cat outbox.txt
welcome email -> ada@example.com
```

The system healed itself. Ada got exactly one email, on the second attempt. Grace's problem from Exercise 4 is solved.

#### Break It

Now do exactly the same thing, but crash *after* sending:

```
$ python3 ex06_leases.py reset
$ python3 ex06_leases.py enqueue ada@example.com
$ python3 ex06_leases.py work --crash-after-send
  job 1 attempt 1: send_welcome_email {"address": "ada@example.com"}
    sent welcome email to ada@example.com
    *** power cut AFTER the email was sent ***
$ sleep 5; python3 ex06_leases.py work
  job 1 attempt 2: send_welcome_email {"address": "ada@example.com"}
    sent welcome email to ada@example.com
^C
$ cat outbox.txt
welcome email -> ada@example.com
welcome email -> ada@example.com
```

Two emails. Stop and look at this carefully, because it is the most important result so far. The code is identical. The *only* difference is the moment the power went out. Crash a little earlier and everything is perfect. Crash a little later and the customer gets a duplicate. Our queue has no way to tell those two situations apart. In both cases it sees exactly the same thing: a job marked `running`, a lease that expired, and silence.

There is a third way to break it, and it does not even need a crash. Run the worker with a lease shorter than the job takes, say `--lease 0.5` when sending takes a full second, and start a second worker a moment later. The first worker is perfectly healthy, just slow. The lease expires while it is still working, the second worker decides the first one must be dead, takes over, and both of them send the email. The lease was a *guess* about how long the work would take, and the guess was wrong.

```
   lease too short: the slow worker is mistaken for a dead one

   Worker A: ├── claim ── working……………………………… send ── ack ┤
   lease:    ├─ 0.5s ─┤ expired!
   Worker B:            ├ claim ── working……………………………… send ── ack ┤

                                           two emails ──▲───────────▲
```

> **Pause and Check 5.1.** Why can't the queue simply check whether the worker is still alive, instead of using a timer?
>
> <details><summary>Answer</summary>
>
> Because over a network, "dead" and "slow" and "unreachable" look exactly the same: silence. The worker might be alive but stuck in a long garbage-collection pause, or alive but cut off by a network glitch, or truly dead. Any "is it alive?" check is itself a message that can be delayed or lost. A lease turns an unanswerable question ("is it alive?") into an answerable one ("has it checked in before the deadline?"). Many real systems also let a long-running worker *extend* its lease periodically, which is called a heartbeat.
> </details>

> **Pause and Check 5.2.** In Exercise 6, crashing before sending gave one email and crashing after sending gave two. Draw the worker loop (claim, do, ack) and mark exactly where the "dangerous" crash happens.
>
> <details><summary>Answer</summary>
>
> ```
>   claim ──▶ [ do the work ] ──▶ ack
>                           ▲
>                 the danger zone: the work is done,
>                 but the queue does not know it yet
> ```
>
> Any crash after the side effect happens but before the ack is recorded will cause the job to run again. Remember this gap. The next two chapters are entirely about it.
> </details>

---

## 6. Retry: Trying Again, Politely

So far, our failures were crashes: the whole worker died. A much more common kind of failure is an *error*: the worker is fine, but the work itself did not succeed. The email provider returned "503 Service Unavailable". The bank's API timed out. The database was briefly locked. **A retry is another attempt after a failure.** In a sense, you already built retries in Chapter 5: an expired lease led to another attempt. Now we make it deliberate.

### Three Kinds of Failure

Before deciding *whether* to retry, you need to know *what kind* of failure you are looking at. It is worth slowing down here, because the classification is the foundation for everything in the next two chapters.

A **transient** failure is temporary. The network blipped, the server was overloaded for a second, a lock was held briefly. Try again in a moment and it will probably work. If your phone call drops in a tunnel, you call back when you come out of the tunnel.

A **permanent** failure will never succeed, no matter how many times you try. The email address does not exist. The credit card has been cancelled. The job refers to a user who was deleted. Retrying a permanent failure is like calling a disconnected phone number every hour forever. It wastes effort and teaches you nothing.

An **ambiguous** failure is the troublemaker. You sent a request and got *no answer*. A timeout. A dropped connection after the request was sent. You do not know whether the work happened. Maybe the request never arrived. Maybe it arrived, was processed perfectly, and only the reply was lost. You will meet this one properly in Chapter 7. For now, just notice that it exists and that it is fundamentally different from the other two.

```
   ┌────────────┬─────────────────────────────┬──────────────────────────────┐
   │ kind       │ example                     │ should we retry?             │
   ├────────────┼─────────────────────────────┼──────────────────────────────┤
   │ transient  │ 503, connection refused,    │ yes, after a pause           │
   │            │ rate limited                │                              │
   ├────────────┼─────────────────────────────┼──────────────────────────────┤
   │ permanent  │ 404 user not found,         │ no: send to dead letter,     │
   │            │ invalid email, bad input    │ alert a human                │
   ├────────────┼─────────────────────────────┼──────────────────────────────┤
   │ ambiguous  │ timeout, connection reset   │ yes, BUT only if repeating   │
   │            │ after sending               │ the work is safe (Ch. 7, 8)  │
   └────────────┴─────────────────────────────┴──────────────────────────────┘
```

### How Long to Wait: Exponential Backoff

If a request fails because a server is overloaded, the worst thing you can do is retry immediately. The server is drowning, and you are throwing it another bucket of water. Now imagine a thousand workers all doing the same thing. The server never gets a chance to recover.

The standard answer is **exponential backoff**: wait a little after the first failure, twice as long after the second, twice as long again after the third, and so on, up to some maximum. With a base of one second, you wait 1, 2, 4, 8, 16, 32 seconds. The early retries are quick, so a brief blip costs almost nothing. The later retries are slow, so a long outage is not hammered. It is the same instinct as a polite person knocking on a door: knock, wait, knock again a bit later, and if nobody comes after a while, stop knocking every few seconds.

There is one more twist. Suppose a hundred jobs all fail at the same instant because the email provider went down at 12:00:00. With pure exponential backoff, all hundred retry at exactly 12:00:01, then all hundred at 12:00:03, then 12:00:07. They move in lockstep, like a crowd that all pushes on the door at the same moment. This is called the **thundering herd**. The fix is **jitter**: add randomness to each delay so the retries spread out. Instead of waiting exactly 4 seconds, wait somewhere between 2 and 4. The herd becomes a trickle.

```
   retries of 8 jobs that all failed at t=0

   WITHOUT JITTER (all in lockstep)       WITH JITTER (spread out)

   t=1  ████████                          t=0.5-1  █ ██ █ ███ █
   t=3  ████████                          t=1-3    █  █ ██  █  █ █
   t=7  ████████                          t=2-7    █   █  █  ██   █ █
        ▲ the server gets slammed               ▲ load arrives smoothly
          by every retry at once
```

<!-- widget:backoff -->

### When to Give Up: Dead Letters

Retrying forever is a bug. If a job has failed ten times over three hours, something is wrong that a retry will not fix: a permanent failure that was misclassified, a bug in the handler, a corrupted job. Such a job is often called a **poison message**: it fails every time, and if you keep retrying it, it wastes worker time forever.

So every retry policy has a maximum number of attempts. When a job exceeds it, the job is moved aside to a **dead-letter queue**, which is a holding area for jobs that could not be processed. The name comes from the postal service, where a "dead letter office" handled mail that could neither be delivered nor returned. Nothing in the dead-letter queue is processed automatically. It exists so that a human can look at what went wrong, fix the cause, and then either replay the jobs or discard them. In our SQLite queue, "dead letter" is simply one more status.

```
                                   ┌─────── fail, attempts < max ───────┐
                                   │       (wait backoff, then retry)   │
                                   ▼                                    │
   enqueue ──▶ queued ──claim──▶ running ───────────────────────────────┤
                                   │                                    │
                                   │ success                            │ fail, attempts = max
                                   ▼                                    ▼
                                 done                                 dead
                                                               (a human looks at it)
```

### Exercise 7: Retries, and the Money Goes Missing

Now we build a worker with retries, backoff, jitter, and a dead-letter status, and point it at something more serious than email: a bank. Alice has $100. We queue five jobs, each charging her $10. The bank is badly unreliable. Thirty percent of the time the request never reaches it (a clean, transient failure). Another thirty percent of the time the bank *does* charge the card, but the reply is lost on the way back, so the worker sees a timeout (an ambiguous failure). Type in `ex07_retries.py`:

```python
# Exercise 7: Retries, backoff, and the dead-letter pile.
# A flaky "bank" fails a lot. We retry. Then we count the money.
#
#   python3 ex07_retries.py setup      # alice gets $100, we queue 5 x $10 charges
#   python3 ex07_retries.py work       # runs until every job is done or dead
#   python3 ex07_retries.py report     # expected balance vs. actual balance
#
# Add --seed 42 to setup/work to make the dice repeatable.

import json
import os
import random
import sqlite3
import sys
import time

DB = "ex07.db"
MAX_ATTEMPTS = 6
BACKOFF_BASE = 0.2     # seconds; real systems use seconds to minutes
BACKOFF_CAP = 5.0
LEASE_SECONDS = 10

rng = random.Random()


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
        );""")
    return db


# --- the outside world ------------------------------------------------------

def bank_charge(db, account, amount):
    roll = rng.random()
    if roll < 0.3:
        # The request never arrived. Nothing happened. Safe to retry.
        raise ConnectionError("could not reach the bank")
    db.execute("UPDATE bank_accounts SET balance = balance - ? WHERE name = ?",
               (amount, account))
    if roll < 0.6:
        # The bank DID charge the card, but the reply got lost on the way back.
        # From where we stand, this looks exactly like the failure above.
        raise TimeoutError("no reply from the bank")
    return "ok"


def charge_card(db, account, amount, order_id):
    bank_charge(db, account, amount)
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
```

Before you run it, look at the claim query. It has learned one new trick: `run_at <= ?`. A job that failed is put back to `queued` with a `run_at` time in the future, so no worker will touch it until its backoff delay has passed. That one column is the entire implementation of "try again later".

#### What You Should See

With `--seed 7` you should see something very close to this (your exact timings may differ):

```
$ python3 ex07_retries.py setup
alice has $100; queued 5 charges of $10
$ python3 ex07_retries.py work --seed 7
  job 1 attempt 1: charge_card {"account": "alice", "amount": 10, "order_id": 1}
    failed (TimeoutError: no reply from the bank); retry in 0.12s
  job 2 attempt 1: charge_card {"account": "alice", "amount": 10, "order_id": 2}
    charged alice $10 for order 2
  job 3 attempt 1: charge_card {"account": "alice", "amount": 10, "order_id": 3}
    failed (ConnectionError: could not reach the bank); retry in 0.15s
  job 4 attempt 1: charge_card {"account": "alice", "amount": 10, "order_id": 4}
    failed (TimeoutError: no reply from the bank); retry in 0.11s
  job 5 attempt 1: charge_card {"account": "alice", "amount": 10, "order_id": 5}
    failed (TimeoutError: no reply from the bank); retry in 0.10s
  job 5 attempt 2: charge_card {"account": "alice", "amount": 10, "order_id": 5}
    failed (TimeoutError: no reply from the bank); retry in 0.21s
  ...
  job 3 attempt 4: charge_card {"account": "alice", "amount": 10, "order_id": 3}
    charged alice $10 for order 3
no unfinished jobs left; worker exiting
```

So far this looks like a triumph. The bank failed over and over, and our patient, polite worker kept retrying with growing delays until every single job succeeded. Now run the report:

```
$ python3 ex07_retries.py report
jobs:
  job 1   done   attempts=2  last_error=TimeoutError: no reply from the bank
  job 2   done   attempts=1  last_error=None
  job 3   done   attempts=4  last_error=TimeoutError: no reply from the bank
  job 4   done   attempts=3  last_error=ConnectionError: could not reach the bank
  job 5   done   attempts=3  last_error=TimeoutError: no reply from the bank

jobs that succeeded:    5 x $10
alice should have:      $50
alice actually has:     $0
alice was overcharged:  $50  <-- duplicates!
```

Alice ordered $50 of things and was charged $100. Every job reports success. Every log line looks reasonable. No exception went unhandled. And yet the system stole fifty dollars from a customer. If you count, there were exactly five `TimeoutError` failures in the run above, and each one cost Alice ten dollars. The `ConnectionError` failures cost nothing.

#### Study Drills

Run setup and work again without a seed, a few times. Count the timeouts in each run and compare to the overcharge. Then change the probabilities in `bank_charge` so that it never raises `TimeoutError` (only `ConnectionError`), and confirm that Alice is always charged correctly. Finally, set `MAX_ATTEMPTS = 2` and look for jobs that end up `dead`. Ask yourself: for a dead job whose last error was a `TimeoutError`, was Alice charged or not? Can you tell from the data you have?

> **Pause and Check 6.1.** Why does exponential backoff include a cap (`BACKOFF_CAP`)?
>
> <details><summary>Answer</summary>
>
> Because doubling grows astonishingly fast. With a one-second base, the twentieth retry would wait 2^19 seconds, which is about six days. Without a cap, a job that fails a handful of times during a long outage might not be tried again for weeks after the outage ends. The cap keeps the longest wait reasonable, typically minutes to an hour.
> </details>

> **Pause and Check 6.2.** Classify each failure as transient, permanent, or ambiguous: (a) HTTP 429 "Too Many Requests"; (b) HTTP 400 "invalid email address"; (c) the connection was reset after you had sent the whole request; (d) DNS lookup failed.
>
> <details><summary>Answer</summary>
>
> (a) Transient: slow down and retry. (b) Permanent: no number of retries will make the address valid. (c) Ambiguous: the request was sent, so the server might have processed it. (d) Transient, and also *safe*: if you could not even find the server's address, the request certainly never arrived, so nothing happened.
> </details>

---

## 7. The Tricky Question: Did It Happen?

We have now reached the centre of this guide. Everything before was building up to this one question, and everything after is an answer to it.

**When a worker retries a job, could repeating the work create a duplicate?**

You have now seen duplicates three times, from three different causes. In Exercise 5, two workers claimed the same job because of a race. We fixed that with an atomic claim. In Exercise 6, a worker crashed after doing the work but before recording that it was done, and the lease handed the job to someone else. In Exercise 7, the bank did the work but the reply was lost, so the worker could not tell success from failure, and retried. The first cause was a bug that we could eliminate. The second and third are not bugs in our code. They are *the nature of the problem*, and no amount of clever coding in the worker can make them go away. Let us understand why.

### The Uncertain Moment

Imagine you send a friend a text message. Your phone shows a spinning icon, and then "Not delivered". Did your friend get the message? Probably not. But possibly yes: maybe the message reached your friend's phone, and it was the delivery receipt that got lost on the way back to you. Do you send it again? If the message was "running late", sending it twice is harmless. If the message was "I've transferred you $500", sending it twice could be a disaster, depending on whether your friend treats the second text as a second transfer.

This is the uncertain moment, and it exists in every system where two parties communicate over something that can fail. When you send a request and hear nothing back, there are three possibilities, and from where you stand **they are completely indistinguishable**:

```
   You (worker)                    Network                  Bank
   ───────────                     ───────                  ────

   Case A: request lost
   charge $10  ─────────────▶  ✗                            (nothing happened)
               ◀ ─ ─ ─ ─ ─ ─ ─ silence ─ ─ ─ ─ ─ ─ ─ ─

   Case B: bank crashed while processing
   charge $10  ──────────────────────────────────▶  ✝  (maybe happened, maybe not)
               ◀ ─ ─ ─ ─ ─ ─ ─ silence ─ ─ ─ ─ ─ ─ ─ ─

   Case C: reply lost
   charge $10  ──────────────────────────────────▶  ✓ charged!
               ✗  ◀─────────────────────────────────── "ok"
               ◀ ─ ─ ─ ─ ─ ─ ─ silence ─ ─ ─ ─ ─ ─ ─ ─

   From the worker's point of view, all three look EXACTLY the same:
   "I asked, and I heard nothing."
```

You might think: just ask the bank whether the charge went through! But that question is itself a message, and it can also be lost, or arrive before the original request has finished processing. Asking again moves the uncertainty around; it does not remove it. This is a close relative of a famous result in computer science called the **Two Generals' Problem**, which shows that two parties communicating over an unreliable channel can never be *certain* they agree. It is not that nobody has been clever enough to solve it. It has been proven unsolvable.

### Two Choices, Both Imperfect

Since the worker cannot know whether the work happened, it has to make a policy decision, and there are only two options. The choice comes down to *when you acknowledge* the job, relative to doing the work.

If you **ack first, then do the work**, a crash in the middle means the job is already marked done but the work never happened. The job is lost. You get **at-most-once** delivery: every job runs zero or one times, never twice.

If you **do the work first, then ack**, a crash in the middle means the work happened but the ack did not, so the job runs again. You get **at-least-once** delivery: every job runs one or more times, never zero.

```
                   AT-MOST-ONCE                      AT-LEAST-ONCE
                   (ack, then work)                  (work, then ack)

   claim           ●                                 ●
                   │                                 │
                   ▼                                 ▼
   step 2      ┌───────┐                         ┌───────┐
               │  ACK  │                         │ WORK  │
               └───┬───┘                         └───┬───┘
       crash here? │ ✝ → job is marked done,         │ ✝ → job not acked,
                   │     work never happened         │     work happened,
                   │     → LOST                      │     will run again
                   ▼                                 ▼     → DUPLICATE
   step 3      ┌───────┐                         ┌───────┐
               │ WORK  │                         │  ACK  │
               └───────┘                         └───────┘

   Guarantee:  0 or 1 times                      1 or more times
   Fails by:   losing work                       repeating work
   Good for:   metrics, "you might like" emails  payments, orders, anything
               where a gap is fine               that MUST happen
```

Look back at your own code. Every worker you wrote in this guide did the work and then marked it done, so they were all at-least-once. That is why duplicates kept appearing. It was not carelessness. It was the price of never losing a job.

Most real systems choose at-least-once, because a lost job is usually worse than a repeated one, *if* you can make the repetition harmless. A lost payment is a customer who paid and got nothing. A lost "your order has shipped" email is a confused customer calling support. Duplicates, on the other hand, can often be *defused*. That is the subject of Chapter 8.

### What About Exactly-Once?

You will hear people, and product brochures, talk about **exactly-once** delivery. Strictly speaking, exactly-once *delivery* over an unreliable network is impossible, for the reasons above. What *is* possible, and what those brochures actually mean when they are being honest, is **exactly-once effect**: the message may be delivered and processed more than once, but the system is arranged so the *outcome* is the same as if it were processed exactly once. Some people call this "effectively-once".

```
   exactly-once DELIVERY:   impossible over an unreliable network

   exactly-once EFFECT  =   at-least-once delivery   +   idempotent processing
                            (never lose anything)        (repeats are harmless)
```

That equation is the single most important idea in this guide. If you take nothing else away, take that.

<!-- widget:crash-timeline -->

> **Pause and Check 7.1.** In Exercise 7, the `ConnectionError` failures never caused overcharges, but the `TimeoutError` failures always did. Explain why, in terms of the three cases in the diagram above.
>
> <details><summary>Answer</summary>
>
> `ConnectionError` in our simulation is Case A: the request never reached the bank, so nothing happened, and a retry is the *first* real charge. `TimeoutError` is Case C: the bank charged the card and only the reply was lost, so a retry is a *second* charge. The worker could not tell the two apart, so it treated them the same way, and the same treatment was right for one and wrong for the other.
> </details>

> **Pause and Check 7.2.** You are building a system that sends "Your package has shipped!" notifications. A duplicate is mildly annoying. A missing one causes a support call. Which delivery guarantee do you choose, and why? What if the job were "add 100 loyalty points"?
>
> <details><summary>Answer</summary>
>
> For notifications, at-least-once: a rare duplicate is cheaper than a support call. For loyalty points you also want at-least-once, because losing points is a real loss to the customer, but now a duplicate is *also* a real loss (to the business), so you must make the operation idempotent. That is exactly what we will do in the capstone.
> </details>

---

## 8. Idempotency: Making Repeats Harmless

There is a button by every elevator. Press it once and the elevator is called. Press it five more times, angrily, and the elevator is still called exactly once. The extra presses do nothing. Compare that to a vending machine that dispenses a can each time you press the button. Pressing it five times gets you five cans and a bill for five cans.

The elevator button is **idempotent**: doing it many times has the same effect as doing it once. The word comes from mathematics, where an operation *f* is idempotent if *f(f(x)) = f(x)*. Taking the absolute value is idempotent: |−5| is 5, and |5| is still 5. Adding one is not: 5+1 is 6, and 6+1 is 7.

```
   IDEMPOTENT                              NOT IDEMPOTENT

   "set the light to ON"                   "toggle the light"
   ON → ON → ON → ON          ✓            ON → OFF → ON → OFF        ✗

   "set balance to $90"                    "subtract $10 from balance"
   90 → 90 → 90               ✓            100 → 90 → 80 → 70         ✗

   "mark order 7 as paid"                  "insert a new payment row"
   paid → paid → paid         ✓            1 row → 2 rows → 3 rows    ✗

   elevator call button       ✓            vending machine button     ✗
```

Here is why this matters so much. In Chapter 7 we decided we want at-least-once delivery, so that no job is ever lost. The cost is that a job may run more than once. If every job is idempotent, that cost drops to zero: running it twice is the same as running it once. **Idempotency is how you turn at-least-once delivery into exactly-once effect.**

Some operations are naturally idempotent, and you should prefer them where you can. "Set the user's status to `verified`" is idempotent; "increment the user's verification count" is not. "Delete file X" is idempotent (deleting something already gone is a no-op); "append a line to file X" is not. Often a little rethinking turns a non-idempotent operation into an idempotent one. But some operations are inherently not idempotent: charging a card, sending an email, adding loyalty points. For those, you need a technique. There are two main ones.

### Technique One: Idempotency Keys

The idea is simple. Give each *intended* piece of work a unique name, called an **idempotency key**, and send that name along with every attempt. The receiver keeps a record of every key it has already processed. If a request arrives with a key it has seen before, it does not do the work again. It just replies "already done".

This is exactly how a cloakroom ticket works. You hand over your coat and receive ticket 47. If you come back and say "coat 47, please", you get your coat. If you come back a second time and say "coat 47, please", the attendant says "you already collected that". The ticket number is the idempotency key. It names *this specific coat*, not "a coat".

```
   attempt 1:   worker ── charge $10, key="charge-for-order-1" ──▶ bank
                                                                    │ key new?  yes
                                                                    │ → charge $10
                                                                    │ → remember key
                worker ✗ ◀── reply lost ───────────────────────────┘

   attempt 2:   worker ── charge $10, key="charge-for-order-1" ──▶ bank
                                                                    │ key new?  NO
                                                                    │ → do nothing
                worker ✓ ◀── "ok (already done)" ──────────────────┘

   Alice is charged exactly once.
```

There are two crucial details, and getting either one wrong destroys the protection.

First, **the key must name the intent, not the attempt**. It must be the same on every retry of the same work. `"charge-for-order-1"` is right: it is derived from data in the job, so every attempt computes the same key. A key generated fresh on each attempt, such as a random number or a timestamp, is useless, because every retry looks like brand-new work to the receiver. You will prove this in the exercise.

Second, **the receiver must check the key and do the work in a single atomic step**. If it checks the key, then does the work, then records the key in three separate steps, a crash between doing the work and recording the key reopens the exact gap we are trying to close. This is the same check-then-act trap from Chapter 4, in a new disguise.

Real payment providers work this way. Stripe, for example, lets you send an `Idempotency-Key` header with any request that creates something, and it guarantees that a repeated request with the same key returns the original result instead of creating a second charge. (Stripe remembers keys for at least 24 hours.) When you integrate with any external API that moves money, sends messages, or creates things, the first question to ask is: *does it accept an idempotency key?*

### Exercise 8: Idempotency Keys

Make a copy of `ex07_retries.py` called `ex08_idempotency.py`. Do not retype the whole thing; this time, practise editing. Change `DB` to `"ex08.db"`. Add a flag near the top so we can test a broken key:

```python
rng = random.Random()
BAD_KEY = "--bad-key" in sys.argv
```

Add a table where the bank remembers keys, inside `connect()`:

```python
        -- The bank remembers every key it has seen, and what it answered.
        CREATE TABLE IF NOT EXISTS bank_requests (
            idempotency_key TEXT PRIMARY KEY,
            response        TEXT NOT NULL
        );
```

Replace `bank_charge` and `charge_card` with these versions:

```python
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
```

Notice the `BEGIN IMMEDIATE` ... `COMMIT` around the check and the charge. That is the bank keeping its side of the bargain: looking up the key, moving the money, and remembering the key all happen as one indivisible unit. The finished file is in `code/ex08_idempotency.py` if you want to compare.

#### What You Should See

Run it with the same seed as before, so the bank fails in exactly the same pattern as in Exercise 7:

```
$ python3 ex08_idempotency.py setup
$ python3 ex08_idempotency.py work --seed 7
  ...
  job 5 attempt 3: charge_card {"account": "alice", "amount": 10, "order_id": 5}
    (bank: I already did charge-for-order-5; not charging again)
    charged alice $10 for order 5
  job 4 attempt 3: charge_card {"account": "alice", "amount": 10, "order_id": 4}
    (bank: I already did charge-for-order-4; not charging again)
    charged alice $10 for order 4
  ...
$ python3 ex08_idempotency.py report
  ...
jobs that succeeded:    5 x $10
alice should have:      $50
alice actually has:     $50
```

The same network failures, the same retries, the same timeouts, and Alice paid exactly what she owed. Each `(bank: I already did ...)` line is a duplicate that would have stolen ten dollars, quietly defused.

#### Break It

```
$ python3 ex08_idempotency.py setup
$ python3 ex08_idempotency.py work --seed 7 --bad-key
$ python3 ex08_idempotency.py report
  ...
alice should have:      $50
alice actually has:     $0
alice was overcharged:  $50  <-- duplicates!
```

The bank's idempotency machinery is still there, still working perfectly, and it saved nothing, because every retry presented a never-before-seen key. An idempotency key that changes between retries is not an idempotency key. This mistake is common in real code, usually as `key = uuid4()` generated inside the retry loop instead of once, when the job is created.

### Technique Two: Commit the Effect With the Ack

Idempotency keys are how you defend against duplicates when the effect happens *somewhere else*, in a system you do not control. But when the effect happens in *your own database*, you have a stronger tool.

Recall the danger zone from Chapter 5: the gap between doing the work and recording that it is done. A crash in that gap causes a duplicate. What if there were no gap? If the work is a database write (say, adding 10 loyalty points), and the queue lives in the *same* database, then you can put both writes, "add 10 points" and "mark job done", in a single transaction. A transaction is atomic, so either both happen or neither does. There is no moment in between for a crash to land in.

```
   SEPARATE STEPS (gap)                    ONE TRANSACTION (no gap)

   UPDATE points + 10                      BEGIN
            ✝ ← crash here = duplicate       UPDATE points + 10
   UPDATE job SET done                       UPDATE job SET done
                                           COMMIT  ← both, or neither
```

This is like a shop where handing over the goods and stamping the receipt happen in the same motion, across a counter, so you can never have one without the other. You will use this technique in the capstone, for the loyalty points.

There is a sibling of this trick for the *producer* side. When your web app creates a user and enqueues "send welcome email", those are two writes. If the app crashes between them, you have a user with no email job, or, if you did them in the other order, an email job for a user who does not exist. If the queue lives in the same database as your data, you can create the user and enqueue the job in one transaction. If the queue is a separate system, the standard answer is the **transactional outbox** pattern: you write the job into an "outbox" table in your own database, in the same transaction as the user, and a separate process copies rows from the outbox to the real queue (at least once, naturally).

### Choosing a Technique

Pulling it together: for every job, ask where its effect lands. If it lands in your own database, put the effect and the ack in one transaction. If it lands in an external system that accepts idempotency keys, derive a stable key from the job and send it on every attempt. If it lands in an external system that does *not* accept keys (some old email servers, some SMS gateways), you cannot fully close the gap. You can narrow it by recording "about to send" before sending and checking that record on retry, but a crash at exactly the wrong moment can still produce a duplicate, or, if you choose the other order, a loss. In that case you are back to Chapter 7: pick at-least-once or at-most-once based on which failure hurts less, and write that decision down where your teammates will find it.

```
   Where does the job's effect land?
                │
     ┌──────────┼───────────────────────────────┐
     ▼          ▼                               ▼
   my own     external system that         external system with
   database   accepts idempotency keys     NO idempotency support
     │          │                               │
     ▼          ▼                               ▼
   effect +   stable key derived           choose: duplicates or losses?
   ack in     from the job, sent on        narrow the gap, document
   ONE txn    every attempt                the choice, monitor it
```

<!-- widget:idempotency -->

> **Pause and Check 8.1.** Which of these are naturally idempotent? (a) `UPDATE users SET email = 'new@x.com' WHERE id = 7`; (b) `UPDATE accounts SET balance = balance - 10 WHERE id = 7`; (c) `INSERT INTO orders (id, item) VALUES (9001, 'book')` where `id` is a primary key; (d) sending an SMS.
>
> <details><summary>Answer</summary>
>
> (a) Yes: setting a value to a fixed value twice leaves it the same. (b) No: each run subtracts another ten. (c) Effectively yes: the second insert fails on the primary key, so you never get two rows. A constraint like this is a crude idempotency key, as long as you treat "already exists" as success rather than an error. (d) No: each send delivers another text.
> </details>

> **Pause and Check 8.2.** A teammate writes `key = str(uuid.uuid4())` at the top of the `charge_card` handler. Explain, using the cloakroom analogy, what is wrong, and where the key should come from instead.
>
> <details><summary>Answer</summary>
>
> It is like the cloakroom handing you a new ticket number every time you ask for your coat. The attendant can never recognize that you already collected it. The key must be fixed when the *intent* is created, not when an *attempt* is made: either derived from stable data in the job (`f"charge-for-order-{order_id}"`), or generated once when the job is enqueued and stored inside the job's arguments.
> </details>

> **Pause and Check 8.3.** Why must the bank check the key and move the money in a single transaction?
>
> <details><summary>Answer</summary>
>
> Otherwise the bank has its own danger zone. If it moves the money, then crashes before recording the key, the next attempt will find no record of the key and charge again. It is the same check-then-act problem as the race in Chapter 4, and the same cure applies: make the check and the action one atomic step.
> </details>

---

## 9. Capstone: tinyq and the Chaos Monkey

You now understand every piece. In this chapter you will put them together into a small but honest job queue library, build a toy shop on top of it, and then attack it with a "chaos monkey", a script that kills workers at random moments, while a flaky network loses requests and replies. At the end, an audit checks whether the books balance. The term comes from Netflix, which built a tool of that name to randomly kill its own production servers, on the theory that the only way to be sure a system survives failure is to make failure happen constantly.

The capstone lives in `code/capstone/`. It is four files.

```
   capstone/
   ├── tinyq.py   the library: everything from Exercises 1-8, ~170 lines
   ├── world.py   the outside world: a flaky mail provider and a flaky bank
   ├── shop.py    our application: signups, and three kinds of job
   └── chaos.py   the test: run workers that die at random, then audit
```

### The Assignment

Here is the challenge, in the Zed Shaw tradition: **try to write `tinyq.py` yourself before reading the reference solution**. You have every piece you need. The specification is below, and it is short.

A `Queue` wraps a SQLite file. `enqueue(kind, args, unique_key=None, delay=0)` inserts a job, and refuses to insert a second job with the same `unique_key` (this is an idempotency key for the *producer*, so that a double-clicked button cannot create two jobs). `claim()` atomically takes one job that is either `queued` with `run_at` in the past, or `running` with an expired lease, and stamps it with a random **token** that identifies this particular claim. `work_one()` claims a job, runs its handler, and marks it `done`, or, on an exception, either schedules a retry with exponential backoff and jitter or, after `max_attempts`, marks it `dead`. Finally, a `Job` has a `complete()` context manager that lets a handler commit its own database writes in the same transaction that marks the job done.

The token deserves a sentence of explanation, because it solves the "lease too short" problem from Exercise 6. When a worker finishes, it marks the job done *only if the job still carries its token*: `UPDATE jobs SET status = 'done' WHERE id = ? AND locked_by = ?`. If the lease expired and another worker re-claimed the job, the token will have changed, the update will match zero rows, and the slow worker knows it has lost ownership. In `complete()`, that means its database writes are rolled back. This is a simple form of what Kleppmann calls a **fencing token**: a number that lets the system reject the actions of a worker who no longer holds the lock but does not know it yet.

### The Reference Solution

Here is the heart of `tinyq.py`. Read it slowly. Every line should now look familiar.

```python
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
        ...
```

That one statement contains the atomic claim from Exercise 5, the lease from Exercise 6, the backoff schedule from Exercise 7 (`run_at <= ?`), and the fencing token. And here is the transactional completion:

```python
    @contextmanager
    def complete(self):
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
```

### The Shop

`shop.py` defines a signup that creates a customer and queues three jobs, one for each technique you learned:

```python
@queue.handler("send_welcome_email")       # external effect → idempotency key
def send_welcome_email(job):
    maybe_crash("before sending email")
    world.send_email(job.args["email"], "Welcome!",
                     idempotency_key=f"welcome-email:{job.args['email']}")
    maybe_crash("after sending email, before ack")


@queue.handler("charge_signup_fee")        # external effect → idempotency key
def charge_signup_fee(job):
    maybe_crash("before charging")
    world.charge(job.args["email"], 5,
                 idempotency_key=f"signup-fee:{job.args['email']}")
    maybe_crash("after charging, before ack")


@queue.handler("award_points")             # internal effect → same transaction
def award_points(job):
    maybe_crash("before awarding points")
    with job.complete() as db:
        db.execute("UPDATE customers SET points = points + 10 WHERE email = ?",
                   (job.args["email"],))
        maybe_crash("inside the transaction, before commit")
```

Every handler is sprinkled with `maybe_crash`, which, with some probability, kills the worker instantly. The crashes are placed at the most dangerous moments: right after an external effect, before the ack, and even in the middle of an open transaction. `world.py` adds its own trouble: fifteen percent of requests never arrive, and another fifteen percent succeed but lose their reply.

And the signup itself does something you learned in Chapter 8: it creates the customer row and enqueues all three jobs in one transaction, so there is never a customer without jobs or jobs without a customer.

```python
def signup(email):
    queue.db.execute("BEGIN IMMEDIATE")
    queue.db.execute("INSERT INTO customers (email) VALUES (?)", (email,))
    for kind in ("send_welcome_email", "charge_signup_fee", "award_points"):
        queue.enqueue(kind, {"email": email}, unique_key=f"{kind}:{email}")
    queue.db.execute("COMMIT")
    ...
```

### Run the Chaos

`chaos.py` signs up twenty customers (sixty jobs), starts three workers with a ten percent crash chance at every crash point, and acts as a supervisor: whenever a worker dies, it starts a fresh one, just as systemd or Kubernetes would in production. When every job is finished, it audits the books. Every customer must have received exactly one email, paid exactly $5, and have exactly 10 points.

#### What You Should See

```
$ cd code/capstone
$ python3 chaos.py
signed up 20 customers -> 60 jobs queued
running 3 workers that crash at random (chaos=0.1)

  [1234] CRASH after sending email, before ack
  [1236] CRASH inside the transaction, before commit
  [1241] CRASH before charging
  ...

finished in 5.6s
worker crashes:                 17
jobs by status:                 {'done': 60}
jobs that needed >1 attempt:    19
duplicates absorbed by keys:    13

AUDIT PASSED: every customer got exactly 1 email, paid exactly $5, and has exactly 10 points.
```

Seventeen workers were killed, many of them at the worst possible moment. Nineteen jobs needed more than one attempt. Thirteen times, a request reached the outside world for work that had already been done, and was harmlessly absorbed by its idempotency key. And the audit passed: every customer was treated exactly once. Run it several times; it should pass every time. That is what at-least-once delivery plus idempotent processing buys you.

#### Break It

Now turn off the idempotency keys. The environment variable makes `world.py` replace each key with a random one, just like the `--bad-key` mistake from Exercise 8:

```
$ TINYQ_NO_KEYS=1 python3 chaos.py
...
worker crashes:                 16
jobs by status:                 {'done': 60}
duplicates absorbed by keys:    0

AUDIT FAILED: 6 problem(s)
  customer00@example.com: got 4 welcome emails (want 1)
  customer03@example.com: balance $90 (want $95)
  customer09@example.com: got 2 welcome emails (want 1)
  customer10@example.com: got 4 welcome emails (want 1)
  customer13@example.com: got 2 welcome emails (want 1)
  customer17@example.com: got 2 welcome emails (want 1)
```

Customers got four welcome emails and were charged twice. But look at what is *not* in the list: points. Not a single customer has the wrong number of points, even with keys turned off, because points never relied on keys. They were committed in the same transaction as the ack, so no crash could separate them. Two techniques, two different jobs, and the audit shows you exactly which one is protecting what.

#### Study Drills

Raise `CHAOS` in `chaos.py` to `"0.3"` and run it. It will be slower, with many more crashes, but the audit should still pass. Then move the line `maybe_crash("inside the transaction, before commit")` in `award_points` to *after* the `with` block, and convince yourself the audit still passes (why?). Next, rewrite `award_points` *without* `job.complete()`, doing a plain `queue.db.execute("UPDATE customers ...")` before returning, and run the chaos test until the audit fails on points. Finally, in `tinyq.py`, delete `AND locked_by = ?` from the `complete()` update, set `lease=0.05` in `shop.py`, and see whether you can make the points go wrong. You have just rediscovered why fencing tokens exist.

<!-- widget:chaos -->

> **Pause and Check 9.1.** With `TINYQ_NO_KEYS=1`, why were the points still correct?
>
> <details><summary>Answer</summary>
>
> Because the points update and the "job done" update are written in one database transaction. Either both commit or neither does. A crash before the commit rolls back both, so the next attempt starts from a clean slate. A crash after the commit means the job is already marked done, so there is no next attempt. There is no in-between state for a duplicate to come from. Idempotency keys were never involved.
> </details>

---

## 10. The Real World

You built a job queue from scratch on SQLite. In production you will usually use an existing system, but every one of them is built from the same parts you have just built by hand, under different names. Knowing the parts lets you read any system's documentation and immediately ask the right questions.

**Database-backed queues** are exactly what you built: a jobs table and workers that poll it. In the Ruby world, Good Job and Solid Queue store jobs in PostgreSQL or MySQL; in Python, Procrastinate does the same with PostgreSQL; in Elixir, Oban. Their great advantage is the one you used in the capstone: the queue lives in the same database as your data, so you can enqueue a job in the same transaction as the data change that caused it. Their claim queries are usually written with `FOR UPDATE SKIP LOCKED`, the PostgreSQL version of your atomic claim, which lets many workers claim different jobs concurrently without blocking each other.

**Redis-backed job libraries** like Sidekiq (Ruby), BullMQ (Node.js), and RQ or Celery with a Redis broker (Python) keep jobs in Redis, an in-memory data store with optional persistence. They are fast and popular. They add retries with backoff out of the box (Sidekiq, for instance, retries a failed job 25 times by default, with exponentially growing gaps spanning about three weeks, before moving it to a "dead" set). Their trade-off is that the queue is a separate system from your main database, so enqueueing atomically with a data change needs something like the transactional outbox.

**Message brokers** like RabbitMQ and **managed queues** like Amazon SQS and Google Cloud Pub/Sub are dedicated servers whose only job is to store messages and hand them to consumers. Here the vocabulary maps directly onto what you know. A consumer receives a message, which hides it from other consumers; SQS calls the hiding period the *visibility timeout*, and it is your lease. The consumer then *acknowledges* (RabbitMQ) or *deletes* (SQS) the message when finished, which is your ack. If the ack does not arrive in time, the message is redelivered, which is your at-least-once retry. Both offer dead-letter queues for messages that fail too many times. SQS also offers FIFO queues with a *deduplication ID* that discards duplicate sends within a five-minute window: an idempotency key for the producer, like your `unique_key`.

**Logs** like Apache Kafka are a different shape. Instead of handing out individual messages and deleting them, Kafka keeps an append-only log, and each consumer remembers a position, called an *offset*, saying how far it has read. "Ack" means saving your offset. The same at-most-once versus at-least-once choice appears in a new form: do you save your offset before processing a batch of messages (and risk losing them) or after (and risk reprocessing them)? Kafka's "exactly-once semantics" feature, when you read the fine print, is exactly-once *effect* within Kafka's own world, achieved with transactions that commit the output and the offset together: your "commit the effect with the ack" technique, again.

One last warning, about defaults. Several popular libraries ack *before* running your code unless you change a setting. Celery, for example, acknowledges a task as soon as a worker receives it, unless you enable `acks_late`. That makes it at-most-once with respect to worker crashes: if the worker dies mid-task, the task is gone. Whenever you adopt a queue, find the answer to four questions before you trust it with anything important. When exactly is a job acked? What happens to a job whose worker dies? How are retries scheduled, and when does a job go to the dead-letter queue? And for each kind of job, what makes a repeat harmless?

### Things We Did Not Cover

A few important topics were left out to keep the guide focused, and you will meet them soon. **Ordering**: most queues with multiple workers do not guarantee that jobs finish in the order they were created, and retries make it worse, because a retried job finishes after jobs that were created later. **Priorities**: urgent jobs (password reset emails) should not wait behind ten thousand bulk jobs (newsletter emails); the usual answer is separate queues with dedicated workers. **Scheduled and recurring jobs**: "send this reminder in three days" is a `run_at` in the future, which you already built. **Backpressure**: if jobs arrive faster than workers can ever process them, the queue grows without bound, and you need to either add workers or reject work at the front door. **Monitoring**: the two numbers to watch on any queue are its *depth* (how many jobs are waiting) and the *age of the oldest job* (how long the unluckiest job has waited). A growing depth means you need more workers. A growing age means something is stuck.

### Further Reading

Martin Kleppmann's *Designing Data-Intensive Applications* (O'Reilly) covers message brokers, logs, exactly-once processing, and fencing tokens (Chapters 8, 9 and 11 of the first edition), and is the best single book on everything in this guide. Brandur Leach's article "Implementing Stripe-like Idempotency Keys in Postgres" walks through a production-grade version of Chapter 8. Marc Brooker's article "Exponential Backoff And Jitter" on the AWS Architecture Blog shows with simulations why jitter matters. And Stripe's API documentation on idempotent requests is a short, clear example of an idempotency-key contract from the receiver's side.

### The One Sentence

If you remember nothing else, remember this. A job is work written down so it can be done later. A queue holds it durably until a worker claims it. The worker claims it atomically, holds it under a lease, and acknowledges it only after the work is done. Because the moment between doing and acknowledging can always be interrupted, any job may run more than once, so every job must be made safe to repeat, either by committing its effect together with its acknowledgement or by naming the work with an idempotency key that the receiver remembers.

---

## Glossary

| Term | Meaning |
|---|---|
| **Ack (acknowledge)** | The worker telling the queue a job is finished, so it will not be handed out again. |
| **Ambiguous failure** | A failure where you cannot tell whether the work happened, typically a timeout after the request was sent. |
| **At-least-once** | Every job runs one or more times. Nothing is lost; duplicates are possible. Achieved by doing the work, then acking. |
| **At-most-once** | Every job runs zero or one times. No duplicates; losses are possible. Achieved by acking, then doing the work. |
| **Atomic** | Happening completely or not at all, with no visible in-between state. |
| **Backoff (exponential)** | Waiting longer between each retry, typically doubling, up to a cap. |
| **Check-then-act** | The bug pattern of reading a value, then acting on it, when it may have changed in between. |
| **Dead-letter queue** | Where jobs go after too many failed attempts, for a human to inspect. |
| **Durable** | Survives a crash or restart, because it is stored on disk. |
| **Exactly-once effect** | The outcome is as if each job ran once, even if it was delivered more than once. At-least-once plus idempotency. |
| **Fencing token** | A value stamped on a claim, used to reject actions by a worker whose claim has been taken over. |
| **Handler** | The function that knows how to perform one kind of job. |
| **Idempotent** | Doing it twice has the same effect as doing it once. |
| **Idempotency key** | A unique name for one intended piece of work, sent with every attempt, so the receiver can ignore repeats. |
| **Jitter** | Randomness added to retry delays so that many failed jobs do not retry at the same instant. |
| **Job** | A message describing work to do. Data, not code. |
| **Lease** | A claim on a job that expires, so a dead worker's jobs are eventually reclaimed. (SQS: visibility timeout.) |
| **Poison message** | A job that fails every time it is attempted. |
| **Producer** | Code that creates jobs and puts them on the queue. |
| **Queue** | Where jobs wait until a worker is ready to process them. |
| **Race condition** | A bug whose outcome depends on the precise timing of concurrent operations. |
| **Retry** | Another attempt after a failure. |
| **Thundering herd** | Many clients retrying at the same moment and overwhelming a recovering server. |
| **Transactional outbox** | Writing outgoing messages into a table in the same transaction as the data change, and relaying them to the queue separately. |
| **Worker** | A running process that claims jobs and performs them. |
