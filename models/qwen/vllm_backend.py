"""vLLM inference backend for Qwen profiles (set QWEN_INFER_BACKEND=vllm)."""

from __future__ import annotations

import os
from typing import Any

_VLLM_BY_PROFILE: dict[str, Any] = {}
_ACTIVE_PROFILE: str | None = None

# Full-precision HF ids for vLLM (avoid bnb-4bit checkpoints).
_VLLM_MODEL_DEFAULTS: dict[str, str] = {
    "qwen3_5_9b_bnb": "Qwen/Qwen3.5-9B",
    "qwen3_5_4b_bnb": "Qwen/Qwen3.5-4B",
    "qwen3_8b_bnb": "Qwen/Qwen3-8B",
    "qwen3_14b_bnb": "Qwen/Qwen3-14B",
    "qwen3_4b_bnb": "Qwen/Qwen3-4B-Instruct-2507",
    "2_5_7b": "Qwen/Qwen2.5-7B-Instruct",
    "qwen3_8_27b_nvfp4": "unsloth/Qwen3.8-27B-NVFP4",
}

NVFP4_PROFILES = frozenset({"qwen3_8_27b_nvfp4"})


def infer_backend() -> str:
    """unsloth (default) or vllm."""
    return os.environ.get("QWEN_INFER_BACKEND", "unsloth").strip().lower()


def gpu_supports_nvfp4() -> bool:
    """NVFP4 kernels need Blackwell (compute capability >= 10.0)."""
    try:
        import torch

        if not torch.cuda.is_available():
            return False
        major, _minor = torch.cuda.get_device_capability(0)
        return major >= 10
    except Exception:
        return False


def _is_nvfp4_model(model_id: str) -> bool:
    return "nvfp4" in model_id.lower()


def should_use_vllm(profile: str) -> bool:
    if profile in ("qwen3_coder_30b_bnb", "qwen3_next_80b_bnb"):
        return False
    if infer_backend() not in ("vllm", "1", "true", "yes"):
        return False
    # Gate on the resolved checkpoint, not the profile name: an NVFP4 build needs
    # Blackwell, but the same profile pointed at FP8/INT4 runs fine on Ada.
    if _is_nvfp4_model(_vllm_model_id(profile)) and not gpu_supports_nvfp4():
        return False
    return True


def _vllm_model_id(profile: str) -> str:
    env_profile = os.environ.get(f"QWEN_{profile.upper()}_VLLM_MODEL_ID", "").strip()
    if env_profile:
        return env_profile
    if profile in _VLLM_MODEL_DEFAULTS:
        return _VLLM_MODEL_DEFAULTS[profile]
    env_global = os.environ.get("QWEN_VLLM_MODEL_ID", "").strip()
    if env_global:
        return env_global
    raise ValueError(
        f"No vLLM model id for profile {profile!r}; set QWEN_VLLM_MODEL_ID or "
        f"QWEN_{profile.upper()}_VLLM_MODEL_ID"
    )


def _eos_stop_ids() -> list[int]:
    ids: list[int] = []
    for key in ("QWEN_VLLM_STOP_TOKEN_IDS", "QWEN_EXTRA_EOS_TOKEN_IDS"):
        raw = os.environ.get(key, "").strip()
        if not raw and key == "QWEN_EXTRA_EOS_TOKEN_IDS":
            raw = "248044"
        for part in raw.split(","):
            part = part.strip()
            if part.isdigit():
                tid = int(part)
                if tid not in ids:
                    ids.append(tid)
    # Qwen3.5 im_end
    if 248046 not in ids:
        ids.insert(0, 248046)
    return ids


def _lora_request():
    if os.environ.get("QWEN_VLLM_USE_LORA", "").strip().lower() not in ("1", "true", "yes"):
        return None
    raw = os.environ.get("QWEN_VLLM_LORA_PATH", "").strip() or os.environ.get(
        "SAST_LORA_ADAPTER", ""
    ).strip()
    if not raw:
        return None
    from pathlib import Path

    from vllm.lora.request import LoRARequest

    path = str(Path(raw).expanduser().resolve())
    name = os.environ.get("QWEN_VLLM_LORA_NAME", "sast_lora")
    return LoRARequest(name, 1, path)


def unload_vllm() -> None:
    global _VLLM_BY_PROFILE, _ACTIVE_PROFILE
    for llm in _VLLM_BY_PROFILE.values():
        try:
            del llm
        except Exception:
            pass
    _VLLM_BY_PROFILE.clear()
    _ACTIVE_PROFILE = None
    try:
        import gc

        import torch

        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass


def kill_vllm_workers() -> None:
    """Best-effort cleanup of vLLM engine subprocesses (CSS eval handoff)."""
    import subprocess
    import time

    unload_vllm()
    subprocess.run(["pkill", "-f", "VLLM::EngineCore"], check=False)
    try:
        import torch

        if torch.cuda.is_available():
            for _ in range(5):
                torch.cuda.synchronize()
                torch.cuda.empty_cache()
                free_gb = torch.cuda.mem_get_info()[0] / (1024**3)
                if free_gb > 35:
                    break
                time.sleep(2)
    except Exception:
        pass


def preload_vllm_profile(profile: str) -> None:
    _get_vllm(profile)
    print(f"[preload] vLLM ready for {profile!r} model={_vllm_model_id(profile)!r}", flush=True)


def _get_vllm(profile: str) -> Any:
    global _ACTIVE_PROFILE
    if _ACTIVE_PROFILE is not None and _ACTIVE_PROFILE != profile:
        unload_vllm()
    _ACTIVE_PROFILE = profile
    if profile in _VLLM_BY_PROFILE:
        return _VLLM_BY_PROFILE[profile]

    from vllm import LLM

    model_id = _vllm_model_id(profile)
    max_len = int(os.environ.get("QWEN_VLLM_MAX_MODEL_LEN", os.environ.get("QWEN_MAX_SEQ_LEN", "16384")))
    gpu_util = float(os.environ.get("QWEN_VLLM_GPU_MEMORY_UTILIZATION", "0.90"))
    dtype_default = "auto" if profile in NVFP4_PROFILES else "bfloat16"
    dtype = os.environ.get("QWEN_VLLM_DTYPE", dtype_default)

    llm_kw: dict[str, Any] = {
        "model": model_id,
        "dtype": dtype,
        "max_model_len": max_len,
        "gpu_memory_utilization": gpu_util,
        "trust_remote_code": True,
    }
    kv_dtype = os.environ.get("QWEN_VLLM_KV_CACHE_DTYPE", "").strip()
    if not kv_dtype and profile in NVFP4_PROFILES:
        kv_dtype = "fp8"
    if kv_dtype:
        llm_kw["kv_cache_dtype"] = kv_dtype
    lora_path = os.environ.get("QWEN_VLLM_LORA_PATH", "").strip() or os.environ.get(
        "SAST_LORA_ADAPTER", ""
    ).strip()
    use_lora = os.environ.get("QWEN_VLLM_USE_LORA", "").strip().lower() in ("1", "true", "yes")
    # Unsloth/PEFT checkpoints break vLLM LoRA on Qwen3.5 (set_lora IndexError). Opt-in only.
    if lora_path and use_lora:
        llm_kw["enable_lora"] = True
        llm_kw["max_lora_rank"] = int(os.environ.get("QWEN_VLLM_MAX_LORA_RANK", "64"))

    tok_id = _vllm_tokenizer_id(model_id, profile)
    if tok_id:
        llm_kw["tokenizer"] = tok_id
    if _vllm_language_model_only(model_id):
        llm_kw["language_model_only"] = True

    if os.environ.get("QWEN_VLLM_ENFORCE_EAGER", "").strip().lower() in ("1", "true", "yes"):
        llm_kw["enforce_eager"] = True

    prefix_cache = os.environ.get("QWEN_VLLM_PREFIX_CACHING", "1").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    llm_kw["enable_prefix_caching"] = prefix_cache
    max_seqs = int(os.environ.get("QWEN_VLLM_BATCH_SIZE", "4"))
    if max_seqs > 0:
        llm_kw["max_num_seqs"] = max_seqs
    batched_toks = os.environ.get("QWEN_VLLM_MAX_NUM_BATCHED_TOKENS", "").strip()
    if batched_toks.isdigit():
        llm_kw["max_num_batched_tokens"] = int(batched_toks)

    print(
        f"[Qwen/vLLM] loading model={model_id!r} max_model_len={max_len} "
        f"gpu_mem_util={gpu_util} dtype={dtype} prefix_cache={prefix_cache} "
        f"max_num_seqs={max_seqs} language_model_only={llm_kw.get('language_model_only', False)} "
        f"tokenizer={llm_kw.get('tokenizer', model_id)!r}",
        flush=True,
    )
    llm = LLM(**llm_kw)
    _VLLM_BY_PROFILE[profile] = llm
    return llm


def _sampling_params(*, max_new_tokens: int, enable_thinking: bool) -> Any:
    from vllm import SamplingParams

    from core.generation_defaults import agent_decoding_kwargs

    gen = agent_decoding_kwargs(enable_thinking=enable_thinking)
    temp = float(gen.get("temperature", 0.2)) if gen.get("do_sample", True) else 0.0
    sp_kw: dict[str, Any] = {
        "max_tokens": max_new_tokens,
        "temperature": temp,
        "stop_token_ids": _eos_stop_ids(),
    }
    rp = gen.get("repetition_penalty")
    if rp is not None and float(rp) > 1.0:
        sp_kw["repetition_penalty"] = float(rp)
    return SamplingParams(**sp_kw)


def _is_merged_vllm_model(model_id: str) -> bool:
    try:
        from pathlib import Path

        name = Path(model_id).expanduser().resolve().name
        return name.endswith("-vllm-merged")
    except Exception:
        return False


def _vllm_tokenizer_id(model_id: str, profile: str) -> str | None:
    """Use hub tokenizer for merged exports (full Qwen3_5Config lives on base id)."""
    env_tok = os.environ.get("QWEN_VLLM_TOKENIZER_ID", "").strip()
    if env_tok and profile not in NVFP4_PROFILES:
        return env_tok
    if _is_merged_vllm_model(model_id):
        return _tokenizer_model_id(model_id, profile)
    return None


def _vllm_max_seq_len() -> int:
    return int(
        os.environ.get("QWEN_VLLM_MAX_MODEL_LEN", os.environ.get("QWEN_MAX_SEQ_LEN", "16384"))
    )


def _vllm_prompt_reserve() -> int:
    """Slack for chat-template / vLLM length checks (avoids 16385>16384 failures)."""
    raw = os.environ.get("QWEN_VLLM_PROMPT_RESERVE", "128").strip()
    return int(raw) if raw.isdigit() else 128


def _vllm_tokenizer_slack() -> int:
    """Extra headroom: HF token count can be 1–32 tokens below vLLM's."""
    raw = os.environ.get("QWEN_VLLM_TOKENIZER_SLACK", "32").strip()
    return int(raw) if raw.isdigit() else 32


def _tokenizer_model_id(model_id: str, profile: str) -> str:
    """Merged LoRA dirs ship Qwen3_5TextConfig; vLLM tokenizer needs full Qwen3_5Config."""
    env_tok = os.environ.get("QWEN_VLLM_TOKENIZER_ID", "").strip()
    if env_tok and profile not in NVFP4_PROFILES:
        return env_tok
    try:
        from pathlib import Path
        import json

        meta = Path(model_id).expanduser().resolve() / "vllm_export.json"
        if meta.is_file():
            base = json.loads(meta.read_text(encoding="utf-8")).get("base_model")
            if isinstance(base, str) and base.strip():
                return base.strip()
    except Exception:
        pass
    merge_base = os.environ.get("QWEN_VLLM_MERGE_BASE", "").strip()
    if merge_base and Path(model_id).expanduser().resolve().name.endswith("-vllm-merged"):
        return merge_base
    if model_id in _VLLM_MODEL_DEFAULTS.values() or model_id.startswith("Qwen/"):
        return model_id
    if profile in _VLLM_MODEL_DEFAULTS:
        return _VLLM_MODEL_DEFAULTS[profile]
    return model_id


def _vllm_language_model_only(model_id: str) -> bool:
    env = os.environ.get("QWEN_VLLM_LANGUAGE_MODEL_ONLY", "").strip().lower()
    if env in ("1", "true", "yes"):
        return True
    if env in ("0", "false", "no"):
        return False
    if "Qwen3.8" in model_id or "qwen3.8" in model_id.lower():
        return True
    return _is_merged_vllm_model(model_id)


def _get_tokenizer(model_id: str, *, profile: str = "qwen3_5_9b_bnb") -> Any:
    from transformers import AutoTokenizer

    tok_id = _tokenizer_model_id(model_id, profile)
    return AutoTokenizer.from_pretrained(tok_id, trust_remote_code=True)


def _prompt_token_len(
    tok: Any,
    str_msgs: list[dict[str, str]],
    *,
    enable_thinking: bool,
) -> int:
    prompt = tok.apply_chat_template(
        str_msgs,
        tokenize=False,
        add_generation_prompt=True,
        enable_thinking=enable_thinking,
    )
    return len(tok.encode(prompt))


def _vllm_prompt_budget(*, for_generation: bool = True) -> int:
    """Max prompt tokens so prompt + min generation fits vLLM max_model_len."""
    from core.generation_defaults import MIN_GENERATION_TOKENS

    gen_floor = MIN_GENERATION_TOKENS if for_generation else 64
    return (
        _vllm_max_seq_len()
        - gen_floor
        - _vllm_prompt_reserve()
        - _vllm_tokenizer_slack()
    )


def _fit_messages_to_vllm_context(
    model_id: str,
    str_msgs: list[dict[str, str]],
    *,
    profile: str,
    enable_thinking: bool,
) -> tuple[list[dict[str, str]], int]:
    """Truncate user turns so prompt + min generation fits vLLM max_model_len."""
    tok = _get_tokenizer(model_id, profile=profile)
    msgs = [{"role": str(m.get("role", "user")), "content": str(m.get("content", ""))} for m in str_msgs]
    max_prompt = _vllm_prompt_budget()
    suffix = "\n...[prompt truncated for vLLM context]...\n"

    def _count() -> int:
        return _prompt_token_len(tok, msgs, enable_thinking=enable_thinking)

    n_tok = _count()
    if n_tok <= max_prompt:
        return msgs, n_tok

    user_idxs = [i for i, m in enumerate(msgs) if m.get("role") == "user"]
    if not user_idxs:
        return msgs, n_tok

    # Shrink user turns from the largest (usually last = case body) backward.
    for idx in reversed(user_idxs):
        content = msgs[idx]["content"]
        lo, hi = 0, len(content)
        best = ""
        while lo <= hi:
            mid = (lo + hi) // 2
            trial = content[:mid] + suffix
            msgs[idx]["content"] = trial
            n_try = _count()
            if n_try <= max_prompt:
                best = trial
                lo = mid + 1
            else:
                hi = mid - 1
        if best:
            msgs[idx]["content"] = best
        else:
            msgs[idx]["content"] = suffix
        n_tok = _count()
        if n_tok <= max_prompt:
            break

    # HF tokenizer can under-count vs vLLM — shrink until clearly under budget.
    while n_tok > max_prompt and user_idxs:
        idx = user_idxs[-1]
        content = msgs[idx]["content"]
        if len(content) <= len(suffix) + 32:
            msgs[idx]["content"] = suffix
        else:
            cut = max(len(suffix) + 32, int(len(content) * 0.85))
            msgs[idx]["content"] = content[:cut] + suffix
        n_tok = _count()

    if n_tok > max_prompt:
        print(
            f"[Qwen/vLLM] warn: prompt still {n_tok} tok > budget {max_prompt} after truncation",
            flush=True,
        )
    else:
        print(
            f"[Qwen/vLLM] truncated prompt to {n_tok} tokens (budget {max_prompt})",
            flush=True,
        )
    return msgs, n_tok


def _cap_max_new_for_messages(
    model_id: str,
    str_msgs: list[dict[str, str]],
    *,
    profile: str,
    enable_thinking: bool,
) -> int:
    from core.generation_defaults import (
        agent_decoding_kwargs,
        cap_max_new_tokens,
    )

    try:
        _, input_len = _fit_messages_to_vllm_context(
            model_id, str_msgs, profile=profile, enable_thinking=enable_thinking
        )
    except Exception:
        input_len = 0
    gen = cap_max_new_tokens(
        agent_decoding_kwargs(enable_thinking=enable_thinking),
        input_token_len=input_len,
        max_seq_len=_vllm_max_seq_len(),
    )
    return int(gen["max_new_tokens"])


def _vllm_chat_once(
    llm: Any,
    model_id: str,
    str_msgs: list[dict[str, str]],
    *,
    profile: str,
    enable_thinking: bool,
    tools: list[dict[str, Any]] | None,
    max_new: int | None = None,
) -> dict[str, Any]:
    if max_new is None:
        str_msgs, _ = _fit_messages_to_vllm_context(
            model_id, str_msgs, profile=profile, enable_thinking=enable_thinking
        )
        max_new = _cap_max_new_for_messages(
            model_id, str_msgs, profile=profile, enable_thinking=enable_thinking
        )
    sp = _sampling_params(max_new_tokens=max_new, enable_thinking=enable_thinking)
    chat_template_kwargs: dict[str, Any] = {}
    if enable_thinking:
        chat_template_kwargs["enable_thinking"] = True
    lora_req = _lora_request()
    outputs = llm.chat(
        str_msgs,
        sp,
        tools=tools,
        chat_template_kwargs=chat_template_kwargs or None,
        lora_request=lora_req,
        add_generation_prompt=True,
    )
    out = outputs[0]
    text = (out.outputs[0].text or "").strip()
    out_tok = len(out.outputs[0].token_ids) if out.outputs[0].token_ids else 0
    in_tok = len(out.prompt_token_ids) if out.prompt_token_ids else 0
    return {"text": text, "input_tokens": in_tok, "output_tokens": out_tok, "max_new": max_new}


def vllm_generate_batch_from_chat(
    messages_batch: list[list[dict[str, Any]]],
    *,
    profile: str,
    enable_thinking: bool = False,
    tools: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Batch vLLM chat; returns one result dict per conversation (text + token counts)."""
    from models.qwen.runner import (
        _normalize_chat_messages,
        _prepare_messages_for_thinking,
    )

    if not messages_batch:
        return []
    llm = _get_vllm(profile)
    model_id = _vllm_model_id(profile)
    str_batches: list[list[dict[str, str]]] = []
    max_new_list: list[int] = []
    for messages in messages_batch:
        norm = _prepare_messages_for_thinking(
            _normalize_chat_messages(messages),
            profile,
            enable_thinking=enable_thinking,
        )
        str_msgs = [
            {"role": str(m.get("role", "user")), "content": str(m.get("content", ""))}
            for m in norm
        ]
        str_msgs, _ = _fit_messages_to_vllm_context(
            model_id, str_msgs, profile=profile, enable_thinking=enable_thinking
        )
        str_batches.append(str_msgs)
        max_new_list.append(
            _cap_max_new_for_messages(
                model_id, str_msgs, profile=profile, enable_thinking=enable_thinking
            )
        )
    max_new = max(max_new_list) if max_new_list else 4096
    sp = _sampling_params(max_new_tokens=max_new, enable_thinking=enable_thinking)
    chat_template_kwargs: dict[str, Any] = {}
    if enable_thinking:
        chat_template_kwargs["enable_thinking"] = True
    lora_req = _lora_request()
    print(
        f"[Qwen/vLLM] batch n={len(str_batches)} max_new={max_new} "
        f"prefix_cache={os.environ.get('QWEN_VLLM_PREFIX_CACHING', '1')}",
        flush=True,
    )
    outputs = llm.chat(
        str_batches,
        sp,
        tools=tools,
        chat_template_kwargs=chat_template_kwargs or None,
        lora_request=lora_req,
        add_generation_prompt=True,
    )
    results: list[dict[str, Any]] = []
    for out in outputs:
        text = (out.outputs[0].text or "").strip()
        out_tok = len(out.outputs[0].token_ids) if out.outputs[0].token_ids else 0
        in_tok = len(out.prompt_token_ids) if out.prompt_token_ids else 0
        results.append(
            {"text": text, "input_tokens": in_tok, "output_tokens": out_tok, "max_new": max_new}
        )
    return results


def vllm_generate_from_chat(
    messages: list[dict[str, Any]],
    *,
    profile: str,
    enable_thinking: bool = False,
    tools: list[dict[str, Any]] | None = None,
    max_new: int | None = None,
) -> str:
    from core.gen_meta import set_gen_meta

    from models.qwen.runner import (
        _normalize_chat_messages,
        _prepare_messages_for_thinking,
    )

    llm = _get_vllm(profile)
    model_id = _vllm_model_id(profile)
    norm = _prepare_messages_for_thinking(
        _normalize_chat_messages(messages),
        profile,
        enable_thinking=enable_thinking,
    )
    str_msgs = [
        {"role": str(m.get("role", "user")), "content": str(m.get("content", ""))}
        for m in norm
    ]
    str_msgs, _ = _fit_messages_to_vllm_context(
        model_id, str_msgs, profile=profile, enable_thinking=enable_thinking
    )

    result = _vllm_chat_once(
        llm,
        model_id,
        str_msgs,
        profile=profile,
        enable_thinking=enable_thinking,
        tools=tools,
        max_new=max_new,
    )
    set_gen_meta(result["input_tokens"], result["output_tokens"])

    if os.environ.get("QWEN_GEN_DEBUG", "").strip().lower() in ("1", "true", "yes"):
        print(
            f"[Qwen/vLLM] in={result['input_tokens']} out={result['output_tokens']} "
            f"max_new={result['max_new']} enable_thinking={enable_thinking} backend=vllm",
            flush=True,
        )
    return result["text"]
