"""Shared Hugging Face Transformers text generation for local agent prompts."""

from __future__ import annotations

import inspect
import os
import warnings
from pathlib import Path
from typing import Any, NoReturn

import torch
from transformers import AutoConfig, AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

from core.generation_defaults import agent_decoding_kwargs
from core.gpu_info import log_gpu_status

_CACHE: dict[str, tuple[Any, Any]] = {}


def _is_gpt_oss_model(model_id: str) -> bool:
    return "gpt-oss" in model_id.lower()


def _trust_remote_code_for_model(model_id: str) -> bool:
    """
    Official Qwen2.x / Qwen2.5 is built into recent Transformers; Hub `modeling_*.py` with
    trust_remote_code=True often lags the library and breaks at generate (e.g. Qwen2Attention
    has no apply_qkv). For those ids we default trust_remote_code=False unless
    QWEN_HF_TRUST_REMOTE_CODE=1.

    Qwen3+ Hub ids (`Qwen/Qwen3-...`, etc.) must NOT use the `qwen/qwen` prefix rule: that
    pattern matched `qwen/qwen3` and incorrectly forced remote code off, which breaks when
    the installed Transformers build lacks built-in Qwen3 or Hub stubs expect library modules.
    """
    v = os.environ.get("HF_TRUST_REMOTE_CODE", "").strip().lower()
    if v in ("0", "false", "no"):
        return False
    if v in ("1", "true", "yes"):
        return True
    ml = model_id.lower()
    if "qwen" in ml and (
        "qwen2.5" in ml
        or "qwen2-" in ml
        or "/qwen2" in ml
        or ml.startswith("qwen/qwen2")
    ):
        return os.environ.get("QWEN_HF_TRUST_REMOTE_CODE", "0").strip().lower() in (
            "1",
            "true",
            "yes",
        )
    return True


def _is_native_mxfp4_checkpoint(model_id: str) -> bool:
    """
    openai/gpt-oss-* ships with Mxfp4Config on the Hub. BitsAndBytesConfig is incompatible;
    we must load with the repo's native quantization only.
    """
    if "gpt-oss" in model_id.lower():
        return True
    try:
        cfg = AutoConfig.from_pretrained(model_id, trust_remote_code=True)
        qc = getattr(cfg, "quantization_config", None)
        if qc is None:
            return False
        name = type(qc).__name__
        return "mxfp4" in name.lower()
    except Exception:
        return False


def clear_hf_cache() -> None:
    """Remove references to cached HF models (pair with torch.cuda.empty_cache())."""
    global _CACHE
    for _k, (model, _tok) in list(_CACHE.items()):
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


def _aggregate_exception_text(exc: BaseException) -> str:
    parts: list[str] = []
    seen: set[int] = set()
    e: BaseException | None = exc
    while e is not None and id(e) not in seen:
        seen.add(id(e))
        parts.append(str(e))
        e = e.__cause__ or e.__context__
    return " ".join(parts).lower()


def _raise_hf_load_failure(model_id: str, exc: BaseException) -> NoReturn:
    """Surface chained causes (torchao, flash-attn, etc.) hidden behind lazy Qwen2 imports."""
    blob = _aggregate_exception_text(exc)
    hint = ""
    if "torchao" in blob or "register_constant" in blob or "_pytree" in blob:
        hint = (
            " Optional: `pip uninstall torchao` (Transformers may pull it and break on some torch builds)."
        )
    if (
        "flash" in blob
        or "triton" in blob
        or "qwen2forcausallm" in blob
        or "qwen3forcausallm" in blob
        or "could not import module" in blob
        or "apply_qkv" in blob
    ):
        hint += (
            " Try: `export HF_ATTN_IMPLEMENTATION=eager`; verify `pip show transformers` (>=5.5 "
            "for built-in Qwen3). For Qwen2.5-only issues, default is trust_remote_code=False."
        )
    if "device-side assert" in blob or ("cuda error" in blob and "assert" in blob):
        hint += (
            " **Restart Python** if another model (e.g. Gemma Unsloth) raised a device-side assert earlier "
            "in this session — the CUDA context stays broken for all later GPU loads until the process exits."
        )
    raise RuntimeError(
        f"Failed to load {model_id!r} from Hugging Face. Root causes are often masked — see chained "
        f"exception below.{hint}\nOriginal: {type(exc).__name__}: {exc}"
    ) from exc


def _patch_transformers_remote_code_compat() -> None:
    """
    Transformers 5.x removed helpers that older Hub `trust_remote_code` modules still import
    (e.g. `is_torch_fx_available`). See HF#44561.
    """
    try:
        import transformers.utils.import_utils as iu
    except ImportError:
        return
    if not hasattr(iu, "is_torch_fx_available"):

        def _is_torch_fx_available() -> bool:
            return True

        iu.is_torch_fx_available = _is_torch_fx_available  # type: ignore[attr-defined, assignment]


def get_hf_model_and_tokenizer(
    model_id: str,
    *,
    cache_key: str,
    use_4bit: bool = False,
) -> tuple[Any, Any]:
    native_mxfp4 = _is_native_mxfp4_checkpoint(model_id)
    use_bnb = (
        use_4bit
        and torch.cuda.is_available()
        and not native_mxfp4
    )
    if use_4bit and native_mxfp4:
        print(
            "[HF] This checkpoint uses native MXFP4 on the Hub; loading without bitsandbytes "
            "(Mxfp4Config and BitsAndBytesConfig cannot be mixed)."
        )
    elif use_4bit and not torch.cuda.is_available():
        print("[HF] 4-bit requested but CUDA unavailable; loading in fp (may OOM).")

    mxfp4_on_cpu = native_mxfp4 and os.environ.get("GPT_OSS_CPU_LOAD", "").lower() in (
        "1",
        "true",
        "yes",
    )
    slot_suffix = (
        "mxfp4_cpu"
        if mxfp4_on_cpu
        else ("mxfp4" if native_mxfp4 else ("bnb4" if use_bnb else "fp"))
    )
    trust_rc = _trust_remote_code_for_model(model_id)
    tr_tag = "trc1" if trust_rc else "trc0"
    slot = f"{cache_key}:{slot_suffix}:{tr_tag}"
    if slot in _CACHE:
        return _CACHE[slot]

    _patch_transformers_remote_code_compat()
    log_gpu_status(f"loading HF model_id={model_id!r} cache={slot!r}")
    if not trust_rc:
        print(
            "[HF] trust_remote_code=False (built-in model code). "
            "Set QWEN_HF_TRUST_REMOTE_CODE=1 if your checkpoint needs custom Hub code."
        )

    tok = AutoTokenizer.from_pretrained(model_id, trust_remote_code=trust_rc)
    device_map = os.environ.get("HF_DEVICE_MAP", "auto")
    if mxfp4_on_cpu:
        device_map = "cpu"
        print(
            "[HF] GPT_OSS_CPU_LOAD=1: loading MXFP4 on CPU (avoids CUDA OOM during mxfp4 swizzle). "
            "Needs large system RAM (often 48GB+ for 20B-class); g5.2xlarge ~32GB may still OOM. "
            "Inference is very slow."
        )
    elif not torch.cuda.is_available():
        dm_env = str(device_map).strip().lower()
        if dm_env in ("auto", "cuda", "cuda:0", ""):
            device_map = "cpu"
            print(
                "[HF] CUDA unavailable (driver too old, no GPU, or torch/CUDA mismatch): "
                "using device_map='cpu'. For GPU: update the NVIDIA driver or install a torch "
                "wheel that matches your driver. Override with HF_DEVICE_MAP if needed."
            )

    load_kw: dict[str, Any] = {
        "trust_remote_code": trust_rc,
        "device_map": device_map,
        "low_cpu_mem_usage": True,
    }

    if use_bnb:
        print("[HF] Using bitsandbytes 4-bit (NF4) load.")
        bnb_kw: dict[str, Any] = {
            "load_in_4bit": True,
            "bnb_4bit_compute_dtype": _dtype(),
            "bnb_4bit_use_double_quant": True,
            "bnb_4bit_quant_type": "nf4",
        }
        # Required when Accelerate puts some layers on CPU/disk (common on 15GB VRAM + 24B-class models).
        if os.environ.get("HF_BNB_ALLOW_CPU_OFFLOAD", "1").lower() not in ("0", "false", "no"):
            params = inspect.signature(BitsAndBytesConfig.__init__).parameters
            if "llm_int8_enable_fp32_cpu_offload" in params:
                bnb_kw["llm_int8_enable_fp32_cpu_offload"] = True
                print(
                    "[HF] llm_int8_enable_fp32_cpu_offload=True "
                    "(allows BnB + CPU/disk-dispatched layers; slower than GPU-only)."
                )
        load_kw["quantization_config"] = BitsAndBytesConfig(**bnb_kw)

    # Native MXFP4 / other repo-defined quant: do not override dtype here.
    if not use_bnb and not native_mxfp4:
        load_kw["dtype"] = _dtype()

    dm = str(device_map).strip().lower()
    if dm == "auto":
        offload = _default_offload_folder()
        Path(offload).mkdir(parents=True, exist_ok=True)
        load_kw["offload_folder"] = offload

    # Attention: GPT-OSS stability; CPU-only: avoid flash/triton import paths in Qwen2 etc.
    # ("Could not import module 'Qwen2ForCausalLM'" often masks a failed flash/triton dep).
    hf_attn = os.environ.get("HF_ATTN_IMPLEMENTATION", "").strip()
    if hf_attn and hf_attn.lower() not in ("auto", "default", "none", ""):
        load_kw["attn_implementation"] = hf_attn
    elif _is_gpt_oss_model(model_id):
        attn = os.environ.get("GPT_OSS_ATTN_IMPLEMENTATION", "eager").strip()
        if attn.lower() not in ("", "auto", "default", "none"):
            load_kw["attn_implementation"] = attn
    elif "qwen" in model_id.lower():
        # On GPU+CUDA, flash/SDPA paths often fail import inside modeling_qwen2 and surface as
        # "Could not import module 'Qwen2ForCausalLM'". Eager is slower but reliable.
        load_kw["attn_implementation"] = "eager"
    elif not torch.cuda.is_available():
        load_kw["attn_implementation"] = "eager"

    used_bnb = use_bnb
    model: Any | None = None
    load_error: BaseException | None = None

    try:
        model = AutoModelForCausalLM.from_pretrained(model_id, **load_kw)
    except TypeError as exc:
        msg = str(exc).lower()
        try:
            if not used_bnb and "dtype" in load_kw and "unexpected keyword" in msg:
                load_kw.pop("dtype", None)
                load_kw["torch_dtype"] = _dtype()
                model = AutoModelForCausalLM.from_pretrained(model_id, **load_kw)
            elif "attn_implementation" in load_kw and "unexpected" in msg:
                load_kw.pop("attn_implementation", None)
                model = AutoModelForCausalLM.from_pretrained(model_id, **load_kw)
            else:
                load_error = exc
        except Exception as exc2:
            load_error = exc2
    except Exception as exc:
        load_error = exc

    if model is None and load_error is not None:
        if (
            not trust_rc
            and "qwen" in model_id.lower()
            and os.environ.get("QWEN_HF_AUTO_TRUST_REMOTE", "1").lower()
            not in ("0", "false", "no")
        ):
            print(
                f"[HF] Load with trust_remote_code=False failed ({type(load_error).__name__}: {load_error}); "
                "retrying with trust_remote_code=True."
            )
            load_kw["trust_remote_code"] = True
            trust_rc = True
            load_error = None
            try:
                model = AutoModelForCausalLM.from_pretrained(model_id, **load_kw)
            except Exception as exc2:
                load_error = exc2

    if model is None and load_error is not None:
        blob = _aggregate_exception_text(load_error)
        if used_bnb and (
            "qwen2forcausallm" in blob
            or "could not import module" in blob
            or "register_constant" in blob
            or "torchao" in blob
        ):
            print(
                "[HF] 4-bit load failed (common with torch/transformers/torchao stacks); "
                "retrying without bitsandbytes in bf16/fp16 on GPU."
            )
            load_kw.pop("quantization_config", None)
            load_kw["dtype"] = _dtype()
            try:
                model = AutoModelForCausalLM.from_pretrained(model_id, **load_kw)
            except Exception as exc2:
                _raise_hf_load_failure(model_id, exc2)
        else:
            _raise_hf_load_failure(model_id, load_error)

    assert model is not None
    final_tr = bool(load_kw.get("trust_remote_code", True))
    slot = f"{cache_key}:{slot_suffix}:{'trc1' if final_tr else 'trc0'}"
    model.eval()
    _CACHE[slot] = (model, tok)
    print(f"[HF] Model loaded into cache slot {slot!r}.")
    return model, tok


def _inputs_device(model: Any) -> torch.device:
    try:
        emb = model.get_input_embeddings()
        d = emb.weight.device
        if getattr(d, "type", "") != "meta":
            print(f"[GPU] Input embeddings device: {d}")
            return d
    except Exception:
        pass
    if torch.cuda.is_available():
        print("[GPU] Falling back to cuda:0 for input tensors.")
        return torch.device("cuda:0")
    print("[GPU] Using CPU for input tensors.")
    return torch.device("cpu")


def messages_to_prompt(tokenizer, messages: list[dict[str, str]]) -> str:
    if hasattr(tokenizer, "apply_chat_template") and tokenizer.chat_template is not None:
        return tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
        )
    parts: list[str] = []
    for m in messages:
        role = m.get("role", "user")
        parts.append(f"### {role.upper()}\n{m.get('content', '')}\n")
    parts.append("### ASSISTANT\n")
    return "\n".join(parts)


def _is_qwen_omni_hub_id(model_id: str) -> bool:
    """
    Return True only for clearly multimodal/vision Qwen checkpoints that require
    AutoModelForImageTextToText + AutoProcessor.

    NOTE:
    - Plain text models like `Qwen/Qwen3.5-9B` and `Qwen/Qwen3.6-27B` must stay
      on AutoModelForCausalLM.
    - Routing text checkpoints through AutoProcessor can trigger
      "Incorrect image source" when the chat template contains `<|im_start|>...`.
    """
    ml = model_id.lower()

    # Explicit opt-in for debugging/edge cases.
    force = os.environ.get("QWEN_FORCE_OMNI", "").strip().lower()
    if force in ("1", "true", "yes"):
        return True

    # Only treat obvious vision/omni model IDs as multimodal.
    if "qwen" not in ml:
        return False

    multimodal_markers = (
        "omni",
        "-vl",
        "vision",
        "image-text-to-text",
    )
    return any(m in ml for m in multimodal_markers)


def _tokenizer_from_processor_obj(processor: Any) -> Any:
    tok = getattr(processor, "tokenizer", None)
    return tok if tok is not None else processor


def get_hf_qwen_omni_model_and_processor(
    model_id: str,
    *,
    cache_key: str,
    use_4bit: bool,
) -> tuple[Any, Any]:
    """Load Qwen3.5/3.6 omnimodal checkpoints for text-only generation (tool-selection)."""
    from transformers import AutoModelForImageTextToText, AutoProcessor, BitsAndBytesConfig

    use_bnb = use_4bit and torch.cuda.is_available()
    slot_suffix = "bnb4" if use_bnb else "fp"
    safe_id = model_id.replace("/", "__").replace(":", "_")
    slot = f"{cache_key}:qwen_omni:{safe_id}:{slot_suffix}"
    if slot in _CACHE:
        return _CACHE[slot]

    log_gpu_status(f"loading Qwen3.x omnimodal HF model_id={model_id!r} cache={slot!r}")
    processor = AutoProcessor.from_pretrained(model_id, trust_remote_code=True)
    device_map = os.environ.get("HF_DEVICE_MAP", "auto")
    if not torch.cuda.is_available():
        dm_env = str(device_map).strip().lower()
        if dm_env in ("auto", "cuda", "cuda:0", ""):
            device_map = "cpu"
            print("[HF-Qwen-omni] CUDA unavailable: device_map='cpu'.")

    load_kw: dict[str, Any] = {
        "trust_remote_code": True,
        "device_map": device_map,
        "low_cpu_mem_usage": True,
    }

    if use_bnb:
        print("[HF-Qwen-omni] Using bitsandbytes 4-bit (NF4) load.")
        bnb_kw: dict[str, Any] = {
            "load_in_4bit": True,
            "bnb_4bit_compute_dtype": _dtype(),
            "bnb_4bit_use_double_quant": True,
            "bnb_4bit_quant_type": "nf4",
        }
        if os.environ.get("HF_BNB_ALLOW_CPU_OFFLOAD", "1").lower() not in ("0", "false", "no"):
            params = inspect.signature(BitsAndBytesConfig.__init__).parameters
            if "llm_int8_enable_fp32_cpu_offload" in params:
                bnb_kw["llm_int8_enable_fp32_cpu_offload"] = True
                print(
                    "[HF-Qwen-omni] llm_int8_enable_fp32_cpu_offload=True "
                    "(BnB + device_map=auto on mid-size GPUs)."
                )
        load_kw["quantization_config"] = BitsAndBytesConfig(**bnb_kw)
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
    else:
        load_kw["attn_implementation"] = "eager"

    model = AutoModelForImageTextToText.from_pretrained(model_id, **load_kw)
    model.eval()
    _CACHE[slot] = (model, processor)
    print(f"[HF-Qwen-omni] Model loaded into cache slot {slot!r}.")
    return model, processor


def _hf_generate_qwen_omni_from_messages(
    model_id: str,
    *,
    cache_key: str,
    messages: list[dict[str, str]],
    max_new_tokens: int | None = None,
    temperature: float | None = None,
    use_4bit: bool = False,
) -> str:
    """Text-only tool routing: tokenizer from processor + chat template (same idea as Gemma3 HF)."""
    dec = agent_decoding_kwargs()
    if max_new_tokens is not None:
        dec["max_new_tokens"] = max_new_tokens
    if temperature is not None:
        dec["do_sample"] = temperature > 0
        if temperature > 0:
            dec["temperature"] = temperature
        else:
            dec.pop("temperature", None)

    model, processor = get_hf_qwen_omni_model_and_processor(
        model_id, cache_key=cache_key, use_4bit=use_4bit
    )
    tok = _tokenizer_from_processor_obj(processor)
    if not hasattr(tok, "apply_chat_template"):
        raise RuntimeError(
            "Qwen omnimodal processor has no tokenizer.apply_chat_template; upgrade transformers."
        )

    max_in = int(
        os.environ.get(
            "QWEN_OMNI_HF_MAX_INPUT_TOKENS",
            os.environ.get("QWEN35_HF_MAX_INPUT_TOKENS", "8192"),
        )
    )
    prompt = tok.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=True,
    )
    enc = tok(
        prompt,
        return_tensors="pt",
        truncation=True,
        max_length=max_in,
    )
    device = _inputs_device(model)
    gen_in = {
        k: v.to(device)
        for k, v in dict(enc).items()
        if isinstance(v, torch.Tensor) and k in ("input_ids", "attention_mask")
    }
    if "input_ids" not in gen_in:
        raise RuntimeError("[HF-Qwen-omni] tokenizer produced no input_ids")
    if "attention_mask" not in gen_in:
        gen_in["attention_mask"] = torch.ones_like(gen_in["input_ids"])

    gen_kwargs: dict[str, Any] = dict(dec)
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=".*attention mask API under `transformers.modeling_attn_mask_utils`.*",
            category=FutureWarning,
        )
        with torch.inference_mode():
            out = model.generate(**gen_in, **gen_kwargs)

    input_len = int(gen_in["input_ids"].shape[1])
    new_tokens = out[0][input_len:]
    from core.gen_meta import set_gen_meta

    set_gen_meta(input_len, int(new_tokens.shape[0]))
    return tok.decode(new_tokens, skip_special_tokens=True).strip()


def hf_generate_from_messages(
    model_id: str,
    *,
    cache_key: str,
    messages: list[dict[str, str]],
    max_new_tokens: int | None = None,
    temperature: float | None = None,
    use_4bit: bool = False,
) -> str:
    dec = agent_decoding_kwargs()
    if max_new_tokens is not None:
        dec["max_new_tokens"] = max_new_tokens
    if temperature is not None:
        dec["do_sample"] = temperature > 0
        if temperature > 0:
            dec["temperature"] = temperature
        else:
            dec.pop("temperature", None)

    if _is_qwen_omni_hub_id(model_id):
        return _hf_generate_qwen_omni_from_messages(
            model_id,
            cache_key=cache_key,
            messages=messages,
            max_new_tokens=max_new_tokens,
            temperature=temperature,
            use_4bit=use_4bit,
        )

    model, tokenizer = get_hf_model_and_tokenizer(
        model_id, cache_key=cache_key, use_4bit=use_4bit
    )
    prompt = messages_to_prompt(tokenizer, messages)
    device = _inputs_device(model)
    inputs = tokenizer(prompt, return_tensors="pt")
    if "attention_mask" not in inputs:
        inputs["attention_mask"] = torch.ones_like(inputs["input_ids"])
    inputs = inputs.to(device)

    gen_kwargs: dict[str, Any] = dict(dec)

    # GPT-OSS: only disable KV cache if GPT_OSS_USE_KV_CACHE=0 (debugging rare shape bugs).
    # Default on — off makes long-prompt decode astronomically slow.
    if _is_gpt_oss_model(model_id):
        if os.environ.get("GPT_OSS_USE_KV_CACHE", "1").lower() in ("0", "false", "no"):
            gen_kwargs["use_cache"] = False
        n_in = int(inputs["input_ids"].shape[1])
        mnt = gen_kwargs.get("max_new_tokens", "?")
        print(
            f"[HF GPT-OSS] generate: prompt_tokens≈{n_in}, max_new_tokens={mnt} "
            "(first tokens can be slow on 22GB; wait or lower AGENT_MAX_NEW_TOKENS).",
            flush=True,
        )

    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=".*attention mask API under `transformers.modeling_attn_mask_utils`.*",
            category=FutureWarning,
        )
        with torch.inference_mode():
            out = model.generate(**inputs, **gen_kwargs)

    input_len = inputs["input_ids"].shape[1]
    new_tokens = out[0][input_len:]
    from core.gen_meta import set_gen_meta
    set_gen_meta(int(input_len), int(new_tokens.shape[0]))
    return tokenizer.decode(new_tokens, skip_special_tokens=True).strip()
