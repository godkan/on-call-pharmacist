# For judges: rerunning the evaluation

Python 3.9+, standard library only. Clone, `cd` into the repository, and run the commands from there.
Tasks are `T1`-`T5`; evaluation seeds are `0`-`4`.

## 0. Harbor (the expected format)

`harbor/tasks/` has T1-T5 (seed 0) as Harbor tasks for the OpenCode harness: the hospital system is
an MCP sidecar, the verifier writes `/logs/verifier/reward.json`, and the oracle is the reference
pharmacist. Details, reward keys and the baseline switch: [harbor/README.md](harbor/README.md).

```bash
harbor run -p harbor/tasks/t1-seed0 -a oracle                        # reference, score 1.00
harbor run -p harbor/tasks/t1-seed0 -a opencode -m <provider/model>   # agent run
```

The commands below do the same without Docker.

## 1. Reference, do-nothing and stop-early runs

```bash
python3 -m pharmacy_env.judge --task T1 --seed 0
```

Runs the three scripted runs for that task and seed and prints each one's penalty and score, plus
the pass threshold. Expected: reference 1.00, do-nothing 0.00 (both by definition of the score),
stop-early below the threshold. All three are deterministic: the same command always prints the
same numbers. Example (T1 seed 0): reference 119.4 points, do-nothing 1211.5, stop-early 1251.5
(score -0.04), threshold 1.00.

## 2. Agent runs

Pick whichever matches your harness. Every option writes a trajectory in the same format, which
step 3 replays and scores.

**a. Our harness, any OpenAI-compatible endpoint** (how every reported run was made):

```bash
export LLM_BASE_URL=https://...  LLM_API_KEY=...  LLM_MODEL=...   # optional: LLM_REASONING_EFFORT
python3 -m pharmacy_env.run_agent --task T1 --seed 0 --memory handover
```

`--memory handover` (each shift sees only the previous shift's note) is the setting of all reported
runs; `--memory full` keeps the whole conversation. The trajectory path is printed at the end.
Claude: `python3 -m pharmacy_env.run_claude --task T1 --seed 0` (needs `pip install anthropic`).

**b. Your own harness, Python reset/step** (`pharmacy_env/gym_env.py`):

```python
from pharmacy_env.gym_env import PharmacyEnv
env = PharmacyEnv("T1", seed=0, trajectory_path="my_run.jsonl")
observation, info = env.reset()       # info["system_prompt"], info["tools"] (OpenAI function schemas)
observation, reward, terminated, truncated, info = env.step({"name": "read_notices", "arguments": {}})
summary = env.close()                 # if stopped early: remaining shifts run unattended and are scored
```

The reward is 0 on each step and the normalised score on the step that ends the rota.

**c. Your own harness, MCP over stdio** (`pharmacy_env/mcp_server.py`):

```bash
python3 -m pharmacy_env.mcp_server --task T1 --seed 0 --out mcp_T1_seed0.jsonl
```

Client configuration: `{"command": "python3", "args": ["-m", "pharmacy_env.mcp_server", "--task", "T1",
"--seed", "0", "--out", "mcp_T1_seed0.jsonl"], "cwd": "<repository>"}`. The system prompt is sent as
the server's `instructions`. The run is scored when the rota ends or the client disconnects.

## 3. Score agent trajectories

```bash
python3 -m pharmacy_env.judge --task T1 --seed 0 --trajectory my_run.jsonl mcp_T1_seed0.jsonl
```

Each trajectory is replayed action by action against a fresh copy of the world; the printed
`replay MATCH` confirms the recorded penalty is reproduced. Scores use the same reference and
do-nothing runs as step 1.

What we observed (README, Results): DeepSeek V4.1 Flash below the reference in 35/35 runs with
reasoning off and 24/25 with reasoning high; Kimi K3.1 Pro below the threshold in every T1 and T2
run but able to pass T3 and T4. Runs vary between repetitions even at temperature 0.

## 4. Everything at once

```bash
python3 -m pharmacy_env.eval                 # all anchors and gates, all 5 seeds, replay of all 121 runs
python3 -m unittest discover tests           # tests
python3 -m pharmacy_env.sensitivity          # penalty weights x0.25 and x4
```

## 5. Looking for reward exploits

The probes we already check on every seed are listed in the README (Reward integrity): stop early,
do nothing, withdraw everything, discard all refrigerated stock, approve a restricted drug
ward-wide, grant every request, hoard every critical medicine. To try your own, script it against
the Python interface and score it:

```python
from pharmacy_env.gym_env import PharmacyEnv
env = PharmacyEnv("T1", seed=0, trajectory_path="exploit.jsonl"); env.reset()
done = False
while not done:
    env.step({"name": "quarantine_lot", "arguments": {"lot": "...", "location": "CENTRAL"}})  # your idea
    _, reward, done, _, info = env.step({"name": "end_shift", "arguments": {}})
print(reward, info["penalty"])        # score, and where the penalty came from
```

Facts that may save time: the world advances only on `end_shift`, so timing and latency cannot be
gamed; malformed or unknown arguments return an error and cost no time; the score is never shown
to the agent; the reward is computed only from what happens to patients, wards and stock.
