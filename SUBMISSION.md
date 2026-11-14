# Junction platform submission - text to paste

## Project Name (max 30)

On-Call Pharmacist

## Punchline (max 200)

A two-week hospital pharmacy rota where frontier agents handle every drug recall correctly, yet read the flu warning and the shortage notice and still let wards run out of critical antibiotics.

## Challenge

Break the Agent (AfterQuery)

## Description (max 5000, markdown)

**On-Call Pharmacist** is a reinforcement learning environment in which an agent works a two-week rota (28 shifts) as the on-duty pharmacist of a fictional regional hospital. Medicines are tracked by batch across a central store and five ward cabinets; wards keep using medicines whatever the agent does. The agent acts through 12 hospital-system functions (find a batch, quarantine it, transfer stock, approve a formulary alternative, place an urgent order, hand over with a note) under 120 minutes of desk time per shift.

**Why this setting.** Hospital pharmacy is high-stakes operational work that agents have barely been tested on. It needs tracing across locations, exact procedure-following, and turning early warnings into action before the consequence arrives. Every outcome is checkable: was a recalled vial given to a patient, did a ward run out of a critical drug.

**Reward.** Computed from the simulation, never judged: recalled units given after the notice, units a ward could not issue (critical drugs weighted, ICU/ED weighted higher), good stock wrongly withdrawn, urgent-order surcharge, and unattended shifts. Score is normalised per seed: doing nothing = 0, reference pharmacist = 1.

**Calibration.** Six scripted anchors use the same functions, time and information as the agent (reference, SOP checklist, stop-early, central-store-only, do-nothing, and an exploit probe that withdraws every batch). The pass threshold is the midpoint of the two best honest anchors. Four gates pass on every seed: ordering, judgment gap, threshold margin, exploit suppression (the exploit scores below doing nothing).

**Result.** Gemini 3.5 Flash scores **0.65 / 0.65 / 0.74** on three seeds against thresholds of 0.82 / 0.82 / 0.86 (reference 1.00). Every trajectory replays to the exact recorded score.

**Failure modes (same in all three runs):**
1. *Reads the early warning, does not act.* It records the Infection Control memo in its handover note ("increased demand for PIP-45 and PCM-IV expected") but orders nothing; standing orders are sized for normal use, so ICU and Medical wards run out of piperacillin/tazobactam from shift 20 (87-114 units). Urgent orders over 28 shifts: 0, 0, 1.
2. *Slow response to a confirmed shortage.* The ceftriaxone allocation notice arrives at shift 7-8 and names alternatives; approvals come at shifts 14-16, and wards run out from shift 17.
3. *Desk time spent re-establishing context* after each handover (23-51 policy re-reads, 133-152 inventory lookups per run), which pushes urgent actions past the end of the shift.

What it gets right: every recall is handled the shift it arrives, no recalled unit reaches a patient, and it ignores a distractor recall for a product the hospital does not stock. A shorter recall-only control task (T1) is solved perfectly, which shows the gap comes from planning ahead under limited memory, not from tool use.

All information needed to do better is available through the functions; the reference uses only that.

**Reproduce (no API key, ~5 s):** `python3 -m pharmacy_env.eval` re-runs all anchors, checks the gates, replays every recorded trajectory and prints the failure modes. Standard library only.

**Credits.** Anchor calibration, gate checks and the reward-hack catalogue approach follow StoreBench (arXiv 2610.10942). Domain, world, tasks and code are ours.

## Links still needed

- Source Code: GitHub repository URL (not created yet)
- Video: optional demo recording
- Presentation: optional slides

## Tech challenges

None claimed by default. We used the Gemini API only as the agent under test; if the team wants to enter "Best Use of Gemini API", the description must explain how Gemini is used.
