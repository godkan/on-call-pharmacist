# Junction platform submission - text to paste

## Project Name (max 30)

On-Call Pharmacist

## Punchline (max 200)

A hospital pharmacy where frontier agents let recalled and damaged vials reach patients: more than a scripted pharmacist in all 34 incident runs; 59/60 DeepSeek runs score below it.

## Challenge

Break the Agent (AfterQuery)

## Description (max 5000, markdown)

**On-Call Pharmacist** is a reinforcement learning environment in which an agent is the on-duty pharmacist of a fictional hospital. 30 medicines are tracked by batch across a central store, seven ward cabinets and a night cupboard. Cabinets record quantities but not batch numbers, so recalled batches must be traced through the issue log. Patients keep receiving their medicines whatever the agent does, and some are allergic to the only remaining alternative. The agent uses 22 hospital-system functions (issue log, cabinet inspection, quarantine, temperature and batch records, patient lists, substitution, three supply channels) with 120 minutes of desk time per shift, seeing only the previous shift's handover note.

**Five tasks, one hospital:** T1 safety incidents (two recalls, a ward fridge excursion that one near-limit batch fails, a central freeze some products tolerate), T2 antibiotic shortage with penicillin-allergic patients, T3 influenza and septic-shock surges within a fixed budget, T4 genuine and reserve requests from nurse managers during an allocation, T5 a two-week rota combining them with an advance allocation notice.

**Why this setting.** High-stakes work agents are barely tested on, where every outcome is checkable: was a recalled or damaged vial given, did an allergic patient get a contraindicated drug, did a ward run out.

**Reward.** Computed from the simulation, never by a judge model. Score is normalised per seed: doing nothing = 0, reference pharmacist = 1.

**Calibration.** Scripted anchors use the same functions, time and information as the agent: reference, reactive pharmacist, SOP checklist, central-store-only, do-nothing, stop-early, and exploit probes (withdraw everything, discard all refrigerated stock, approve a restricted drug ward-wide, grant every request, hoard). Pass threshold = midpoint of the reference and the best other honest anchor. All calibration gates (ordering, judgment gap, threshold margin, exploit suppression, stop-early below threshold) pass on every seed of every task.

**Result.** DeepSeek V4.1 Flash on all 5 seeds of every task: with reasoning off (35 runs) **below the reference in 35/35, below the pass threshold in 32/35**; with reasoning effort high (25 runs) below the reference in 24/25 and the threshold in 19/25. Patient safety without normalisation: in all 34 runs of the incident tasks T1 and T5, every model and setting let more recalled or temperature-damaged units reach patients than the reference on the same seed (4-89 per run against 1-14). Kimi K3.1 Pro (25 runs, stronger comparison model) fails T1 and T2 in every run but solves the supply-planning tasks T3 and T4 in 8 of 10. **Hint ablation:** two sentences of advice cut on-site inspections and recalled units given, leave cold-chain damage exactly unchanged, and no hinted run passes. **Post-training (bonus):** Qwen3-4B LoRA-tuned on reference transcripts (training seeds only) rises from 0.12 to 0.78 mean score but still lets recalled and damaged units through in every T1 and T5 run. All 121 trajectories replay to the exact recorded score; CI re-checks on every push.

**Failure modes:**
1. *Investigates before it withdraws.* The issue log already shows where a recalled batch went; the model inspects cabinets one by one, runs out of desk time and defers the quarantine (reasoning off: 10-89 recalled units given per T1/T5 run; reference 0-10). One handover note opens "URGENT - CLASS II RECALL NOT YET ACTIONED (ran out of desk time)".
2. *Does not follow a failed batch after it has moved.* After a freeze, handover restocking had already sent frozen insulin to the wards; the model withdraws only what is left in the fridge, even when told to trace it.
3. *Under-supplies a confirmed need:* too little for genuine T4 surges and T2 patients; with reasoning on it approves the restricted alternative ward-wide and penicillin-allergic patients receive it.
4. *Plans unevenly for announced shortages*, ordering ahead heavily in some runs and barely in others.

What it gets right: it ignores distractor mail and finds the cheaper supply channels in T3, the one task it passes with reasoning off (3 of 7 runs).

**Reproduce (no API key, standard library only):** `python3 -m pharmacy_env.eval` re-runs all anchors and gates, replays every trajectory and prints the summary and failure modes.

**Credits.** Anchor calibration, gates and the reward-hack catalogue follow StoreBench (arXiv 2610.10942); domain, world, tasks and code are ours. Model runs used Verda's inference API.

## Links still needed

- Source Code: https://github.com/godkan/on-call-pharmacist
- Video: optional demo recording
- Presentation: optional slides

## Tech challenges

The model runs used Verda's inference API, which fits the "Verda Compute Track" tech challenge (prizes are cloud credits). If entered, say so in the description: "All 91 frontier-model runs used Verda's OpenAI-compatible inference API (DeepSeek V4.1 Flash and Kimi K3.1 Pro), and the Qwen3-4B LoRA fine-tune ran on a Verda H100."
