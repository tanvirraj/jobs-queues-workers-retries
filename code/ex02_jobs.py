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
