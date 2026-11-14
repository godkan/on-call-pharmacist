# Junction platform submission - text to paste

## Project Name (max 30)

On-Call Pharmacist

## Punchline (max 200)

A hospital pharmacy where frontier agents let recalled and damaged vials reach patients: in all 26 incident runs, more than a scripted pharmacist; 40/40 DeepSeek runs score below it.

## Challenge

Break the Agent (AfterQuery)

## Description (max 5000, markdown)

**On-Call Pharmacist** is a reinforcement learning environment in which an agent works as the on-duty pharmacist of a fictional regional hospital. 30 medicines in 9 classes are tracked by batch across a central store, seven ward and theatre cabinets and an out-of-hours cupboard. Cabinets record quantities but not batch numbers, so recalled batches must be traced through the issue log. Patients keep receiving their medicines whatever the agent does, and some are allergic to the only remaining alternative. The agent uses 22 hospital-system functions (issue log, cabinet inspection, quarantine, temperature logs, batch records, patient lists, per-patient substitution, urgent courier, second wholesaler, loans from a neighbouring hospital) under 120 minutes of desk time per shift, and each shift sees only the previous shift's handover note.

**Five tasks in one hospital:** T1 safety incidents (two recalls, a ward fridge excursion that one near-limit batch fails, a central freeze some products tolerate), T2 antibiotic shortage with penicillin-allergic patients, T3 influenza and septic-shock surges within a fixed budget, T4 genuine and reserve requests from nurse managers during an allocation, T5 a two-week rota combining them with an advance allocation notice.

**Why this setting.** Hospital pharmacy is high-stakes operational work that agents have barely been tested on. Every outcome is checkable: was a recalled or temperature-damaged vial given, did an allergic patient get a contraindicated drug, did a ward run out of a critical medicine.

**Reward.** Computed from the simulation, never judged. Score is normalised per seed: doing nothing = 0, reference pharmacist = 1.

**Calibration.** Scripted anchors use the same functions, time and information as the agent: reference, reactive pharmacist (repairs shortages after they happen), SOP checklist, central-store-only, do-nothing, stop-early, and per-task exploit probes (withdraw everything, discard all refrigerated stock, approve the restricted alternative ward-wide, grant every request, hoard every critical medicine). Pass threshold = midpoint of the reference and the best other honest anchor. The calibration gates (ordering, judgment gap, threshold margin, exploit suppression, stopping early below the threshold) pass on every seed of every task.

**Result.** DeepSeek V4.1 Flash, 40 runs (5 tasks x 3 seeds plus 2 repeats of seed 0 with reasoning off; 5 tasks x 3 seeds with reasoning effort high): **below the reference in 40/40, below the pass threshold in 35/40.** Kimi K3.1 Pro (25 runs, a stronger comparison model) is below the threshold in all 10 runs of T1 and T2 and 4 of 5 of T5, but solves the supply-planning tasks T3 and T4 in 8 of 10 runs. Patient safety without normalisation: in all 26 runs of the incident tasks T1 and T5, every model let more recalled or temperature-damaged units reach patients than the reference on the same seed (4-89 per run against 1-6). Every trajectory replays to the exact recorded score.

**Failure modes:**
1. *Investigates before it withdraws.* The issue log already shows where a recalled batch went; the model inspects cabinets one by one, runs out of desk time and defers the quarantine. Recalled units reached patients in every T1 and T5 run with reasoning off (10-89 per run; reference 0-6). One handover note opens "URGENT - CLASS II RECALL NOT YET ACTIONED (ran out of desk time)".
2. *Does not follow a failed batch after it has moved.* After a freeze, handover restocking had already sent frozen insulin to the wards; the model withdraws only what is left in the fridge.
3. *Under-supplies a confirmed need.* It refuses every reserve request in T4 but sends too little to wards in a genuine surge; in T2 patients still go without antibiotics, and in one run two doses reached penicillin-allergic patients.
4. *Plans unevenly for announced shortages.* It sometimes orders ahead of an announced allocation and sometimes barely at all.

What it gets right: it never withdraws usable stock, ignores distractor mail, and finds the cheaper supply channels in T3, which is why T3 is the one task where it passes the threshold in some runs.

All information needed to do better is available through the functions; the reference uses only that.

**Reproduce (no API key, standard library only):** `python3 -m pharmacy_env.eval` re-runs all anchors, checks the gates, replays every trajectory and prints a per-task summary and the failure modes.

**Credits.** Anchor calibration, gate checks and the reward-hack catalogue approach follow StoreBench (arXiv 2610.10942). Domain, world, tasks and code are ours. Model runs used Verda's inference API.

## Links still needed

- Source Code: GitHub repository URL
- Video: optional demo recording
- Presentation: optional slides

## Tech challenges

The model runs used Verda's inference API, which fits the "Verda Compute Track" tech challenge (prizes are cloud credits). If entered, say so in the description: "All 65 agent runs used Verda's OpenAI-compatible inference API (DeepSeek V4.1 Flash and Kimi K3.1 Pro)."
