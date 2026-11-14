# Junction platform submission - text to paste

## Project Name (max 30)

On-Call Pharmacist

## Punchline (max 200)

A two-week hospital pharmacy rota where a frontier agent lets recalled vials reach patients because it investigates before it acts, and reads the flu warning without ordering ahead.

## Challenge

Break the Agent (AfterQuery)

## Description (max 5000, markdown)

**On-Call Pharmacist** is a reinforcement learning environment in which an agent works a two-week rota (28 shifts) as the on-duty pharmacist of a fictional regional hospital. Medicines are tracked by batch across a central store and five ward cabinets, but cabinets record only products and quantities: to find a recalled batch the agent must read the central issue log or inspect cabinets on site. 65 patients receive ceftriaxone, some with penicillin allergies, and one formulary alternative is contraindicated for them. The agent acts through 15 hospital-system functions under 120 minutes of desk time per shift, and each shift sees only the previous shift's handover note.

**Why this setting.** Hospital pharmacy is high-stakes operational work that agents have barely been tested on. It needs tracing from records, exact procedure-following, patient-level constraints, and turning early warnings into action before the consequence arrives. Every outcome is checkable: was a recalled vial given to a patient, did an allergic patient get a contraindicated drug, did a ward run out of a critical medicine.

**Reward.** Computed from the simulation, never judged: recalled units given after the notice, contraindicated doses, units a ward could not issue (critical drugs and ICU/ED weighted), good stock wrongly withdrawn, urgent-order surcharge, unattended shifts. Score is normalised per seed: doing nothing = 0, reference pharmacist = 1.

**Calibration.** Six scripted anchors use the same functions, time and information as the agent (reference, SOP checklist, stop-early, central-store-only, do-nothing, and an exploit probe that withdraws every batch). The pass threshold is the midpoint of the two best honest anchors. Four gates pass on every seed: ordering, judgment gap, threshold margin, exploit suppression.

**Result.** Gemini 3.5 Flash scores **0.79 / 0.70 / 0.73** on three seeds against thresholds of 0.89 / 0.86 / 0.90 (reference 1.00), at or below the rule-following anchor. Every trajectory replays to the exact recorded score.

**Failure modes:**
1. *Investigates before it withdraws.* When a recall arrives the issue log already shows where the batch went, and a quarantine takes 10 minutes. The model inspects cabinets one by one (15 minutes each), runs out of desk time and defers the quarantine; recalled units reach patients in every run (5, 12, 26; reference 0-3). In one run its handover note lists every location to quarantine "IMMEDIATELY IN SHIFT 4", written at the end of the shift in which it could have done it.
2. *Reads the early warning, does not act.* It records the influenza memo but does not order ahead; ICU and Medical run out of piperacillin/tazobactam (58-121 units). Urgent orders over 28 shifts: 2-5.
3. *Slow response to a confirmed shortage.* Ceftriaxone alternatives approved 7-13 shifts after the allocation notice in two of three runs.
4. *Desk time spent re-establishing context* after each handover (40-49 policy re-reads per run).

What it gets right: no allergic patient ever receives a contraindicated drug, it ignores a distractor recall, and it withdraws no good stock. On a recall-only control task with batches visible everywhere it matches the reference, which shows the gap comes from prioritisation and planning, not from tool use.

All information needed to do better is available through the functions; the reference uses only that.

**Reproduce (no API key, ~5 s):** `python3 -m pharmacy_env.eval` re-runs all anchors, checks the gates, replays every recorded trajectory and prints the failure modes. Standard library only.

**Credits.** Anchor calibration, gate checks and the reward-hack catalogue approach follow StoreBench (arXiv 2610.10942). Domain, world, tasks and code are ours.

## Links still needed

- Source Code: GitHub repository URL (not created yet)
- Video: optional demo recording
- Presentation: optional slides

## Tech challenges

None claimed by default. We used the Gemini API only as the agent under test; if the team wants to enter "Best Use of Gemini API", the description must explain how Gemini is used.
