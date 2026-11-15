"""MCP server (stdio, JSON-RPC 2.0) exposing the 22 hospital functions to any MCP-capable agent harness.
Standard library only.

    python3 -m pharmacy_env.mcp_server --task T1 --seed 0 --out results/traj/mcp_T1_seed0.jsonl

Example client configuration (Claude Code, Claude Desktop and most MCP clients):

    {"mcpServers": {"pharmacy": {"command": "python3",
        "args": ["-m", "pharmacy_env.mcp_server", "--task", "T1", "--seed", "0", "--out", "mcp_T1_seed0.jsonl"],
        "cwd": "<path to this repository>"}}}

The server's `instructions` (sent on initialize) carry the same system prompt run_agent uses, with
full memory: an MCP client keeps its own conversation, so it sees every earlier shift (our reported
runs use handover notes only; see the README). One server process is one rota. When the agent
calls end_shift, the result also carries the next shift's start message. When the rota ends, or the
client disconnects, the remaining shifts run unattended, the run is scored and the trajectory is
written in run_agent's format; score it with
`python3 -m pharmacy_env.judge --task T1 --seed 0 --trajectory <file>`.
The score is not shown to the agent.
"""
import argparse
import json
import os
import sys
import time

from .engine import Env
from .run_agent import TOOLS, finish, shift_start_message, system_prompt
from .tasks import TASKS

PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")


class Server:
    def __init__(self, task, seed, out):
        self.task, self.seed = task, seed
        self.env = Env(TASKS[task](seed))
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        self.log = open(out, "w", buffering=1)
        self.out, self.steps, self.summary = out, 0, None
        self.tools = [{"name": t["function"]["name"], "description": t["function"]["description"],
                       "inputSchema": t["function"]["parameters"]} for t in TOOLS]

    def handle(self, msg):
        method, params = msg.get("method"), msg.get("params") or {}
        if method == "initialize":
            version = params.get("protocolVersion")
            return {"protocolVersion": version if version in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0],
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "on-call-pharmacist", "version": "1.0"},
                    "instructions": system_prompt(self.env, "full") + "\n\n" + shift_start_message(self.env, "full")}
        if method == "ping":
            return {}
        if method == "tools/list":
            return {"tools": self.tools}
        if method == "tools/call":
            return self.call(params.get("name"), params.get("arguments") or {})
        raise LookupError(method)

    def call(self, name, args):
        if self.summary is not None:
            return {"content": [{"type": "text", "text": json.dumps({"error": "The rota period has ended."})}],
                    "isError": True}
        self.steps += 1
        result = self.env.call(name, args)
        self.log.write(json.dumps({"type": "tool", "shift": self.env.shift, "name": name, "args": args,
                                   "result": result, "minutes_left": self.env.minutes_left}) + "\n")
        text = json.dumps(result)
        if self.env.done:
            self.finish()
            text += "\n\nThe rota period has ended. Thank you."
        elif name == "end_shift" and "error" not in result:
            self.log.write(json.dumps({"type": "handover", "shift": self.env.shift,
                                       "note": self.env.handover_note}) + "\n")
            # The client keeps its own conversation, so the note is a reminder, not the only memory.
            text += "\n\n" + shift_start_message(self.env, "handover")
        return {"content": [{"type": "text", "text": text}], "isError": "error" in result}

    def finish(self):
        if self.summary is None:
            self.summary = finish(self.env, self.task, self.seed, self.log, self.steps, {},
                                  {"model": "mcp-client", "memory": "full", "harness": "pharmacy_env.mcp_server"})
            print("pharmacy_env.mcp_server: scored %s seed %d, score %.2f, trajectory %s"
                  % (self.task, self.seed, self.summary["score"], self.out), file=sys.stderr, flush=True)


def serve(server, stdin=sys.stdin, stdout=sys.stdout):
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            stdout.write(json.dumps({"jsonrpc": "2.0", "id": None,
                                     "error": {"code": -32700, "message": "Parse error"}}) + "\n")
            stdout.flush()
            continue
        if "id" not in msg:          # a notification (e.g. notifications/initialized): no reply
            continue
        try:
            reply = {"jsonrpc": "2.0", "id": msg["id"], "result": server.handle(msg)}
        except LookupError:
            reply = {"jsonrpc": "2.0", "id": msg["id"],
                     "error": {"code": -32601, "message": "Method not found: %s" % msg.get("method")}}
        except Exception as ex:      # never let one bad request end the rota
            reply = {"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32603, "message": str(ex)}}
        stdout.write(json.dumps(reply) + "\n")
        stdout.flush()
    server.finish()                  # client disconnected: score what was done


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", default="T1", choices=sorted(TASKS))
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default=None, help="trajectory file (default results/traj/mcp_<task>_seed<seed>_<time>.jsonl)")
    a = ap.parse_args()
    out = a.out or os.path.join("results", "traj", "mcp_%s_seed%d_%d.jsonl" % (a.task, a.seed, int(time.time())))
    serve(Server(a.task, a.seed, out))


if __name__ == "__main__":
    main()
