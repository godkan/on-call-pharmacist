"""Replay the actions in a trajectory file and check the score is reproduced.

    python3 -m pharmacy_env.replay results/traj/T1_seed0_....jsonl
"""
import json
import sys

from .engine import Env
from .scoring import penalty
from .tasks import TASKS


def replay(path):
    with open(path) as f:
        rows = [json.loads(l) for l in f]
    summary = rows[-1]
    env = Env(TASKS[summary["task"]](summary["seed"]))
    for r in rows:
        if r["type"] == "tool" and r["args"] is not None and not env.done:
            env.call(r["name"], r["args"])
    env.run_to_end()
    got = penalty(env.metrics)["total"]
    want = summary["penalty"]["total"]
    return got, want


if __name__ == "__main__":
    got, want = replay(sys.argv[1])
    print("replayed penalty %.3f, recorded %.3f -> %s" % (got, want, "MATCH" if abs(got - want) < 1e-9 else "MISMATCH"))
    sys.exit(0 if abs(got - want) < 1e-9 else 1)
