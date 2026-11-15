"""Harbor verifier for an On-Call Pharmacist task (copied into each task's tests/ with pharmacy_env).

Fetches the actions the agent took from the hospital-system sidecar, replays them on a fresh copy of
the world (the remaining shifts run unattended if the agent stopped early), scores the run against
the reference and do-nothing runs for the same seed, and writes /logs/verifier/reward.json and
the replayable trajectory /logs/verifier/trajectory.jsonl.
"""
import json
import os
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from pharmacy_env.anchors import anchor_table  # noqa: E402
from pharmacy_env.engine import Env  # noqa: E402
from pharmacy_env.eval import threshold  # noqa: E402
from pharmacy_env.scoring import normalised, penalty  # noqa: E402
from pharmacy_env.tasks import TASKS  # noqa: E402

OUT = os.environ.get("PHARMACY_VERIFIER_DIR", "/logs/verifier")


def fetch_rows(url, attempts=30):
    for i in range(attempts):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                return [json.loads(l) for l in r.read().decode().splitlines() if l.strip()]
        except OSError:
            if i == attempts - 1:
                raise
            time.sleep(2)


def main():
    with open(os.path.join(HERE, "config.json")) as f:
        cfg = json.load(f)
    task, seed = cfg["task"], cfg["seed"]
    rows = fetch_rows(cfg["mcp_url"].rstrip("/") + "/trajectory")

    env = Env(TASKS[task](seed))
    calls = 0
    for r in rows:
        if r.get("type") == "tool" and r.get("args") is not None and not env.done:
            env.call(r["name"], r["args"])
            calls += 1
    stopped_early = not env.done
    env.run_to_end()
    pen = penalty(env.metrics)

    anchors = anchor_table(task, [seed])
    scores = {n: anchors[n][0][1] for n in anchors}
    p_nothing = anchors["do_nothing"][0][0]["total"]
    p_ref = anchors["careful_pharmacist"][0][0]["total"]
    score = normalised(pen["total"], p_nothing, p_ref)
    thr = threshold(scores)
    m = env.metrics

    os.makedirs(OUT, exist_ok=True)
    summary = dict(type="summary", task=task, seed=seed, stopped_early=stopped_early, tool_calls=calls,
                   penalty=pen, score=score, threshold=thr, model=os.environ.get("PHARMACY_AGENT", "harbor-agent"),
                   harness="harbor", metrics={k: (v if k != "shortfall" else {"%s/%s" % kk: vv for kk, vv in v.items()})
                                               for k, v in m.items()})
    with open(os.path.join(OUT, "trajectory.jsonl"), "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
        f.write(json.dumps(summary) + "\n")
    reward = {
        "reward": max(0.0, min(1.0, score)),        # normalised score clipped to [0, 1]
        "score": score,                              # do nothing = 0, reference pharmacist = 1
        "pass_threshold": thr,
        "passed": 1.0 if score >= thr else 0.0,
        "penalty": pen["total"],
        "reference_penalty": p_ref,
        "recalled_units_given": float(m["recalled_given"]),
        "damaged_units_given": float(m.get("damaged_given", 0)),
        "contraindicated_doses": float(m.get("contraindicated_given", 0)),
        "stopped_early": 1.0 if stopped_early else 0.0,
    }
    with open(os.path.join(OUT, "reward.json"), "w") as f:
        json.dump(reward, f, indent=1)
    print("%s seed %d: %d function calls, penalty %.1f (reference %.1f), score %.3f, threshold %.3f%s"
          % (task, seed, calls, pen["total"], p_ref, score, thr, ", stopped early" if stopped_early else ""))
    print(json.dumps(reward))


if __name__ == "__main__":
    main()
