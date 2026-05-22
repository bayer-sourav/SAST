"""Hugging Face Gemma 3 / Gemma 3n (multimodal checkpoints, text-only chat here)."""

from __future__ import annotations

import contextlib
import os
from pathlib import Path
from typing import Any, NoReturn

import torch

from core.generation_defaults import agent_decoding_kwargs, cap_max_new_tokens, model_max_seq_len
from core.gpu_info import log_gpu_status

_CACHE: dict[str, tuple[Any, Any]] = {}


def clear_gemma3_hf_cache() -> None:
    global _CACHE
    for _k, (model, _proc) in list(_CACHE.items()):
        del model
    _CACHE.clear()


def _dtype():
    if torch.cuda.is_available():
        return torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
    return torch.float32


def _default_offload_folder() -> str:
    base = os.environ.get("HF_OFFLOAD_FOLDER")
    if base:
        return os.path.expanduser(base)
    return str(Path.cwd() / ".hf_offload")


def _tokenizer_from_processor(processor: Any) -> Any:
    tok = getattr(processor, "tokenizer", None)
    return tok if tok is not None else processor


def _embedding_vocab_size(model: Any) -> int | None:
    emb = model.get_input_embeddings()
    if emb is not None and hasattr(emb, "num_embeddings"):
        return int(emb.num_embeddings)
    cfg = getattr(model, "config", None)
    vs = getattr(cfg, "vocab_size", None) if cfg is not None else None
    return int(vs) if vs is not None else None


def _clamp_input_ids_for_generate(model: Any, batch: dict[str, Any], *, label: str) -> None:
    """Chat-template / tokenizer mismatches can yield ids >= embedding rows → CUDA index assert."""
    ii = batch.get("input_ids")
    if ii is None or not isinstance(ii, torch.Tensor):
        return
    vs = _embedding_vocab_size(model)
    if vs is None or vs <= 0:
        return
    bad = (ii < 0) | (ii >= vs)
    if bad.any():
        print(
            f"[{label}] {int(bad.sum().item())} token id(s) outside [0, {vs}); "
            "clamping to avoid CUDA embedding index asserts (quality may suffer)."
        )
        batch["input_ids"] = torch.clamp(ii, 0, vs - 1)


def _transformers_gemma3():
    """Defer import; Transformers may pull torchao (needs torch.int1) or break on torch 2.6 (_pytree)."""
    try:
        from transformers import AutoModelForImageTextToText, AutoProcessor, BitsAndBytesConfig
    except Exception as exc:
        blob = _aggregate_exception_text(exc)
        if "int1" in blob or "torchao" in blob or "register_constant" in blob:
            raise RuntimeError(
                "Could not import Hugging Face Transformers for Gemma (torchao vs torch mismatch is common). "
                "Fix one of:  (1) pip uninstall -y torchao  (2) upgrade PyTorch to a version that provides "
                "torch.int1 if you need torchao. Then restart Python."
            ) from exc
        raise
    return AutoModelForImageTextToText, AutoProcessor, BitsAndBytesConfig


def _aggregate_exception_text(exc: BaseException) -> str:
    parts: list[str] = []
    seen: set[int] = set()
    e: BaseException | None = exc
    while e is not None and id(e) not in seen:
        seen.add(id(e))
        parts.append(str(e))
        e = e.__cause__ or e.__context__
    return " ".join(parts).lower()


def _reraise_gemma3_hub_or_deps(model_id: str, exc: BaseException) -> NoReturn:
    """Turn common HF / vision dependency failures into actionable RuntimeErrors."""
    raw = str(exc)
    msg = _aggregate_exception_text(exc)
    if "429" in raw or "too many requests" in msg:
        raise RuntimeError(
            f"Hugging Face rate-limited requests for {model_id!r} (HTTP 429). Wait and retry, set HF_TOKEN "
            "or `huggingface-cli login`, and avoid many parallel Hub downloads."
        ) from exc
    if "401" in raw or "gated" in msg or "restricted" in msg or "cannot access" in msg:
        base = f"Cannot access Hugging Face repo {model_id!r} (gated or not logged in). "
        if model_id.startswith("google/"):
            raise RuntimeError(
                base
                + "Use `huggingface-cli login` (token with read access), accept the Gemma license on the "
                "model card, then retry. If you only need 3n E4B, try Unsloth first (menu uses Unsloth when "
                "installed) — Unsloth Hub repos are often not Google-gated the same way."
            ) from exc
        raise RuntimeError(
            base
            + "Use `huggingface-cli login` with a token that can read this repo, or set GEMMA_3_12B_MODEL_ID "
            "to another checkpoint."
        ) from exc
    if "timm" in msg or "timmwrapper" in msg.replace(" ", ""):
        raise RuntimeError(
            "Gemma 3 / 3n checkpoints use a vision tower that requires `timm`. "
            "Install: pip install timm  (restart the Python process after installing)."
        ) from exc
    if "torchvision" in msg and "pytorch" in msg and "cuda" in msg:
        raise RuntimeError(
            "PyTorch and torchvision were built for different CUDA versions. Reinstall matching "
            "wheels from the same PyTorch index (https://pytorch.org/get-started/locally/), then "
            "restart Python."
        ) from exc
    raise exc


def get_gemma3_model_and_processor(
    model_id: str,
    *,
    cache_key: str,
    use_4bit: bool = False,
) -> tuple[Any, Any]:
    use_bnb = use_4bit and torch.cuda.is_available()
    slot_suffix = "bnb4" if use_bnb else "fp"
    safe_id = model_id.replace("/", "__").replace(":", "_")
    slot = f"{cache_key}:{safe_id}:{slot_suffix}"
    if slot in _CACHE:
        return _CACHE[slot]

    AutoModelForImageTextToText, AutoProcessor, BitsAndBytesConfig = _transformers_gemma3()

    log_gpu_status(f"loading Gemma3 HF model_id={model_id!r} cache={slot!r}")
    if model_id.startswith("google/"):
        print(
            "[Gemma3] google/gemma-* checkpoints are gated — run `huggingface-cli login` and accept "
            "the license on the model page if download fails. Multimodal weights also need: pip install timm"
        )
    else:
        print("[Gemma3] Loading from Hugging Face Hub (if vision stack errors: pip install timm).")

    try:
        processor = AutoProcessor.from_pretrained(model_id, trust_remote_code=True)
    except Exception as exc:
        _reraise_gemma3_hub_or_deps(model_id, exc)
    device_map = os.environ.get("HF_DEVICE_MAP", "auto")
    if not torch.cuda.is_available():
        dm_env = str(device_map).strip().lower()
        if dm_env in ("auto", "cuda", "cuda:0", ""):
            device_map = "cpu"
            print(
                "[HF-Gemma3] CUDA unavailable: device_map='cpu'. "
                "Update driver / torch for GPU or set HF_DEVICE_MAP."
            )

    load_kw: dict[str, Any] = {
        "trust_remote_code": True,
        "device_map": device_map,
        "low_cpu_mem_usage": True,
    }

    if use_bnb:
        print("[HF-Gemma3] Using bitsandbytes 4-bit (NF4) load.")
        bnb_kw: dict[str, Any] = {
            "load_in_4bit": True,
            "bnb_4bit_compute_dtype": _dtype(),
            "bnb_4bit_use_double_quant": True,
            "bnb_4bit_quant_type": "nf4",
        }
        allow_cpu = os.environ.get("HF_BNB_ALLOW_CPU_OFFLOAD", "1").lower() not in (
            "0",
            "false",
            "no",
        )
        quant_cfg: Any
        if allow_cpu:
            # Transformers 5.x may forward kwargs; inspect.signature often omits fields → always try explicit kw.
            try:
                quant_cfg = BitsAndBytesConfig(
                    **bnb_kw,
                    llm_int8_enable_fp32_cpu_offload=True,
                )
                print(
                    "[HF-Gemma3] llm_int8_enable_fp32_cpu_offload=True "
                    "(BnB layers on CPU/disk need this with device_map=auto on ~24GB GPUs)."
                )
            except TypeError:
                quant_cfg = BitsAndBytesConfig(**bnb_kw)
        else:
            quant_cfg = BitsAndBytesConfig(**bnb_kw)
        load_kw["quantization_config"] = quant_cfg
    else:
        load_kw["dtype"] = _dtype()

    dm = str(device_map).strip().lower()
    if dm == "auto":
        offload = _default_offload_folder()
        Path(offload).mkdir(parents=True, exist_ok=True)
        load_kw["offload_folder"] = offload

    hf_attn = os.environ.get("HF_ATTN_IMPLEMENTATION", "").strip()
    if hf_attn and hf_attn.lower() not in ("auto", "default", "none", ""):
        load_kw["attn_implementation"] = hf_attn
    elif not torch.cuda.is_available():
        load_kw["attn_implementation"] = "eager"
    elif "gemma" in model_id.lower() and os.environ.get("GEMMA_HF_USE_SDPA", "0").lower() not in (
        "1",
        "true",
        "yes",
    ):
        # SDPA/flash paths have been a common source of flaky CUDA errors with Gemma3 + bnb on some stacks.
        load_kw["attn_implementation"] = "eager"

    used_bnb = use_bnb
    try:
        try:
            model = AutoModelForImageTextToText.from_pretrained(model_id, **load_kw)
        except TypeError as exc:
            msg = str(exc).lower()
            if not used_bnb and "dtype" in load_kw and "unexpected keyword" in msg:
                load_kw.pop("dtype", None)
                load_kw["torch_dtype"] = _dtype()
                model = AutoModelForImageTextToText.from_pretrained(model_id, **load_kw)
            elif "attn_implementation" in load_kw and "unexpected" in msg:
                load_kw.pop("attn_implementation", None)
                model = AutoModelForImageTextToText.from_pretrained(model_id, **load_kw)
            else:
                raise
    except Exception as exc:
        _reraise_gemma3_hub_or_deps(model_id, exc)
    model.eval()
    _CACHE[slot] = (model, processor)
    print(f"[HF-Gemma3] Model loaded into cache slot {slot!r}.")
    return model, processor


def gemma3_generate_from_messages(
    model_id: str,
    *,
    cache_key: str,
    messages: list[dict[str, str]],
    use_4bit: bool = False,
) -> str:
    """
    Text-only tool routing: use the same pattern as Qwen (chat template → string prompt → tokenizer),
    not processor.apply_chat_template(tokenize=True), which returns BatchFeature blobs that break
    generate() on some Transformers 5.x + Gemma3 multimodal builds.
    """
    model, processor = get_gemma3_model_and_processor(
        model_id, cache_key=cache_key, use_4bit=use_4bit
    )
    tok = _tokenizer_from_processor(processor)
    if not hasattr(tok, "apply_chat_template"):
        raise RuntimeError("Gemma tokenizer has no apply_chat_template; upgrade transformers.")

    cfg = getattr(model, "config", None)
    mpe = getattr(cfg, "max_position_embeddings", None) if cfg is not None else None
    max_in_env = int(os.environ.get("GEMMA_HF_MAX_INPUT_TOKENS", "8192"))
    max_in = min(max_in_env, int(mpe)) if mpe is not None else max_in_env
    reserve = int(os.environ.get("GEMMA_HF_GEN_RESERVE", "2048"))
    max_prompt_len = max(max_in - reserve, 512)

    prompt = tok.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=True,
    )
    enc = tok(
        prompt,
        return_tensors="pt",
        truncation=True,
        max_length=max_prompt_len,
    )
    device = next(model.parameters()).device
    gen_in = {
        k: v.to(device)
        for k, v in dict(enc).items()
        if isinstance(v, torch.Tensor) and k in ("input_ids", "attention_mask")
    }
    if "input_ids" not in gen_in:
        raise RuntimeError("HF-Gemma3: tokenizer produced no input_ids")
    if "attention_mask" not in gen_in:
        gen_in["attention_mask"] = torch.ones_like(gen_in["input_ids"])

    input_len_pre = int(gen_in["input_ids"].shape[1])
    mpe2 = getattr(cfg, "max_position_embeddings", None) if cfg is not None else None
    ctx_cap = min(model_max_seq_len(), int(mpe2)) if mpe2 is not None else model_max_seq_len()
    gen_kw = cap_max_new_tokens(
        agent_decoding_kwargs(),
        input_token_len=input_len_pre,
        max_seq_len=ctx_cap,
    )
    _clamp_input_ids_for_generate(model, gen_in, label="HF-Gemma3")

    # Transformers 5.x may compile forwards; Dynamo + Gemma3 + bnb can raise InternalTorchDynamoError
    # wrapping a CUDA assert. Disable compile for this call unless opted in.
    #
    # Use @torch.compiler.disable as a decorator, not `with torch.compiler.disable():` — on torch 2.5
    # the context-manager form can raise: "torch.dynamo.optimize(...) is used with a context manager"
    # when nested with Transformers / checkpoint dynamo (see pytorch#123771).
    allow_tc = os.environ.get("GEMMA_HF_ALLOW_TORCH_COMPILE", "0").lower() in ("1", "true", "yes")

    with torch.inference_mode():
        if not allow_tc:
            try:
                _disable = torch.compiler.disable  # type: ignore[attr-defined]
            except Exception:
                gen_out = model.generate(**gen_in, **gen_kw)
            else:

                @_disable(recursive=True)  # type: ignore[misc]
                def _gemma3_hf_generate() -> Any:
                    return model.generate(**gen_in, **gen_kw)

                gen_out = _gemma3_hf_generate()
        else:
            gen_out = model.generate(**gen_in, **gen_kw)
    if isinstance(gen_out, torch.Tensor):
        seq = gen_out
    else:
        seq = getattr(gen_out, "sequences", None)
        if seq is None:
            raise RuntimeError(
                f"HF-Gemma3: unexpected generate() return {type(gen_out)!r}; expected Tensor or .sequences"
            )
    if seq.dim() != 2:
        raise RuntimeError(f"HF-Gemma3: expected rank-2 sequences, got shape {tuple(seq.shape)}")

    input_ids = gen_in["input_ids"]
    input_len = int(input_ids.shape[1])
    new_tokens = seq[0][input_len:]
    from core.gen_meta import set_gen_meta
    set_gen_meta(input_len, int(new_tokens.shape[0]))
    return tok.decode(new_tokens, skip_special_tokens=True).strip()
