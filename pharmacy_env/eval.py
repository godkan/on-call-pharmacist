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
import re
import sys

from .analyze import analyse
from .anchors import anchor_table
from .replay import replay
from .scoring import normalised, penalty

SEEDS = [0, 1, 2, 3, 4]
TASK_IDS = ["T1", "T2", "T3", "T4", "T5"]
CONTROL = ["C1"]
TRAJ_DIR = os.path.join("results", "trajectories")
HONEST = ["careful_pharmacist", "reactive_pharmacist", "sop_checklist", "central_only", "do_nothing"]
# Shortcut probes per task: each must lose clearly to the reference.
PROBES = {"T1": ["blanket_quarantine", "discard_all_cold", "hoard_critical"],
          "T2": ["wardwide_alternatives", "hoard_critical"], "T3": ["hoard_critical"],
          "T4": ["grant_all_requests", "hoard_critical"], "T5": ["blanket_quarantine", "hoard_critical"]}
PROCEDURE_TASKS = ["T1"]   # the SOP fully specifies the task: no judgment gap is claimed
JUDGMENT_GAP = 0.15        # reference must beat the rule-based checklist by this much
FLAP_MARGIN = 0.05         # threshold must sit this far from both anchors around it
EXPLOIT_MARGIN = 0.05      # a shortcut must score at least this much below the reference


def threshold(scores):
    """Midpoint of the reference and the best other honest anchor on this seed, never above the
    reference itself (on the procedure task T1 another honest anchor can edge the reference)."""
    best = sorted((scores[n] for n in HONEST), reverse=True)[:2]
    return min(scores["careful_pharmacist"], (best[0] + best[1]) / 2)


def check_gates(task, rows):
    fails, thresholds = [], {}
    for i, seed in enumerate(SEEDS):
        sc = {n: rows[n][i][1] for n in rows}
        thr = thresholds[seed] = threshold(sc)
        if task in CONTROL:
            continue
        ref, sop = sc["careful_pharmacist"], sc["sop_checklist"]
        if not (ref > sop >= sc["do_nothing"] - 1e-9) and task not in PROCEDURE_TASKS:
            fails.append("seed %d: ordering" % seed)
        if task in PROCEDURE_TASKS and not ref >= max(sc[n] for n in HONEST) - 0.05:
            fails.append("seed %d: reference not best" % seed)
        if task not in PROCEDURE_TASKS:
            if ref - sop < JUDGMENT_GAP:
                fails.append("seed %d: judgment gap" % seed)
            second = sorted((sc[n] for n in HONEST if n != "careful_pharmacist"), reverse=True)[0]
            if min(ref - thr, thr - second) < FLAP_MARGIN:
                fails.append("seed %d: threshold margin" % seed)
        for probe in PROBES.get(task, []):
            if sc[probe] > ref - EXPLOIT_MARGIN:
                fails.append("seed %d: %s not suppressed" % (seed, probe))
        if sc["stop_early"] >= thr:
            fails.append("seed %d: stop_early reaches threshold" % seed)
    return fails, thresholds


def main():
    ok = True
    print("=" * 78)
    print("1. Anchor policies (normalised score: do_nothing = 0, careful_pharmacist = 1)")
    print("=" * 78)
    thresholds, anchor_pen = {}, {}
    for task in TASK_IDS + CONTROL:
        rows = anchor_table(task, SEEDS)
        for i, seed in enumerate(SEEDS):
            anchor_pen[(task, seed)] = (rows["do_nothing"][i][0]["total"], rows["careful_pharmacist"][i][0]["total"])
        print("\n%s            %s    mean" % (task, "  ".join("seed%d" % s for s in SEEDS)))
        for n, vals in rows.items():
            scs = [sc for _, sc in vals]
            print("  %-20s %s   %5.2f" % (n, "  ".join("%5.2f" % x for x in scs), sum(scs) / len(scs)))
        fails, thresholds[task] = check_gates(task, rows)
        print("  pass threshold       %s" % "  ".join("%5.2f" % thresholds[task][s] for s in SEEDS))
        if task in CONTROL:
            print("  gates: not claimed (control task)")
        elif fails:
            ok = False
            print("  GATES FAILED: " + "; ".join(fails))
        elif task in PROCEDURE_TASKS:
            print("  gates (reference best, exploit suppression, stop-early below threshold): all passed")
        else:
            print("  gates (ordering, judgment gap, threshold margin, exploit suppression, "
                  "stop-early below threshold): all passed")

    print("\n" + "=" * 78)
    print("2. Recorded model runs (replayed from %s)" % TRAJ_DIR)
    print("=" * 78)
    paths = sorted(glob.glob(os.path.join(TRAJ_DIR, "*.jsonl")))
    if not paths:
        print("  no trajectories found")
    print("\n  %-5s %-5s %-4s %-31s %-9s %6s %9s %7s  %s" % (
        "task", "seed", "run", "model", "memory", "score", "threshold", "pass?", "replay"))
    results, scored = [], []
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
        run = re.search(r"_run(\d+)\.jsonl$", p)
        # Runs with reasoning switched on are reported separately from the default runs.
        effort = summary.get("reasoning_effort")
        label = summary.get("model") + ("" if effort in (None, "none") else " (%s)" % effort) + \
            (" +hint" if summary.get("hint") else "")
        scored.append((summary["task"], label, score, thr))
        print("  %-5s %-5s %-4s %-31s %-9s %6.2f %9s %7s  %s" % (
            summary["task"], summary["seed"], run.group(1) if run else "1", label,
            summary.get("memory", "full"), score, "%.2f" % thr if thr is not None else "-",
            {True: "yes", False: "NO", None: "-"}[passed], "MATCH" if match else "MISMATCH"))

    if scored:
        print("\n  Per task (all seeds and repeated runs; reference = 1.00 on every seed):")
        print("  %-5s %-31s %4s %6s %6s %6s %16s %16s" % ("task", "model", "runs", "mean", "min", "max",
                                                         "below reference", "below threshold"))
        for key in sorted({(t, m) for t, m, _, _ in scored}):
            rows = [(sc, thr) for t, m, sc, thr in scored if (t, m) == key]
            scs = [sc for sc, _ in rows]
            below_ref = sum(1 for sc in scs if sc < 1.0)
            below_thr = sum(1 for sc, thr in rows if thr is not None and sc < thr)
            print("  %-5s %-31s %4d %6.2f %6.2f %6.2f %16s %16s" % (
                key[0], key[1], len(rows), sum(scs) / len(scs), min(scs), max(scs),
                "%d/%d" % (below_ref, len(rows)), "%d/%d" % (below_thr, len(rows))))

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
