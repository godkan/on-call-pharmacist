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


class TestTracingAndPatients(unittest.TestCase):
    def test_cabinets_hide_batches_in_t5(self):
        env = Env(TASKS["T5"](0))
        inv = env.call("list_inventory", {"location": "ICU", "product_code": "HEP-5K"})
        self.assertTrue(all(r["lot"] == "not recorded by cabinet" for r in inv["stock"] if r["status"] == "available"))
        lot = next(e["lot"] for e in env.stock if e["loc"] == "ICU" and e["drug"] == "HEP-5K")
        self.assertTrue(all(r["location"] == "CENTRAL" for r in env.call("find_lot", {"lot": lot})["locations"]))
        log = env.call("get_issue_log", {"product_code": "HEP-5K", "lot": lot})["entries"]
        self.assertIn("ICU", [e["to"] for e in log])
        found = env.call("inspect_cabinet", {"ward": "ICU", "product_code": "HEP-5K"})["found"]
        self.assertIn(lot, [f["lot"] for f in found])

    def test_empty_cabinet_visit_costs_time(self):
        env = Env(TASKS["T5"](0))
        before = env.minutes_left
        r = env.call("quarantine_lot", {"lot": "NOSUCHLOT", "location": "PED"})
        self.assertEqual(r["quarantined_units"], 0)
        self.assertEqual(env.minutes_left, before - 10)

    def _run_shortage(self, approve):
        env = Env(TASKS["T5"](0))
        allergic = [p for p in env.patients if "penicillin" in p["allergies"]]
        ward = allergic[0]["ward"]
        for e in env.stock:                      # empty the ward's ceftriaxone and cefotaxime
            if e["loc"] == ward and e["drug"] in ("CTX-1G", "CTAX-1G"):
                e["qty"] = 0
        approve(env, ward)
        env._consume()
        return env.metrics["contraindicated_given"]

    def test_ward_wide_restricted_approval_harms_allergic_patients(self):
        def wardwide(env, ward):
            env.call("approve_substitution", {"ward": ward, "product_code": "CTX-1G", "alternative_code": "PIP-45"})
        env = Env(TASKS["T5"](0))
        ward = next(p for p in env.patients if "penicillin" in p["allergies"])["ward"]
        allergic_now = [p for p in env.active_patients(ward=ward, drug="CTX-1G") if "penicillin" in p["allergies"]]
        if allergic_now:
            self.assertGreater(self._run_shortage(wardwide), 0)

    def test_per_patient_approval_avoids_allergic_patients(self):
        def per_patient(env, ward):
            for p in env.active_patients(ward=ward, drug="CTX-1G"):
                if "penicillin" not in p["allergies"]:
                    env.call("approve_substitution", {"ward": ward, "product_code": "CTX-1G",
                                                      "alternative_code": "PIP-45", "patient_id": p["id"]})
        self.assertEqual(self._run_shortage(per_patient), 0)


class TestFiveTasks(unittest.TestCase):
    def test_all_gates_pass(self):
        from pharmacy_env.anchors import anchor_table
        from pharmacy_env.eval import TASK_IDS, check_gates, SEEDS
        for t in TASK_IDS:
            fails, _ = check_gates(t, anchor_table(t, SEEDS))
            self.assertEqual(fails, [], t)

    def test_urgent_cap_and_budget(self):
        env = Env(TASKS["T2"](0))
        self.assertIn("error", env.call("place_urgent_order", {"product_code": "CTX-1G", "qty": 5}))
        self.assertIn("ok", env.call("place_urgent_order", {"product_code": "CTX-1G", "qty": 4}))
        self.assertIn("error", env.call("place_urgent_order", {"product_code": "CTX-1G", "qty": 1}))
        env = Env(TASKS["T3"](0))
        left = env.call("get_status")["urgent_order_budget_left_eur"]
        self.assertIn("error", env.call("place_urgent_order", {"product_code": "PIP-45", "qty": 200}))
        self.assertEqual(env.call("get_status")["urgent_order_budget_left_eur"], left)

    def test_revoke_substitution(self):
        env = Env(TASKS["T2"](0))
        a = {"ward": "MED", "product_code": "CTX-1G", "alternative_code": "PIP-45"}
        env.call("approve_substitution", a)
        self.assertIn(("MED", "CTX-1G", "PIP-45"), env.substitutions)
        self.assertIn("ok", env.call("revoke_substitution", a))
        self.assertNotIn(("MED", "CTX-1G", "PIP-45"), env.substitutions)


class TestColdChain(unittest.TestCase):
    def _after_event(self, i, seed=0):
        t = TASKS["T1"](seed)
        env = Env(t)
        ev = t["cold_events"][i]
        while env.shift <= ev["shift"]:
            env.call("end_shift")
        return t, env, ev

    def test_warm_excursion_fails_only_the_near_limit_batch(self):
        t, env, ev = self._after_event(0)
        damaged = [e for e in env.stock if e.get("damaged") and e["qty"]]
        self.assertEqual({e["drug"] for e in damaged}, {"SUX-100"})
        self.assertTrue(all(e["loc"] == ev["location"] for e in damaged))

    def test_freeze_spares_rocuronium_and_later_deliveries(self):
        t, env, ev = self._after_event(1)
        central = [e for e in env.stock if e["loc"] == "CENTRAL" and e["drug"] in ("INS-REG", "SUX-100", "ROC-50") and e["qty"]]
        self.assertTrue(any(e.get("damaged") for e in central if e["drug"] == "INS-REG"))
        self.assertFalse(any(e.get("damaged") for e in central if e["drug"] == "ROC-50"))
        for e in central:
            if e.get("damaged"):
                self.assertFalse(e["lot"] in env.received and env.received[e["lot"]] > ev["shift"])

    def test_withdrawing_a_failed_batch_is_not_wrong(self):
        t, env, ev = self._after_event(1)
        lot = next(e["lot"] for e in env.stock if e["loc"] == "CENTRAL" and e.get("damaged") and e["qty"])
        env.call("quarantine_lot", {"lot": lot, "location": "CENTRAL"})
        self.assertEqual(env.metrics["wrong_quarantine_units"], 0)

    def test_log_shows_the_excursion(self):
        t, env, ev = self._after_event(1)
        temps = [r["celsius"] for r in env.call("get_temperature_log", {"location": "CENTRAL"})["last_24_hours"]]
        self.assertLess(min(temps), 0)


class TestSuppliersAndWorld(unittest.TestCase):
    def test_tool_definitions_match_engine(self):
        from pharmacy_env.engine import TOOL_MINUTES
        from pharmacy_env.run_agent import TOOLS
        self.assertEqual({t["function"]["name"] for t in TOOLS}, set(TOOL_MINUTES))

    def test_wholesaler_order_arrives_in_two_shifts(self):
        env = Env(TASKS["T3"](0))
        r = env.call("place_wholesaler_order", {"product_code": "PIP-45", "qty": 20})
        self.assertIn("ok", r)
        env.call("end_shift")
        self.assertFalse(any(e["lot"].startswith("NH") for e in env.stock))
        env.call("end_shift")
        self.assertTrue(any(e["lot"].startswith("NH") and e["loc"] == "CENTRAL" for e in env.stock))

    def test_budget_covers_wholesaler_orders(self):
        env = Env(TASKS["T3"](0))
        left = env.call("get_status")["urgent_order_budget_left_eur"]
        env.call("place_wholesaler_order", {"product_code": "PIP-45", "qty": 20})
        self.assertAlmostEqual(env.call("get_status")["urgent_order_budget_left_eur"], left - 20 * 7.60 * 1.10, places=2)

    def test_loans_are_limited_and_refused_under_allocation(self):
        env = Env(TASKS["T4"](0))
        self.assertIn("error", env.call("borrow_from_hospital", {"product_code": "NOR-4MG", "qty": 5}))
        self.assertIn("ok", env.call("borrow_from_hospital", {"product_code": "PIP-45", "qty": 10}))
        self.assertIn("error", env.call("borrow_from_hospital", {"product_code": "PIP-45", "qty": 1}))

    def test_potassium_only_where_allowed(self):
        env = Env(TASKS["T1"](0))
        r = env.call("transfer_stock", {"product_code": "KCL-20", "from_location": "CENTRAL",
                                        "to_location": "MED", "qty": 2})
        self.assertIn("error", r)

    def test_night_cupboard_only_used_at_night(self):
        env = Env(TASKS["C1"](0))
        env.call("end_shift")          # day shift
        self.assertFalse(any(u["ward"] == "NIGHT" for u in env.usage_log))
        env.call("end_shift")          # night shift
        self.assertTrue(any(u["ward"] == "NIGHT" for u in env.usage_log))


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


class TestJudgeInterfaces(unittest.TestCase):
    """The interfaces judges may plug their own harness into: Python reset/step and MCP over stdio."""

    def test_reference_through_python_api_scores_one_and_replays(self):
        from pharmacy_env.gym_env import PharmacyEnv
        path = os.path.join(tempfile.mkdtemp(), "g.jsonl")
        gym = PharmacyEnv("T1", seed=1, trajectory_path=path)
        gym.reset()

        class Adapter:          # lets the reference policy act through step()
            def __getattr__(self, k):
                return getattr(gym.env, k)

            def call(self, name, args=None):
                obs, reward, done, _, info = gym.step({"name": name, "arguments": args or {}})
                return info["function_result"] if info.get("new_shift") else json.loads(obs)

        careful_pharmacist(Adapter())
        s = gym.close()
        self.assertAlmostEqual(s["score"], 1.0)
        got, want = replay(path)
        self.assertAlmostEqual(got, want)

    def test_mcp_server_round_trip(self):
        import io
        from pharmacy_env import mcp_server
        path = os.path.join(tempfile.mkdtemp(), "m.jsonl")
        reqs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                 "params": {"name": "place_urgent_order", "arguments": {"product_code": "EPI-1MG", "qty": "x"}}},
                {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "end_shift", "arguments": {}}}]
        out = io.StringIO()
        mcp_server.serve(mcp_server.Server("T2", 0, path), io.StringIO("\n".join(map(json.dumps, reqs)) + "\n"), out)
        replies = {r["id"]: r for r in map(json.loads, out.getvalue().splitlines())}
        self.assertEqual(sorted(replies), [1, 2, 3, 4])
        self.assertEqual(len(replies[2]["result"]["tools"]), len(run_agent.TOOLS))
        self.assertTrue(replies[3]["result"]["isError"])
        self.assertIn("shift 2 of", replies[4]["result"]["content"][0]["text"])
        got, want = replay(path)
        self.assertAlmostEqual(got, want)

    def test_malformed_arguments_never_crash(self):
        env = Env(TASKS["T5"](0))
        bad = [("place_urgent_order", {"product_code": "EPI-1MG", "qty": "lots"}),
               ("transfer_stock", {"product_code": "EPI-1MG", "from_location": "CENTRAL", "to_location": "ICU",
                                   "qty": None}),
               ("quarantine_lot", {"lot": None, "location": "ICU"}), ("get_issue_log", ["ICU"]),
               ("approve_substitution", {"ward": 3, "product_code": [], "alternative_code": {}}),
               ("list_inventory", {"location": "CENTRAL", "unexpected": 1}), ("no_such_function", {})]
        for name, args in bad:
            self.assertIn("error", env.call(name, args), name)


if __name__ == "__main__":
    unittest.main()
