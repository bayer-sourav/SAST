"""OpenAI gpt-oss-20b: Unsloth first, then Hugging Face Transformers (4-bit optional)."""

from __future__ import annotations

import gc
import os
from typing import Any

import torch
from langchain_core.tools import BaseTool

from core.generation_defaults import agent_decoding_kwargs
from core.gpu_info import log_gpu_status
from core.hf_backend import hf_generate_from_messages
from core.parsing import parse_tool_selection
from core.prompts import tool_selection_chat_messages

_DEFAULT_MODEL = "openai/gpt-oss-20b"


def _warn_if_missing_kernels_for_gpt_oss(model_id: str) -> None:
    """Hub MXFP4 needs PyPI `kernels`; otherwise HF dequantizes to bf16 and ~22GB GPUs OOM or mis-compile."""
    if "gpt-oss" not in model_id.lower():
        return
    try:
        import kernels  # type: ignore[import-not-found]  # noqa: F401
    except ImportError:
        print(
            "\n[ERROR] Missing package `kernels` — openai/gpt-oss-20b will NOT stay in MXFP4.\n"
            "        Transformers then dequantizes to bf16 (~40GB+ VRAM) → OOM / hangs / Dynamo errors on A10G.\n"
            "        Fix:  pip install 'kernels>=0.12.0'\n"
            "        Then: rm -rf unsloth_compiled_cache  (in project dir) and retry.\n"
        )


_US_MODEL: Any = None
_US_TOKENIZER: Any = None
_US_4BIT: bool | None = None
_US_MODEL_ID: str | None = None


def unload_gpt_oss_unsloth() -> None:
    global _US_MODEL, _US_TOKENIZER, _US_4BIT, _US_MODEL_ID
    _US_MODEL = None
    _US_TOKENIZER = None
    _US_4BIT = None
    _US_MODEL_ID = None


def _hf_cache_key(model_id: str) -> str:
    safe = model_id.replace("/", "__").replace("-", "_")[:80]
    return f"gpt_oss_hf:{safe}"


def _load_unsloth_gpt_oss(*, use_4bit: bool) -> tuple[Any, Any]:
    global _US_MODEL, _US_TOKENIZER, _US_4BIT, _US_MODEL_ID
    model_id = os.environ.get("GPT_OSS_MODEL_ID", _DEFAULT_MODEL)
    if (
        _US_MODEL is not None
        and _US_4BIT == use_4bit
        and _US_MODEL_ID == model_id
    ):
        assert _US_TOKENIZER is not None
        return _US_MODEL, _US_TOKENIZER
    if _US_MODEL is not None:
        unload_gpt_oss_unsloth()

    # Unsloth's compiled gpt-oss attention can hit Torch Dynamo errors on some stacks; small VRAM
    # setups also benefit from disabling compile for stability.
    if torch.cuda.is_available():
        total_v = torch.cuda.get_device_properties(0).total_memory
        if total_v < 28 * (1024**3):
            os.environ.setdefault("TORCH_COMPILE_DISABLE", "1")
            try:
                # Do not `import torch._dynamo` here — it binds `torch` as a local for this
                # function and breaks earlier `torch.cuda` uses (UnboundLocalError).
                from torch import _dynamo

                _dynamo.config.disable = True
            except Exception:
                pass
            print(
                "[GPT-OSS] Torch Dynamo disabled (low VRAM): avoids Unsloth compiled attention errors. "
                "If you still see Dynamo errors, remove stale graphs: rm -rf unsloth_compiled_cache"
            )

    from unsloth import FastLanguageModel  # type: ignore[import-not-found]
    _warn_if_missing_kernels_for_gpt_oss(model_id)

    log_gpu_status("GPT-OSS Unsloth")
    if torch.cuda.is_available():
        total = torch.cuda.get_device_properties(0).total_memory
        if total < 28 * (1024**3):
            print(
                "[WARN] openai/gpt-oss-20b: MXFP4 weight conversion on GPU often needs **>24GB VRAM**. "
                "A10G frequently CUDA-OOMs in Transformers mxfp4 swizzle. Options: "
                "**GPT_OSS_CPU_LOAD=1** (CPU load + slow inference), **40GB+ GPU**, or use **Qwen (1)** / **Gemma 3 12B (2)**.\n"
            )
    max_seq = int(os.environ.get("GPT_OSS_MAX_SEQ_LEN", "4096"))
    extra_kw: dict[str, Any] = {}
    if "gpt-oss" in model_id.lower():
        attn = os.environ.get("GPT_OSS_ATTN_IMPLEMENTATION", "eager").strip()
        if attn.lower() not in ("", "auto", "default", "none"):
            extra_kw["attn_implementation"] = attn
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=model_id,
        max_seq_length=max_seq,
        dtype=None,
        load_in_4bit=use_4bit,
        **extra_kw,
    )
    FastLanguageModel.for_inference(model)
    _US_MODEL, _US_TOKENIZER = model, tokenizer
    _US_4BIT = use_4bit
    _US_MODEL_ID = model_id
    print(f"[GPT-OSS] Unsloth loaded model={model_id!r} load_in_4bit={use_4bit}")
    return model, tokenizer


def _generate_unsloth(messages: list[dict[str, str]], *, use_4bit: bool) -> str:
    model, tokenizer = _load_unsloth_gpt_oss(use_4bit=use_4bit)
    prompt = tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=True,
    )
    device = next(model.parameters()).device
    print(f"[GPU] GPT-OSS generate: first param device={device}")
    inputs = tokenizer(prompt, return_tensors="pt").to(device)
    gen_kwargs = agent_decoding_kwargs()
    # Default was use_cache=False to dodge rare attention shape bugs; that makes each decode step
    # recompute the full prompt (O(seq²) per token) — with ~3k tool-catalog tokens × 1024 new
    # tokens it can look “stuck” for tens of minutes. Eager attention + KV cache is the stable default.
    if os.environ.get("GPT_OSS_USE_KV_CACHE", "1").lower() in ("0", "false", "no"):
        gen_kwargs["use_cache"] = False
    n_in = int(inputs["input_ids"].shape[1])
    mnt = gen_kwargs.get("max_new_tokens", "?")
    print(
        f"[GPT-OSS] generate: prompt_tokens≈{n_in}, max_new_tokens={mnt} "
        "(first forward may take ~30–120s on A10G; not frozen).",
        flush=True,
    )
    with torch.inference_mode():
        out = model.generate(**inputs, **gen_kwargs)
    input_len = inputs["input_ids"].shape[1]
    new_tokens = out[0][input_len:]
    return tokenizer.decode(new_tokens, skip_special_tokens=True).strip()


def generate_tool_selection_raw(
    user_message: str,
    tools: list[BaseTool],
    *,
    use_4bit: bool = True,
) -> str:
    model_id = os.environ.get("GPT_OSS_MODEL_ID", _DEFAULT_MODEL)
    messages = tool_selection_chat_messages(tools, user_message)
    try:
        return _generate_unsloth(messages, use_4bit=use_4bit)
    except ImportError:
        print("[GPT-OSS] unsloth not installed; using Hugging Face Transformers.")
    except Exception as exc:  # noqa: BLE001
        print(f"[GPT-OSS] Unsloth load/generate failed ({exc}); using Hugging Face Transformers.")
    unload_gpt_oss_unsloth()
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.synchronize()
    if torch.cuda.is_available():
        tot = torch.cuda.get_device_properties(0).total_memory
        if tot < 28 * (1024**3) and os.environ.get("GPT_OSS_CPU_LOAD", "").lower() not in (
            "1",
            "true",
            "yes",
        ):
            print(
                "[GPT-OSS] If HF MXFP4 load CUDA-OOMs, retry with: export GPT_OSS_CPU_LOAD=1 "
                "(needs enough system RAM; very slow)."
            )
    return hf_generate_from_messages(
        model_id,
        cache_key=_hf_cache_key(model_id),
        messages=messages,
        use_4bit=use_4bit,
    )


def run_tool_selection(
    user_message: str,
    tools: list[BaseTool],
    *,
    use_4bit: bool = True,
) -> dict:
    raw = generate_tool_selection_raw(user_message, tools, use_4bit=use_4bit)
    return parse_tool_selection(raw).model_dump()
