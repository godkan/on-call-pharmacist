"""Harbor oracle for an On-Call Pharmacist task (copied into each task's solution/ with pharmacy_env).

Runs a scripted policy (default: the reference pharmacist) on a local copy of the world to get its
function calls, then makes exactly those calls on the hospital-system sidecar through MCP. The world
is deterministic, so the sidecar ends in the same state and the verifier scores the policy's run.

    PHARMACY_POLICY=careful_pharmacist   # reference, score 1.00 (default)
    PHARMACY_POLICY=do_nothing           # do-nothing baseline, score 0.00
    PHARMACY_POLICY=stop_early           # stop-early baseline, below the pass threshold
"""
import json
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from pharmacy_env.engine import Env  # noqa: E402
from pharmacy_env.policies import POLICIES  # noqa: E402
from pharmacy_env.tasks import TASKS  # noqa: E402


class MCPClient:
    def __init__(self, url):
        self.url, self.session, self.next_id = url, None, 0

    def rpc(self, method, params=None, notify=False):
        msg = {"jsonrpc": "2.0", "method": method, "params": params or {}}
        if not notify:
            self.next_id += 1
            msg["id"] = self.next_id
        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        if self.session:
            headers["Mcp-Session-Id"] = self.session
        req = urllib.request.Request(self.url, data=json.dumps(msg).encode(), headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=120) as r:
            self.session = r.headers.get("Mcp-Session-Id") or self.session
            body = r.read()
        return None if notify else json.loads(body)


def main():
    with open(os.path.join(HERE, "config.json")) as f:
        cfg = json.load(f)
    policy = os.environ.get("PHARMACY_POLICY", "careful_pharmacist")
    if policy not in POLICIES:
        raise SystemExit("unknown PHARMACY_POLICY %r; one of %s" % (policy, ", ".join(sorted(POLICIES))))

    local = Env(TASKS[cfg["task"]](cfg["seed"]))
    calls = []

    class Recorder:                 # the policy acts on the local copy; every call is recorded
        def __getattr__(self, k):
            return getattr(local, k)

        def call(self, name, args=None):
            calls.append((name, dict(args or {})))
            return local.call(name, args)

    POLICIES[policy](Recorder())

    client = MCPClient(cfg["mcp_url"].rstrip("/") + "/mcp")
    client.rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                              "clientInfo": {"name": "pharmacy-oracle", "version": "1.0"}})
    client.rpc("notifications/initialized", notify=True)
    for name, args in calls:
        reply = client.rpc("tools/call", {"name": name, "arguments": args})
        if "error" in reply:
            raise SystemExit("MCP error on %s: %s" % (name, reply["error"]))
    print("oracle (%s): made %d function calls on %s" % (policy, len(calls), cfg["mcp_url"]))


if __name__ == "__main__":
    main()
