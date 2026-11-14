# On-Call Pharmacist: a hospital medicines-safety environment for agents

An agent works a two-week rota as the on-duty pharmacist of a (fictional) regional hospital.
Medicines are tracked by batch across a central store and five ward cabinets. Over the rota
the inbox brings recalls, a supply shortage and an influenza warning, and wards keep using
medicines whatever the agent does. The agent acts through the same kind of functions a
pharmacist uses (look up a batch, quarantine it, transfer stock, approve a formulary
alternative, place an urgent order) under a fixed amount of desk time per shift.

**Result.** On the two-week task (T5), Gemini 3.5 Flash scores **0.65, 0.65 and 0.74**
on three seeds, against a pass threshold of **0.82-0.86** and a scripted reference
pharmacist at **1.00**. It handles every recall correctly, but it reads the influenza
warning and the shortage notice, writes them into its handover notes, and does not act on
them in time. Wards then run out of piperacillin/tazobactam and ceftriaxone.

```bash
python3 -m pharmacy_env.eval        # one command, no API key, ~5 s
```

This re-runs every scripted anchor, checks the calibration gates, replays every recorded
model trajectory and checks the recorded score is reproduced exactly, and prints the
failure modes found in each trajectory. Saved output: [results/eval_output.txt](results/eval_output.txt).

---

## Why this setting

Hospital pharmacy is a high-stakes operational job that agents have barely been tested on.
The skills it needs are general and hard: tracing items across locations, following
procedures exactly, and turning early warnings into action before the consequence arrives,
with limited time and incomplete memory across shifts. Every decision has a checkable
outcome in this environment (was a recalled vial given to a patient, did a ward run out of
a critical drug), so the reward can be computed rather than judged.

## The world

| Part | What it contains |
|---|---|
| Medicines | 10 products (7 critical): epinephrine, norepinephrine, heparin, insulin, ceftriaxone, cefotaxime, piperacillin/tazobactam, morphine, ondansetron, IV paracetamol |
| Locations | Central store + ICU, ED, Surgical, Paediatrics and Medical ward cabinets |
| Stock | Batches (lot number, expiry, quantity, status available/quarantined) at each location |
| Ward use | Every shift each ward draws a Poisson-distributed amount of each product, earliest expiry first |
| Automatic replenishment | At handover cabinets are refilled to par from the central store; the wholesaler delivers to central every second day (fixed standing orders in T5) |
| Inbox | Recall notices, wholesaler bulletins, hospital memos and unrelated routine mail |
| Policies | Four SOPs the agent can read: recalls, shortages, therapeutic substitution, urgent orders |

All hospital, lot and staff data are synthetic. Product names and presentations are real
generic medicines.

## What the agent can do

12 functions. Each costs desk time; a shift has 120 minutes. The world advances only when
the agent calls `end_shift` (or runs out of time), so the outcome depends only on the
action sequence, never on model latency.

| Function | Minutes | Purpose |
|---|---|---|
| `get_status` | 0 | shift, time left, unread notices |
| `read_notices`, `read_policy`, `get_drug_info`, `list_inventory`, `find_lot`, `get_usage_report` | 5 | look things up |
| `quarantine_lot`, `transfer_stock`, `approve_substitution` | 10 | act on stock |
| `place_urgent_order` | 15 | express order, arrives next shift, +40% cost |
| `end_shift(handover_note)` | 0 | hand over to the next shift |

The system prompt describes the job, the time budget and the automatic replenishment. It
does not say what will happen or what to prioritise. Tool names and outputs read like a
hospital system; nothing mentions a simulation, a test or a score.

## Tasks

| Task | Shifts | What happens | Role |
|---|---|---|---|
| **T1 recall** | 10 | Two batch recalls (heparin, epinephrine) spread over central and cabinets; routine supply of each paused for 2 days; distractor mail including a recall for a presentation the hospital does not stock | Control task |
| **T5 two-week rota** | 28 | Heparin recall (shift 3-4); ceftriaxone shortage rumoured (shift 5-6), confirmed two shifts later with standing orders suspended for 12 shifts; Infection Control memo (shift 11-12) warning of an influenza surge, after which ICU and Medical use of piperacillin/tazobactam (x2.5) and IV paracetamol (x2) rises for 16 shifts; epinephrine recall (shift 19-20); routine mail throughout | Main task |

The seed changes initial stock, which cabinets hold the recalled batches, event timing,
and daily demand. In T5 the agent sees only the previous shift's handover note at the start
of each shift (it is told this), which also keeps a 28-shift run affordable.

## Reward

Penalty points, all computed from the simulation:

| Event | Points |
|---|---|
| A recalled unit given to a patient after the recall notice | 10 per unit |
| A ward cannot issue a critical medicine | 2 per unit x ward weight (ICU, ED 1.5) |
| A ward cannot issue a non-critical medicine | 0.5 per unit x ward weight |
| A non-recalled unit quarantined | 0.5 per unit |
| Urgent-order surcharge | 1 per EUR 25 |
| A shift with no action (including shifts left after stopping early) | 5 per shift |

The score normalises the penalty per seed: `score = (P_do_nothing - P) / (P_do_nothing - P_reference)`,
so doing nothing scores 0 and the reference pharmacist scores 1.

## Anchors and calibration

Following the anchor-policy method of StoreBench (Raghuvanshi, Vedere, Wang, arXiv 2610.10942),
six scripted policies run under the same functions, time budget and information as the
agent. They read recall lots and supply news from the notice text, not from hidden state.

| Policy | Behaviour | T5 mean |
|---|---|---|
| `careful_pharmacist` (reference) | Recall protocol; watches every product a notice mentions; orders when central cover falls below six shifts of expected use; approves alternatives when supply is interrupted; refills cabinets emptied by a withdrawal | 1.00 |
| `sop_checklist` | Does exactly what the SOPs say (recall protocol, approve alternatives, refill), never plans ahead | 0.68 |
| `stop_early` | Reference behaviour for the first quarter of the rota, then stops | 0.43 |
| `central_only` | Common mistake: quarantines recalled batches in the central store only | 0.13 |
| `do_nothing` | Attends every shift, takes no action | 0.00 |
| `blanket_quarantine` | Exploit probe: withdraws every batch of any recalled product | -1.02 |

**Pass threshold** per seed is the midpoint of the two best honest anchors (reference and
SOP checklist): 0.79-0.89 on T5. The evaluation checks four gates on every T5 seed, and
all pass:

1. Ordering: reference > SOP checklist > central-only >= do-nothing.
2. Judgment gap: the reference beats the SOP checklist by at least 0.15.
3. Threshold margin: the threshold is at least 0.05 away from both anchors around it.
4. Exploit suppression: the exploit probe scores below every honest anchor.

T1 is reported as a control. The SOP checklist already reaches the reference there, so T1
measures procedure-following only and no gap is claimed for it.

## Results

Gemini 3.5 Flash (`gemini-3.5-flash` through Google's OpenAI-compatible endpoint,
temperature 0), one run per seed:

| Task | Seed | Score | Threshold | Below threshold | Replay |
|---|---|---|---|---|---|
| T1 | 0 | 1.00 | 1.00 | no | match |
| T5 | 0 | **0.65** | 0.82 | yes | match |
| T5 | 1 | **0.65** | 0.82 | yes | match |
| T5 | 2 | **0.74** | 0.86 | yes | match |

On T5 the model lands at the level of the rule-following anchor (0.65 / 0.64 / 0.72 on the
same seeds): it does what procedures say and misses what requires planning ahead.

## Failure modes (T5)

All three runs show the same pattern. Shift numbers below are 1-based and can be checked in
the trajectories with `python3 -m pharmacy_env.analyze results/trajectories/<file>`.

**1. Reads the early warning, does not act on it.** Every run reads the Infection Control
memo and records it. Seed 0, handover note written after reading it:

> "Notice N-2005 (Infection Control): Influenza A admissions rising; increased demand for
> PIP-45 and PCM-IV expected. CENTRAL holds 119 available units of PIP-45 and 168 available
> units of PCM-IV; all ward cabinets stocked."

No order follows. Standing orders are sized for normal use, so the central store drains and
ICU and Medical wards cannot issue piperacillin/tazobactam from shift 20-21 (about 100 units
in seed 0, 114 in seed 1, 87 in seed 2). Urgent orders placed over 28 shifts: 0, 0 and 1.
The reference orders when cover drops below six shifts and loses almost nothing.

**2. Slow response to a confirmed shortage.** The ceftriaxone allocation notice arrives at
shift 7-8 and names formulary alternatives. In seed 0 the agent approves cefotaxime for one
ward at shift 14, runs out of desk time trying to approve the next, and covers all wards only
at shift 16. No replacement ceftriaxone is ordered. Wards cannot issue ceftriaxone from
shift 17-18 in all three seeds.

**3. Desk time spent re-establishing context.** Because each shift starts from the handover
note, the agent re-reads policies (48, 51 and 23 times) and inventories (152, 136 and 133
`list_inventory` calls) instead of acting. This is what pushes the substitution approvals in
failure 2 past the end of the shift.

**4. What it gets right.** Every recall is handled the shift it arrives: all locations
holding the batch are found and quarantined and no recalled unit reaches a patient (0 in all
runs). It is not misled by the distractor recall for a presentation the hospital does not
stock. On T1 it matches the reference.

These failures come from decisions, not missing information: the memo, the allocation
notice, central stock levels, usage reports and the urgent-order SOP are all available
through the functions, and the reference uses only those.

## Reward integrity

Defences built into the simulation, each exercised by an anchor or a test:

| Possible shortcut | Defence |
|---|---|
| Stop early | Remaining shifts are simulated and penalised as unattended; ward demand continues (`stop_early` anchor, test) |
| Withdraw everything so no recalled unit is ever given | Shortages and wrongly withdrawn units cost more (`blanket_quarantine` anchor, scores below doing nothing) |
| Stockpile with urgent orders | Every urgent order pays a 40% surcharge; quantity per order is capped |
| Withdraw by product name instead of batch | Only lots named in a notice count as recalled; other quarantined units are penalised |
| Substitute any similar drug | Only formulary-listed alternatives can be approved |
| Partial issue counted as full | Shortages are counted per unit, not per request |
| Game timing or latency | Simulated time depends only on the action sequence |

Determinism: ward demand comes from an RNG keyed only by seed, shift, ward and product, and
all iteration orders are fixed. A test runs the anchors under three different Python hash
seeds and requires identical scores.

## Reproduce

Requirements: Python 3.9+, standard library only for the environment and the evaluation.

```bash
python3 -m pharmacy_env.eval                         # everything above
python3 -m unittest discover tests                   # 7 tests (Claude harness test skips without `anthropic`)
python3 -m pharmacy_env.anchors --task T5 --seeds 0 1 2 3 4
python3 -m pharmacy_env.replay results/trajectories/T5_seed0_gemini-3.5-flash_handover.jsonl
python3 -m pharmacy_env.analyze results/trajectories/*.jsonl
```

Run a model yourself (costs API credits). Put keys in `api.env` (git-ignored):

```bash
# Gemini or any OpenAI-compatible endpoint: LLM_BASE_URL, LLM_API_KEY, LLM_MODEL
python3 -m pharmacy_env.run_agent --task T5 --seed 0 --memory handover
# Claude (pip install anthropic): ANTHROPIC_API_KEY, CLAUDE_MODEL, CLAUDE_EFFORT
python3 -m pharmacy_env.run_claude --task T1 --seed 0
```

Each run writes a JSONL trajectory: every model message, every function call with its
arguments and result, desk time left, handover notes, and a final summary with metrics,
penalty breakdown, score and token usage.

## Files

| Path | Contents |
|---|---|
| `pharmacy_env/world.py` | Products, locations, par levels, formulary alternatives |
| `pharmacy_env/engine.py` | Simulation and the 12 functions |
| `pharmacy_env/tasks.py` | Task generators T1 and T5 |
| `pharmacy_env/scoring.py` | Penalty and normalised score |
| `pharmacy_env/policies.py` | Six anchor policies |
| `pharmacy_env/eval.py` | One-command evaluation and calibration gates |
| `pharmacy_env/replay.py` | Replays a trajectory's actions and checks the score |
| `pharmacy_env/analyze.py` | Tags failure modes in a trajectory |
| `pharmacy_env/run_agent.py` | Agent harness for OpenAI-compatible APIs (Gemini) |
| `pharmacy_env/run_claude.py` | Agent harness for Claude (Anthropic SDK) |
| `results/trajectories/` | The four model runs reported above |
| `results/eval_output.txt` | Output of `python3 -m pharmacy_env.eval` |
| `tests/test_env.py` | Determinism, anchor ordering, stop-early penalty, harness and replay tests |

## Limitations and next steps

- **One run per seed, three seeds, one model.** The gap is consistent across seeds; more runs
  per seed and more models (including stronger ones) would tighten the claim.
- **The second recall in T5 is weak.** By shift 19-20 the recalled epinephrine batch has
  mostly been used up, so that recall rarely tests anything. The fix is to recall a newer batch.
- **Handover mode is part of the task.** T5 results are with handover notes only. A
  full-history run on T5 would separate planning failures from memory limits.
- **Model version.** The endpoint served `gemini-3.5-flash`; Google may route this name to
  a newer build. The trajectories record the name sent.
- **Claude harness.** `run_claude.py` passes its scripted test but has not been run against
  the live API.
- **Synthetic data.** Demand rates, prices and par levels are invented, not taken from a
  real hospital.
- **Stretch goal not done yet.** Training a 3-7B model on reference trajectories (for
  example with Gemma) is the next step.

Anchor-policy calibration, the gate checks and the reward-hack catalogue approach follow
StoreBench (arXiv 2610.10942). The domain, world, tasks and code are our own.
