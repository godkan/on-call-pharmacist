"""MCP server (JSON-RPC 2.0 over stdio, or over streamable HTTP) exposing the 22 hospital functions to
any MCP-capable agent harness. Standard library only.

    python3 -m pharmacy_env.mcp_server --task T1 --seed 0 --out results/traj/mcp_T1_seed0.jsonl
    python3 -m pharmacy_env.mcp_server --task T1 --seed 0 --http 8000     # POST /mcp; GET /trajectory

Over HTTP (used by the Harbor tasks in harbor/), GET /trajectory returns the actions taken so far as
JSONL; the Harbor verifier replays them on a fresh world to score the run.

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
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

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
        self.out, self.steps, self.summary, self.rows = out, 0, None, []
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
        self._row({"type": "tool", "shift": self.env.shift, "name": name, "args": args,
                   "result": result, "minutes_left": self.env.minutes_left})
        text = json.dumps(result)
        if self.env.done:
            self.finish()
            text += "\n\nThe rota period has ended. Thank you."
        elif name == "end_shift" and "error" not in result:
            self._row({"type": "handover", "shift": self.env.shift, "note": self.env.handover_note})
            # The client keeps its own conversation, so the note is a reminder, not the only memory.
            text += "\n\n" + shift_start_message(self.env, "handover")
        return {"content": [{"type": "text", "text": text}], "isError": "error" in result}

    def _row(self, row):
        self.rows.append(row)
        self.log.write(json.dumps(row) + "\n")

    def finish(self):
        if self.summary is None:
            self.summary = finish(self.env, self.task, self.seed, self.log, self.steps, {},
                                  {"model": "mcp-client", "memory": "full", "harness": "pharmacy_env.mcp_server"})
            print("pharmacy_env.mcp_server: scored %s seed %d, score %.2f, trajectory %s"
                  % (self.task, self.seed, self.summary["score"], self.out), file=sys.stderr, flush=True)


def dispatch(server, msg):
    """The JSON-RPC reply to one message, or None for a notification."""
    if not isinstance(msg, dict) or "id" not in msg:   # e.g. notifications/initialized: no reply
        return None
    try:
        return {"jsonrpc": "2.0", "id": msg["id"], "result": server.handle(msg)}
    except LookupError:
        return {"jsonrpc": "2.0", "id": msg["id"],
                "error": {"code": -32601, "message": "Method not found: %s" % msg.get("method")}}
    except Exception as ex:          # never let one bad request end the rota
        return {"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32603, "message": str(ex)}}


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
        reply = dispatch(server, msg)
        if reply is not None:
            stdout.write(json.dumps(reply) + "\n")
            stdout.flush()
    server.finish()                  # client disconnected: score what was done


def serve_http(server, port, host="0.0.0.0"):
    """Streamable HTTP transport: POST /mcp carries JSON-RPC (JSON responses, no SSE stream);
    GET /trajectory returns the rows logged so far; GET /health for container health checks."""
    lock, session = threading.Lock(), uuid.uuid4().hex

    class Handler(BaseHTTPRequestHandler):
        def _send(self, code, body=b"", ctype="application/json", extra=None):
            self.send_response(code)
            if body:
                self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if body:
                self.wfile.write(body)

        def do_POST(self):
            if self.path.split("?")[0].rstrip("/") != "/mcp":
                return self._send(404)
            try:
                msg = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"null")
            except ValueError:
                return self._send(400, json.dumps({"jsonrpc": "2.0", "id": None,
                                                   "error": {"code": -32700, "message": "Parse error"}}).encode())
            with lock:
                replies = [r for r in (dispatch(server, m) for m in (msg if isinstance(msg, list) else [msg]))
                           if r is not None]
            if not replies:
                return self._send(202)
            body = replies if isinstance(msg, list) else replies[0]
            self._send(200, json.dumps(body).encode(), extra={"Mcp-Session-Id": session})

        def do_GET(self):
            path = self.path.split("?")[0].rstrip("/")
            if path == "/health":
                return self._send(200, b"ok", "text/plain")
            if path == "/trajectory":
                with lock:
                    body = "".join(json.dumps(r) + "\n" for r in server.rows).encode()
                return self._send(200, body, "application/x-ndjson")
            self._send(405 if path == "/mcp" else 404)

        def do_DELETE(self):
            self._send(200 if self.path.split("?")[0].rstrip("/") == "/mcp" else 404)

        def log_message(self, fmt, *args):
            pass

    ThreadingHTTPServer((host, port), Handler).serve_forever()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", default="T1", choices=sorted(TASKS))
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default=None, help="trajectory file (default results/traj/mcp_<task>_seed<seed>_<time>.jsonl)")
    ap.add_argument("--http", type=int, default=None, metavar="PORT", help="serve streamable HTTP on PORT instead of stdio")
    a = ap.parse_args()
    out = a.out or os.path.join("results", "traj", "mcp_%s_seed%d_%d.jsonl" % (a.task, a.seed, int(time.time())))
    server = Server(a.task, a.seed, out)
    if a.http:
        serve_http(server, a.http)
    else:
        serve(server)


if __name__ == "__main__":
    main()
