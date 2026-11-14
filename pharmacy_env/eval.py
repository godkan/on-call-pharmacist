"""One-command evaluation. No API key needed.

    python3 -m pharmacy_env.eval

1. Runs every scripted anchor on T1 and T5 over five seeds and checks the
   calibration gates (ordering, judgment gap, threshold margin, exploit suppression).
2. Replays every recorded model trajectory in results/trajectories/ and checks the
   recorded score is reproduced exactly.
3. Prints the results table (model vs pass threshold per seed) and the failure
   modes found in each trajectory.

Exit code is non-zero if any gate or replay check fails.
"""
import glob
import json
import os
import sys

from .analyze import analyse
from .anchors import anchor_table
from .replay import replay
from .scoring import normalised, penalty

SEEDS = [0, 1, 2, 3, 4]
TRAJ_DIR = os.path.join("results", "trajectories")
HONEST = ["careful_pharmacist", "sop_checklist", "central_only", "do_nothing"]
JUDGMENT_GAP = 0.15   # reference must beat the rule-based checklist by this much (T5)
FLAP_MARGIN = 0.05    # threshold must sit this far from both anchors around it


def threshold(scores):
    """Midpoint of the two best honest anchors on this seed."""
    best = sorted((scores[n] for n in HONEST), reverse=True)[:2]
    return (best[0] + best[1]) / 2


def check_gates(task, rows):
    """Gates are claimed for T5 only. T1 is a control task where the rule-based
    checklist already reaches the reference, so it has no judgment gap by design."""
    fails, thresholds = [], {}
    for i, seed in enumerate(SEEDS):
        sc = {n: rows[n][i][1] for n in rows}
        thr = thresholds[seed] = threshold(sc)
        if task != "T5":
            continue
        if not (sc["careful_pharmacist"] > sc["sop_checklist"] > sc["central_only"] >= sc["do_nothing"]):
            fails.append("seed %d: ordering" % seed)
        if sc["careful_pharmacist"] - sc["sop_checklist"] < JUDGMENT_GAP:
            fails.append("seed %d: judgment gap" % seed)
        if min(sc["careful_pharmacist"] - thr, thr - sc["sop_checklist"]) < FLAP_MARGIN:
            fails.append("seed %d: threshold margin" % seed)
        # As in StoreBench, the exploit must score below every honest anchor that acts;
        # do_nothing is the zero point, not a competitor.
        if not all(sc["blanket_quarantine"] < sc[n] for n in HONEST if n != "do_nothing"):
            fails.append("seed %d: exploit not suppressed" % seed)
    return fails, thresholds


def main():
    ok = True
    print("=" * 78)
    print("1. Anchor policies (normalised score: do_nothing = 0, careful_pharmacist = 1)")
    print("=" * 78)
    thresholds, anchor_pen = {}, {}
    for task in ("T1", "T5"):
        rows = anchor_table(task, SEEDS)
        for i, seed in enumerate(SEEDS):
            anchor_pen[(task, seed)] = (rows["do_nothing"][i][0]["total"], rows["careful_pharmacist"][i][0]["total"])
        print("\n%s            %s    mean" % (task, "  ".join("seed%d" % s for s in SEEDS)))
        for n, vals in rows.items():
            scs = [sc for _, sc in vals]
            print("  %-20s %s   %5.2f" % (n, "  ".join("%5.2f" % x for x in scs), sum(scs) / len(scs)))
        fails, thresholds[task] = check_gates(task, rows)
        print("  pass threshold       %s" % "  ".join("%5.2f" % thresholds[task][s] for s in SEEDS))
        if task != "T5":
            print("  gates: not claimed (control task)")
        elif fails:
            ok = False
            print("  GATES FAILED: " + "; ".join(fails))
        else:
            print("  gates (ordering, judgment gap, threshold margin, exploit suppression): all passed")

    print("\n" + "=" * 78)
    print("2. Recorded model runs (replayed from %s)" % TRAJ_DIR)
    print("=" * 78)
    paths = sorted(glob.glob(os.path.join(TRAJ_DIR, "*.jsonl")))
    if not paths:
        print("  no trajectories found")
    print("\n  %-5s %-5s %-18s %-9s %7s %10s  %-6s %s" % (
        "task", "seed", "model", "memory", "score", "threshold", "pass?", "replay"))
    results = []
    for p in paths:
        with open(p) as f:
            summary = json.loads(f.readlines()[-1])
        got, want = replay(p)
        match = abs(got - want) < 1e-6
        ok &= match
        key = (summary["task"], summary["seed"])
        # Score is recomputed from the replayed penalty against the current anchors.
        score = normalised(got, *anchor_pen[key]) if key in anchor_pen else summary["score"]
        thr = thresholds.get(summary["task"], {}).get(summary["seed"])
        passed = score >= thr if thr is not None else None
        results.append((p, summary))
        print("  %-5s %-5s %-18s %-9s %7.2f %10s  %-6s %s" % (
            summary["task"], summary["seed"], summary.get("model"), summary.get("memory", "full"),
            score, "%.2f" % thr if thr is not None else "-",
            {True: "yes", False: "NO", None: "-"}[passed], "MATCH" if match else "MISMATCH"))

    print("\n" + "=" * 78)
    print("3. Failure modes per trajectory (shift numbers are 1-based)")
    print("=" * 78)
    for p, s in results:
        _, findings = analyse(p)
        print("\n  %s" % os.path.basename(p))
        for kind, shift, text in findings:
            print("    [%s] %s%s" % (kind, "" if shift is None else "shift %d: " % (shift + 1), text))
    print("\nOVERALL:", "OK" if ok else "FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
