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
