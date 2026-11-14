# Post-training a small model on the reference pharmacist

Behaviour cloning: a 4B instruct model is fine-tuned (LoRA) on transcripts of the
reference pharmacist, then run through the same harness and tasks as the frontier models.

## Data

`make_sft_data.py` runs the reference policy (`careful_pharmacist`) on training seeds and
records every tool call it makes, one transcript per shift, in exactly the format the
harness sends in handover mode (system prompt, shift-start message with the previous
note, then assistant tool call / tool result pairs, ending with `end_shift`).

- Seeds 5-24 for all five tasks: 1,720 shift transcripts, 15.5 M tokens, 1.16 M of them
  assistant tokens (the only ones with loss).
- Evaluation seeds 0-4 are refused by the script, so no evaluation episode is in training.
- The reference keeps its state in Python variables. A model in handover mode only has the
  note, so the note written at `end_shift` is built from what that shift saw and did
  (notices received, withdrawals, orders, approvals) plus the previous note's list of
  notices. Nothing in the note comes from hidden simulator state.

```bash
python3 -m training.make_sft_data --seeds 5-24 --out training/data/sft.jsonl
```

## Training

`train_sft.py`: LoRA rank 32 on all attention and MLP projections, learning rate 1e-4,
one epoch, gradient accumulation 8, sequences up to 16k tokens, loss on assistant turns
only. Base model: Qwen3-4B-Instruct-2507. One H100 80GB (Verda, spot instance), about
40 minutes.

```bash
python3 -m training.train_sft --model Qwen3-4B-Instruct-2507 --data training/data/sft.jsonl --out ckpt/
```

## Evaluation

The base and fine-tuned models were served with vLLM (OpenAI-compatible, Hermes tool-call
parser) and run with `pharmacy_env.run_agent --memory handover --max-steps 1000` on
T1-T5, seeds 0-2. Their trajectories are in `results/trajectories/` and are replayed and
scored by `python3 -m pharmacy_env.eval` like every other run.
