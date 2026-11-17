"""
Writes event_log.csv: a made-up event log of 300 orders.

Every order is supposed to go Order, Credit check, Pick, Pack, QC, Ship, Invoice.
Some of them don't. A few skip the credit check, some sit in credit review twice,
and some fail QC and go back to packing. The log is seeded, so it comes out the
same every time.

    python make_log.py
"""

import csv
import random
from datetime import datetime, timedelta

STEPS = ["Order", "Credit check", "Pick", "Pack", "QC", "Ship", "Invoice"]

# Typical hours a step takes once it starts, and typical hours an order waits before it.
WORK_HOURS = {"Order": 0.2, "Credit check": 1.5, "Pick": 1.0, "Pack": 1.5, "QC": 2.0, "Ship": 0.8, "Invoice": 0.3}
WAIT_HOURS = {"Order": 0.0, "Credit check": 3.0, "Pick": 2.0, "Pack": 1.5, "QC": 9.0, "Ship": 2.0, "Invoice": 1.0}


def path_random(seed=42):
    """The same small random number generator the demo on my site uses, so both show the same 300 orders."""
    state = seed & 0xFFFFFFFF

    def imul(a, b):
        return (a * b) & 0xFFFFFFFF

    def rnd():
        nonlocal state
        state = (state + 0x6D2B79F5) & 0xFFFFFFFF
        t = imul(state ^ (state >> 15), 1 | state)
        t = ((t + imul(t ^ (t >> 7), 61 | t)) & 0xFFFFFFFF) ^ t
        return (t ^ (t >> 14)) / 4294967296

    return rnd


def build_paths(orders=300, seed=42):
    rnd = path_random(seed)
    paths = []
    for _ in range(orders):
        path = [0]
        if rnd() > 0.22:              # most orders get a credit check
            path.append(1)
            if rnd() < 0.11:          # some are held and checked again
                path.append(1)
        path += [2, 3, 4]
        if rnd() < 0.18:              # failed QC, back to packing
            path += [3, 4]
            if rnd() < 0.3:           # and sometimes a second time
                path += [3, 4]
        path += [5, 6]
        paths.append([STEPS[i] for i in path])
    return paths


def build_events(paths, seed=7):
    clock = random.Random(seed)
    first_day = datetime(2026, 9, 1, 8, 0)
    rows = []
    for number, path in enumerate(paths, start=1):
        order_id = f"SO-{1000 + number}"
        now = first_day + timedelta(hours=clock.uniform(0, 24 * 45))   # orders arrive over about six weeks
        for step in path:
            now += timedelta(hours=WAIT_HOURS[step] * clock.uniform(0.3, 1.9))
            started = now
            now += timedelta(hours=WORK_HOURS[step] * clock.uniform(0.6, 1.6))
            rows.append((order_id, step, started, now))
    rows.sort(key=lambda r: (r[2], r[0]))
    return rows


def main():
    rows = build_events(build_paths())
    with open("event_log.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["order_id", "step", "started_at", "finished_at"])
        for order_id, step, started, finished in rows:
            writer.writerow([order_id, step, started.strftime("%Y-%m-%d %H:%M"), finished.strftime("%Y-%m-%d %H:%M")])
    print(f"Wrote event_log.csv: {len(rows)} events across {len({r[0] for r in rows})} orders")


if __name__ == "__main__":
    main()
