"""Run an LLM agent on a task through any OpenAI-compatible Chat Completions API
(OpenAI, Gemini's OpenAI-compatible endpoint, OpenRouter, ...).

    export LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai
    export LLM_API_KEY=...            # never commit keys
    export LLM_MODEL=gemini-3.5-flash
    python3 -m pharmacy_env.run_agent --task T1 --seed 0 --out results/traj

Every step (assistant message, tool call, tool result, minutes left) is written to
a JSONL trajectory so results can be audited and replayed.
"""
import argparse
import json
import os
import time
import urllib.request

from . import world as W
from .anchors import run_anchor
from .engine import SHIFT_MINUTES, Env
from .scoring import normalised, penalty
from .tasks import TASKS

LOC = {"type": "string", "enum": W.LOCATIONS}
WARD = {"type": "string", "enum": W.WARDS}
CODE = {"type": "string", "description": "Product code, e.g. HEP-5K"}


def _fn(name, desc, props=None, required=None):
    return {"type": "function", "function": {
        "name": name, "description": desc,
        "parameters": {"type": "object", "properties": props or {}, "required": required or []}}}


TOOLS = [
    _fn("get_status", "Current shift, desk time left this shift and number of unread notices. Takes no time."),
    _fn("read_notices", "Read new messages in the pharmacy inbox (5 min).",
        {"include_read": {"type": "boolean", "description": "Also show messages already read."}}),
    _fn("read_policy", "Read a pharmacy standard operating procedure (5 min).",
        {"topic": {"type": "string", "enum": ["recall", "shortage", "substitution", "ward_requests",
                                              "urgent_order", "cold_chain"]}}, ["topic"]),
    _fn("get_drug_info", "Formulary entry: criticality, approved alternatives, routine supply status, par levels (5 min).",
        {"product_code": CODE}, ["product_code"]),
    _fn("list_inventory", "Stock by lot at one location, optionally one product (5 min).",
        {"location": LOC, "product_code": CODE}, ["location"]),
    _fn("find_lot", "Every location currently holding a given lot/batch number (5 min).",
        {"lot": {"type": "string"}}, ["lot"]),
    _fn("get_usage_report", "Units issued and units a ward cabinet could not issue, last 4 shifts (5 min).",
        {"location": WARD, "product_code": CODE}, ["location"]),
    _fn("get_issue_log", "Central store issue log: which batches were sent to which cabinet and when (5 min).",
        {"product_code": CODE, "lot": {"type": "string", "description": "Optional batch number filter."}},
        ["product_code"]),
    _fn("inspect_cabinet", "Pharmacist checks a ward cabinet on site and reports batches held (15 min).",
        {"ward": WARD, "product_code": CODE}, ["ward", "product_code"]),
    _fn("list_patients", "Current patients on a ward, with the product they receive and allergies (5 min).",
        {"ward": WARD, "product_code": CODE}, ["ward"]),
    _fn("quarantine_lot", "Withdraw all available units of a lot at one location from use (10 min).",
        {"lot": {"type": "string"}, "location": LOC}, ["lot", "location"]),
    _fn("transfer_stock", "Move units of a product between locations, earliest expiry first (10 min).",
        {"product_code": CODE, "from_location": LOC, "to_location": LOC, "qty": {"type": "integer"}},
        ["product_code", "from_location", "to_location", "qty"]),
    _fn("approve_substitution", "Approve a formulary alternative when the product is out, for a whole ward or "
        "one patient (10 min).",
        {"ward": WARD, "product_code": CODE, "alternative_code": CODE,
         "patient_id": {"type": "string", "description": "Optional: approve for this patient only."}},
        ["ward", "product_code", "alternative_code"]),
    _fn("get_temperature_log", "Hourly readings of a location's medication refrigerator, last 24 hours (5 min).",
        {"location": LOC}, ["location"]),
    _fn("get_lot_record", "Batch record: product, expiry, when it reached the central store, and cold-chain "
        "history for refrigerated products (5 min).", {"lot": {"type": "string"}}, ["lot"]),
    _fn("list_approvals", "Active substitution approvals, ward-level and per patient (5 min).",
        {"ward": WARD}),
    _fn("revoke_substitution", "Withdraw a substitution approval for a ward or one patient (5 min).",
        {"ward": WARD, "product_code": CODE, "alternative_code": CODE,
         "patient_id": {"type": "string", "description": "Set to revoke a per-patient approval."}},
        ["ward", "product_code", "alternative_code"]),
    _fn("place_wholesaler_order", "Off-contract order from Nordic Hospital Supply: list price +10%, delivered in "
        "two shifts, minimum order EUR 100; not available for products out of stock nationally (15 min).",
        {"product_code": CODE, "qty": {"type": "integer"}}, ["product_code", "qty"]),
    _fn("borrow_from_hospital", "Ask Lahti Central Hospital pharmacy for a loan: free, arrives next shift, at most "
        "10 units of a product per rota, refused for products on national allocation (15 min).",
        {"product_code": CODE, "qty": {"type": "integer"}}, ["product_code", "qty"]),
    _fn("return_to_supplier", "Send quarantined stock in the central store back to the wholesaler (10 min).",
        {"lot": {"type": "string"}}, ["lot"]),
    _fn("place_urgent_order", "Urgent order from RapidRx Express to the central store; arrives next shift, +40% cost (15 min).",
        {"product_code": CODE, "qty": {"type": "integer"}}, ["product_code", "qty"]),
    _fn("end_shift", "Hand over and move to your next shift. Ward cabinets are restocked from central at handover.",
        {"handover_note": {"type": "string",
                           "description": "Note for the pharmacist on the next shift: open issues, follow-ups."}}),
]

SYSTEM = """You are the on-duty pharmacist for medicines supply and safety at {hospital} hospital pharmacy.
You cover the rota from {start} for {n} consecutive 12-hour shifts (day 07:00-19:00, night 19:00-07:00).

Your responsibilities: act on anything that arrives in the pharmacy inbox, keep ward cabinets supplied with safe
medicines, and follow the hospital's pharmacy SOPs. Routine replenishment is automatic: ward cabinets are restocked
from the central store at each handover and the wholesaler delivers to the central store every second day.

You work through the pharmacy system functions. Each function uses desk time; you have {minutes} minutes of desk
time per shift. When you have finished what you need to do in a shift, call end_shift to hand over; the next shift
then starts. Keep working shift by shift until the rota is complete.

Locations: {locs}.
Product codes: {codes}."""

HANDOVER = """

Shift handover: each shift starts fresh. You will not see the details of earlier shifts, only the handover note the
previous shift wrote with end_shift. Put anything the next shift needs to follow up in that note."""


def chat(messages, model, base, key, temperature):
    payload = {"model": model, "messages": messages, "tools": TOOLS,
               "tool_choice": "auto", "temperature": temperature}
    if os.environ.get("LLM_REASONING_EFFORT"):
        payload["reasoning_effort"] = os.environ["LLM_REASONING_EFFORT"]
    body = json.dumps(payload).encode()
    req = urllib.request.Request(base.rstrip("/") + "/chat/completions", data=body, method="POST",
                                 headers={"Content-Type": "application/json", "Authorization": "Bearer " + key})
    for attempt in range(6):
        try:
            with urllib.request.urlopen(req, timeout=240) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < 5:
                time.sleep(10 * (attempt + 1))
                continue
            raise RuntimeError("API error %s: %s" % (e.code, e.read()[:500]))
        except (OSError, ValueError) as e:   # timeouts, dropped connections, truncated bodies
            if attempt < 5:
                print("  request failed (%s), retrying" % e, flush=True)
                time.sleep(10 * (attempt + 1))
                continue
            raise


def shift_start_message(env, memory):
    if memory == "handover" and env.shift > 0:
        return ("Your shift starts now: %s (shift %d of %d).\n\nHandover note from the previous shift:\n%s"
                % (env.shift_label(), env.shift + 1, env.n_shifts, env.handover_note or "(no note left)"))
    return "Your rota starts now: %s." % env.shift_label(0)


def run(task_id, seed, model, base, key, out_path, temperature=0.0, max_steps=2000, max_nudges=2, memory="full",
        hint=None):
    env = Env(TASKS[task_id](seed))
    sysmsg = {"role": "system", "content": system_prompt(env, memory, hint)}
    messages = [sysmsg, {"role": "user", "content": shift_start_message(env, memory)}]
    log = open(out_path, "w", buffering=1)  # line-buffered: trajectory survives a crash
    usage = {"prompt_tokens": 0, "completion_tokens": 0}
    steps = nudges = 0
    while not env.done and steps < max_steps:
        try:
            resp = chat(messages, model, base, key, temperature)
        except RuntimeError as e:
            if "maximum context length" not in str(e):
                raise
            # The conversation outgrew the model's context: treat as stopping early.
            log.write(json.dumps({"type": "error", "shift": env.shift, "error": "context length exceeded"}) + "\n")
            break
        for k in usage:
            usage[k] += (resp.get("usage") or {}).get(k, 0)
        msg = resp["choices"][0]["message"]
        messages.append({k: v for k, v in msg.items() if k in ("role", "content", "tool_calls") and v is not None})
        calls = msg.get("tool_calls") or []
        log.write(json.dumps({"type": "assistant", "shift": env.shift, "content": msg.get("content"),
                              "tool_calls": [{"name": c["function"]["name"], "arguments": c["function"]["arguments"]}
                                             for c in calls]}) + "\n")
        if not calls:
            if nudges >= max_nudges:
                break
            nudges += 1
            messages.append({"role": "user", "content": "(Handover system) The rota is still in progress: %s." %
                             env.shift_label()})
            continue
        for c in calls:
            steps += 1
            name = c["function"]["name"]
            try:
                args = json.loads(c["function"]["arguments"] or "{}")
            except ValueError:
                args, result = None, {"error": "Arguments were not valid JSON."}
            if args is not None:
                result = env.call(name, args)
            log.write(json.dumps({"type": "tool", "shift": env.shift, "name": name, "args": args,
                                  "result": result, "minutes_left": env.minutes_left}) + "\n")
            messages.append({"role": "tool", "tool_call_id": c["id"], "content": json.dumps(result)})
            if env.done:
                break
            if memory == "handover" and name == "end_shift" and "error" not in result:
                # New shift: start a fresh conversation carrying only the handover note.
                messages = [sysmsg, {"role": "user", "content": shift_start_message(env, memory)}]
                log.write(json.dumps({"type": "handover", "shift": env.shift, "note": env.handover_note}) + "\n")
                break
        print("  shift %d/%d, %d tool calls, %d prompt tokens so far" % (
            min(env.shift + 1, env.n_shifts), env.n_shifts, steps, usage["prompt_tokens"]), flush=True)
    return finish(env, task_id, seed, log, steps, usage,
                  {"model": model, "temperature": temperature, "memory": memory, "base_url": base,
                   "max_steps": max_steps,
                   "reasoning_effort": os.environ.get("LLM_REASONING_EFFORT"), "hint": hint})


def system_prompt(env, memory="full", hint=None):
    text = (SYSTEM + (HANDOVER if memory == "handover" else "")).format(
        hospital=W.HOSPITAL, start=env.shift_label(0), n=env.n_shifts, minutes=SHIFT_MINUTES,
        locs=", ".join("%s (%s)" % (k, v) for k, v in W.LOCATION_NAMES.items()),
        codes=", ".join("%s = %s" % (k, W.drug_name(k)) for k in env.products))
    return text + ("\n\n" + hint if hint else "")


# Ablation only (not used in the main runs): two sentences naming the judgment the models miss.
HINT = ("Practice note: when a recall arrives, the central store issue log already shows which cabinets "
        "received each affected batch, so quarantine it at those cabinets in the same shift and inspect on site "
        "only where the log cannot tell you. After a refrigerator excursion, compare each batch's received time "
        "with the excursion, and remember that stock issued from that refrigerator since the excursion may "
        "already be in ward cabinets.")


def finish(env, task_id, seed, log, steps, usage, config):
    """Run any remaining shifts unattended, score, and write the summary line."""
    stopped_early = not env.done
    env.run_to_end()
    pen = penalty(env.metrics)
    ref = penalty(run_anchor(task_id, seed, "careful_pharmacist").metrics)["total"]
    nothing = penalty(run_anchor(task_id, seed, "do_nothing").metrics)["total"]
    summary = dict(type="summary", task=task_id, seed=seed, stopped_early=stopped_early, tool_calls=steps,
                   usage=usage, penalty=pen, score=normalised(pen["total"], nothing, ref),
                   metrics={k: (v if k != "shortfall" else {"%s/%s" % kk: vv for kk, vv in v.items()})
                            for k, v in env.metrics.items()}, **config)
    log.write(json.dumps(summary) + "\n")
    log.close()
    return summary


def load_dotenv(paths=(".env", "api.env")):
    """Read KEY=VALUE lines from .env or api.env (both git-ignored) without overriding the shell."""
    for path in paths:
        if not os.path.exists(path):
            continue
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    v = v.strip().strip('"').strip("'")
                    if v and not os.environ.get(k.strip()):
                        os.environ[k.strip()] = v


def list_models(base, key):
    req = urllib.request.Request(base.rstrip("/") + "/models", headers={"Authorization": "Bearer " + key})
    with urllib.request.urlopen(req, timeout=60) as r:
        return sorted(m["id"] for m in json.loads(r.read()).get("data", []))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", default="T1")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default="results/traj")
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--max-steps", type=int, default=2000,
                    help="safety cap on tool calls per run (desk time already limits each shift)")
    ap.add_argument("--memory", choices=["full", "handover"], default="full",
                    help="full: whole conversation; handover: each shift sees only the previous handover note")
    ap.add_argument("--list-models", action="store_true", help="print model ids the API offers and exit")
    ap.add_argument("--hint", action="store_true", help="ablation: append the practice note HINT to the system prompt")
    a = ap.parse_args()
    load_dotenv()
    base, key = os.environ["LLM_BASE_URL"], os.environ["LLM_API_KEY"]
    if a.list_models:
        print("\n".join(list_models(base, key)))
        return
    model = os.environ["LLM_MODEL"]
    os.makedirs(a.out, exist_ok=True)
    path = os.path.join(a.out, "%s_seed%d_%s_%s%s_%d_%d.jsonl" % (
        a.task, a.seed, model.replace("/", "_"), a.memory, "_hint" if a.hint else "", int(time.time()), os.getpid()))
    s = run(a.task, a.seed, model, base, key, path, a.temperature, max_steps=a.max_steps, memory=a.memory,
            hint=HINT if a.hint else None)
    print(json.dumps({k: s[k] for k in ("task", "seed", "model", "score", "penalty", "tool_calls",
                                        "stopped_early", "usage")}, indent=1))
    print("trajectory:", path)


if __name__ == "__main__":
    main()
