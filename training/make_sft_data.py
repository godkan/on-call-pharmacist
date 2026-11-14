"""Turn reference-pharmacist runs into chat transcripts for supervised fine-tuning.

    python3 -m training.make_sft_data --seeds 5-16 --out training/data/sft.jsonl

Each line is one shift in handover mode, in the same format the agent harness
(pharmacy_env/run_agent.py, --memory handover) sends to a model: the system prompt,
the shift-start message with the previous handover note, then one assistant tool call
and one tool result at a time, ending with end_shift. Seeds 0-4 are the evaluation
seeds and are refused here.

The reference policy keeps its state in Python variables; a model in handover mode only
has the note. The note written at end_shift is therefore built from what this shift saw
and did (notices received, quarantines, orders, approvals) plus the previous note's list
of notices, so everything in it is visible in the transcript.
"""
import argparse
import json
import os

from pharmacy_env.engine import Env
from pharmacy_env.policies import careful_pharmacist
from pharmacy_env.run_agent import TOOLS, shift_start_message, system_prompt
from pharmacy_env.tasks import TASKS

EVAL_SEEDS = {0, 1, 2, 3, 4}
ACTION_TOOLS = {"quarantine_lot", "transfer_stock", "approve_substitution", "revoke_substitution",
                "return_to_supplier", "place_urgent_order", "place_wholesaler_order", "borrow_from_hospital"}


def _note(prev_notices, shift_calls):
    notices = dict(prev_notices)
    actions = []
    for name, args, result in shift_calls:
        if name == "read_notices":
            for n in result.get("notices", []):
                notices[n["id"]] = n["subject"]
        elif name in ACTION_TOOLS and isinstance(result, dict) and "error" not in result:
            actions.append("%s %s" % (name, json.dumps(args, sort_keys=True)))
    lines = ["Notices received so far (read_notices include_read=true shows full text):"]
    lines += ["- %s: %s" % (k, v) for k, v in notices.items()] or ["- none"]
    lines.append("Done this shift:")
    lines += ["- " + a for a in actions] or ["- no withdrawals, orders or approvals"]
    return "\n".join(lines)[:3900], notices


class Recorder:
    """Proxy around Env that logs every call per shift and writes the handover note."""

    def __init__(self, env):
        self._env, self.shifts, self._calls, self._notices = env, [], [], {}
        self._sys = {"role": "system", "content": system_prompt(env, "handover")}
        self._start = shift_start_message(env, "handover")
        self._n = 0

    def __getattr__(self, k):
        return getattr(self._env, k)

    def call(self, name, args=None):
        args = dict(args or {})
        if name == "end_shift":
            note, self._notices = _note(self._notices, self._calls)
            args = {"handover_note": note}
        result = self._env.call(name, args)
        self._calls.append((name, args, result))
        if name == "end_shift" and "error" not in result:
            self._flush()
        return result

    def _flush(self):
        msgs = [self._sys, {"role": "user", "content": self._start}]
        for name, args, result in self._calls:
            self._n += 1
            cid = "call_%d" % self._n
            msgs.append({"role": "assistant", "content": "", "tool_calls": [
                {"id": cid, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]})
            msgs.append({"role": "tool", "tool_call_id": cid, "name": name, "content": json.dumps(result)})
        self.shifts.append(msgs)
        self._calls = []
        if not self._env.done:
            self._start = shift_start_message(self._env, "handover")


def episodes(task, seed):
    if seed in EVAL_SEEDS:
        raise ValueError("seed %d is an evaluation seed" % seed)
    rec = Recorder(Env(TASKS[task](seed)))
    careful_pharmacist(rec)
    return rec.shifts


def parse_seeds(text):
    a, _, b = text.partition("-")
    return list(range(int(a), int(b or a) + 1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", nargs="+", default=["T1", "T2", "T3", "T4", "T5"])
    ap.add_argument("--seeds", default="5-16")
    ap.add_argument("--out", default="training/data/sft.jsonl")
    a = ap.parse_args()
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    n = chars = 0
    with open(a.out, "w") as f:
        for task in a.tasks:
            for seed in parse_seeds(a.seeds):
                for msgs in episodes(task, seed):
                    f.write(json.dumps({"task": task, "seed": seed, "messages": msgs, "tools": TOOLS}) + "\n")
                    n += 1
                    chars += sum(len(m["content"] or "") for m in msgs)
    print("%d shift transcripts, %.1f M characters -> %s" % (n, chars / 1e6, a.out))


if __name__ == "__main__":
    main()
