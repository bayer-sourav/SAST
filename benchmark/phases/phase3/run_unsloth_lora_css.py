#!/usr/bin/env python3
"""LoRA SFT with CSS validation checkpoint selection (Phase 3B)."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import unsloth  # noqa: F401 — must import before trl/transformers

from unsloth import FastLanguageModel  # type: ignore[import-not-found]
from datasets import Dataset, load_dataset
from transformers import TrainerCallback
from trl import SFTConfig, SFTTrainer

_sast = Path(__file__).resolve().parents[3]
if str(_sast) not in sys.path:
    sys.path.insert(0, str(_sast))

from benchmark.phases.phase3._phase3b_common import load_manifest, output_path  # noqa: E402
from benchmark.phases.phase3.lora_disk_guard import (  # noqa: E402
    ensure_disk_gb,
    prune_vllm_merged,
)


def _training_checkpoints(adapter: Path) -> list[Path]:
    """HF checkpoint dirs only (exclude ``checkpoint-N-vllm-merged`` export siblings)."""
    import re

    pat = re.compile(r"^checkpoint-\d+$")
    ckpts = [p for p in adapter.glob("checkpoint-*") if pat.match(p.name)]
    return sorted(ckpts, key=lambda p: int(p.name.rsplit("-", 1)[-1]))


def _load_messages_jsonl(path: Path):
    rows = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            rows.append({"messages": obj["messages"]})
    return Dataset.from_list(rows)


class CssEvalCallback(TrainerCallback):
    def __init__(
        self,
        *,
        rank: int,
        val_eval_root: Path,
        registry_path: Path,
        patience: int,
        css_script: Path,
    ) -> None:
        self.rank = rank
        self.val_eval_root = val_eval_root
        self.registry_path = registry_path
        self.patience = patience
        self.css_script = css_script
        self.history: list[dict[str, Any]] = []
        self.best_css = -1.0
        self.stale = 0
        self.deferred_stop = False
        self.early_stopped = False

    def _adapter_for_epoch(self, adapter: Path, state) -> Path:
        """Checkpoint for this epoch — on_epoch_end fires before HF saves, so use global_step."""
        step = int(state.global_step or 0)
        return adapter / f"checkpoint-{step}"

    def on_epoch_end(self, args, state, control, **kwargs):
        epoch = int(state.epoch or 0)
        every = max(1, int(os.environ.get("PHASE3_CSS_EVAL_EVERY", "1")))
        total_epochs = int(getattr(args, "num_train_epochs", 0) or 0)
        is_last = total_epochs > 0 and epoch >= total_epochs
        if not is_last and every > 1 and epoch % every != 0:
            print(f"[css] skip epoch={epoch} (eval every {every} epochs)", flush=True)
            return control
        adapter = Path(args.output_dir)
        adapter_dir = self._adapter_for_epoch(adapter, state)

        defer = os.environ.get("PHASE3_CSS_DEFER", "1").strip().lower() not in ("0", "false", "no")
        if defer:
            pending_path = adapter / "pending_css.json"
            queue: list[dict[str, Any]] = []
            if pending_path.is_file():
                queue = json.loads(pending_path.read_text(encoding="utf-8"))
            step = int(state.global_step or 0)
            key = (epoch, step)
            queue = [
                q
                for q in queue
                if (int(q["epoch"]), int(q.get("step", 0))) != key
            ]
            queue.append(
                {
                    "epoch": epoch,
                    "step": step,
                    "adapter": str(adapter_dir.resolve()),
                }
            )
            pending_path.write_text(json.dumps(queue, indent=2), encoding="utf-8")
            self.deferred_stop = True
            print(
                f"[css] deferred epoch={epoch} adapter=checkpoint-{step} — "
                f"stopping train for external CSS",
                flush=True,
            )
            control.should_training_stop = True
            return control

        out_dir = self.val_eval_root / f"r{self.rank}" / f"epoch-{epoch}"
        ckpt_dirs = _training_checkpoints(adapter)
        adapter_dir = ckpt_dirs[-1] if ckpt_dirs else adapter_dir
        result_path = out_dir / "css_result.json"
        if result_path.is_file():
            print(f"[css] reuse existing result epoch={epoch} -> {result_path}", flush=True)
            result = json.loads(result_path.read_text(encoding="utf-8"))
        else:
            cmd = [
                sys.executable,
                str(self.css_script),
                "--adapter",
                str(adapter_dir),
                "--out-dir",
                str(out_dir),
                "--mode",
                os.environ.get("PHASE3_CSS_VAL_MODE", "fast"),
                "--lora-r",
                str(self.rank),
                "--epoch",
                str(epoch),
            ]
            print(f"[css] epoch={epoch} eval adapter={adapter_dir}", flush=True)
            eval_env = os.environ.copy()
            eval_env.setdefault("QWEN_INFER_BACKEND", "vllm")
            eval_env.pop("SAST_LORA_ADAPTER", None)
            eval_env["TORCHINDUCTOR_FX_GRAPH_REMOTE_CACHE"] = "0"
            eval_env["QWEN_VLLM_GPU_MEMORY_UTILIZATION"] = os.environ.get(
                "PHASE3_CSS_VLLM_GPU_UTIL", "0.82"
            )
            manifest_env = os.environ.get("PHASE3_MANIFEST") or os.environ.get("PHASE3B_MANIFEST")
            if manifest_env:
                eval_env["PHASE3_MANIFEST"] = manifest_env
            eval_env["PYTHONPATH"] = os.pathsep.join(
                [str(_sast), str(_sast / "benchmark"), eval_env.get("PYTHONPATH", "")]
            ).strip(os.pathsep)
            min_disk = float(os.environ.get("PHASE3_MIN_DISK_GB", "25"))
            try:
                ensure_disk_gb(_sast, min_disk, lora_run_dir=adapter)
            except RuntimeError as exc:
                print(f"[css] {exc}", flush=True)
                raise
            freed_gpu = False
            if eval_env.get("QWEN_INFER_BACKEND", "").strip().lower() == "vllm":
                import gc

                import torch

                m = kwargs.get("model")
                if m is not None and torch.cuda.is_available():
                    print("[css] offloading trainer to CPU for vLLM eval", flush=True)
                    m.cpu()
                    torch.cuda.synchronize()
                    torch.cuda.empty_cache()
                    gc.collect()
                    freed_gpu = True
            css_timeout = int(os.environ.get("PHASE3_CSS_TIMEOUT_SEC", "7200"))
            css_ok = False
            try:
                subprocess.run(
                    cmd,
                    cwd=str(_sast),
                    env=eval_env,
                    check=True,
                    start_new_session=True,
                    timeout=css_timeout if css_timeout > 0 else None,
                )
                css_ok = result_path.is_file()
            except subprocess.CalledProcessError as exc:
                print(f"[css] eval subprocess failed epoch={epoch} rc={exc.returncode}", flush=True)
            except subprocess.TimeoutExpired:
                print(f"[css] eval timed out epoch={epoch} after {css_timeout}s", flush=True)
            finally:
                if eval_env.get("QWEN_INFER_BACKEND", "").strip().lower() == "vllm":
                    from models.qwen.vllm_backend import kill_vllm_workers

                    print("[css] releasing vLLM GPU memory", flush=True)
                    kill_vllm_workers()
                    prune_vllm_merged(adapter)
                if freed_gpu:
                    import torch

                    m = kwargs.get("model")
                    if m is not None:
                        print("[css] reloading trainer to GPU", flush=True)
                        m.cuda()
                        torch.cuda.empty_cache()
            if not css_ok:
                print(
                    f"[css] skipping registry/early-stop for epoch={epoch} — training continues",
                    flush=True,
                )
                return control
            result = json.loads(result_path.read_text(encoding="utf-8"))
        css = float(result["css"]["css"])
        self.history.append(result)
        (adapter / "css_history.json").write_text(json.dumps(self.history, indent=2), encoding="utf-8")

        eligible = not result["css"]["disqualified"]
        if eligible:
            reg: list[dict] = []
            if self.registry_path.is_file():
                reg = json.loads(self.registry_path.read_text(encoding="utf-8"))
            reg.append(
                {
                    "adapter": str(adapter_dir.resolve()),
                    "rank": self.rank,
                    "epoch": epoch,
                    "css": css,
                    "metrics": result["metrics"],
                }
            )
            self.registry_path.parent.mkdir(parents=True, exist_ok=True)
            self.registry_path.write_text(json.dumps(reg, indent=2), encoding="utf-8")

        if css > self.best_css + 1e-6:
            self.best_css = css
            self.stale = 0
        else:
            self.stale += 1
        if self.stale >= self.patience:
            print(f"[css] early stop rank={self.rank} patience={self.patience}", flush=True)
            self.early_stopped = True
            control.should_training_stop = True
        return control


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--dataset",
        type=Path,
        default=None,
    )
    ap.add_argument("--out-dir", type=Path, default=None)
    ap.add_argument("--model-id", default=os.environ.get("PHASE3_BASE_MODEL", "unsloth/Qwen3.5-9B"))
    args = ap.parse_args()

    manifest = load_manifest()
    train_cfg = manifest.get("train_prompt") or {}
    enable_thinking = bool(train_cfg.get("thinking", True))
    dataset_path = args.dataset or (output_path(manifest, "sft_data") / "distill_train.jsonl")
    dataset_path = dataset_path.expanduser().resolve()
    if not dataset_path.is_file():
        raise FileNotFoundError(f"missing distill dataset: {dataset_path}")

    rank = int(os.environ.get("PHASE3_LORA_R", "32"))
    lora_alpha = int(os.environ.get("PHASE3_LORA_ALPHA", str(rank)))
    max_seq = int(
        os.environ.get(
            "PHASE3_MAX_SEQ_LEN",
            str(manifest.get("hyperparameters", {}).get("max_seq_len", 16384)),
        )
    )
    epochs = float(os.environ.get("PHASE3_EPOCHS", str(manifest["hyperparameters"]["epochs_max"])))
    lr = float(os.environ.get("PHASE3_LR", str(manifest["hyperparameters"]["learning_rate"])))
    batch_size = int(os.environ.get("PHASE3_BATCH_SIZE", "1"))
    grad_accum = int(os.environ.get("PHASE3_GRAD_ACCUM", "8"))
    packing = os.environ.get("PHASE3_PACKING", "1").lower() in ("1", "true", "yes")
    patience = int(os.environ.get("PHASE3_CSS_EARLY_STOP_PATIENCE", "3"))

    lora_root = args.out_dir or output_path(manifest, "lora")
    run_dir = lora_root.expanduser().resolve() / f"r{rank}"
    run_dir.mkdir(parents=True, exist_ok=True)
    min_disk = float(os.environ.get("PHASE3_MIN_DISK_GB", "25"))
    ensure_disk_gb(_sast, min_disk, lora_run_dir=run_dir)
    prune_vllm_merged(run_dir)
    val_eval_root = output_path(manifest, "val_eval")
    registry_path = output_path(manifest, "css_eligible_registry")

    print(
        f"[train] rank={rank} max_seq={max_seq} thinking={enable_thinking} "
        f"packing={packing} dataset={dataset_path}",
        flush=True,
    )
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
        r=rank,
        target_modules=target_modules,
        lora_alpha=lora_alpha,
        lora_dropout=0,
        bias="none",
        use_gradient_checkpointing="unsloth",
        random_state=3407,
    )

    ds = _load_messages_jsonl(dataset_path)

    def _formatting(examples):
        convos = examples["messages"]
        if convos and isinstance(convos[0], dict):
            convos = [convos]
        return [
            tokenizer.apply_chat_template(
                convo,
                tokenize=False,
                add_generation_prompt=False,
                enable_thinking=enable_thinking,
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
        report_to="none",
        max_length=max_seq,
        packing=packing,
        dataloader_num_workers=int(os.environ.get("PHASE3_DATALOADER_WORKERS", "4")),
    )

    css_cb = CssEvalCallback(
        rank=rank,
        val_eval_root=val_eval_root,
        registry_path=registry_path,
        patience=patience,
        css_script=_sast / "benchmark/phases/phase3/eval_val_for_css.py",
    )

    trainer = SFTTrainer(
        model=model,
        processing_class=tokenizer,
        train_dataset=ds,
        formatting_func=_formatting,
        args=sft_args,
        callbacks=[css_cb],
    )

    resume_ckpt = os.environ.get("PHASE3_RESUME_CHECKPOINT", "").strip()
    if resume_ckpt:
        ckpt_path = Path(resume_ckpt).expanduser().resolve()
        if not ckpt_path.is_dir():
            raise FileNotFoundError(f"PHASE3_RESUME_CHECKPOINT not found: {ckpt_path}")
        print(f"[train] resume from {ckpt_path}", flush=True)
        trainer.train(resume_from_checkpoint=str(ckpt_path))
    else:
        trainer.train()
    if css_cb.deferred_stop:
        print(
            "[train] paused for deferred CSS — not writing train_meta (auto-resume will continue)",
            flush=True,
        )
        return

    target_epochs = int(sft_args.num_train_epochs)
    if int(trainer.state.epoch or 0) < target_epochs and not css_cb.early_stopped:
        print(
            f"[train] stopped early at epoch={trainer.state.epoch} "
            f"(target={target_epochs}) — not marking complete",
            flush=True,
        )
        return

    model.save_pretrained(str(run_dir))
    tokenizer.save_pretrained(str(run_dir))

    meta = {
        "base_model": args.model_id,
        "dataset": str(dataset_path),
        "n_train": len(ds),
        "max_seq_length": max_seq,
        "lora_r": rank,
        "lora_alpha": lora_alpha,
        "epochs": epochs,
        "learning_rate": lr,
        "packing": packing,
        "enable_thinking": enable_thinking,
        "css_history": css_cb.history,
        "adapter_dir": str(run_dir),
        "target_global_step": int(trainer.state.global_step or 0),
        "status": "complete",
        "finished_at": datetime.now(timezone.utc).isoformat(),
    }
    (run_dir / "train_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"[train] saved adapter -> {run_dir}")


if __name__ == "__main__":
    main()
