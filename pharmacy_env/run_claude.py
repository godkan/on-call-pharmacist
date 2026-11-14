"""Run a Claude model on a task with the Anthropic Python SDK (manual agentic loop,
so every step is logged and the rota can be stopped and scored exactly as for
other models).

    # api.env (git-ignored):  ANTHROPIC_API_KEY=...   CLAUDE_MODEL=claude-opus-5-5   CLAUDE_EFFORT=medium
    python3 -m pharmacy_env.run_claude --task T1 --seed 0

No server-side refusal fallback is enabled on purpose: a fallback would switch
models mid-run and mix two models in one measurement. A refusal ends the run and
is recorded in the trajectory.
"""
import argparse
import json
import os
import time

import anthropic

from .engine import Env
from .run_agent import TOOLS, finish, load_dotenv, system_prompt
from .tasks import TASKS

# USD per million tokens: input, cache write (5 min), cache read, output
PRICES = {
    "claude-opus-5-5": (4.00, 5.00, 0.20, 20.00),
    "claude-sonnet-5-5": (2.00, 2.50, 0.10, 10.00),
    "claude-haiku-5-5": (0.10, 0.125, 0.01, 0.50),
}

CLAUDE_TOOLS = [{"name": t["function"]["name"], "description": t["function"]["description"],
                 "input_schema": t["function"]["parameters"]} for t in TOOLS]


def cost(model, u):
    p = PRICES.get(model)
    if not p:
        return None
    return (u["input_tokens"] * p[0] + u["cache_creation_input_tokens"] * p[1]
            + u["cache_read_input_tokens"] * p[2] + u["output_tokens"] * p[3]) / 1e6


def run(task_id, seed, model, effort, out_path, max_steps=2000, max_nudges=2):
    # Pin the public endpoint: never inherit a base URL from the environment.
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"],
                                 base_url="https://api.anthropic.com", max_retries=6, timeout=600)
    env = Env(TASKS[task_id](seed))
    system = system_prompt(env)
    messages = [{"role": "user", "content": "Your rota starts now: %s." % env.shift_label(0)}]
    log = open(out_path, "w", buffering=1)
    usage = dict(input_tokens=0, cache_creation_input_tokens=0, cache_read_input_tokens=0, output_tokens=0)
    steps = nudges = 0
    stop = None
    while not env.done and steps < max_steps:
        resp = client.messages.create(
            model=model, max_tokens=16000, system=system, tools=CLAUDE_TOOLS, messages=messages,
            output_config={"effort": effort}, cache_control={"type": "ephemeral"})
        for k in usage:
            usage[k] += getattr(resp.usage, k, 0) or 0
        stop = resp.stop_reason
        uses = [b for b in resp.content if b.type == "tool_use"]
        text = "\n".join(b.text for b in resp.content if b.type == "text")
        log.write(json.dumps({"type": "assistant", "shift": env.shift, "content": text, "stop_reason": stop,
                              "tool_calls": [{"name": b.name, "arguments": b.input} for b in uses]}) + "\n")
        messages.append({"role": "assistant", "content": resp.content})
        if stop == "refusal":
            break
        if not uses:
            if nudges >= max_nudges:
                break
            nudges += 1
            messages.append({"role": "user", "content": "(Handover system) The rota is still in progress: %s." %
                             env.shift_label()})
            continue
        results = []
        for b in uses:
            steps += 1
            args = b.input if isinstance(b.input, dict) else {}
            result = env.call(b.name, args)
            log.write(json.dumps({"type": "tool", "shift": env.shift, "name": b.name, "args": args,
                                  "result": result, "minutes_left": env.minutes_left}) + "\n")
            results.append({"type": "tool_result", "tool_use_id": b.id, "content": json.dumps(result),
                            "is_error": "error" in result})
        messages.append({"role": "user", "content": results})
        c = cost(model, usage)
        print("  shift %d/%d, %d tool calls, cost so far %s" % (
            min(env.shift + 1, env.n_shifts), env.n_shifts, steps, "$%.2f" % c if c is not None else "n/a"),
            flush=True)
    usage["cost_usd"] = cost(model, usage)
    return finish(env, task_id, seed, log, steps, usage,
                  {"model": model, "effort": effort, "final_stop_reason": stop})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", default="T1")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default="results/traj")
    a = ap.parse_args()
    load_dotenv()
    model = os.environ.get("CLAUDE_MODEL", "claude-opus-5-5")
    effort = os.environ.get("CLAUDE_EFFORT", "medium")
    os.makedirs(a.out, exist_ok=True)
    path = os.path.join(a.out, "%s_seed%d_%s_%s_%d.jsonl" % (a.task, a.seed, model, effort, int(time.time())))
    s = run(a.task, a.seed, model, effort, path)
    print(json.dumps({k: s[k] for k in ("task", "seed", "model", "effort", "score", "penalty", "tool_calls",
                                        "stopped_early", "final_stop_reason", "usage")}, indent=1))
    print("trajectory:", path)


if __name__ == "__main__":
    main()
