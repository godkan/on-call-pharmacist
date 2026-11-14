"""Tag failure modes in a trajectory by replaying it against the task's ground truth.

    python3 -m pharmacy_env.analyze results/traj/T1_seed0_....jsonl [more files]

Each finding names the shift and location so it can be checked in the trajectory.
"""
import json
import sys
from collections import defaultdict

from . import world as W
from .engine import Env
from .tasks import TASKS


class AuditEnv(Env):
    """Env that records the state at every handover."""

    def __init__(self, task):
        super().__init__(task)
        self.snapshots = []   # (shift, recalled stock still available by location, shortfall so far)
        self.read_at = {}     # notice id -> shift it was first read
        self.found = set()    # lots the agent looked up or quarantined

    def call(self, name, args=None):
        args = args or {}
        if name == "end_shift" and not self.done:
            self._snapshot()
        r = super().call(name, args)
        if name == "read_notices" and "notices" in r:
            for n in r["notices"]:
                self.read_at.setdefault(n["id"], self.shift)
        if name in ("find_lot", "quarantine_lot") and "error" not in r:
            self.found.add(str(args.get("lot", "")).upper())
        return r

    def _snapshot(self):
        recalled = self.recalled_lots()
        left = defaultdict(int)
        for e in self.stock:
            if e["lot"] in recalled and e["status"] == "available" and e["qty"] > 0:
                left[(e["lot"], e["loc"])] += e["qty"]
        self.snapshots.append((self.shift, dict(left)))


def analyse(path):
    rows = [json.loads(l) for l in open(path)]
    summary = rows[-1]
    env = AuditEnv(TASKS[summary["task"]](summary["seed"]))
    for r in rows:
        if r["type"] == "tool" and r["args"] is not None and not env.done:
            env.call(r["name"], r["args"])
    stopped_at = env.shift
    env.run_to_end()

    findings = []
    recalls = [n for n in env.notices if n.get("recall_lots")]
    for n in recalls:
        label = "%s (%s)" % (n["id"], ", ".join(n["recall_lots"]))
        if n["id"] not in env.read_at:
            findings.append(("notice_never_read", n["shift"], label))
        elif env.read_at[n["id"]] > n["shift"]:
            findings.append(("notice_read_late", env.read_at[n["id"]],
                             "%s published shift %d, read shift %d" % (label, n["shift"] + 1, env.read_at[n["id"]] + 1)))
        for shift, left in env.snapshots:
            if shift < n["shift"]:
                continue
            missed = {loc: q for (lot, loc), q in left.items() if lot in n["recall_lots"]}
            if missed:
                findings.append(("recalled_stock_left_in_use", shift,
                                 "%s still available at handover: %s" % (
                                     label, ", ".join("%s %d" % kv for kv in sorted(missed.items())))))
                break   # first handover where it was missed is enough
    if env.metrics["wrong_quarantine_units"]:
        findings.append(("good_stock_withdrawn", None, "%d units of non-recalled lots quarantined"
                         % env.metrics["wrong_quarantine_units"]))
    by_ward = defaultdict(int)
    for u in env.usage_log:
        if u["unmet"] and W.critical(u["drug"]):
            by_ward[(u["ward"], u["drug"])] += u["unmet"]
    for (ward, drug), units in sorted(by_ward.items(), key=lambda kv: -kv[1]):
        first = min(u["shift"] for u in env.usage_log if u["ward"] == ward and u["drug"] == drug and u["unmet"])
        findings.append(("critical_shortage", first, "%s could not issue %d x %s (first in shift %d)"
                         % (ward, units, drug, first + 1)))
    for drug, (start, end) in env.task.get("suspended", {}).items():
        alts = W.ALTERNATIVES.get(drug)
        if alts and not any(d == drug for (_, d, _) in env.substitutions):
            findings.append(("no_substitution_during_shortage", start,
                             "%s routine supply suspended shifts %d-%d; no ward was approved %s"
                             % (drug, start + 1, end + 1, "/".join(alts))))
    if env.metrics["urgent_spend"]:
        findings.append(("urgent_orders", None, "urgent orders EUR %.0f (surcharge EUR %.0f)"
                         % (env.metrics["urgent_spend"], env.metrics["urgent_premium"])))
    if summary.get("stopped_early"):
        findings.append(("stopped_early", stopped_at, "agent stopped before the rota ended"))
    return summary, findings


def main():
    for path in sys.argv[1:]:
        s, f = analyse(path)
        print("== %s  seed %s  model %s  score %.2f  penalty %.1f" % (
            s["task"], s["seed"], s.get("model"), s["score"], s["penalty"]["total"]))
        for kind, shift, text in f:
            print("  [%s] %s%s" % (kind, "" if shift is None else "shift %d: " % (shift + 1), text))


if __name__ == "__main__":
    main()
