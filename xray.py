"""
Process X-ray

The flowchart says how orders are supposed to move. The event log says how they
really moved. This reads the log and reports the difference: every path orders
actually took, how many skipped a step or repeated one, where they waited, and
what the detours cost in time.

    python xray.py
    python xray.py --log my_events.csv --official "Order,Credit check,Pick,Pack,QC,Ship,Invoice"
"""

import argparse
import sys

import pandas as pd

OFFICIAL = ["Order", "Credit check", "Pick", "Pack", "QC", "Ship", "Invoice"]
NEEDED = ["order_id", "step", "started_at", "finished_at"]


def load_log(path):
    """Read the event log and put each order's events in the order they happened."""
    log = pd.read_csv(path)
    missing = [c for c in NEEDED if c not in log.columns]
    if missing:
        raise ValueError(f"{path} is missing these columns: {', '.join(missing)}")
    if log.empty:
        raise ValueError(f"{path} has no events in it")
    log["started_at"] = pd.to_datetime(log["started_at"])
    log["finished_at"] = pd.to_datetime(log["finished_at"])
    if (log["finished_at"] < log["started_at"]).any():
        raise ValueError("Some events finish before they start")
    return log.sort_values(["order_id", "started_at"], kind="stable").reset_index(drop=True)


def paths(log):
    """One row per order: the steps it went through, in order."""
    return log.groupby("order_id")["step"].agg(tuple)


def variants(order_paths, official=OFFICIAL):
    """Every distinct path, most common first."""
    counts = order_paths.value_counts()
    table = pd.DataFrame({
        "path": [" > ".join(p) for p in counts.index],
        "orders": counts.values,
        "share": counts.values / counts.sum(),
        "official": [list(p) == list(official) for p in counts.index],
    })
    return table


def deviations(order_paths, official=OFFICIAL):
    """How many orders skipped an official step, and how many did a step more than once."""
    skipped = {step: int(sum(step not in p for p in order_paths)) for step in official}
    repeated = {step: int(sum(p.count(step) > 1 for p in order_paths)) for step in official}
    return {
        "orders": len(order_paths),
        "on_the_flowchart": int(sum(list(p) == list(official) for p in order_paths)),
        "skipped": {k: v for k, v in skipped.items() if v},
        "repeated": {k: v for k, v in repeated.items() if v},
    }


def handoffs(log):
    """How often each step was followed by each other step."""
    nxt = log.groupby("order_id")["step"].shift(-1)
    pairs = pd.DataFrame({"from_step": log["step"], "to_step": nxt}).dropna()
    return pairs.value_counts().rename("orders").reset_index()


def waits(log):
    """Hours an order sat between the end of one step and the start of the next, by the step it was waiting for."""
    previous_end = log.groupby("order_id")["finished_at"].shift(1)
    hours = (log["started_at"] - previous_end).dt.total_seconds() / 3600
    table = pd.DataFrame({"step": log["step"], "hours": hours}).dropna()
    summary = table.groupby("step")["hours"].agg(median="median", worst="max", times="count")
    return summary.sort_values("median", ascending=False)


def cycle_times(log, official=OFFICIAL):
    """Hours from an order's first event to its last, with flags for how it strayed from the flowchart."""
    per_order = log.groupby("order_id").agg(start=("started_at", "min"), end=("finished_at", "max"), path=("step", tuple))
    per_order["hours"] = (per_order["end"] - per_order["start"]).dt.total_seconds() / 3600
    per_order["official"] = [list(p) == list(official) for p in per_order["path"]]
    per_order["skipped"] = [any(step not in p for step in official) for p in per_order["path"]]
    per_order["repeated"] = [len(set(p)) < len(p) for p in per_order["path"]]
    return per_order[["hours", "official", "skipped", "repeated"]]


def draw_map(log, official, path):
    """Draw the process the log describes. Thicker lines carried more orders. Blue lines are not on the flowchart."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.patches import FancyArrowPatch
    except ImportError:
        raise SystemExit("The map needs matplotlib. Install it with: pip install -r requirements.txt")

    extra = [s for s in log["step"].unique() if s not in official]
    order = list(official) + extra
    x = {step: i for i, step in enumerate(order)}
    pairs = handoffs(log)
    busiest = pairs["orders"].max()
    planned = set(zip(official, official[1:]))

    fig, ax = plt.subplots(figsize=(10, 4.4), dpi=160)
    for row in pairs.itertuples():
        a, b = x[row.from_step], x[row.to_step]
        width = 1 + 7 * row.orders / busiest
        on_chart = (row.from_step, row.to_step) in planned
        colour = "#d9d9d9" if on_chart else "#1433ff"
        if a == b:                                    # the same step twice in a row
            loop = FancyArrowPatch((a - 0.12, 0.05), (a + 0.12, 0.05), connectionstyle="arc3,rad=-2.2", arrowstyle="-", lw=width, color=colour, alpha=0.75)
            ax.add_patch(loop)
            ax.text(a, 0.4, f"{row.orders} done twice in a row", ha="center", va="bottom", fontsize=8, color=colour)
        elif on_chart:
            ax.plot([a, b], [0, 0], lw=width, color=colour, solid_capstyle="round", zorder=1)
        else:
            bend = 0.55 if b < a else 0.45            # going back arcs over the top, skipping ahead arcs underneath
            arc = FancyArrowPatch((a, 0), (b, 0), connectionstyle=f"arc3,rad={bend}", arrowstyle="-|>", mutation_scale=10, lw=width, color=colour, alpha=0.75, zorder=1)
            ax.add_patch(arc)
            label = f"{row.orders} sent back" if b < a else f"{row.orders} skipped ahead"
            ax.text((a + b) / 2, (0.4 if b < a else -0.44) * abs(a - b) ** 0.6, label, ha="center", va="center", fontsize=8, color=colour)
    for step, i in x.items():
        ax.scatter([i], [0], s=170, color="white", edgecolors="black", linewidths=1.5, zorder=3)
        ax.text(i, -0.2, step, ha="center", va="top", fontsize=9)
    ax.set_xlim(-0.6, len(order) - 0.4)
    ax.set_ylim(-1.1, 1.2)
    ax.axis("off")
    ax.set_title(f"What {log['order_id'].nunique()} orders actually did", loc="left", fontsize=11)
    fig.text(0.02, 0.02, "Grey is the flowchart. Blue is everything else. Thicker lines carried more orders.", fontsize=8, color="#5f5f5f")
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(path)
    plt.close(fig)


def report(log, official=OFFICIAL):
    """Everything the tool has to say, as text."""
    order_paths = paths(log)
    table = variants(order_paths, official)
    found = deviations(order_paths, official)
    total = found["orders"]
    lines = []
    say = lines.append

    say(f"\n{total} orders, {len(log):,} events, {len(table)} different paths through one process.\n")
    say(f"On the flowchart: {found['on_the_flowchart']} orders ({found['on_the_flowchart'] / total:.0%}). "
        f"Everything else: {total - found['on_the_flowchart']} ({1 - found['on_the_flowchart'] / total:.0%}).\n")

    say("Paths, most common first")
    for row in table.itertuples():
        tag = "   (the flowchart)" if row.official else ""
        say(f"  {row.orders:>4}  {row.share:>5.1%}  {row.path}{tag}")

    if found["skipped"]:
        say("\nSteps that were skipped")
        for step, n in found["skipped"].items():
            say(f"  {step}: {n} orders ({n / total:.0%}) never had it")
    if found["repeated"]:
        say("\nSteps done more than once")
        for step, n in found["repeated"].items():
            say(f"  {step}: {n} orders ({n / total:.0%})")

    wait = waits(log)
    say("\nWhere orders wait, in hours before the step starts")
    for step, row in wait.iterrows():
        say(f"  {step:<14} median {row['median']:>5.1f}   worst {row['worst']:>5.1f}")
    slowest = wait.index[0]

    times = cycle_times(log, official)
    clean = times.loc[times["official"], "hours"].median()
    say(f"\nOrder to invoice, median hours (all orders: {times['hours'].median():.1f})")
    for label, flag in (("on the flowchart", "official"), ("skipped a step", "skipped"), ("repeated a step", "repeated")):
        group = times.loc[times[flag], "hours"]
        if len(group):
            gap = "" if flag == "official" or pd.isna(clean) else f"   ({group.median() - clean:+.1f} against the flowchart)"
            say(f"  {label:<17} {group.median():>5.1f}   {len(group)} orders{gap}")

    say(f"\nWhat I'd look at first: the wait before {slowest}. It is the longest queue in the process, "
        f"and it is where the repeats pile up.\n" if slowest in found["repeated"] else
        f"\nWhat I'd look at first: the wait before {slowest}. It is the longest queue in the process.\n")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Compare an event log with the official process.")
    parser.add_argument("--log", default="event_log.csv", help="CSV with order_id, step, started_at, finished_at")
    parser.add_argument("--official", default=",".join(OFFICIAL), help="the official steps, in order, separated by commas")
    parser.add_argument("--map", default=None, help="save a picture of the real process to this PNG file")
    args = parser.parse_args(argv)
    official = [s.strip() for s in args.official.split(",") if s.strip()]

    try:
        log = load_log(args.log)
    except FileNotFoundError:
        print(f"Can't find the log file '{args.log}'. Run 'python make_log.py' to create the sample one.", file=sys.stderr)
        return 1
    except ValueError as problem:
        print(f"Can't read the log: {problem}", file=sys.stderr)
        return 1

    print(report(log, official))
    if args.map:
        draw_map(log, official, args.map)
        print(f"Map saved to {args.map}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
