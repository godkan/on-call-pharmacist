"""Does the result depend on the penalty weights? No API key needed.

    python3 -m pharmacy_env.sensitivity [model-substring]

Scales one penalty weight at a time by 0.25 and by 4, recomputes the penalty of every recorded
run (hint ablation excluded) and of the reference on the same seed, and counts the runs that stay
below the reference. Default model filter: "deepseek".
"""
import glob
import json
import os
import sys

from . import scoring as S
from .anchors import run_anchor

TRAJ_DIR = os.path.join("results", "trajectories")
FACTORS = (0.25, 4.0)


def load_runs(model_filter):
    runs = []
    for path in sorted(glob.glob(os.path.join(TRAJ_DIR, "*.jsonl"))):
        with open(path) as f:
            s = json.loads(f.readlines()[-1])
        if model_filter not in (s.get("model") or "") or s.get("hint"):
            continue
        m = s["metrics"]
        m["shortfall"] = {tuple(k.split("/")): v for k, v in m["shortfall"].items()}
        if abs(S.penalty(m)["total"] - s["penalty"]["total"]) > 1e-6:
            raise SystemExit("penalty of %s does not recompute" % path)
        runs.append((s["task"], s["seed"], m))
    return runs


def below_reference(runs, ref, weights):
    saved = dict(S.WEIGHTS)
    S.WEIGHTS.clear()
    S.WEIGHTS.update(weights)
    try:
        return sum(1 for t, seed, m in runs if S.penalty(m)["total"] > S.penalty(ref[(t, seed)])["total"])
    finally:
        S.WEIGHTS.clear()
        S.WEIGHTS.update(saved)


def main():
    model_filter = sys.argv[1] if len(sys.argv) > 1 else "deepseek"
    runs = load_runs(model_filter)
    ref = {(t, seed): run_anchor(t, seed, "careful_pharmacist").metrics for t, seed in {(t, s) for t, s, _ in runs}}
    base = dict(S.WEIGHTS)
    print("%d runs matching %r; below the reference with the default weights: %d"
          % (len(runs), model_filter, below_reference(runs, ref, base)))
    print("%-20s %s" % ("weight", "  ".join("x%-5s" % f for f in FACTORS)))
    for key in sorted(base):
        counts = [below_reference(runs, ref, dict(base, **{key: base[key] * f})) for f in FACTORS]
        print("%-20s %s" % (key, "  ".join("%-6d" % c for c in counts)))
    print("(T3 uses its own weight of 6 for critical shortfalls, so shortfall_critical does not change T3.)")


if __name__ == "__main__":
    main()
