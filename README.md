# On-Call Pharmacist: a hospital medicines-safety environment for agents

An agent works as the on-duty pharmacist of a (fictional) regional hospital. 30 medicines are
tracked by batch across a central store, seven ward and theatre cabinets and an out-of-hours
cupboard. Ward cabinets record products and quantities but not batch numbers. Patients keep
receiving their medicines whatever the agent does, and some of them have drug allergies. Over
each rota the inbox brings recalls, refrigerator alarms, shortages, allocation notices, an
influenza warning and requests from nurse managers. The agent acts through 22 hospital-system
functions under a fixed amount of desk time per shift, and in multi-day rotas sees only the
handover note the previous shift wrote.

One environment, five tasks (T1-T5) that differ in length, objective and events, plus a control
task (C1).

**Result.** DeepSeek V4.1 Flash, 25 runs (5 tasks x 3 seeds, plus 2 repeats of seed 0 per task):

| | T1 incidents | T2 shortage and allergies | T3 epidemic and budget | T4 ward requests | T5 two-week rota |
|---|---|---|---|---|---|
| mean score (reference = 1.00) | 0.70 | 0.48 | 0.73 | 0.27 | 0.65 |
| range | 0.51-0.84 | 0.25-0.67 | 0.56-0.94 | 0.13-0.37 | 0.49-0.82 |
| below the reference | 5/5 | 5/5 | 5/5 | 5/5 | 5/5 |
| below the pass threshold | 5/5 | 5/5 | 2/5 | 5/5 | 5/5 |

**25/25 runs score below the scripted reference pharmacist; 22/25 score below the pass
threshold.** A second, stronger model, Kimi K3.1 Pro (25 runs: 3 seeds per task plus 2 repeats
on seed 0), scores below the threshold in all 10 runs of T1 and T2 and 4 of 5 of T5, but passes T4
in every run and T3 in three of five, beating the reference once on each. Every run replays to the exact recorded score.

```bash
python3 -m pharmacy_env.eval        # one command, no API key, standard library only
```

This re-runs every scripted anchor on all tasks and five seeds, checks the calibration gates,
replays every recorded model trajectory and checks the recorded score is reproduced exactly,
prints a per-task summary and the failure modes found in each trajectory (about a minute).
Saved output: [results/eval_output.txt](results/eval_output.txt).

---

## Why this setting

Hospital pharmacy is high-stakes operational work that agents have barely been tested on. It
needs tracing items through records, following procedures exactly, respecting patient-level
constraints, and turning early warnings into action before the consequence arrives, with limited
time and incomplete memory across shifts. Every decision has a checkable outcome (was a recalled
or temperature-damaged vial given to a patient, did an allergic patient receive a contraindicated
drug, did a ward run out of a critical medicine), so the reward is computed, never judged.

## The world

| Part | What it contains |
|---|---|
| Medicines | 30 products in 9 classes: resuscitation (epinephrine, norepinephrine, amiodarone, atropine), anticoagulation (heparin, enoxaparin, protamine), anti-infectives (ceftriaxone, cefotaxime, piperacillin/tazobactam, meropenem, vancomycin, oseltamivir), analgesia and anaesthesia (morphine, fentanyl, midazolam, propofol), neuromuscular blockade (suxamethonium, rocuronium, sugammadex), insulin and glucose, GI (ondansetron, pantoprazole), fluids and electrolytes (sodium chloride 1 L, potassium chloride concentrate, IV paracetamol), obstetrics and paediatrics (oxytocin, paracetamol oral suspension) |
| Attributes | Critical medicine, controlled drug, high-alert medicine, restricted storage (concentrated potassium only in central, ICU, theatres), look-alike/sound-alike pair, restricted antimicrobial, storage volume, cold-chain guidance for 5 refrigerated products |
| Locations | Central store; ICU, ED, Surgical, Paediatrics, Medical, Operating Theatres, Maternity cabinets; out-of-hours cupboard (night shifts only) |
| Batch visibility | The central store records batches; ward cabinets do not. The issue log records every batch movement from the central store; a pharmacist can inspect a cabinet on site |
| Patients | Patient-level ceftriaxone in T2 and T5 (40-69 patients over a rota, stays of 4-14 shifts, 19-36% penicillin-allergic) |
| Ward use | Poisson demand per ward and product, earliest expiry first; per patient for patient-level products |
| Supply | Routine wholesaler (deliveries every second day), second wholesaler (+10%, two shifts), urgent courier (+40%, next shift), loans from a neighbouring hospital (free, 10 units per product), returns to supplier |
| Inbox | Recall notices, refrigerator alarms, wholesaler bulletins and allocation notices, hospital memos, nurse-manager requests, unrelated routine mail |
| Policies | Six SOPs the agent can read: recalls, shortages, substitution, urgent orders, ward requests, cold chain |

All hospital, patient, lot and staff data are synthetic, and so is the cold-chain guidance table.
Product names and presentations are real generic medicines.

## What the agent can do

22 functions. Each costs desk time; a shift has 120 minutes. The world advances only when the
agent calls `end_shift` (or runs out of time), so the outcome depends only on the action
sequence, never on model latency.

| Minutes | Functions |
|---|---|
| 0 | `get_status`, `end_shift(handover_note)` |
| 5 | `read_notices`, `read_policy`, `get_drug_info`, `list_inventory`, `find_lot`, `get_issue_log`, `get_usage_report`, `get_temperature_log`, `get_lot_record`, `list_patients`, `list_approvals`, `revoke_substitution` |
| 10 | `quarantine_lot` (a cabinet visit costs the time even if the batch is gone), `transfer_stock`, `approve_substitution` (ward-wide or per patient), `return_to_supplier` |
| 15 | `inspect_cabinet`, `place_urgent_order`, `place_wholesaler_order`, `borrow_from_hospital` |

The system prompt describes the job, the time budget, automatic replenishment and the handover.
It does not say what will happen or what to prioritise. Tool names and outputs read like a
hospital system; nothing mentions a simulation, a test or a score.

## Tasks

| Task | Shifts | Objective (from the rota brief) | What happens |
|---|---|---|---|
| **T1 incidents** | 10 | No recalled or compromised medicine reaches a patient, without withdrawing usable stock | Two recalls with batches hidden in cabinets; a warm excursion in a ward refrigerator that only one near-limit suxamethonium batch fails; a freeze in the central refrigerator that both insulins, suxamethonium and oxytocin fail and rocuronium tolerates, after which handover restocking has already moved frozen stock to wards; a delivery that arrives after the freeze is unaffected |
| **T2 shortage and allergies** | 14 | Every patient keeps an effective antibiotic; nobody receives a drug they are allergic to | Ceftriaxone and cefotaxime on allocation for the whole rota with express supply capped; piperacillin/tazobactam is the remaining alternative and is contraindicated for penicillin-allergic patients, who keep being admitted |
| **T3 epidemic and budget** | 20 | Critical medicines first within a fixed off-contract budget (EUR 1,800) | Influenza memo at shift 7-8, surge in piperacillin/tazobactam, IV paracetamol and ondansetron from the next shift; septic-shock memo at shift 13-14, norepinephrine surge from the next shift; critical shortfalls weighted 6 |
| **T4 ward requests** | 14 | Scarce stock goes to the wards that need it | Norepinephrine and epinephrine on allocation (standing orders halved, express capped); three genuine requests from wards in a surge and three reserve requests from wards that rarely use the product |
| **T5 two-week rota** | 28 | All of the above | Heparin recall; ceftriaxone shortage (rumoured, then confirmed); influenza memo, followed one shift later by advance notice that piperacillin/tazobactam goes on national allocation three shifts after that; epinephrine recall; patient-level ceftriaxone with allergies |
| C1 control | 10 | | Two recalls with batches visible in every cabinet (procedure-following only) |

The seed changes initial stock, which cabinets hold affected batches, event timing, patients and
their allergies, and daily demand. All tasks run with handover notes only: each shift starts
from the previous shift's note, and the system prompt says so.

## Reward

Penalty points, all computed from the simulation:

| Event | Points |
|---|---|
| A recalled unit given after the recall notice | 10 per unit |
| A unit from a batch that failed a refrigerator excursion given to a patient | 10 per unit |
| A dose of an alternative given to a patient allergic to it | 15 per dose |
| A ward cannot issue a critical medicine | 2 per unit (6 in T3) x area weight (ICU, ED, theatres, maternity 1.5) |
| A ward cannot issue a non-critical medicine | 0.5 per unit x area weight |
| A usable unit quarantined | 0.5 per unit |
| Purchase premium (urgent +40%, second wholesaler +10%) | 1 per EUR 25 |
| A shift with no action (including shifts left after stopping early) | 5 per shift |

The score normalises the penalty per seed: `score = (P_do_nothing - P) / (P_do_nothing - P_reference)`,
so doing nothing scores 0 and the reference pharmacist scores 1.

## Anchors and calibration

Following the anchor-policy method of StoreBench (Raghuvanshi, Vedere, Wang, arXiv 2610.10942),
scripted policies run under the same functions, time budget and information as the agent. They
read recalls, alarms and supply news from the notice text and trace batches through the issue
log, never from hidden state.

| Policy | Behaviour | T1 | T2 | T3 | T4 | T5 |
|---|---|---|---|---|---|---|
| `careful_pharmacist` (reference) | Withdraws recalled and failed batches (central first, then cabinets the issue log shows, including stock moved on from a failed fridge); bridges supply gaps to the resume date; buys through the cheapest channel that arrives in time (loan, second wholesaler, courier); orders ahead on warnings and allocation notices, critical first within a budget; approves restricted alternatives per patient every shift; verifies and follows up ward requests | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| `reactive_pharmacist` | Follows the SOPs and repairs shortages after wards report them; never acts on warnings | 0.98 | 0.60 | 0.33 | 0.52 | 0.78 |
| `sop_checklist` | Does what the SOPs literally say; never buys ahead | 0.99 | 0.19 | 0.00 | 0.02 | 0.60 |
| `central_only` | Common mistake: withdraws recalled batches in the central store only | 0.28 | 0.00 | 0.00 | 0.00 | 0.18 |
| `do_nothing` | Attends every shift, takes no action | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| `stop_early` | Reference for the first quarter of the rota, then stops | 0.49 | 0.02 | -0.12 | 0.01 | 0.26 |
| exploit probes | T1/T5: withdraw every batch of a recalled product, or discard every refrigerated batch after an alarm; T2: approve the restricted alternative ward-wide; T4: grant every request unchecked | 0.50 / 0.84 | 0.10 | | 0.82 | 0.05 |

Means over five seeds. **Pass threshold** per seed is the midpoint of the reference and the best
other honest anchor (reference, reactive, SOP checklist, central-only, do-nothing): T1 0.99-1.01,
T2 0.77-0.83, T3 0.50-0.83, T4 0.71-0.79, T5 0.86-0.93. The evaluation checks these gates on
every seed of T1-T5, and all pass:

1. Ordering: reference > SOP checklist >= do-nothing (T1: the reference is within 0.05 of the best honest anchor).
2. Judgment gap: the reference beats the SOP checklist by at least 0.15 (not claimed for T1, where the SOPs fully specify the task).
3. Threshold margin: the threshold is at least 0.05 from the reference and from the next honest anchor.
4. Exploit suppression: every probe for the task scores at least 0.05 below the reference.
5. Stopping early scores below the threshold.

## Results

DeepSeek V4.1 Flash (`deepseek-4-1-flash-1017` through Verda's OpenAI-compatible inference API,
temperature 0, reasoning effort none, handover notes). Score / pass threshold:

| Task | Seed 0 (3 runs) | Seed 1 | Seed 2 |
|---|---|---|---|
| T1 | 0.51, 0.76, 0.58 / 1.00 | 0.82 / 1.00 | 0.84 / 0.99 |
| T2 | 0.62, 0.51, 0.33 / 0.82 | 0.25 / 0.83 | 0.67 / 0.77 |
| T3 | 0.63, 0.94, 0.64 / 0.80 | 0.56 / 0.50 | 0.86 / 0.70 |
| T4 | 0.13, 0.15, 0.34 / 0.71 | 0.35 / 0.79 | 0.37 / 0.79 |
| T5 | 0.82, 0.49, 0.65 / 0.89 | 0.70 / 0.86 | 0.58 / 0.92 |

**Second model.** Kimi K3.1 Pro (`kimi-k3-1-pro`, same endpoint, reasoning effort low), three runs
on seed 0 and one each on seeds 1 and 2 (score / pass threshold):

| | seed 0 (3 runs) | seed 1 | seed 2 | mean | below threshold |
|---|---|---|---|---|---|
| T1 | 0.95, 0.64, 0.89 / 1.00 | 0.85 / 1.00 | 0.91 / 0.99 | 0.85 | 5/5 |
| T2 | 0.56, 0.75, 0.52 / 0.82 | 0.56 / 0.83 | 0.53 / 0.77 | 0.58 | 5/5 |
| T3 | 0.59, 0.58, 0.83 / 0.80 | 0.91 / 0.50 | **1.06** / 0.70 | 0.79 | 2/5 |
| T4 | 0.84, 0.96, 0.89 / 0.71 | **1.07** / 0.79 | 0.98 / 0.79 | 0.95 | 0/5 |
| T5 | 0.84, 0.99, 0.86 / 0.89 | 0.85 / 0.86 | 0.91 / 0.92 | 0.89 | 4/5 |

Kimi is below the reference in 23 of 25 runs and below the threshold in 16 of 25. The split is by
task:

- **T1, T2, T5 hold for both models.** In every T1 run damaged cold-chain stock reached patients
  (2-16 units) and in three of five it also withdrew 100-163 usable units; recalled units reached
  patients in every T5 run (7-24). In T2 it switched wards to cefotaxime but approved
  piperacillin/tazobactam per patient in only one of five runs, so 70-102 ceftriaxone doses could
  not be given per run. T5 is close: one run passes (0.99) and two are only 0.01 below.
- **T3 and T4 do not separate a strong model.** Both are supply-planning tasks. Kimi supplied the
  genuine T4 surges well and, on T3 seed 2, ran short of norepinephrine less than the reference
  (14 vs 19 units). No reward hack is involved: its penalty is entirely shortfall and courier
  premium, with no wrong quarantines or contraindicated doses. The two runs above 1.00 show that the
  reference's purchasing rule is not optimal on those seeds.

The 25 Kimi runs used 8.9 million input tokens.

The DeepSeek runs used 23.5 million input tokens in total (0.4-1.8 million per run). On T2 and T5 the
model also scores below the reactive anchor (a script that only repairs shortages after they
happen) in 4 of 5 runs, and on T1 and T4 in every run.

## Failure modes

Shift numbers are 1-based; `python3 -m pharmacy_env.analyze results/trajectories/<file>` lists the
findings for any run.

**1. Investigates before it withdraws (T1, T5).** When a recall arrives the issue log already
shows which cabinets received the batch, and a quarantine takes 10 minutes. The model inspects
cabinets one by one on site (15 minutes each; 24-90 inspections per run in T1 and T5), runs out of desk time
and leaves the quarantine to the next shift, by which time wards have used the batch. Recalled
units reached patients in every T1 and T5 run: 10-48 per T1 run, 24-89 per T5 run (reference:
0-3). One T5 handover note opens with "URGENT - CLASS II RECALL NOT YET ACTIONED (ran out of desk
time)" and lists every location and quantity it had confirmed during the shift.

**2. Does not follow a failed batch after it has moved (T1).** After the central refrigerator
freezes, handover restocking has already sent frozen insulin and suxamethonium to the wards. The
model withdraws stock in the central refrigerator but not the units now in ward cabinets: 4-13
damaged units reached patients per run.

**3. Under-supplies a confirmed need (T2, T4).** In T2 the model approves alternatives (13-40
approvals per run) but ceftriaxone patients still go without doses (50-128 per run against 26-44
for the reference). In four of five runs it approved piperacillin/tazobactam only per patient;
in the fifth it also approved it ward-wide on four wards, and two doses reached penicillin-allergic
patients. In T4 it correctly refuses all reserve requests, but sends too
little, or nothing, to the wards in a genuine surge: 42-263 norepinephrine and 111-224 epinephrine
doses could not be issued per run.

**4. Plans unevenly for announced shortages (T3, T5).** With the influenza warning and the advance
allocation notice in T5, the model ordered piperacillin/tazobactam before the allocation started in
four of five runs (100-210 vials) and once almost not at all (16), and wards still ran out in four
runs. In T3 it found the cheaper second wholesaler and free loans, which is why it passes the
threshold in two runs, but norepinephrine ran short in the second week in every run.

**5. Desk time spent re-establishing context.** Every shift starts from the handover note; the
model re-reads policies 16-75 times per run.

**Kimi's distinct failure (T1).** After the central freeze, Kimi withdrew every refrigerated
batch in the central store in three of five runs, including deliveries that arrived after the
excursion and were never frozen: 100-163 usable units of insulin, oxytocin and suxamethonium
withdrawn. In the other two it withdrew nothing usable but left frozen stock in use (11-13 damaged
units reached patients). In every run it left frozen stock that had already moved to wards.

**What DeepSeek gets right.** It never quarantines usable stock, ignores distractor mail including a
recall for a presentation the hospital does not stock, refuses every reserve request in T4, and in
four of five T2 runs approves the restricted alternative only patient by patient.

All failures come from decisions, not missing information: the issue log, temperature logs, batch
records, patient lists, usage reports, notices and SOPs are available through the functions, and
the reference uses only those.

## Reward integrity

| Possible shortcut | Defence |
|---|---|
| Stop early | Remaining shifts are simulated and penalised; patients and wards keep using medicines (`stop_early` anchor) |
| Withdraw everything so nothing bad is given | Shortages and wrongly withdrawn units cost more (`blanket_quarantine`, `discard_all_cold`) |
| Visit every cabinet blindly | Each visit costs desk time even when the batch is gone |
| Approve a restricted alternative ward-wide | Contraindicated doses cost 15 each (`wardwide_alternatives`) |
| Grant every request | Scarce stock lands where it is not used (`grant_all_requests`) |
| Buy your way out | Purchase premiums are penalised; express supply is capped under allocation; T3 has a hard budget covering the courier and the second wholesaler |
| Free loans | 10 units per product per rota; refused for products on national allocation |
| Store concentrated potassium on a ward | Refused by hospital policy |
| Withdraw by product name instead of batch | Only named batches count as recalled; other withdrawn units are penalised |
| Game timing or latency | Simulated time depends only on the action sequence |

Determinism: demand comes from an RNG keyed only by seed, shift, ward and product; patients and
events are fixed per seed; all iteration orders are fixed. A test runs the anchors under three
different Python hash seeds and requires identical scores.

## Reproduce

Python 3.9+; the environment and the evaluation use the standard library only.

```bash
python3 -m pharmacy_env.eval                         # everything above (about a minute)
python3 -m unittest discover tests                   # 24 tests (about a minute)
python3 -m pharmacy_env.anchors --task T5 --seeds 0 1 2 3 4
python3 -m pharmacy_env.replay results/trajectories/T5_seed0_deepseek-4-1-flash_handover.jsonl
python3 -m pharmacy_env.analyze results/trajectories/*.jsonl
```

Run a model (costs API credits). Put keys in `api.env` (git-ignored):

```bash
# any OpenAI-compatible endpoint: LLM_BASE_URL, LLM_API_KEY, LLM_MODEL, optional LLM_REASONING_EFFORT
# e.g. LLM_BASE_URL=https://inference.verda.com/v1  LLM_MODEL=deepseek-4-1-flash-1017
python3 -m pharmacy_env.run_agent --task T5 --seed 0 --memory handover
# Claude (pip install anthropic): ANTHROPIC_API_KEY, CLAUDE_MODEL, CLAUDE_EFFORT
python3 -m pharmacy_env.run_claude --task T1 --seed 0
```

Each run writes a JSONL trajectory: every model message, every function call with arguments and
result, desk time left, every handover note, and a summary with metrics, penalty breakdown, score,
token usage, endpoint and settings.

## Files

| Path | Contents |
|---|---|
| `pharmacy_env/world.py` | Products, attributes, locations, par levels, formulary, cold-chain guidance |
| `pharmacy_env/engine.py` | Simulation and the 22 functions |
| `pharmacy_env/tasks.py` | Task generators C1 and T1-T5 |
| `pharmacy_env/scoring.py` | Penalty and normalised score |
| `pharmacy_env/policies.py` | Anchor policies and exploit probes |
| `pharmacy_env/eval.py` | One-command evaluation, gates and per-task summary |
| `pharmacy_env/replay.py` | Replays a trajectory's actions and checks the score |
| `pharmacy_env/analyze.py` | Tags failure modes in a trajectory |
| `pharmacy_env/run_agent.py` | Agent harness for OpenAI-compatible APIs |
| `pharmacy_env/run_claude.py` | Agent harness for Claude (Anthropic SDK) |
| `results/trajectories/` | The 50 model runs reported above (25 DeepSeek, 25 Kimi) |
| `results/eval_output.txt` | Output of `python3 -m pharmacy_env.eval` |
| `tests/test_env.py` | Determinism, gates, harness and replay, batch tracing, allergies, cold chain, supply channels |

## How the environment was calibrated

We report the changes made after looking at model results, because they affect how the numbers
should be read.

- **Stronger reference.** After the first DeepSeek runs, the model beat the reference on T3: it
  used the second wholesaler and loans, which the reference did not, and the reference
  overestimated the surge and spent the budget early. The reference was improved (cheapest channel
  that arrives in time; surge estimated at 1.3x hospital-wide with a fixed budget; at most 35% of
  the remaining budget per purchase). Model trajectories were not rerun; their penalties are
  unchanged and only the normalisation moved.
- **Reactive anchor.** Added after the first results, because the SOP checklist scores near zero on
  T2-T4 and set a low threshold there. The threshold rule did not change.
- **T5 rebalanced.** With the reactive anchor, reacting nearly matched planning on T5 and the
  threshold-margin gate failed. As StoreBench does with tasks that fail a gate, we rebalanced the
  task instead of relaxing the gate: T5 now has an advance allocation notice for
  piperacillin/tazobactam. All five T5 runs were rerun on the new version.
- **Tool-call cap.** The first T5 runs hit a harness cap of 600 tool calls; the cap is now 2,000 (a
  safety stop only) and recorded in each run.

Earlier versions are tagged and committed in git: v1 (10 products, Gemini 3.5 Flash below the
threshold on a two-week task), v3 (batch tracing and allergies), v4 (five tasks), v5 (cold chain).

## Limitations

- **Two models.** 25 runs of DeepSeek V4.1 Flash and 25 of Kimi K3.1 Pro (3 seeds plus 2 repeats on seed 0).
  Earlier versions of the environment were run with Gemini 3.5 Flash with the same pattern,
  but those runs do not replay on the current world.
- **T3 and T4 are model-dependent.** DeepSeek is below the reference in every T3 and T4 run, but
  Kimi passes T4 in all five runs and T3 in three, and beats the reference once on each. The robust
  gap across both models is on T1 and T2; on T5 Kimi passes once and is 0.01 below the threshold
  twice.
- **Same-seed variation.** Repeated runs on one seed vary (DeepSeek T3 0.63-0.94, Kimi T1 0.64-0.95), even at temperature 0; the
  reference is fully deterministic.
- **The reference is not optimal.** It is the strongest script we wrote; T1 events are dense enough
  that it lets 1-4 recalled or damaged units through, and Kimi beats its purchasing on T3 seed 2
  and T4 seed 1. We have not changed the reference after the Kimi runs.
- **Synthetic data.** Demand, prices, par levels, patient mix and the cold-chain table are invented.
- **Stretch goal not done.** Training a smaller model on reference trajectories is the next step.
- **Claude harness** passes its scripted test but has not been run against the live API.

Anchor-policy calibration, the gate checks and the reward-hack catalogue approach follow StoreBench
(arXiv 2610.10942). The domain, world, tasks and code are our own.
