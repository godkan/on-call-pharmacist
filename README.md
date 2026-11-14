# On-Call Pharmacist: a hospital medicines-safety environment for agents

An agent works a two-week rota as the on-duty pharmacist of a (fictional) regional hospital.
Medicines are tracked by batch across a central store and five ward cabinets, but the ward
cabinets record only products and quantities, not batch numbers. Patients on the wards
receive their medicines whatever the agent does, and some of them have drug allergies. Over
the rota the inbox brings two recalls, a supply shortage and an influenza warning. The agent
acts through the functions a hospital pharmacist uses (read the issue log, inspect a cabinet,
quarantine a batch, transfer stock, approve a formulary alternative for a ward or a patient,
place an urgent order) under a fixed amount of desk time per shift.

**Result.** On the two-week task (T5), Gemini 3.5 Flash scores **0.79, 0.70 and 0.73** on
three seeds, against pass thresholds of **0.89, 0.86 and 0.90** and a scripted reference
pharmacist at **1.00**. Two kinds of failure repeat across runs:

- **Recalls: it investigates before it withdraws.** With batch numbers not recorded in the
  cabinets, it spends the recall shift inspecting cabinets one by one instead of acting on the
  issue log, runs out of desk time, and defers the quarantine to the next shift. Recalled
  units reach patients in every run (5, 12 and 26 units; the reference: 0-3).
- **Early warnings: it reads them and does not act.** It records the influenza memo in its
  handover notes but does not order ahead; ICU and Medical wards run out of
  piperacillin/tazobactam (58-121 units).

```bash
python3 -m pharmacy_env.eval        # one command, no API key, ~5 s
```

This re-runs every scripted anchor, checks the calibration gates, replays every recorded
model trajectory and checks the recorded score is reproduced exactly, and prints the failure
modes found in each trajectory. Saved output: [results/eval_output.txt](results/eval_output.txt).

---

## Why this setting

Hospital pharmacy is a high-stakes operational job that agents have barely been tested on.
The skills it needs are general and hard: tracing items across locations from records,
following procedures exactly, respecting patient-level constraints, and turning early
warnings into action before the consequence arrives, with limited time and incomplete memory
across shifts. Every decision has a checkable outcome here (was a recalled vial given to a
patient, did a ward run out of a critical drug, did an allergic patient receive a
contraindicated drug), so the reward is computed, not judged.

## The world

| Part | What it contains |
|---|---|
| Medicines | 10 products (7 critical): epinephrine, norepinephrine, heparin, insulin, ceftriaxone, cefotaxime, piperacillin/tazobactam, morphine, ondansetron, IV paracetamol |
| Locations | Central store + ICU, ED, Surgical, Paediatrics and Medical ward cabinets |
| Stock | Batches (lot number, expiry, quantity, available/quarantined) at each location |
| Batch visibility (T5) | The central store records batches. Ward cabinets record product and quantity only. The **issue log** records every movement of a batch from the central store to a cabinet (including before the rota); a pharmacist can also **inspect** a cabinet on site |
| Patients (T5) | 65 patients receive ceftriaxone over the rota, with stays of 4-14 shifts; 12 are allergic to penicillin (others have latex or sulfonamide allergies) |
| Ward use | Ceftriaxone is given per patient; other products are drawn per ward (Poisson), earliest expiry first |
| Automatic replenishment | At handover cabinets are refilled to par from the central store; the wholesaler delivers to central every second day (fixed standing orders in T5) |
| Formulary | Ceftriaxone may be replaced by cefotaxime (no restriction, small stock) or piperacillin/tazobactam (**contraindicated in penicillin allergy; approve per patient only**) |
| Inbox | Recall notices, wholesaler bulletins, hospital memos and unrelated routine mail |
| Policies | Four SOPs the agent can read: recalls, shortages, therapeutic substitution, urgent orders |

All hospital, patient, lot and staff data are synthetic. Product names and presentations are
real generic medicines.

## What the agent can do

15 functions. Each costs desk time; a shift has 120 minutes. The world advances only when the
agent calls `end_shift` (or runs out of time), so the outcome depends only on the action
sequence, never on model latency.

| Function | Minutes | Purpose |
|---|---|---|
| `get_status` | 0 | shift, time left, unread notices |
| `read_notices`, `read_policy`, `get_drug_info`, `list_inventory`, `find_lot`, `get_usage_report`, `get_issue_log`, `list_patients` | 5 | look things up |
| `quarantine_lot`, `transfer_stock`, `approve_substitution` | 10 | act on stock (a cabinet visit costs the time even if the batch is no longer there) |
| `inspect_cabinet` | 15 | check a cabinet's batches on site |
| `place_urgent_order` | 15 | express order, arrives next shift, +40% cost |
| `end_shift(handover_note)` | 0 | hand over to the next shift |

`approve_substitution` works for a whole ward or for one patient (`patient_id`). The system
prompt describes the job, the time budget and the automatic replenishment. It does not say
what will happen or what to prioritise. Tool names and outputs read like a hospital system;
nothing mentions a simulation, a test or a score.

## Tasks

| Task | Shifts | What happens | Role |
|---|---|---|---|
| **T1 recall** | 10 | Two batch recalls spread over central and cabinets (batches visible everywhere); routine supply of each paused for 2 days; distractor mail including a recall for a presentation the hospital does not stock | Control task |
| **T5 two-week rota** | 28 | Heparin recall (shift 3-4); ceftriaxone shortage rumoured (shift 5-6) and confirmed two shifts later, standing orders suspended for 12 shifts; Infection Control memo (shift 11-12) warning of an influenza surge, after which ICU and Medical use of piperacillin/tazobactam (x2.5) and IV paracetamol (x2) rises for 16 shifts; recall of two routine epinephrine deliveries that by then sit in every location (shift 19-21); routine mail throughout. Batches hidden in cabinets; patient-level ceftriaxone with allergies | Main task |

The seed changes initial stock, which cabinets hold the recalled batches, event timing,
patients and their allergies, and daily demand. In T5 the agent sees only the previous
shift's handover note at the start of each shift (it is told this), which also keeps a
28-shift run affordable.

## Reward

Penalty points, all computed from the simulation:

| Event | Points |
|---|---|
| A recalled unit given to a patient after the recall notice | 10 per unit |
| A dose of an alternative given to a patient allergic to it | 15 per dose |
| A ward cannot issue a critical medicine | 2 per unit x ward weight (ICU, ED 1.5) |
| A ward cannot issue a non-critical medicine | 0.5 per unit x ward weight |
| A non-recalled unit quarantined | 0.5 per unit |
| Urgent-order surcharge | 1 per EUR 25 |
| A shift with no action (including shifts left after stopping early) | 5 per shift |

The score normalises the penalty per seed: `score = (P_do_nothing - P) / (P_do_nothing - P_reference)`,
so doing nothing scores 0 and the reference pharmacist scores 1.

## Anchors and calibration

Following the anchor-policy method of StoreBench (Raghuvanshi, Vedere, Wang, arXiv 2610.10942),
six scripted policies run under the same functions, time budget and information as the agent.
They read recall lots and supply news from the notice text and trace batches through the
issue log, never from hidden state.

| Policy | Behaviour | T5 mean |
|---|---|---|
| `careful_pharmacist` (reference) | Recall: quarantines the central store first, then every cabinet the issue log shows received the batch, highest-use wards first, and rechecks the log on later shifts; watches every product a notice mentions; orders when central cover falls below six shifts of expected use; approves only unrestricted alternatives ward-wide; refills cabinets emptied by a withdrawal | 1.00 |
| `sop_checklist` | Does what the SOPs literally say (same recall tracing, unrestricted alternatives, refills), never plans ahead with urgent orders | 0.78 |
| `stop_early` | Reference behaviour for the first quarter of the rota, then stops | 0.26 |
| `central_only` | Common mistake: quarantines recalled batches in the central store only | 0.20 |
| `do_nothing` | Attends every shift, takes no action | 0.00 |
| `blanket_quarantine` | Exploit probe: inspects every cabinet and withdraws every batch of any recalled product | -0.16 |

**Pass threshold** per seed is the midpoint of the two best honest anchors (reference and SOP
checklist): 0.86-0.92 on T5. The evaluation checks four gates on every T5 seed, and all pass:

1. Ordering: reference > SOP checklist > central-only >= do-nothing.
2. Judgment gap: the reference beats the SOP checklist by at least 0.15.
3. Threshold margin: the threshold is at least 0.05 away from both anchors around it.
4. Exploit suppression: the exploit probe scores below every honest anchor that acts
   (do-nothing is the zero point, not a competitor, as in StoreBench).

The reference is not perfect: the second recall covers up to 12 batch-location pairs, which do
not all fit in one shift, so it lets 0-3 recalled units through per seed. T1 is reported as a
control: the SOP checklist already reaches the reference there, so T1 measures
procedure-following only and no gap is claimed for it.

## Results

Gemini 3.5 Flash (`gemini-3.5-flash` through Google's OpenAI-compatible endpoint, temperature
0), one run per seed:

| Task | Seed | Score | Threshold | SOP checklist | Replay |
|---|---|---|---|---|---|
| T1 | 0 | 1.00 | 1.00 | 1.01 | match |
| T5 | 0 | **0.79** | 0.89 | 0.79 | match |
| T5 | 1 | **0.70** | 0.86 | 0.71 | match |
| T5 | 2 | **0.73** | 0.90 | 0.80 | match |

On T5 the model lands at or below the rule-following anchor on every seed. On T1 it matches
the reference (1.0044 against a threshold of 1.0047, so the evaluation prints "NO" next to two
values that both round to 1.00; T1 is a control and no gap is claimed).

## Failure modes (T5)

Shift numbers are 1-based and can be checked with
`python3 -m pharmacy_env.analyze results/trajectories/<file>`.

**1. Investigates before it withdraws.** When a recall arrives, the issue log already shows
which cabinets received the batch, and quarantining a cabinet takes 10 minutes. The model
instead inspects cabinets one by one on site (15 minutes each, 10-11 inspections per run),
re-reads policies, and runs out of desk time:

| Seed | First recall | What happened | Recalled units given |
|---|---|---|---|
| 0 | shift 4 | Central, ICU and ED quarantined in the shift; ED, Surgical and Medical left to shift 5; three cabinets missed again at the second recall | 5 |
| 1 | shift 4 | Whole shift spent inspecting four cabinets (the fifth inspection ran out of time); nothing quarantined until shift 5 | 12 |
| 2 | shift 3 | Issue log read, then five inspections, inventory and drug info; nothing quarantined until shift 4, by which time handover restocking had moved more of the recalled batch from central into the cabinets | 26 |

Its own handover note in seed 2 lists every location and quantity to quarantine and says
"ACTION REQUIRED IMMEDIATELY IN SHIFT 4", written at the end of the shift in which it could
have done so.

**2. Reads the early warning, does not act.** Every run reads the Infection Control memo and
records it in handover notes. Standing orders are sized for normal use, so the central store
drains; ICU and Medical wards cannot issue piperacillin/tazobactam from shift 17-21 (103, 121
and 58 units). The reference orders when cover drops below six shifts and keeps these wards supplied.

**3. Slow response to a confirmed shortage.** The ceftriaxone allocation notice arrives at
shift 7-8. In seeds 0 and 2 cefotaxime is approved ward by ward only at shifts 15-21 (one
approval in seed 2 fails for lack of desk time) and wards cannot issue ceftriaxone (24 and 47
units). In seed 1 urgent orders cover the gap.

**4. Desk time spent re-establishing context.** Each shift starts from the handover note; the
model re-reads policies 40-49 times per run and calls `list_inventory` 89-151 times.

**What it gets right.** It never gives an allergic patient a contraindicated drug: it checks
patient lists (2-13 times per run) and approves only the unrestricted alternative ward-wide.
It is not misled by the distractor recall for a presentation the hospital does not stock, and
it quarantines no good stock. On T1, where batches are visible everywhere, it matches the
reference.

These failures come from decisions, not missing information: the issue log, the memo, the
allocation notice, stock levels, usage reports and the SOPs are all available through the
functions, and the reference uses only those.

## Reward integrity

Defences built into the simulation, each exercised by an anchor or a test:

| Possible shortcut | Defence |
|---|---|
| Stop early | Remaining shifts are simulated and penalised as unattended; patients and wards keep using medicines (`stop_early` anchor, test) |
| Withdraw everything so no recalled unit is ever given | Shortages and wrongly withdrawn units cost more (`blanket_quarantine` anchor) |
| Visit every cabinet blindly | Each visit costs desk time even when the batch is gone (test) |
| Approve the restricted alternative ward-wide | Doses given to allergic patients cost 15 each, more than a recalled unit (tests) |
| Stockpile with urgent orders | Every urgent order pays a 40% surcharge; quantity per order is capped |
| Withdraw by product name instead of batch | Only lots named in a notice count as recalled; other quarantined units are penalised |
| Partial issue counted as full | Shortages are counted per unit or dose, not per request |
| Game timing or latency | Simulated time depends only on the action sequence |

Determinism: ward demand comes from an RNG keyed only by seed, shift, ward and product,
patients are fixed per seed, and all iteration orders are fixed. A test runs the anchors under
three different Python hash seeds and requires identical scores.

## Reproduce

Requirements: Python 3.9+, standard library only for the environment and the evaluation.

```bash
python3 -m pharmacy_env.eval                         # everything above
python3 -m unittest discover tests                   # 11 tests (Claude harness test skips without `anthropic`)
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
penalty breakdown, score and token usage. The three T5 runs used 2.1-3.2 million input tokens
each.

## Files

| Path | Contents |
|---|---|
| `pharmacy_env/world.py` | Products, locations, par levels, formulary alternatives and restrictions |
| `pharmacy_env/engine.py` | Simulation and the 15 functions |
| `pharmacy_env/tasks.py` | Task generators T1 and T5 (issue history, patients) |
| `pharmacy_env/scoring.py` | Penalty and normalised score |
| `pharmacy_env/policies.py` | Six anchor policies and the recall tracker they share |
| `pharmacy_env/eval.py` | One-command evaluation and calibration gates |
| `pharmacy_env/replay.py` | Replays a trajectory's actions and checks the score |
| `pharmacy_env/analyze.py` | Tags failure modes in a trajectory |
| `pharmacy_env/run_agent.py` | Agent harness for OpenAI-compatible APIs (Gemini) |
| `pharmacy_env/run_claude.py` | Agent harness for Claude (Anthropic SDK) |
| `results/trajectories/` | The four model runs reported above |
| `results/eval_output.txt` | Output of `python3 -m pharmacy_env.eval` |
| `tests/test_env.py` | Determinism, anchor ordering, stop-early, batch tracing, allergy rules, harness and replay tests |

## Limitations and next steps

- **One run per seed, three seeds, one model.** The gap holds on every seed; more runs per seed
  and more models (including stronger ones) would tighten the claim.
- **The allergy trap did not trigger.** Gemini handled patient allergies correctly in every
  run. The patient layer adds realism and a real hazard, but no measured gap yet.
- **Handover mode is part of the task.** T5 results are with handover notes only. A
  full-history run would separate planning failures from memory limits.
- **Model version.** The endpoint served `gemini-3.5-flash`; Google may route this name to a
  newer build. The trajectories record the name sent.
- **Claude harness.** `run_claude.py` passes its scripted test but has not been run against
  the live API.
- **Synthetic data.** Demand rates, prices, par levels and patient mix are invented, not taken
  from a real hospital.
- **Stretch goal not done yet.** Training a 3-7B model on reference trajectories (for example
  with Gemma) is the next step.

An earlier version (git tag `v1`) had batches visible in every cabinet, no patient layer, and a
second recall that had mostly been used up by the time it arrived; there Gemini scored 0.65,
0.65 and 0.74 against thresholds of 0.82-0.86 and never let a recalled unit through.

Anchor-policy calibration, the gate checks and the reward-hack catalogue approach follow
StoreBench (arXiv 2610.10942). The domain, world, tasks and code are our own.
