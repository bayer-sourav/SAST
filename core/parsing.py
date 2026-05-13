"""Recover JSON tool selections from messy local-LLM outputs."""

from __future__ import annotations

import ast
import json
import os
import re

from pydantic import ValidationError

from core.schemas import MultiToolSelection


def _strip_redacted_thinking(text: str) -> str:
    """
    Phi-4-reasoning and similar models may emit long <redacted_thinking>...</redacted_thinking>
    chains before any JSON. Remove them so extract_json_object can see the answer.
    """
    text = re.sub(
        r"<redacted_thinking>[\s\S]*?</redacted_thinking>",
        "",
        text,
        flags=re.IGNORECASE,
    )
    # Truncated generation: opening tag without closing tag — drop from opener to end
    text = re.sub(r"<redacted_thinking>[\s\S]*\Z", "", text, flags=re.IGNORECASE)
    return text.strip()


def _slice_matching_delimiters(s: str, start: int, open_c: str, close_c: str) -> str | None:
    if start >= len(s) or s[start] != open_c:
        return None
    depth = 0
    for j in range(start, len(s)):
        if s[j] == open_c:
            depth += 1
        elif s[j] == close_c:
            depth -= 1
            if depth == 0:
                return s[start : j + 1]
    return None


def _ast_to_literal(node: ast.AST):
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.List):
        return [_ast_to_literal(elt) for elt in node.elts]
    if isinstance(node, ast.Tuple):
        return tuple(_ast_to_literal(elt) for elt in node.elts)
    if isinstance(node, ast.Dict):
        keys = []
        for k in node.keys:
            if k is None:
                raise ValueError("dict unpack not supported")
            keys.append(_ast_to_literal(k))
        vals = [_ast_to_literal(v) for v in node.values]
        return dict(zip(keys, vals))
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        inner = _ast_to_literal(node.operand)
        if isinstance(inner, (int, float)):
            return -inner
    raise ValueError(f"unsupported AST in tool args: {type(node).__name__}")


def _parse_python_style_tool_invocation(expr: str) -> tuple[str, dict] | None:
    expr = expr.strip()
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError:
        return None
    if not isinstance(tree, ast.Expression):
        return None
    call = tree.body
    if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name):
        return None
    name = call.func.id
    params: dict = {}
    for kw in call.keywords:
        if kw.arg is None:
            continue
        params[kw.arg] = _ast_to_literal(kw.value)
    return name, params


def _intent_tail_after_native_block(text: str, pos: int) -> str:
    rest = text[pos:].strip()
    rest = re.sub(r"^<\|[^>|]+\|>\s*", "", rest, count=1).strip()
    if not rest:
        return "Tool selected from native model output."
    line = rest.split("\n", 1)[0].strip()
    return line[:500] if len(line) > 500 else line


def try_extract_lfm2_native_tool_call(text: str) -> dict | None:
    """
    LFM2 / Kimi-style: <|tool_call_start|>[tool_name(key=val,...)]<|...|> plus optional prose.
    Converts to ToolSelection-shaped dict or returns None.
    """
    marker = "<|tool_call_start|>"
    idx = text.find(marker)
    if idx == -1:
        return None
    i = idx + len(marker)
    while i < len(text) and text[i].isspace():
        i += 1
    outer = _slice_matching_delimiters(text, i, "[", "]")
    if not outer or len(outer) < 2:
        return None
    inner = outer[1:-1].strip()
    parsed = _parse_python_style_tool_invocation(inner)
    if parsed is None:
        return None
    tool_name, parameters = parsed
    intent = _intent_tail_after_native_block(text, i + len(outer))
    return {"tool_name": tool_name, "parameters": parameters, "intent": intent}


def _must_be_json_dict(obj: object, *, ctx: str) -> dict:
    """json.loads can return list/str/null; we only accept top-level objects for tool selection."""
    if isinstance(obj, dict):
        return obj
    raise ValueError(f"{ctx}: expected a JSON object {{...}}, got {type(obj).__name__}")


def _norm_reasoning_steps_from_payload(data: dict) -> tuple[str, list[str]]:
    """Extract optional single-turn ReAct fields; tolerate missing or malformed values."""
    reasoning = data.get("reasoning", "")
    if reasoning is None:
        reasoning = ""
    elif not isinstance(reasoning, str):
        reasoning = str(reasoning)
    reasoning = reasoning.strip()

    steps_raw = data.get("steps", [])
    if steps_raw is None:
        steps: list[str] = []
    elif isinstance(steps_raw, str):
        lines = [ln.strip() for ln in steps_raw.split("\n") if ln.strip()]
        steps = lines if lines else ([steps_raw.strip()] if steps_raw.strip() else [])
    elif isinstance(steps_raw, list):
        steps = [str(s).strip() for s in steps_raw if str(s).strip()]
    else:
        steps = []
    return reasoning, steps


def _coerce_multi_tool_dict(data: dict) -> dict:
    """
    Accept new shape {"tools": [...], "intent": ...} or legacy single-tool
    {"tool_name", "parameters", "intent"}.
    """
    if not isinstance(data, dict):
        raise ValueError(f"Expected a JSON object, got {type(data).__name__}")
    if "tools" in data:
        tools_raw = data["tools"]
        # Models often emit a single string, one object, or a non-list; normalize to a list of steps.
        if isinstance(tools_raw, str):
            tools_raw = [tools_raw.strip()] if tools_raw.strip() else []
        elif isinstance(tools_raw, dict):
            tools_raw = [tools_raw]
        elif not isinstance(tools_raw, list):
            raise ValueError(
                f"'tools' must be a JSON array, object, or string tool name, got {type(tools_raw).__name__}"
            )

        def _norm_parameters(p: object) -> dict:
            if p is None:
                return {}
            if isinstance(p, dict):
                return p
            if isinstance(p, str):
                try:
                    loaded = json.loads(p)
                    return loaded if isinstance(loaded, dict) else {}
                except json.JSONDecodeError:
                    return {}
            return {}

        tools_norm: list[dict[str, object]] = []
        for i, item in enumerate(tools_raw):
            if isinstance(item, str):
                name = item.strip()
                if name:
                    tools_norm.append({"tool_name": name, "parameters": {}})
                continue
            if not isinstance(item, dict):
                raise ValueError(
                    f"tools[{i}] must be an object or a string tool name, got {type(item).__name__}"
                )
            tn = item.get("tool_name")
            if tn is None:
                raise ValueError(f"tools[{i}] missing 'tool_name'")
            tools_norm.append(
                {
                    "tool_name": str(tn).strip(),
                    "parameters": _norm_parameters(item.get("parameters")),
                }
            )

        intent = data.get("intent", "")
        if not isinstance(intent, str):
            intent = str(intent) if intent is not None else ""
        reasoning, steps = _norm_reasoning_steps_from_payload(data)
        return {
            "tools": tools_norm,
            "intent": intent,
            "reasoning": reasoning,
            "steps": steps,
        }
    if "tool_name" in data:
        params = data.get("parameters") or {}
        if not isinstance(params, dict):
            params = {}
        intent = data.get("intent", "")
        if not isinstance(intent, str):
            intent = str(intent) if intent is not None else ""
        reasoning, steps = _norm_reasoning_steps_from_payload(data)
        return {
            "tools": [
                {
                    "tool_name": data["tool_name"],
                    "parameters": params,
                }
            ],
            "intent": intent,
            "reasoning": reasoning,
            "steps": steps,
        }
    raise ValueError(
        "JSON must include either a 'tools' array of {tool_name, parameters} objects, "
        "or legacy fields 'tool_name' + 'parameters' + 'intent'"
    )


def _first_balanced_object_slice(s: str, start: int | None = None) -> str | None:
    """
    Slice from first '{' to the matching '}' using brace depth, respecting JSON string literals.
    More reliable than first-'{' to last-'}' when the model emits extra braces or trailing text.
    """
    i = start if start is not None else s.find("{")
    if i < 0:
        return None
    depth = 0
    in_str = False
    esc = False
    for j in range(i, len(s)):
        c = s[j]
        if esc:
            esc = False
            continue
        if in_str:
            if c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return s[i : j + 1]
    return None


def _try_parse_json_object(blob: str, *, ctx: str) -> dict | None:
    blob = blob.strip()
    if not blob:
        return None
    try:
        return _must_be_json_dict(json.loads(blob), ctx=ctx)
    except (json.JSONDecodeError, ValueError):
        sl = _first_balanced_object_slice(blob, 0)
        if sl and sl != blob:
            try:
                return _must_be_json_dict(json.loads(sl), ctx=ctx)
            except (json.JSONDecodeError, ValueError):
                return None
        return None


def extract_json_object(text: str) -> dict:
    text = _strip_redacted_thinking(text.strip())

    # 1) Markdown ```json ... ``` fences (try every fence; prefer first valid object).
    for m in re.finditer(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE):
        body = m.group(1).strip()
        parsed = _try_parse_json_object(body, ctx="JSON inside markdown fence")
        if parsed is not None:
            return parsed

    # 2) First balanced top-level {...} in the whole text.
    sl = _first_balanced_object_slice(text)
    if sl:
        try:
            return _must_be_json_dict(
                json.loads(sl),
                ctx="JSON from balanced brace slice",
            )
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON in balanced object slice: {exc}") from exc

    # 3) Legacy: first '{' through last '}' (last resort).
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("No JSON object found in model output")
    try:
        return _must_be_json_dict(
            json.loads(text[start : end + 1]),
            ctx="JSON between first '{' and last '}'",
        )
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON between first '{{' and last '}}': {exc}") from exc


def _raw_preview(text: str, *, limit: int = 2000) -> str:
    s = (text or "").strip()
    if not s:
        return "(empty)"
    if len(s) > limit:
        return s[:limit] + "\n... [truncated]"
    return s


def parse_tool_selection(text: str) -> MultiToolSelection:
    raw = _strip_redacted_thinking((text or "").strip())
    preview = _raw_preview(raw)
    try:
        data: dict
        try:
            data = extract_json_object(raw)
        except ValueError as json_exc:
            native = try_extract_lfm2_native_tool_call(raw)
            if native is None:
                raise ValueError(f"{json_exc}. Raw output (preview):\n{preview}") from json_exc
            data = native
        if not isinstance(data, dict):
            raise ValueError(
                f"Parsed tool data must be an object, got {type(data).__name__}. "
                f"Raw output (preview):\n{preview}"
            )
        coerced = _coerce_multi_tool_dict(data)
        return MultiToolSelection.model_validate(coerced)
    except TypeError as exc:
        if os.environ.get("AGENT_DEBUG_TOOL_PARSE", "").strip().lower() in ("1", "true", "yes"):
            print(f"[AGENT_DEBUG_TOOL_PARSE] model text ({len(raw)} chars):\n{raw}\n---", flush=True)
        raise ValueError(
            f"TypeError while parsing tool output: {exc}. "
            f"Set AGENT_DEBUG_TOOL_PARSE=1 to print full model text. "
            f"Raw output (preview):\n{preview}"
        ) from exc
    except ValidationError as exc:
        raise ValueError(
            f"JSON parsed but does not match multi-tool schema: {exc}. "
            f"Raw output (preview):\n{preview}"
        ) from exc
