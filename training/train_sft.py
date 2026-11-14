"""LoRA fine-tune of a small instruct model on reference-pharmacist shift transcripts.

    python3 -m training.train_sft --model /root/models/qwen3-4b --data training/data/sft.jsonl \
        --out /root/ckpt/qwen3-4b-pharm

Loss is computed on assistant turns only (the tool calls and the handover note); the
system prompt, shift-start message and tool results are context. Needs torch, transformers
and peft (see training/README.md); run on a GPU machine.
"""
import argparse
import json
import random

import torch
from peft import LoraConfig, get_peft_model
from transformers import AutoModelForCausalLM, AutoTokenizer


def encode(tok, row, max_len):
    """Token ids and labels with everything except assistant turns masked (-100)."""
    msgs, tools = row["messages"], row["tools"]
    ids, labels, prev = [], [], 0
    for i, m in enumerate(msgs):
        if m["role"] != "assistant":
            continue
        before = tok.apply_chat_template(msgs[:i], tools=tools, tokenize=True, add_generation_prompt=True)
        upto = tok.apply_chat_template(msgs[:i + 1], tools=tools, tokenize=True)
        if not isinstance(before, list):
            before, upto = before["input_ids"], upto["input_ids"]
        assert upto[:len(before)] == before, "chat template is not prefix-stable"
        ids += before[prev:] + upto[len(before):]
        labels += [-100] * (len(before) - prev) + upto[len(before):]
        prev = len(upto)
    return ids[:max_len], labels[:max_len]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--data", default="training/data/sft.jsonl")
    ap.add_argument("--out", required=True)
    ap.add_argument("--epochs", type=float, default=1.0)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--rank", type=int, default=32)
    ap.add_argument("--max-len", type=int, default=16384)
    ap.add_argument("--grad-accum", type=int, default=8)
    a = ap.parse_args()

    torch.manual_seed(0)
    random.seed(0)
    tok = AutoTokenizer.from_pretrained(a.model)
    rows = [json.loads(l) for l in open(a.data)]
    data = [encode(tok, r, a.max_len) for r in rows]
    n_tok = sum(len(i) for i, _ in data)
    n_lab = sum(sum(1 for x in l if x != -100) for _, l in data)
    print("%d transcripts, %.1f M tokens, %.2f M trained tokens, max %d" % (
        len(data), n_tok / 1e6, n_lab / 1e6, max(len(i) for i, _ in data)), flush=True)

    model = AutoModelForCausalLM.from_pretrained(a.model, torch_dtype=torch.bfloat16,
                                                 attn_implementation="sdpa").cuda()
    model.gradient_checkpointing_enable()
    model.enable_input_require_grads()
    model = get_peft_model(model, LoraConfig(
        r=a.rank, lora_alpha=2 * a.rank, lora_dropout=0.0, task_type="CAUSAL_LM",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]))
    model.print_trainable_parameters()
    opt = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=a.lr, weight_decay=0.0)

    steps = int(len(data) * a.epochs)
    sched = torch.optim.lr_scheduler.LambdaLR(
        opt, lambda s: min(1.0, (s + 1) / 10) * max(0.0, 1 - s / max(1, steps // a.grad_accum)))
    order = []
    while len(order) < steps:
        perm = list(range(len(data)))
        random.shuffle(perm)
        order += perm
    model.train()
    run = 0.0
    for step, idx in enumerate(order[:steps]):
        ids, lab = data[idx]
        out = model(input_ids=torch.tensor([ids]).cuda(), labels=torch.tensor([lab]).cuda())
        (out.loss / a.grad_accum).backward()
        run = 0.98 * run + 0.02 * out.loss.item() if step else out.loss.item()
        if (step + 1) % a.grad_accum == 0:
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            sched.step()
            opt.zero_grad()
        if step % 50 == 0:
            print("step %d/%d loss %.4f" % (step, steps, run), flush=True)
    model.save_pretrained(a.out)
    tok.save_pretrained(a.out)
    print("saved", a.out, flush=True)


if __name__ == "__main__":
    main()
