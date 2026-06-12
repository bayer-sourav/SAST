"""Unsloth FastModel path for Gemma 2 / Gemma 3 IT (text-only chat).

Env: GEMMA_UNSLOTH_USE_CACHE defaults to off (0) to avoid KV-cache CUDA asserts on some stacks;
set GEMMA_UNSLOTH_USE_CACHE=1 when generation is stable. GEMMA_UNSLOTH_DEBUG=1 logs vocab/lengths.
"""

from __future__ import annotations

try:
    import unsloth  # noqa: F401
except (ImportError, AttributeError):
    # AttributeError: torch.int1 vs torch<2.6 when torchao/unsloth mismatch; do not block module import.
    pass

import inspect
import os
from typing import Any

import torch

from core.generation_defaults import agent_decoding_kwargs, cap_max_new_tokens, model_max_seq_len
from core.gpu_info import log_gpu_status

_CACHE: dict[str, tuple[Any, Any]] = {}
_LOADED_4BIT: dict[str, bool] = {}
_GEMMA_CACHE_ENV_WARNED = False


def _warn_wrong_gemma_cache_env_once() -> None:
    global _GEMMA_CACHE_ENV_WARNED
    if _GEMMA_CACHE_ENV_WARNED:
        return
    wrong = os.environ.get("GEMMA_UNSLOTH_CACHE", "").strip()
    right = os.environ.get("GEMMA_UNSLOTH_USE_CACHE", "").strip().lower()
    if wrong and right not in ("1", "true", "yes"):
        print(
            "[Gemma Unsloth] GEMMA_UNSLOTH_CACHE is ignored. "
            "For KV-cache (faster decode when stable): export GEMMA_UNSLOTH_USE_CACHE=1",
            flush=True,
        )
    _GEMMA_CACHE_ENV_WARNED = True


def clear_gemma3_unsloth_cache() -> None:
    global _CACHE, _LOADED_4BIT
    for _k, (model, _tok) in list(_CACHE.items()):
        del model
    _CACHE.clear()
    _LOADED_4BIT.clear()


def _embedding_vocab_size(model: Any) -> int | None:
    """Prefer the actual nn.Embedding row count (quant wrappers may hide it one level down)."""
    emb = model.get_input_embeddings()
    cur: Any = emb
    seen: set[int] = set()
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        ne = getattr(cur, "num_embeddings", None)
        if ne is not None:
            return int(ne)
        nxt = getattr(cur, "base_layer", None) or getattr(cur, "embed_tokens", None)
        if nxt is None or id(nxt) in seen:
            break
        cur = nxt
    cfg = getattr(model, "config", None)
    vs = getattr(cfg, "vocab_size", None) if cfg is not None else None
    return int(vs) if vs is not None else None


def _clamp_input_ids_for_generate(model: Any, batch: dict[str, Any], *, label: str) -> None:
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


def _sanitize_gen_special_token_ids(
    model: Any,
    tok: Any,
    gen_kw: dict[str, Any],
    *,
    label: str,
) -> None:
    """
    Tokenizer eos/pad can exceed FastModel / BnB embedding rows → CUDA index assert in embedding forward.
    Drop or replace out-of-range ids before generate().
    """
    vs = _embedding_vocab_size(model)
    if vs is None or vs <= 0:
        return
    cfg = getattr(model, "config", None)

    def _in_range(x: Any) -> bool:
        try:
            i = int(x)
        except (TypeError, ValueError):
            return False
        return 0 <= i < vs

    def _first_valid(*candidates: Any) -> int | None:
        for c in candidates:
            if c is None:
                continue
            if isinstance(c, (list, tuple)):
                for x in c:
                    if _in_range(x):
                        return int(x)
            elif _in_range(c):
                return int(c)
        return None

    for key in ("eos_token_id", "pad_token_id"):
        if key not in gen_kw:
            continue
        val = gen_kw[key]
        if val is None:
            del gen_kw[key]
            continue
        if isinstance(val, (list, tuple)):
            cleaned = [int(x) for x in val if _in_range(x)]
            if not cleaned:
                fb = _first_valid(
                    getattr(cfg, key, None) if cfg is not None else None,
                    getattr(tok, key, None),
                )
                if fb is not None:
                    gen_kw[key] = fb
                    print(
                        f"[{label}] Replaced invalid {key} list with in-vocab id {fb} "
                        f"(embedding rows={vs})."
                    )
                else:
                    del gen_kw[key]
                    print(
                        f"[{label}] Removed {key} (all candidates out of [0, {vs})); "
                        "using generate() defaults."
                    )
            elif len(cleaned) == 1:
                gen_kw[key] = cleaned[0]
            else:
                gen_kw[key] = cleaned
        elif not _in_range(val):
            fb = _first_valid(
                getattr(cfg, key, None) if cfg is not None else None,
                getattr(tok, key, None),
            )
            if fb is not None:
                print(
                    f"[{label}] Replaced out-of-range {key}={val!r} with {fb} "
                    f"(embedding rows={vs})."
                )
                gen_kw[key] = fb
            else:
                del gen_kw[key]
                print(
                    f"[{label}] Removed out-of-range {key}={val!r}; "
                    f"no in-vocab fallback (embedding rows={vs})."
                )


def _text_tokenizer(tok_or_proc: Any) -> Any:
    inner = getattr(tok_or_proc, "tokenizer", None)
    return inner if inner is not None else tok_or_proc


def _apply_chat_template_kwargs(tok: Any, *, enable_thinking: bool) -> dict[str, Any]:
    """Build apply_chat_template kwargs; pass enable_thinking only when supported (Gemma 4)."""
    kw: dict[str, Any] = {"tokenize": False, "add_generation_prompt": True}
    try:
        params = inspect.signature(tok.apply_chat_template).parameters
    except (TypeError, ValueError):
        return kw
    if "enable_thinking" in params:
        kw["enable_thinking"] = enable_thinking
    return kw


def _maybe_gemma4_chat_template(tok_or_proc: Any, model_name: str) -> Any:
    """Install Unsloth gemma-4 chat template when loading Gemma 4 checkpoints."""
    if "gemma-4" not in model_name.lower():
        return tok_or_proc
    try:
        from unsloth.chat_templates import get_chat_template  # type: ignore[import-not-found]

        t = _text_tokenizer(tok_or_proc)
        updated = get_chat_template(t, chat_template="gemma-4")
        if getattr(tok_or_proc, "tokenizer", None) is not None:
            tok_or_proc.tokenizer = updated
            return tok_or_proc
        return updated
    except Exception as exc:
        print(f"[Gemma Unsloth] gemma-4 chat template setup skipped: {exc!r}", flush=True)
        return tok_or_proc


def _encode_messages(
    tok_or_proc: Any,
    messages: list[dict[str, str]],
    device: torch.device,
    *,
    max_context_tokens: int,
    enable_thinking: bool = False,
) -> dict[str, Any]:
    """
    Match Qwen Unsloth: chat_template → string prompt → tokenizer(..., return_tensors='pt').
    Pass only input_ids + attention_mask into generate (extra tensor keys have triggered index asserts).
    """
    t = _text_tokenizer(tok_or_proc)
    if not hasattr(t, "apply_chat_template"):
        raise RuntimeError(
            "Unsloth Gemma: tokenizer/processor has no apply_chat_template; upgrade transformers/unsloth."
        )
    reserve = int(os.environ.get("GEMMA_UNSLOTH_GEN_RESERVE", "3072"))
    hard_cap = int(os.environ.get("GEMMA_UNSLOTH_MAX_PROMPT_TOKENS", "3072"))
    max_prompt_len = max(min(max_context_tokens - reserve, hard_cap), 256)

    prompt = t.apply_chat_template(
        messages,
        **_apply_chat_template_kwargs(t, enable_thinking=enable_thinking),
    )
    # Same call shape as Qwen runner (truncation keeps long tool catalogs inside a safe window).
    enc = t(prompt, return_tensors="pt", truncation=True, max_length=max_prompt_len)
    inputs_d: dict[str, Any] = {}
    if "input_ids" in enc:
        inputs_d["input_ids"] = enc["input_ids"].to(device)
    if "attention_mask" in enc:
        inputs_d["attention_mask"] = enc["attention_mask"].to(device)
    elif "input_ids" in inputs_d:
        inputs_d["attention_mask"] = torch.ones_like(inputs_d["input_ids"])
    if "input_ids" not in inputs_d:
        raise RuntimeError("Gemma Unsloth: tokenizer returned no input_ids")
    return inputs_d


def _unsloth_env_bnb8(*, use_4bit: bool) -> bool:
    """Bitsandbytes 8-bit load via Unsloth FastModel (only when menu N / not 4-bit)."""
    if use_4bit:
        return False
    return os.environ.get("GEMMA_UNSLOTH_LOAD_8BIT", "").strip().lower() in ("1", "true", "yes")


def _unsloth_cache_slot(
    cache_key: str, *, max_seq_length: int, use_4bit: bool, use_8bit: bool
) -> str:
    if use_4bit:
        q = "bnb4"
    elif use_8bit:
        q = "bnb8"
    else:
        q = "fp"
    return f"{cache_key}:msl{max_seq_length}:{q}"


def _load_fastmodel(
    cache_key: str,
    *,
    model_name: str,
    use_4bit: bool,
    max_seq_length: int,
) -> tuple[Any, Any]:
    use_8bit = _unsloth_env_bnb8(use_4bit=use_4bit)
    slot = _unsloth_cache_slot(
        cache_key, max_seq_length=max_seq_length, use_4bit=use_4bit, use_8bit=use_8bit
    )
    if slot in _CACHE:
        return _CACHE[slot]
    # Drop any other slot for this logical cache_key so VRAM isn't doubled (e.g. after msl default change).
    for k in list(_CACHE.keys()):
        if k.startswith(f"{cache_key}:") and k != slot:
            m, _ = _CACHE.pop(k)
            del m
            _LOADED_4BIT.pop(k, None)

    from unsloth import FastModel  # type: ignore[import-not-found]

    log_gpu_status(
        f"Gemma Unsloth load slot={slot!r} model={model_name!r}"
    )
    fm_kw: dict[str, Any] = {
        "model_name": model_name,
        "max_seq_length": max_seq_length,
        "dtype": None,
        "load_in_4bit": use_4bit,
        "load_in_8bit": use_8bit,
        "trust_remote_code": True,
    }
    if "load_in_16bit" in inspect.signature(FastModel.from_pretrained).parameters:
        # fp16/bf16 path only when neither 4- nor 8-bit BnB.
        fm_kw["load_in_16bit"] = not use_4bit and not use_8bit
    model, tokenizer = FastModel.from_pretrained(**fm_kw)
    tokenizer = _maybe_gemma4_chat_template(tokenizer, model_name)
    model.eval()
    _CACHE[slot] = (model, tokenizer)
    _LOADED_4BIT[slot] = use_4bit or use_8bit
    print(
        f"[Gemma Unsloth] Loaded {model_name!r} load_in_4bit={use_4bit} load_in_8bit={use_8bit} "
        f"max_seq_length={max_seq_length}"
    )
    return model, tokenizer


def gemma3_unsloth_generate_from_messages(
    *,
    cache_key: str,
    model_name: str,
    messages: list[dict[str, str]],
    use_4bit: bool,
    max_seq_length: int | None = None,
    enable_thinking: bool = False,
) -> str:
    _warn_wrong_gemma_cache_env_once()
    msl = max_seq_length
    if msl is None:
        # Tighter default reduces FastModel internal canvas mismatches that show up as CUDA index asserts.
        msl = int(os.environ.get("GEMMA_UNSLOTH_MAX_SEQ_LEN", "32768"))
    model, tok_or_proc = _load_fastmodel(
        cache_key,
        model_name=model_name,
        use_4bit=use_4bit,
        max_seq_length=msl,
    )
    device = next(model.parameters()).device
    cfg = getattr(model, "config", None)
    mpe = getattr(cfg, "max_position_embeddings", None) if cfg is not None else None
    # Do not let prompt+gen planning exceed the checkpoint's position table (avoids RoPE/index asserts).
    ctx_cap = min(msl, int(mpe)) if mpe is not None else msl
    inputs = _encode_messages(
        tok_or_proc,
        messages,
        device,
        max_context_tokens=ctx_cap,
        enable_thinking=enable_thinking,
    )
    input_len = int(inputs["input_ids"].shape[1])
    gen_kw = cap_max_new_tokens(
        agent_decoding_kwargs(enable_thinking=enable_thinking),
        input_token_len=input_len,
        max_seq_len=ctx_cap,
    )
    t = _text_tokenizer(tok_or_proc)
    if getattr(t, "pad_token_id", None) is not None:
        gen_kw.setdefault("pad_token_id", t.pad_token_id)
    if getattr(t, "eos_token_id", None) is not None:
        gen_kw.setdefault("eos_token_id", t.eos_token_id)
    _sanitize_gen_special_token_ids(model, t, gen_kw, label="Gemma Unsloth")

    def _prune(batch: dict[str, Any]) -> dict[str, Any]:
        out_d: dict[str, Any] = {}
        for k in list(batch.keys()):
            v = batch[k]
            if v is None:
                continue
            if hasattr(v, "numel") and v.numel() == 0 and k in (
                "pixel_values",
                "image_grid_thw",
                "attention_mask_image",
            ):
                continue
            out_d[k] = v
        return out_d

    gen_in = _prune(inputs)
    # Qwen-style: only these keys reach model.generate (same as causal LM Unsloth path).
    gen_in = {k: gen_in[k] for k in ("input_ids", "attention_mask") if k in gen_in}
    _clamp_input_ids_for_generate(model, gen_in, label="Gemma Unsloth")

    input_len_pre = int(gen_in["input_ids"].shape[1])
    margin = int(os.environ.get("GEMMA_UNSLOTH_GEN_MARGIN", "48"))
    room = ctx_cap - input_len_pre - margin
    mnt = int(gen_kw.get("max_new_tokens", 1024))
    if room > 0 and mnt > room:
        gen_kw["max_new_tokens"] = max(16, room)

    # Default off: FastModel + Gemma + bnb on some torch/CUDA stacks hits device-side asserts in KV paths.
    # Set GEMMA_UNSLOTH_USE_CACHE=1 to re-enable (faster when stable).
    if os.environ.get("GEMMA_UNSLOTH_USE_CACHE", "0").strip().lower() not in (
        "1",
        "true",
        "yes",
    ):
        gen_kw["use_cache"] = False

    if os.environ.get("GEMMA_UNSLOTH_DEBUG", "").strip().lower() in ("1", "true", "yes"):
        ii = gen_in["input_ids"]
        mx = int(ii.max().item()) if ii.numel() else -1
        vs = _embedding_vocab_size(model)
        tvs = getattr(t, "vocab_size", None)
        print(
            f"[Gemma Unsloth debug] ctx_cap={ctx_cap} input_len={input_len_pre} "
            f"max_new_tokens={gen_kw.get('max_new_tokens')} max_input_id={mx} "
            f"embed_vocab={vs} tokenizer.vocab_size={tvs} "
            f"use_cache={gen_kw.get('use_cache', True)} eos={gen_kw.get('eos_token_id', '—')} "
            f"pad={gen_kw.get('pad_token_id', '—')}"
        )

    # Do not wrap generate() in torch.compiler.disable(): on PyTorch 2.10+ that nests badly with
    # Unsloth FastModel's own dynamo usage → "torch._dynamo.optimize(...) is used with a context manager".
    with torch.inference_mode():
        gen_out = model.generate(**gen_in, **gen_kw)
    if isinstance(gen_out, torch.Tensor):
        seq = gen_out
    else:
        seq = getattr(gen_out, "sequences", None)
        if seq is None:
            raise RuntimeError(
                f"Gemma Unsloth: unexpected generate() return {type(gen_out)!r}; expected Tensor or .sequences"
            )
    if seq.dim() != 2:
        raise RuntimeError(f"Gemma Unsloth: expected rank-2 sequences, got shape {tuple(seq.shape)}")

    input_ids = gen_in["input_ids"]
    input_len = int(input_ids.shape[1])
    new_tokens = seq[0][input_len:]
    from core.gen_meta import set_gen_meta
    set_gen_meta(input_len, int(new_tokens.shape[0]))
    return t.decode(new_tokens, skip_special_tokens=True).strip()
