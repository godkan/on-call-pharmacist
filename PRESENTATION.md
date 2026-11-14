# Demo video (2 minutes) and slides (5 pages)

All numbers are from `results/eval_output.txt` and the README.

## Video script (English, about 270 words, 2 minutes)

Record the screen: the README on GitHub, then a terminal, then one trajectory file.

**0:00-0:20 - The setting** (show the README title and the first paragraph)
> On-Call Pharmacist is a reinforcement learning environment where an agent runs the medicines
> service of a hospital for up to two weeks. Thirty medicines tracked by batch, nine storage
> locations, patients with allergies, and an inbox of recalls, fridge alarms, shortages and ward
> requests. The agent works through 22 hospital-system functions, with limited desk time per shift
> and only a handover note between shifts.

**0:20-0:50 - The result** (show the figure and the summary table)
> We compare frontier models with a scripted reference pharmacist that uses exactly the same
> functions and information. Across all five seeds, DeepSeek V4.1 Flash scores below the reference
> in 59 of its 60 runs, with or without reasoning. And the failures are about patient safety: in
> all 34 runs of the two incident tasks, every model let more recalled or temperature-damaged vials
> reach patients than the reference did.

**0:50-1:20 - Why it fails** (open `results/trajectories/T5_seed0_deepseek-4-1-flash_handover_run2.jsonl`, search for "NOT YET ACTIONED")
> The issue log already shows where a recalled batch went. The model instead inspects cabinets one
> by one, runs out of desk time, and hands the recall over to the next shift - this note starts
> "URGENT - CLASS II RECALL NOT YET ACTIONED". By then the wards have used the batch.
> When we add two sentences pointing at the issue log, on-site inspections drop by up to
> 80% and recalled units reaching patients fall in five of six runs - the information
> was there; the judgment was missing. But the frozen insulin that had moved to the wards still
> reached exactly as many patients, and no hinted run passes.

**1:20-1:45 - The reward is honest** (terminal: `python3 -m pharmacy_env.eval`, show OVERALL: OK)
> The reward is computed from the simulation, never judged by a model. One command re-runs every
> anchor, checks the calibration gates, tries seven shortcuts - withdraw everything, hoard, grant
> every request - and replays every model run to its exact recorded score. It runs on every push.

**1:45-2:00 - Learnable** (show the post-training table)
> Fine-tuning a 4B model on reference transcripts lifts it from 0.12 to 0.78 - the environment
> teaches - but it still lets recalled vials through. That is the gap we built this to measure.

## Slides

1. **On-Call Pharmacist** - a hospital medicines-safety environment where frontier agents let
   recalled vials reach patients. Team, challenge (Break the Agent, AfterQuery).
2. **The world** - one hospital: 30 medicines, batch tracking, 9 locations, patients with
   allergies, 22 functions, desk time, handover notes. Five tasks: incidents, shortage and
   allergies, epidemic and budget, ward requests, two-week rota.
3. **The gap** - the figure `results/scores.svg` and the summary table; the patient-safety line
   (recalled or damaged units reaching patients, model vs reference).
4. **Why it fails** - three failure modes with one quote each: investigates before it withdraws;
   does not follow damaged stock that has moved; under-supplies a confirmed need. Hint ablation:
   a two-sentence hint cuts inspections and recalled units given, leaves cold-chain damage
   unchanged, and no hinted run passes.
5. **Reward integrity and learnability** - simulated reward, anchors and gates, seven shortcut
   probes and their scores, replay of every run, CI on every push; 4B fine-tune 0.12 -> 0.78.
