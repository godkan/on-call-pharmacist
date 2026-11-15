"""Generate Harbor tasks (harborframework.com) for On-Call Pharmacist.

    python3 harbor/make_tasks.py                      # T1-T5, seed 0, into harbor/tasks/
    python3 harbor/make_tasks.py --tasks T1 T5 --seeds 0 1 2

Each task runs the hospital system as an MCP sidecar (streamable HTTP) next to the agent's container.
The agent sees only the instruction and the 22 MCP tools: the simulator code and its state live in
the sidecar. After the agent finishes, tests/test.sh fetches the actions it took from the sidecar,
replays them on a fresh copy of the world and writes the score; the scoring code is uploaded only
then. solution/solve.sh (Harbor's oracle) makes the reference pharmacist's calls; set
PHARMACY_POLICY=do_nothing or stop_early to run the two baselines instead.
"""
import argparse
import json
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from pharmacy_env.engine import Env  # noqa: E402
from pharmacy_env.run_agent import shift_start_message, system_prompt  # noqa: E402
from pharmacy_env.tasks import TASKS  # noqa: E402

PORT = 8000
SECONDS_PER_SHIFT = 180       # agent time budget per shift of the rota
TITLES = {"T1": "safety incidents", "T2": "antibiotic shortage and allergies", "T3": "epidemic and budget",
          "T4": "ward requests under allocation", "T5": "two-week rota"}

TASK_TOML = """schema_version = "1.4"

[task]
name = "on-call-pharmacist/{slug}"
authors = [{{ name = "On-Call Pharmacist team" }}]
description = "On-Call Pharmacist {task} ({title}), seed {seed}: run a hospital's medicines service for {shifts} shifts."
keywords = ["healthcare", "pharmacy", "medication-safety", "long-horizon", "mcp"]

[metadata]
category = "operations"
task_id = "{task}"
seed = {seed}
shifts = {shifts}
difficulty_explanation = "Recalls must be traced through the issue log, failed cold-chain batches followed to the wards, restricted alternatives approved per patient, and shortages planned ahead, within 120 minutes of desk time per shift."

[verifier]
timeout_sec = 600.0

[agent]
timeout_sec = {agent_timeout:.1f}

[solution]
env = {{ PHARMACY_POLICY = "careful_pharmacist" }}

[environment]
build_timeout_sec = 900.0
cpus = 1
memory_mb = 2048

[[environment.mcp_servers]]
name = "pharmacy"
transport = "streamable-http"
url = "http://mcp-server:{port}/mcp"
"""

COMPOSE = """services:
  main:
    depends_on:
      mcp-server:
        condition: service_healthy

  mcp-server:
    build:
      context: ./mcp-server
    expose:
      - "{port}"
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:{port}/health', timeout=2)"]
      interval: 2s
      timeout: 5s
      retries: 15
      start_period: 5s
"""

MAIN_DOCKERFILE = """FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \\
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
"""

SIDECAR_DOCKERFILE = """FROM python:3.12-slim
WORKDIR /srv
COPY pharmacy_env /srv/pharmacy_env
EXPOSE {port}
CMD ["python", "-m", "pharmacy_env.mcp_server", "--task", "{task}", "--seed", "{seed}", "--http", "{port}", "--out", "/tmp/trajectory.jsonl"]
"""

TEST_SH = """#!/bin/bash
set -euo pipefail
mkdir -p /logs/verifier
python3 /tests/verify.py
"""

SOLVE_SH = """#!/bin/bash
set -euo pipefail
python3 /solution/oracle.py
"""

INSTRUCTION_TAIL = """

The hospital pharmacy system's functions are available to you as the tools of the `pharmacy` MCP
server. Use them to do the job, one shift at a time, calling `end_shift` with your handover note
when you are done with a shift. The rota is complete when `end_shift` tells you the rota period has
ended.
"""


def copy_package(dst):
    src = os.path.join(ROOT, "pharmacy_env")
    os.makedirs(dst, exist_ok=True)
    for name in sorted(os.listdir(src)):
        if name.endswith(".py"):
            shutil.copy2(os.path.join(src, name), os.path.join(dst, name))


def write(path, text, mode=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)
    if mode:
        os.chmod(path, mode)


def make_task(task, seed, out_dir):
    env = Env(TASKS[task](seed))
    slug = "%s-seed%d" % (task.lower(), seed)
    d = os.path.join(out_dir, slug)
    if os.path.exists(d):
        shutil.rmtree(d)
    fmt = dict(task=task, seed=seed, slug=slug, title=TITLES[task], shifts=env.n_shifts, port=PORT,
               agent_timeout=float(env.n_shifts * SECONDS_PER_SHIFT))
    write(os.path.join(d, "task.toml"), TASK_TOML.format(**fmt))
    write(os.path.join(d, "instruction.md"),
          system_prompt(env, "full") + "\n\n" + shift_start_message(env, "full") + INSTRUCTION_TAIL)
    write(os.path.join(d, "environment", "Dockerfile"), MAIN_DOCKERFILE)
    write(os.path.join(d, "environment", "docker-compose.yaml"), COMPOSE.format(**fmt))
    write(os.path.join(d, "environment", "mcp-server", "Dockerfile"), SIDECAR_DOCKERFILE.format(**fmt))
    copy_package(os.path.join(d, "environment", "mcp-server", "pharmacy_env"))
    cfg = json.dumps({"task": task, "seed": seed, "mcp_url": "http://mcp-server:%d" % PORT}, indent=1) + "\n"
    for part, script, sh, sh_name in (("tests", "verify.py", TEST_SH, "test.sh"),
                                      ("solution", "oracle.py", SOLVE_SH, "solve.sh")):
        write(os.path.join(d, part, sh_name), sh, 0o755)
        shutil.copy2(os.path.join(HERE, script), os.path.join(d, part, script))
        write(os.path.join(d, part, "config.json"), cfg)
        copy_package(os.path.join(d, part, "pharmacy_env"))
    return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", nargs="+", default=["T1", "T2", "T3", "T4", "T5"])
    ap.add_argument("--seeds", nargs="+", type=int, default=[0])
    ap.add_argument("--out", default=os.path.join(HERE, "tasks"))
    a = ap.parse_args()
    for task in a.tasks:
        for seed in a.seeds:
            print("wrote", os.path.relpath(make_task(task, seed, a.out), ROOT))


if __name__ == "__main__":
    main()
