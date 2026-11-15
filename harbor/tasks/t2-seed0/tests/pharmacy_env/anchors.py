"""Run every scripted anchor on a task over several seeds.

    python3 -m pharmacy_env.anchors --task T1 --seeds 0 1 2
"""
import argparse

from .engine import Env
from .policies import POLICIES
from .scoring import normalised, penalty
from .tasks import TASKS


def run_anchor(task_id, seed, name):
    env = Env(TASKS[task_id](seed))
    POLICIES[name](env)
    return env


def anchor_table(task_id, seeds):
    rows = {}
    for seed in seeds:
        pens = {n: penalty(run_anchor(task_id, seed, n).metrics) for n in POLICIES}
        for n, p in pens.items():
            rows.setdefault(n, []).append(
                (p, normalised(p["total"], pens["do_nothing"]["total"], pens["careful_pharmacist"]["total"])))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", default="T1")
    ap.add_argument("--seeds", type=int, nargs="+", default=[0, 1, 2])
    a = ap.parse_args()
    rows = anchor_table(a.task, a.seeds)
    print("%-20s %s" % ("policy", "  ".join("seed%-2d score  penalty(recalled/short/wrongQ/urgent/missed)" % s
                                             for s in a.seeds)))
    for n, vals in rows.items():
        cells = []
        for p, sc in vals:
            cells.append("%6.2f  %6.1f (%5.0f/%5.0f/%4.0f/%4.0f/%3.0f)" % (
                sc, p["total"], p["recalled_given"], p["shortfall"], p["wrong_quarantine"],
                p["urgent_premium"], p["missed_shifts"]))
        print("%-20s %s" % (n, "   ".join(cells)))


if __name__ == "__main__":
    main()
