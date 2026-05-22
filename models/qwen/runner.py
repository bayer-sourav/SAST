"""Qwen inference via Unsloth when available; otherwise Hugging Face Transformers.

Menu profiles (see main.py):
  2_5_7b — Qwen2.5-7B Instruct (default Unsloth bnb-4bit).
  qwen3_4b_2507 — Qwen3-4B-Instruct-2507 (Unsloth bnb-4bit + HF).
  qwen3_8b_bnb — Qwen3-8B (Unsloth bnb-4bit hub + HF instruct fallback).
  qwen3_14b_bnb — Qwen3-14B (Unsloth bnb-4bit hub + HF instruct fallback).
  qwen3_5_9b_bnb — Qwen3.5-9B (Unsloth 4-bit hub id + HF fallback).
"""

from __future__ import annotations

# Unsloth is imported lazily in _load_unsloth so HF fallback is not patched on import failure.

import inspect
import json
import os
from typing import Any

import torch
from langchain_core.tools import BaseTool

from core.generation_defaults import agent_decoding_kwargs, cap_max_new_tokens, model_max_seq_len
from core.gpu_info import cuda_error_suggests_poisoned_context, log_gpu_status
from core.parsing import parse_tool_selection
from core.prompts import tool_selection_chat_messages

_DEFAULT_UNSLOTH_7B = "unsloth/Qwen2.5-7B-Instruct-bnb-4bit"
_DEFAULT_HF_7B = "Qwen/Qwen2.5-7B-Instruct"

_MODEL: Any = None
_TOKENIZER: Any = None
_LOADED_4BIT: bool | None = None
_LOADED_UNSLOTH_ID: str | None = None
_ACTIVE_PROFILE: str | None = None

# Profiles using Qwen3 chat templates (enable_thinking / thinking blocks).
QWEN3_PROFILES = frozenset(
    {
        "qwen3_4b_bnb",
        "qwen3_8b_bnb",
        "qwen3_14b_bnb",
        "qwen3_coder_30b_bnb",
    }
)


def _drop_qwen_weights() -> None:
    global _MODEL, _TOKENIZER, _LOADED_4BIT, _LOADED_UNSLOTH_ID
    _MODEL = None
    _TOKENIZER = None
    _LOADED_4BIT = None
    _LOADED_UNSLOTH_ID = None


def unload_qwen() -> None:
    global _ACTIVE_PROFILE
    _drop_qwen_weights()
    _ACTIVE_PROFILE = None


def _resolve_ids(profile: str) -> tuple[str, str]:
    """Returns (unsloth_model_id, hf_fallback_id)."""
    if profile == "2_5_7b":
        u = os.environ.get("QWEN_UNSLOTH_MODEL_ID", _DEFAULT_UNSLOTH_7B)
        h = os.environ.get("QWEN_HF_MODEL_ID", _DEFAULT_HF_7B)
        return u, h
    if profile == "qwen3_4b_bnb":
        u = os.environ.get(
            "QWEN3_4B_UNSLOTH_MODEL_ID",
            "unsloth/Qwen3-4B-Instruct-2507-unsloth-bnb-4bit",
        )
        h = os.environ.get("QWEN3_4B_HF_MODEL_ID", "Qwen/Qwen3-4B-Instruct-2507")
        return u, h
    if profile == "qwen3_8b_bnb":
        u = os.environ.get(
            "QWEN3_8B_UNSLOTH_MODEL_ID",
            "unsloth/Qwen3-8B-unsloth-bnb-4bit",
        )
        h = os.environ.get("QWEN3_8B_HF_MODEL_ID", "Qwen/Qwen3-8B-Instruct")
        return u, h
    if profile == "qwen3_14b_bnb":
        u = os.environ.get(
            "QWEN3_14B_UNSLOTH_MODEL_ID",
            "unsloth/Qwen3-14B-unsloth-bnb-4bit",
        )
        h = os.environ.get("QWEN3_14B_HF_MODEL_ID", "Qwen/Qwen3-14B-Instruct")
        return u, h
    if profile == "qwen3_coder_30b_bnb":
        u = os.environ.get(
            "QWEN3_CODER_30B_UNSLOTH_MODEL_ID",
            "unsloth/Qwen3-Coder-30B-A3B-Instruct",
        )
        h = os.environ.get("QWEN3_CODER_30B_HF_MODEL_ID", "Qwen/Qwen3-Coder-30B-A3B-Instruct")
        return u, h
    raise ValueError(f"unknown Qwen profile {profile!r}")


def _hf_cache_key(profile: str) -> str:
    return f"qwen_hf:{profile}"


def _hf_generate(
    model_id: str,
    messages: list[dict[str, str]],
    *,
    use_4bit: bool,
    cache_key: str,
) -> str:
    from core.hf_backend import hf_generate_from_messages

    return hf_generate_from_messages(
        model_id,
        cache_key=cache_key,
        messages=messages,
        use_4bit=use_4bit,
    )


def _load_unsloth(*, use_4bit: bool, unsloth_model_id: str) -> tuple[Any, Any]:
    global _MODEL, _TOKENIZER, _LOADED_4BIT, _LOADED_UNSLOTH_ID
    if (
        _MODEL is not None
        and _LOADED_4BIT == use_4bit
        and _LOADED_UNSLOTH_ID == unsloth_model_id
    ):
        assert _TOKENIZER is not None
        return _MODEL, _TOKENIZER
    if _MODEL is not None:
        _drop_qwen_weights()

    try:
        import unsloth  # noqa: F401 - ensure patches before FastLanguageModel (lazy path)
        from unsloth import FastLanguageModel  # type: ignore[import-not-found]
    except (ImportError, AttributeError, NameError, NotImplementedError) as exc:
        raise ImportError(f"Unsloth not usable on this device: {exc}") from exc

    log_gpu_status("Qwen Unsloth")
    max_seq = int(os.environ.get("QWEN_MAX_SEQ_LEN", "32768"))
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=unsloth_model_id,
        max_seq_length=max_seq,
        dtype=None,
        load_in_4bit=use_4bit,
    )
    FastLanguageModel.for_inference(model)
    _MODEL, _TOKENIZER = model, tokenizer
    _LOADED_4BIT = use_4bit
    _LOADED_UNSLOTH_ID = unsloth_model_id
    print(f"[Qwen] Unsloth loaded model={unsloth_model_id!r} load_in_4bit={use_4bit}")
    return model, tokenizer


def _prepare_messages_for_thinking(
    messages: list[dict[str, Any]],
    profile: str,
    *,
    enable_thinking: bool,
) -> list[dict[str, Any]]:
    """Qwen3 soft switch: append /no_think on the last user turn when thinking is off."""
    if profile not in QWEN3_PROFILES or enable_thinking:
        return messages
    out: list[dict[str, Any]] = [dict(m) for m in messages]
    for i in range(len(out) - 1, -1, -1):
        if out[i].get("role") == "user":
            content = str(out[i].get("content", ""))
            if "/no_think" not in content and "/think" not in content:
                out[i]["content"] = content.rstrip() + "\n/no_think"
            break
    return out


def _apply_chat_template_maybe_tools(
    tok: Any,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    *,
    enable_thinking: bool = False,
    profile: str | None = None,
) -> str:
    kwargs: dict[str, Any] = {"tokenize": False, "add_generation_prompt": True}
    # Unsloth wraps apply_chat_template (signature hides enable_thinking) but forwards **kwargs.
    use_thinking_kw = profile in QWEN3_PROFILES if profile else False
    if not use_thinking_kw:
        try:
            use_thinking_kw = "enable_thinking" in inspect.signature(tok.apply_chat_template).parameters
        except (TypeError, ValueError):
            use_thinking_kw = False
    if use_thinking_kw:
        kwargs["enable_thinking"] = enable_thinking
    if tools:
        try:
            if "tools" in inspect.signature(tok.apply_chat_template).parameters:
                kwargs["tools"] = tools
        except (TypeError, ValueError):
            pass
    return tok.apply_chat_template(messages, **kwargs)


def _normalize_chat_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for m in messages:
        msg = dict(m)
        c = msg.get("content")
        if isinstance(c, list):
            texts: list[str] = []
            for block in c:
                if isinstance(block, dict) and block.get("type") == "text":
                    texts.append(str(block.get("text", "")))
            msg["content"] = "\n".join(texts) if texts else json.dumps(c)
        elif c is None:
            msg["content"] = ""
        else:
            msg["content"] = str(c)
        out.append(msg)
    return out


def _messages_str_only(messages: list[dict[str, Any]]) -> list[dict[str, str]]:
    return [{"role": str(m.get("role", "user")), "content": str(m.get("content", ""))} for m in messages]


def _hf_generate_with_template(
    hf_id: str,
    *,
    cache_key: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    use_4bit: bool,
    enable_thinking: bool = False,
    profile: str | None = None,
) -> str:
    from core.hf_backend import get_hf_model_and_tokenizer

    model, tokenizer = get_hf_model_and_tokenizer(hf_id, cache_key=cache_key, use_4bit=use_4bit)
    tok = getattr(tokenizer, "tokenizer", tokenizer)
    prompt = _apply_chat_template_maybe_tools(
        tok, messages, tools, enable_thinking=enable_thinking, profile=profile
    )
    device = next(model.parameters()).device
    inputs = tok(prompt, return_tensors="pt").to(device)
    input_len = int(inputs["input_ids"].shape[1])
    gen_kwargs = cap_max_new_tokens(
        agent_decoding_kwargs(enable_thinking=enable_thinking),
        input_token_len=input_len,
        max_seq_len=model_max_seq_len(),
    )
    with torch.inference_mode():
        out = model.generate(**inputs, **gen_kwargs)
    new_tokens = out[0][input_len:]
    from core.gen_meta import set_gen_meta

    set_gen_meta(input_len, int(new_tokens.shape[0]))
    return tok.decode(new_tokens, skip_special_tokens=True).strip()


def _generate_unsloth(
    messages: list[dict[str, Any]],
    *,
    use_4bit: bool,
    unsloth_model_id: str,
    tools: list[dict[str, Any]] | None = None,
    enable_thinking: bool = False,
) -> str:
    model, tokenizer = _load_unsloth(use_4bit=use_4bit, unsloth_model_id=unsloth_model_id)
    # Some Qwen3.5 checkpoints expose a Processor-like object from Unsloth.
    # For text-only routing we must use the underlying tokenizer; otherwise
    # processor.__call__(prompt, ...) treats prompt as image input.
    tok = getattr(tokenizer, "tokenizer", tokenizer)

    prompt = _apply_chat_template_maybe_tools(
        tok,
        messages,
        tools,
        enable_thinking=enable_thinking,
        profile=_ACTIVE_PROFILE,
    )
    if _ACTIVE_PROFILE in QWEN3_PROFILES:
        print(
            f"[Qwen] chat_template enable_thinking={enable_thinking} "
            f"(profile={_ACTIVE_PROFILE!r})"
        )
    device = next(model.parameters()).device
    print(f"[GPU] Qwen generate: first param device={device}")
    inputs = tok(prompt, return_tensors="pt").to(device)
    input_len = int(inputs["input_ids"].shape[1])
    gen_kwargs = cap_max_new_tokens(
        agent_decoding_kwargs(enable_thinking=enable_thinking),
        input_token_len=input_len,
        max_seq_len=model_max_seq_len(),
    )
    with torch.inference_mode():
        out = model.generate(**inputs, **gen_kwargs)
    new_tokens = out[0][input_len:]
    from core.gen_meta import set_gen_meta
    set_gen_meta(input_len, int(new_tokens.shape[0]))
    return tok.decode(new_tokens, skip_special_tokens=True).strip()


def generate_tool_selection_raw(
    user_message: str,
    tools: list[BaseTool],
    *,
    use_4bit: bool = True,
    profile: str = "2_5_7b",
) -> str:
    global _ACTIVE_PROFILE
    if _ACTIVE_PROFILE is not None and _ACTIVE_PROFILE != profile:
        _drop_qwen_weights()
    _ACTIVE_PROFILE = profile

    messages = tool_selection_chat_messages(tools, user_message)
    unsloth_id, hf_id = _resolve_ids(profile)

    if not torch.cuda.is_available():
        print(
            "[Qwen] torch.cuda.is_available() is False — skipping Unsloth. "
            "Using Hugging Face (likely CPU); large models may OOM without GPU."
        )
        return _hf_generate(hf_id, messages, use_4bit=use_4bit, cache_key=_hf_cache_key(profile))

    try:
        return _generate_unsloth(messages, use_4bit=use_4bit, unsloth_model_id=unsloth_id, tools=None)
    except ImportError:
        print("[Qwen] unsloth not installed; using Hugging Face Transformers.")
    except NotImplementedError as exc:
        print(f"[Qwen] Unsloth needs a working GPU ({exc}); using Hugging Face Transformers.")
    except Exception as exc:
        err = str(exc)
        print(f"[Qwen] Unsloth failed ({type(exc).__name__}: {exc}).")
        if torch.cuda.is_available() and cuda_error_suggests_poisoned_context(exc):
            print(
                "[Qwen] Poisoned CUDA context — restart `python3 main.py` before other GPU models."
            )
            raise RuntimeError(
                "CUDA context invalid after a device-side assert; restart Python before using GPU models."
            ) from exc
        print("[Qwen] Falling back to Hugging Face Transformers.")
        if "download" in err.lower() or "force download" in err.lower():
            print("[Qwen] Check disk space, HF_TOKEN / huggingface-cli login, and hub cache.")
        if "register_constant" in err or "_pytree" in err:
            print("[Qwen] PyTorch / Unsloth version mismatch is common; try pinned torch or HF-only.")

    return _hf_generate(hf_id, messages, use_4bit=use_4bit, cache_key=_hf_cache_key(profile))


def generate_from_chat_messages(
    messages: list[dict[str, Any]],
    *,
    use_4bit: bool = True,
    profile: str = "2_5_7b",
    tools: list[dict[str, Any]] | None = None,
    enable_thinking: bool = False,
) -> str:
    """Run Qwen on OpenAI-style chat messages (optional OpenAI ``tools`` for ``apply_chat_template``)."""
    global _ACTIVE_PROFILE
    if _ACTIVE_PROFILE is not None and _ACTIVE_PROFILE != profile:
        _drop_qwen_weights()
    _ACTIVE_PROFILE = profile

    norm = _normalize_chat_messages(messages)
    norm = _prepare_messages_for_thinking(norm, profile, enable_thinking=enable_thinking)
    unsloth_id, hf_id = _resolve_ids(profile)

    if not torch.cuda.is_available():
        print(
            "[Qwen] torch.cuda.is_available() is False — using Hugging Face path "
            "(tools in template only if tokenizer supports ``tools=``)."
        )
        if tools:
            return _hf_generate_with_template(
                hf_id,
                cache_key=_hf_cache_key(profile),
                messages=norm,
                tools=tools,
                use_4bit=use_4bit,
                enable_thinking=enable_thinking,
                profile=profile,
            )
        return _hf_generate(
            hf_id,
            _messages_str_only(norm),
            use_4bit=use_4bit,
            cache_key=_hf_cache_key(profile),
        )

    try:
        return _generate_unsloth(
            norm,
            use_4bit=use_4bit,
            unsloth_model_id=unsloth_id,
            tools=tools,
            enable_thinking=enable_thinking,
        )
    except ImportError:
        print("[Qwen] unsloth not installed; using Hugging Face Transformers.")
    except NotImplementedError as exc:
        print(f"[Qwen] Unsloth needs a working GPU ({exc}); using Hugging Face Transformers.")
    except Exception as exc:
        err = str(exc)
        print(f"[Qwen] Unsloth failed ({type(exc).__name__}: {exc}).")
        if torch.cuda.is_available() and cuda_error_suggests_poisoned_context(exc):
            print(
                "[Qwen] Poisoned CUDA context — restart Python before other GPU models."
            )
            raise RuntimeError(
                "CUDA context invalid after a device-side assert; restart Python before using GPU models."
            ) from exc
        print("[Qwen] Falling back to Hugging Face Transformers.")
        if "download" in err.lower() or "force download" in err.lower():
            print("[Qwen] Check disk space, HF_TOKEN / huggingface-cli login, and hub cache.")
        if "register_constant" in err or "_pytree" in err:
            print("[Qwen] PyTorch / Unsloth version mismatch is common; try pinned torch or HF-only.")

    if tools:
        return _hf_generate_with_template(
            hf_id,
            cache_key=_hf_cache_key(profile),
            messages=norm,
            tools=tools,
            use_4bit=use_4bit,
            enable_thinking=enable_thinking,
            profile=profile,
        )
    return _hf_generate(
        hf_id,
        _messages_str_only(norm),
        use_4bit=use_4bit,
        cache_key=_hf_cache_key(profile),
    )


def run_tool_selection(
    user_message: str,
    tools: list[BaseTool],
    *,
    use_4bit: bool = True,
    profile: str = "2_5_7b",
) -> dict:
    raw = generate_tool_selection_raw(
        user_message, tools, use_4bit=use_4bit, profile=profile
    )
    return parse_tool_selection(raw).model_dump()
