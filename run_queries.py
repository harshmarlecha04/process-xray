"""
Loads event_log.csv into SQLite and runs every query in queries.sql.

    python run_queries.py
"""

import csv
import sqlite3
import sys


def load(path="event_log.csv"):
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE events (order_id TEXT, step TEXT, started_at TEXT, finished_at TEXT)")
    with open(path, newline="") as f:
        rows = [(r["order_id"], r["step"], r["started_at"], r["finished_at"]) for r in csv.DictReader(f)]
    db.executemany("INSERT INTO events VALUES (?, ?, ?, ?)", rows)
    return db


def read_queries(path="queries.sql"):
    """Split the file on '-- name:' lines. Returns a list of (name, sql)."""
    queries, name, lines = [], None, []
    with open(path) as f:
        for line in f:
            if line.startswith("-- name:"):
                if name:
                    queries.append((name, "".join(lines).strip()))
                name, lines = line.split(":", 1)[1].strip(), []
            elif name:
                lines.append(line)
    if name:
        queries.append((name, "".join(lines).strip()))
    return queries


def run(db, sql):
    cursor = db.execute(sql)
    return [c[0] for c in cursor.description], cursor.fetchall()


def main():
    try:
        db = load()
    except FileNotFoundError:
        print("Can't find event_log.csv. Run 'python make_log.py' first.", file=sys.stderr)
        return 1
    for name, sql in read_queries():
        columns, rows = run(db, sql)
        print(f"\n{name}")
        print("  " + " | ".join(columns))
        for row in rows:
            print("  " + " | ".join(str(v) for v in row))
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
