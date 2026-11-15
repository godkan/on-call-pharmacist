"""The runs a judge needs for one task and seed, in one command. No API key needed.

    python3 -m pharmacy_env.judge --task T1 --seed 0
    python3 -m pharmacy_env.judge --task T1 --seed 0 --trajectory results/traj/T1_seed0_*.jsonl

Runs the reference pharmacist, the do-nothing baseline and the stop-early baseline, prints each one's
penalty and normalised score, and the pass threshold for that seed. Any agent trajectories given
(from run_agent, run_claude, the Python API in pharmacy_env.gym_env or the MCP server) are replayed
action by action and scored against the same anchors.
"""
import argparse
import glob
import json

from .anchors import anchor_table
from .eval import HONEST, threshold
from .replay import replay
from .scoring import normalised
from .tasks import TASKS

SHOWN = ["careful_pharmacist", "do_nothing", "stop_early"]
LABEL = {"careful_pharmacist": "reference", "do_nothing": "do-nothing baseline", "stop_early": "stop-early baseline"}
EXPECT = {"careful_pharmacist": "1.00 by definition", "do_nothing": "0.00 by definition",
          "stop_early": "below the threshold"}


def judge(task, seed, trajectories=()):
    rows = anchor_table(task, [seed])
    pen = {n: rows[n][0][0] for n in rows}
    sc = {n: rows[n][0][1] for n in rows}
    thr = threshold(sc)
    p_nothing, p_ref = pen["do_nothing"]["total"], pen["careful_pharmacist"]["total"]
    print("%s seed %d  (score = (P_do_nothing - P) / (P_do_nothing - P_reference))" % (task, seed))
    print("  %-34s %9s %7s   %s" % ("run", "penalty", "score", "expected"))
    for n in SHOWN:
        print("  %-34s %9.1f %7.2f   %s" % (LABEL[n], pen[n]["total"], sc[n], EXPECT[n]))
    second = max((n for n in HONEST if n != "careful_pharmacist"), key=lambda n: sc[n])
    print("  pass threshold %.2f  (midpoint of the reference and the best other honest anchor, %s %.2f)"
          % (thr, second, sc[second]))
    ok = abs(sc["careful_pharmacist"] - 1) < 1e-9 and abs(sc["do_nothing"]) < 1e-9 and sc["stop_early"] < thr
    for path in trajectories:
        with open(path) as f:
            summary = json.loads(f.readlines()[-1])
        if (summary.get("task"), summary.get("seed")) != (task, seed):
            print("  %s: recorded for %s seed %s, skipped" % (path, summary.get("task"), summary.get("seed")))
            continue
        got, want = replay(path)
        match = abs(got - want) < 1e-6
        ok &= match
        score = normalised(got, p_nothing, p_ref)
        effort = summary.get("reasoning_effort")
        label = (summary.get("model") or "?") + ("" if effort in (None, "none") else " (%s)" % effort) + \
            (" +hint" if summary.get("hint") else "")
        print("  %-34s %9.1f %7.2f   %s threshold; replay %s" % (
            label, got, score, "below" if score < thr else "AT OR ABOVE", "MATCH" if match else "MISMATCH"))
        print("      %s" % path)
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", default="T1", choices=sorted(TASKS))
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--trajectory", nargs="*", default=[], help="agent trajectory files (globs allowed)")
    a = ap.parse_args()
    paths = [p for pattern in a.trajectory for p in sorted(glob.glob(pattern))]
    ok = judge(a.task, a.seed, paths)
    print("OK" if ok else "CHECK FAILED")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
