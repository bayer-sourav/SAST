#!/usr/bin/env python3
"""LoRA SFT on Qwen3.5-9B with Unsloth (Phase 3A)."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Unsloth must import before trl/transformers
import unsloth  # noqa: F401

from unsloth import FastLanguageModel  # type: ignore[import-not-found]
from datasets import load_dataset
from trl import SFTConfig, SFTTrainer

_sast = Path(__file__).resolve().parents[3]
if str(_sast) not in sys.path:
    sys.path.insert(0, str(_sast))


def _load_messages_jsonl(path: Path):
    rows = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            rows.append({"messages": obj["messages"]})
    from datasets import Dataset

    return Dataset.from_list(rows)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--dataset",
        type=Path,
        default=_sast / "runs/phase3/stage3a/data/sft_train.jsonl",
    )
    ap.add_argument(
        "--out-dir",
        type=Path,
        default=_sast / "runs/phase3/stage3a/lora",
    )
    ap.add_argument("--model-id", default=os.environ.get("PHASE3_BASE_MODEL", "unsloth/Qwen3.5-9B"))
    args = ap.parse_args()

    dataset_path = args.dataset.expanduser().resolve()
    if not dataset_path.is_file():
        raise FileNotFoundError(f"missing SFT dataset: {dataset_path}")

    max_seq = int(os.environ.get("PHASE3_MAX_SEQ_LEN", "16384"))
    lora_r = int(os.environ.get("PHASE3_LORA_R", "16"))
    lora_alpha = int(os.environ.get("PHASE3_LORA_ALPHA", str(lora_r)))
    epochs = float(os.environ.get("PHASE3_EPOCHS", "1"))
    lr = float(os.environ.get("PHASE3_LR", "2e-4"))
    batch_size = int(os.environ.get("PHASE3_BATCH_SIZE", "1"))
    grad_accum = int(os.environ.get("PHASE3_GRAD_ACCUM", "8"))
    max_steps = int(os.environ.get("PHASE3_MAX_STEPS", "-1"))

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    run_dir = args.out_dir.expanduser().resolve() / stamp
    run_dir.mkdir(parents=True, exist_ok=True)
    latest = args.out_dir.expanduser().resolve() / "latest"
    if latest.is_symlink() or latest.exists():
        if latest.is_symlink():
            latest.unlink()
        elif latest.is_dir():
            pass  # leave existing dir; overwrite symlink below if possible
    try:
        latest.symlink_to(run_dir.name, target_is_directory=True)
    except OSError:
        pass

    print(f"[train] loading base model {args.model_id!r} max_seq={max_seq}", flush=True)
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=args.model_id,
        max_seq_length=max_seq,
        dtype=None,
        load_in_4bit=True,
    )

    target_modules = [
        "q_proj",
        "k_proj",
        "v_proj",
        "o_proj",
        "gate_proj",
        "up_proj",
        "down_proj",
    ]
    model = FastLanguageModel.get_peft_model(
        model,
        r=lora_r,
        target_modules=target_modules,
        lora_alpha=lora_alpha,
        lora_dropout=0,
        bias="none",
        use_gradient_checkpointing="unsloth",
        random_state=3407,
    )

    ds = _load_messages_jsonl(dataset_path)
    print(f"[train] dataset n={len(ds)} from {dataset_path}", flush=True)

    def _formatting(examples):
        convos = examples["messages"]
        if convos and isinstance(convos[0], dict):
            convos = [convos]
        return [
            tokenizer.apply_chat_template(
                convo,
                tokenize=False,
                add_generation_prompt=False,
                enable_thinking=False,
            )
            for convo in convos
        ]

    sft_args = SFTConfig(
        output_dir=str(run_dir),
        per_device_train_batch_size=batch_size,
        gradient_accumulation_steps=grad_accum,
        num_train_epochs=epochs,
        learning_rate=lr,
        logging_steps=10,
        save_strategy="epoch",
        bf16=True,
        max_steps=max_steps if max_steps > 0 else -1,
        report_to="none",
        max_length=max_seq,
        packing=False,
    )

    trainer = SFTTrainer(
        model=model,
        processing_class=tokenizer,
        train_dataset=ds,
        formatting_func=_formatting,
        args=sft_args,
    )

    trainer.train()
    model.save_pretrained(str(run_dir))
    tokenizer.save_pretrained(str(run_dir))

    meta = {
        "base_model": args.model_id,
        "dataset": str(dataset_path),
        "n_train": len(ds),
        "max_seq_length": max_seq,
        "lora_r": lora_r,
        "lora_alpha": lora_alpha,
        "epochs": epochs,
        "learning_rate": lr,
        "batch_size": batch_size,
        "grad_accum": grad_accum,
        "adapter_dir": str(run_dir),
    }
    (run_dir / "train_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"[train] saved adapter -> {run_dir}")
    print(f"[train] latest -> {latest}")


if __name__ == "__main__":
    main()
