"""Determinism, replay and anchor-ordering checks.  python3 -m unittest discover tests"""
import json
import os
import tempfile
import unittest

from pharmacy_env import run_agent
from pharmacy_env.anchors import run_anchor
from pharmacy_env.engine import Env
from pharmacy_env.policies import careful_pharmacist
from pharmacy_env.replay import replay
from pharmacy_env.scoring import penalty
from pharmacy_env.tasks import TASKS

SEEDS = [0, 1, 2, 3, 4]


class RecordingEnv(Env):
    """Records every call so a scripted run can be fed through the agent harness."""
    def __init__(self, task):
        super().__init__(task)
        self.calls = []

    def call(self, name, args=None):
        self.calls.append((name, args or {}))
        return super().call(name, args)


class TestEnv(unittest.TestCase):
    def test_deterministic(self):
        for s in SEEDS:
            a = penalty(run_anchor("T1", s, "careful_pharmacist").metrics)
            b = penalty(run_anchor("T1", s, "careful_pharmacist").metrics)
            self.assertEqual(a, b)

    def test_anchor_ordering(self):
        for t, s in [(t, s) for t in ("T1", "T5") for s in SEEDS]:
            p = {n: penalty(run_anchor(t, s, n).metrics)["total"]
                 for n in ["do_nothing", "central_only", "blanket_quarantine", "careful_pharmacist"]}
            self.assertLess(p["careful_pharmacist"], p["central_only"], s)
            self.assertLess(p["careful_pharmacist"], p["blanket_quarantine"], s)
            self.assertLessEqual(p["central_only"], p["do_nothing"], s)

    def test_same_results_across_processes(self):
        """Anchor scores must not depend on Python's per-process hash seed."""
        import subprocess, sys
        code = ("from pharmacy_env.anchors import anchor_table;"
                "print([round(sc, 9) for t in ('T1', 'T5') for n, v in sorted(anchor_table(t, [0, 1]).items())"
                " for _, sc in v])")
        outs = {subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True,
                               env=dict(os.environ, PYTHONHASHSEED=str(h))).stdout for h in (1, 2, 3)}
        self.assertEqual(len(outs), 1)

    def test_quitting_is_penalised(self):
        env = Env(TASKS["T1"](0))
        env.call("read_notices")
        env.call("end_shift")
        env.run_to_end()
        self.assertGreater(env.metrics["missed_shifts"], 0)

    def test_harness_and_replay(self):
        self._harness("T1", 1, "full")

    def test_harness_handover_long_task(self):
        self._harness("T5", 0, "handover")

    def _harness(self, task, seed, memory):
        """Drive the agent harness with the reference policy's calls and check replay."""
        rec = RecordingEnv(TASKS[task](seed))
        careful_pharmacist(rec)
        script = list(rec.calls)

        def fake_chat(messages, *a, **k):
            if not script:
                return {"choices": [{"message": {"role": "assistant", "content": "done"}}]}
            name, args = script.pop(0)
            return {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
                {"id": "c%d" % len(script), "type": "function",
                 "function": {"name": name, "arguments": json.dumps(args)}}]}}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1}}

        orig = run_agent.chat
        run_agent.chat = fake_chat
        try:
            path = os.path.join(tempfile.mkdtemp(), "t.jsonl")
            s = run_agent.run(task, seed, "scripted", "", "", path, memory=memory, max_steps=5000)
        finally:
            run_agent.chat = orig
        self.assertAlmostEqual(s["score"], 1.0)
        got, want = replay(path)
        self.assertAlmostEqual(got, want)


class TestClaudeHarness(unittest.TestCase):
    def test_claude_loop_with_scripted_client(self):
        """Feed the reference policy's calls through the Claude loop via a fake client."""
        from types import SimpleNamespace as NS
        try:
            from pharmacy_env import run_claude
        except ImportError:
            self.skipTest("anthropic package not installed")
        rec = RecordingEnv(TASKS["T1"](2))
        careful_pharmacist(rec)
        script = list(rec.calls)

        class FakeMessages:
            def create(self, **kw):
                u = NS(input_tokens=10, cache_creation_input_tokens=0, cache_read_input_tokens=0, output_tokens=5)
                if not script:
                    return NS(content=[NS(type="text", text="done")], stop_reason="end_turn", usage=u)
                name, args = script.pop(0)
                return NS(content=[NS(type="tool_use", id="t%d" % len(script), name=name, input=args)],
                          stop_reason="tool_use", usage=u)

        orig = run_claude.anthropic.Anthropic
        run_claude.anthropic.Anthropic = lambda **kw: NS(messages=FakeMessages())
        os.environ.setdefault("ANTHROPIC_API_KEY", "test")
        try:
            path = os.path.join(tempfile.mkdtemp(), "c.jsonl")
            s = run_claude.run("T1", 2, "claude-opus-5-5", "medium", path)
        finally:
            run_claude.anthropic.Anthropic = orig
        self.assertAlmostEqual(s["score"], 1.0)
        got, want = replay(path)
        self.assertAlmostEqual(got, want)


if __name__ == "__main__":
    unittest.main()
