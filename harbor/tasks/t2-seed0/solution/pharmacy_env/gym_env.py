"""A reset/step interface for plugging the environment into any agent harness. Standard library only.

    from pharmacy_env.gym_env import PharmacyEnv
    env = PharmacyEnv("T1", seed=0, trajectory_path="results/traj/my_run.jsonl")
    observation, info = env.reset()          # info: system_prompt, tools (OpenAI function schemas)
    observation, reward, terminated, truncated, info = env.step(
        {"name": "read_notices", "arguments": {}})

An action is one function call: {"name": ..., "arguments": {...} or a JSON string}. The observation is
the function result as a JSON string. The reward is 0 on every step and, on the step that ends the
rota, the normalised score (do nothing = 0, reference pharmacist = 1); info["penalty"] then holds the
breakdown. Calling end_shift starts the next shift: info["new_shift"] is True and observation is the
next shift's start message with the handover note the agent wrote (the function result is in
info["function_result"]). A harness that keeps only the handover between shifts, as in our reported
runs, starts a fresh conversation from that message.

close() ends the episode early if it is still running: the remaining shifts run unattended and are
scored, as with an agent that stops. The trajectory file has the same format as run_agent's and
is replayed and scored by `python3 -m pharmacy_env.judge --task T1 --seed 0 --trajectory <file>`.
"""
import io
import json

from .engine import Env
from .run_agent import TOOLS, finish, shift_start_message, system_prompt
from .tasks import TASKS


class PharmacyEnv:
    def __init__(self, task="T1", seed=0, memory="handover", trajectory_path=None, model="external-harness"):
        if task not in TASKS:
            raise ValueError("unknown task %r; one of %s" % (task, ", ".join(sorted(TASKS))))
        self.task, self.seed, self.memory, self.model = task, seed, memory, model
        self.trajectory_path = trajectory_path
        self.env = self.log = self.summary = None

    # -- episode -------------------------------------------------------------------------------
    def reset(self):
        if self.log is not None and self.summary is None:
            self.close()
        self.env = Env(TASKS[self.task](self.seed))
        self.log = open(self.trajectory_path, "w", buffering=1) if self.trajectory_path else io.StringIO()
        self.steps, self.summary = 0, None
        info = {"system_prompt": system_prompt(self.env, self.memory), "tools": TOOLS,
                "task": self.task, "seed": self.seed, "shifts": self.env.n_shifts}
        return shift_start_message(self.env, self.memory), info

    def step(self, action):
        if self.env is None:
            raise RuntimeError("call reset() first")
        if self.summary is not None:
            raise RuntimeError("the episode has ended; call reset()")
        name = action.get("name")
        args = action.get("arguments", {})
        if isinstance(args, str):
            try:
                args = json.loads(args or "{}")
            except ValueError:
                args = None
        self.steps += 1
        result = self.env.call(name, args) if args is not None else {"error": "Arguments were not valid JSON."}
        self.log.write(json.dumps({"type": "tool", "shift": self.env.shift, "name": name, "args": args,
                                   "result": result, "minutes_left": self.env.minutes_left}) + "\n")
        info = {"new_shift": False}
        observation = json.dumps(result)
        if self.env.done:
            summary = self._finish()
            info.update(penalty=summary["penalty"], score=summary["score"])
            return observation, summary["score"], True, False, info
        if name == "end_shift" and "error" not in result:
            self.log.write(json.dumps({"type": "handover", "shift": self.env.shift,
                                       "note": self.env.handover_note}) + "\n")
            info["new_shift"] = True
            info["function_result"] = result
            observation = shift_start_message(self.env, "handover")
        return observation, 0.0, False, False, info

    def close(self):
        """End the episode (remaining shifts run unattended) and return the summary."""
        if self.env is not None and self.summary is None:
            self._finish()
        return self.summary

    def _finish(self):
        self.summary = finish(self.env, self.task, self.seed, self.log, self.steps, {},
                              {"model": self.model, "memory": self.memory, "harness": "pharmacy_env.gym_env"})
        return self.summary
