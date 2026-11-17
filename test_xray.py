"""Run with:  python -m unittest"""

import os
import unittest

import pandas as pd

import make_log
import run_queries
import xray

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(HERE, "event_log.csv")
SQL = os.path.join(HERE, "queries.sql")


def tiny_log():
    """Three orders I can check by hand: one clean, one that skips the credit check, one sent back to packing."""
    rows = [
        ("A", "Order", "2026-01-05 08:00", "2026-01-05 08:10"),
        ("A", "Credit check", "2026-01-05 09:10", "2026-01-05 10:00"),
        ("A", "Pick", "2026-01-05 12:00", "2026-01-05 13:00"),
        ("B", "Order", "2026-01-05 08:00", "2026-01-05 08:10"),
        ("B", "Pick", "2026-01-05 09:10", "2026-01-05 10:00"),
        ("C", "Order", "2026-01-05 08:00", "2026-01-05 08:10"),
        ("C", "Credit check", "2026-01-05 08:40", "2026-01-05 09:00"),
        ("C", "Pick", "2026-01-05 10:00", "2026-01-05 11:00"),
        ("C", "Credit check", "2026-01-05 15:00", "2026-01-05 15:30"),
        ("C", "Pick", "2026-01-05 16:30", "2026-01-05 17:30"),
    ]
    log = pd.DataFrame(rows, columns=["order_id", "step", "started_at", "finished_at"])
    log["started_at"] = pd.to_datetime(log["started_at"])
    log["finished_at"] = pd.to_datetime(log["finished_at"])
    return log


OFFICIAL = ["Order", "Credit check", "Pick"]


class HandCheckedTests(unittest.TestCase):
    def setUp(self):
        self.log = tiny_log()
        self.paths = xray.paths(self.log)

    def test_paths(self):
        self.assertEqual(self.paths["A"], ("Order", "Credit check", "Pick"))
        self.assertEqual(self.paths["B"], ("Order", "Pick"))
        self.assertEqual(self.paths["C"], ("Order", "Credit check", "Pick", "Credit check", "Pick"))

    def test_variants(self):
        table = xray.variants(self.paths, OFFICIAL)
        self.assertEqual(len(table), 3)
        self.assertEqual(int(table["official"].sum()), 1)
        self.assertAlmostEqual(table["share"].sum(), 1.0)

    def test_deviations(self):
        found = xray.deviations(self.paths, OFFICIAL)
        self.assertEqual(found["on_the_flowchart"], 1)
        self.assertEqual(found["skipped"], {"Credit check": 1})
        self.assertEqual(found["repeated"], {"Credit check": 1, "Pick": 1})

    def test_handoffs(self):
        pairs = xray.handoffs(self.log).set_index(["from_step", "to_step"])["orders"]
        self.assertEqual(pairs[("Order", "Credit check")], 2)
        self.assertEqual(pairs[("Order", "Pick")], 1)
        self.assertEqual(pairs[("Pick", "Credit check")], 1)

    def test_waits(self):
        wait = xray.waits(self.log)
        # before Pick: A waited 2h, B 1h, C 1h and 1h
        self.assertAlmostEqual(wait.loc["Pick", "median"], 1.0)
        self.assertAlmostEqual(wait.loc["Pick", "worst"], 2.0)

    def test_cycle_times(self):
        times = xray.cycle_times(self.log, OFFICIAL)
        self.assertAlmostEqual(times.loc["A", "hours"], 5.0)
        self.assertAlmostEqual(times.loc["C", "hours"], 9.5)
        self.assertTrue(times.loc["B", "skipped"])
        self.assertTrue(times.loc["C", "repeated"])
        self.assertTrue(times.loc["A", "official"])


class SampleLogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.log = xray.load_log(LOG)
        cls.paths = xray.paths(cls.log)

    def test_log_matches_generator(self):
        made = [tuple(p) for p in make_log.build_paths()]
        self.assertEqual(sorted(made), sorted(self.paths.tolist()))

    def test_headline_numbers(self):
        found = xray.deviations(self.paths)
        self.assertEqual(found["orders"], 300)
        self.assertEqual(len(xray.variants(self.paths)), 9)
        self.assertEqual(found["skipped"]["Credit check"], 70)
        self.assertEqual(found["repeated"]["Pack"], 47)

    def test_every_order_starts_and_ends_properly(self):
        self.assertTrue(all(p[0] == "Order" and p[-1] == "Invoice" for p in self.paths))

    def test_report_runs(self):
        text = xray.report(self.log)
        self.assertIn("9 different paths", text)


class SqlAgreesWithPandas(unittest.TestCase):
    """The SQL and the Python are two ways of asking the same thing. They have to agree."""

    @classmethod
    def setUpClass(cls):
        cls.db = run_queries.load(LOG)
        cls.queries = dict(run_queries.read_queries(SQL))
        cls.log = xray.load_log(LOG)
        cls.paths = xray.paths(cls.log)

    def test_paths(self):
        _, rows = run_queries.run(self.db, self.queries["Paths, most common first"])
        from_sql = {path: orders for path, orders, _ in rows}
        table = xray.variants(self.paths)
        self.assertEqual(from_sql, dict(zip(table["path"], table["orders"])))

    def test_skipped_credit_check(self):
        _, rows = run_queries.run(self.db, self.queries["Orders that never had a credit check"])
        self.assertEqual(rows[0][0], xray.deviations(self.paths)["skipped"]["Credit check"])

    def test_packed_twice(self):
        _, rows = run_queries.run(self.db, self.queries["Orders packed more than once"])
        self.assertEqual(rows[0][0], xray.deviations(self.paths)["repeated"]["Pack"])

    def test_handoffs(self):
        _, rows = run_queries.run(self.db, self.queries["Hand-offs between steps"])
        from_sql = {(a, b): n for a, b, n in rows}
        pairs = xray.handoffs(self.log)
        self.assertEqual(from_sql, {(r.from_step, r.to_step): r.orders for r in pairs.itertuples()})

    def test_average_waits(self):
        _, rows = run_queries.run(self.db, self.queries["Average wait before each step, in hours"])
        previous_end = self.log.groupby("order_id")["finished_at"].shift(1)
        hours = (self.log["started_at"] - previous_end).dt.total_seconds() / 3600
        means = hours.groupby(self.log["step"]).mean().dropna()
        for step, avg, _ in rows:
            self.assertAlmostEqual(avg, means[step], delta=0.06)


class BadInputTests(unittest.TestCase):
    def test_missing_column(self):
        path = os.path.join(HERE, "_bad.csv")
        with open(path, "w") as f:
            f.write("order_id,step\nA,Order\n")
        self.addCleanup(os.remove, path)
        with self.assertRaises(ValueError):
            xray.load_log(path)


if __name__ == "__main__":
    unittest.main()
