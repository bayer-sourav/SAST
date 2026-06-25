#!/usr/bin/env python3
"""Merge Unsloth/PEFT LoRA into BF16 weights for vLLM (no runtime LoRA adapter)."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

_sast = Path(__file__).resolve().parents[3]
if str(_sast) not in sys.path:
    sys.path.insert(0, str(_sast))


def _adapter_signature(adapter_dir: Path) -> dict:
    cfg = adapter_dir / "adapter_config.json"
    weights = adapter_dir / "adapter_model.safetensors"
    out: dict[str, object] = {"adapter": str(adapter_dir.resolve())}
    if cfg.is_file():
        out["adapter_config_mtime"] = int(cfg.stat().st_mtime)
    if weights.is_file():
        out["adapter_weights_mtime"] = int(weights.stat().st_mtime)
        out["adapter_weights_bytes"] = int(weights.stat().st_size)
    return out


def merged_out_dir(adapter_dir: Path) -> Path:
    return adapter_dir.parent / f"{adapter_dir.name}-vllm-merged"


def ensure_vllm_merged_adapter(
    adapter_dir: Path,
    *,
    base_model_id: str | None = None,
    force: bool = False,
) -> Path:
    """Merge LoRA into base weights once; cache under ``{checkpoint}-vllm-merged/``."""
    adapter_dir = adapter_dir.expanduser().resolve()
    if not adapter_dir.is_dir():
        raise FileNotFoundError(f"adapter not found: {adapter_dir}")

    base = (base_model_id or os.environ.get("QWEN_VLLM_MERGE_BASE", "Qwen/Qwen3.5-9B")).strip()
    out_dir = merged_out_dir(adapter_dir)
    meta_path = out_dir / "vllm_export.json"
    sig = _adapter_signature(adapter_dir)

    if not force and meta_path.is_file():
        try:
            prev = json.loads(meta_path.read_text(encoding="utf-8"))
            if prev.get("signature") == sig and (out_dir / "config.json").is_file():
                print(f"[vllm-export] cache hit {out_dir}", file=sys.stderr, flush=True)
                return out_dir
        except Exception:
            pass

    print(
        f"[vllm-export] merging adapter={adapter_dir.name} base={base!r} -> {out_dir}",
        file=sys.stderr,
        flush=True,
    )
    t0 = time.perf_counter()

    import torch
    from peft import PeftModel
    from transformers import AutoConfig, AutoModelForCausalLM, AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(base, trust_remote_code=True)
    base_model = AutoModelForCausalLM.from_pretrained(
        base,
        torch_dtype=torch.bfloat16,
        device_map="cpu",
        trust_remote_code=True,
        low_cpu_mem_usage=True,
    )
    model = PeftModel.from_pretrained(base_model, str(adapter_dir), is_trainable=False)
    merged = model.merge_and_unload()

    out_dir.mkdir(parents=True, exist_ok=True)
    merged.save_pretrained(str(out_dir), safe_serialization=True)
    tokenizer.save_pretrained(str(out_dir))

    # vLLM renderer expects full Qwen3_5Config (with vision_config), not flat text-only.
    flat_cfg = json.loads((out_dir / "config.json").read_text(encoding="utf-8"))
    hub_cfg = AutoConfig.from_pretrained(base, trust_remote_code=True).to_dict()
    text_cfg = {k: v for k, v in flat_cfg.items() if k != "architectures"}
    full_cfg = dict(hub_cfg)
    full_cfg["text_config"] = text_cfg
    full_cfg["architectures"] = ["Qwen3_5ForCausalLM"]
    full_cfg["model_type"] = "qwen3_5"
    (out_dir / "config.json").write_text(json.dumps(full_cfg, indent=2), encoding="utf-8")

    meta = {
        "signature": sig,
        "base_model": base,
        "adapter": str(adapter_dir),
        "merged_dir": str(out_dir),
        "elapsed_sec": round(time.perf_counter() - t0, 1),
    }
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"[vllm-export] done in {meta['elapsed_sec']}s -> {out_dir}", file=sys.stderr, flush=True)
    return out_dir


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--adapter", type=Path, required=True)
    ap.add_argument("--base-model", default=None)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    out = ensure_vllm_merged_adapter(
        args.adapter,
        base_model_id=args.base_model,
        force=args.force,
    )
    print(out)


if __name__ == "__main__":
    main()
