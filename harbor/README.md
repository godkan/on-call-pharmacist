# On-Call Pharmacist as Harbor tasks

`tasks/` holds one [Harbor](https://harborframework.com) task per evaluation task, seed 0:

| Task | Shifts | Agent timeout |
|---|---|---|
| `t1-seed0` safety incidents | 10 | 30 min |
| `t2-seed0` antibiotic shortage and allergies | 14 | 42 min |
| `t3-seed0` epidemic and budget | 20 | 60 min |
| `t4-seed0` ward requests under allocation | 14 | 42 min |
| `t5-seed0` two-week rota | 28 | 84 min |

## Layout of each task

```
instruction.md                 the job description the agent receives (our system prompt)
task.toml                      timeouts, resources, and the MCP server [[environment.mcp_servers]]
environment/Dockerfile         the agent's container (python:3.12-slim + curl); no simulator code
environment/docker-compose.yaml   adds the sidecar "mcp-server" and waits for it to be healthy
environment/mcp-server/        the hospital system: pharmacy_env as an MCP server (streamable HTTP, port 8000)
tests/test.sh, verify.py       verifier: fetch the agent's actions from the sidecar, replay, score
solution/solve.sh, oracle.py   oracle: the reference pharmacist's calls, made through MCP
```

The agent reaches the 22 hospital functions as the tools of the MCP server `pharmacy`
(`http://mcp-server:8000/mcp`). The simulator and its state live only in the sidecar, and the
scoring code reaches the agent's container only after the agent has finished, so the agent can
neither read the world nor see its score.

## Reward

`/logs/verifier/reward.json`:

| Key | Meaning |
|---|---|
| `reward` | normalised score clipped to [0, 1] |
| `score` | normalised score: do nothing = 0, reference pharmacist = 1 (can be negative, or above 1) |
| `pass_threshold`, `passed` | the seed's pass threshold, and whether the run reached it |
| `penalty`, `reference_penalty` | penalty points of the run and of the reference |
| `recalled_units_given`, `damaged_units_given`, `contraindicated_doses` | patient-safety counts |
| `stopped_early` | 1 if the agent ended before the rota did (remaining shifts run unattended) |

`/logs/verifier/trajectory.jsonl` is the run in the repository's trajectory format:
`python3 -m pharmacy_env.judge --task T1 --seed 0 --trajectory <it>` replays and scores it again.

## Runs a judge needs

```bash
harbor run -p harbor/tasks/t1-seed0 -a oracle                       # reference: score 1.00
# do-nothing (0.00) and stop-early baselines: set the oracle's policy in task.toml,
#   [solution] env = { PHARMACY_POLICY = "do_nothing" }   (or "stop_early")
harbor run -p harbor/tasks/t1-seed0 -a opencode -m <provider/model>  # an agent run
```

Checked with Harbor 0.26.0 and local Docker (`harbor run -p harbor/tasks -a oracle`): the oracle
scores 1.000 on all five tasks with no errors, the same as `python3 -m pharmacy_env.judge`. With
`PHARMACY_POLICY` set, T1 gives do-nothing 0.000 and stop-early -0.037. Harbor's `nop` agent scores
-0.046 on T1: it does not even attend the shifts, which the do-nothing baseline does.

## Other seeds

```bash
python3 harbor/make_tasks.py --tasks T1 T2 T3 T4 T5 --seeds 0 1 2 3 4
```

Regenerate after any change to `pharmacy_env/`, since each task carries a copy of it.
