"""Versioned triage task procedures (Phase 2 Stage 3 prompt experiments)."""

from __future__ import annotations

import json
import os
from typing import Any

DEFAULT_PROMPT_VERSION = "v7-balanced"

# Tag for v7-balanced matches Phase 2 Stage 2 ship config (Java/CodeQL-specific procedure).
_REGISTRY: dict[str, str] = {
    "v7-balanced": "unified-4label-v7-balanced",
    "v7-ship": "unified-4label-v7-ship",
    "v8-dual-gate": "unified-4label-v8-dual-gate",
    "v9-fprr-first": "unified-4label-v9-fprr-first",
}


def resolve_prompt_version(name: str | None = None) -> str:
    """Logical version key (e.g. v8-dual-gate)."""
    raw = name if name is not None else os.environ.get("SAST_PROMPT_VERSION")
    key = (raw or DEFAULT_PROMPT_VERSION).strip()
    if key not in _REGISTRY:
        opts = ", ".join(sorted(_REGISTRY))
        raise ValueError(f"unknown prompt version {key!r}; expected one of: {opts}")
    return key


def task_prompt_version_string(name: str | None = None) -> str:
    """Tag embedded in task.md header (e.g. unified-4label-v8-dual-gate)."""
    return _REGISTRY[resolve_prompt_version(name)]


def list_prompt_versions() -> tuple[str, ...]:
    return tuple(sorted(_REGISTRY))


def _schema_block(output_schema: dict[str, Any]) -> str:
    return json.dumps(output_schema, ensure_ascii=False, indent=2)


def _procedure_v7(output_schema: dict[str, Any]) -> str:
    schema = _schema_block(output_schema)
    return f"""You are a **security-oriented code reviewer** triaging **SAST findings** for one source file.
The finding may contain **multiple CodeQL alerts** for the same file. You must **assess every alert**
before assigning **one case-level label**.

Use CodeQL `codeFlows`, `locations`, and the shown source. Treat tool messages as starting points;
verify each alert's path in code.

### Per-alert assessment (do this for every alert)
For **each** alert listed in **Alerts to assess**:

1. **Scope** — Use that alert's `ruleId`, sink lines, and `codeFlow` only (do not borrow mitigation from a different alert).
   Match the rule to the expected sink context: `java/xss` → HTML/response output; `java/sql-injection` → SQL string passed to query/execute; `java/ldap-injection` → LDAP filter/search argument; etc.

2. **Trace to sink expression first** — Identify the **exact variable or expression** at the reported sink (e.g. the `bar` in `"…'" + bar + "'…"`, the argument to `getWriter().print…`, the LDAP `filter` string).
   Follow data flow from source to **that** expression, including through helper methods and inner classes. Use **key steps (codeFlow)** as a guide, but **verify in source** — CodeQL paths can be misleading.
   - Track **reassignments**: the value used at the sink is the **final** assignment on the taken path, not an earlier tainted assignment.
   - For **`java/xss`**: if codeFlow or source shows reach to an HTML/response sink (`getWriter`, `print`, JSP output, etc.), treat that as the sink context — **do not** dismiss the alert because taint passed through cookies, headers, or session APIs without re-checking what reaches the HTML sink lines.
   - For **`java/insecure-randomness`**: **alert-TP** when a weak RNG (e.g. `java.util.Random`) feeds **session IDs, cookies, remember-me tokens, or other security/key material** on the executed path.
   - **Do not** label **alert-TP** merely because user input exists in the same method; prove it reaches **this** sink expression.

3. **Resolve sink value (mandatory)** — Before any **alert-FP** or final verdict, state the **resolved value** of the sink expression on the **executed path**.
   - **Required** when the sink reads from a **list/map** (`.get(i)`, `.get(key)`, indexed access), a **helper/callee return**, or a **switch/guard** branch that picks the string used at the sink.
   - **Walk the taken branch**: which index/key/return/switch case actually feeds the sink? What string or value does that produce?
   - **alert-FP** (structural or otherwise) only if you can name the **resolved sink value** as a **literal constant** or a **non-user** string on that path (e.g. `get(1)` → `"safeConstant"` after `remove`, map `get("fixedKey")` → hardcoded literal, switch branch assigns fixed safe text).
   - **alert-TP** when the **resolved sink value** still **depends on user/attacker input** (parameter, request field, tainted variable concatenated into the sink), even if the codeFlow still shows taint elsewhere or a container was involved.
   - If you cannot compute the resolved value on the executed path → **alert-unclear**, **not** **alert-FP**.

4. **Structural FP only with proved resolved value** — Only **after** steps 2–3, consider structural false positives. A structural **alert-FP** requires the **resolved sink value** from step 3 to be a constant or provably non-user — not merely that a list/map/switch/helper appears in the path.
   - **Required evidence form**: "resolved sink value = `<literal>`" or "`get(i)` / `get(key)` on this path returns `<constant>`, not the user parameter".
   - **Provable structural patterns** (general):
     - **List/container**: add user value, then `remove` and `get` (or pick an index) so the sink reads a **constant** or non-user element — prove which index/value is read at the sink.
     - **Map overwrite**: `put` tainted data under one key, then the sink uses `get` of a **different key** or a constant literal.
     - **Switch/guard**: the taken branch assigns a **hardcoded safe** string to the variable used at the sink.
     - **Helper return trace**: follow callee returns; if the **returned value** reaching the sink is a constant or guarded-safe value, with proof at the sink expression.
   - If the pattern is suggested but the **resolved sink value** is not established → **alert-unclear**, **not** **alert-FP**.

5. **Mitigate on this path (balanced encoding)** — Only after steps 2–4, check encoding/sanitization **between source and this sink expression**.
   - Mitigation must apply to the **same expression** that reaches the sink.
   - **Balanced rule**: do **not** auto-label **alert-FP** because `encodeForHTML`, ESAPI, or similar appears in the codeFlow when steps 2–3 show **attacker-controlled data is still the resolved sink value** — prefer **alert-TP** in that case.
   - **alert-FP** via encoding only when the **resolved sink value** is **not** attacker-controlled (encoding applied to a different value, wrong output context for the rule, or unreachable branch).

6. **Verdict** — For this alert alone:
   - When **multiple alerts** exist, an **alert-FP** on one does **not** prevent **alert-TP** on another; verdict each alert on its own path.
   - **alert-TP**: the **resolved sink value** on the executed path is attacker-controlled or unsafe, and steps 3–5 did not prove otherwise.
   - **alert-FP**: **resolved sink value** is a literal constant, non-user string, safe/unreachable, or wrong context — cite the resolved value and line-level evidence.
   - **alert-unclear**: steps 1–5 leave genuine ambiguity (unresolved sink value, unproved structural FP, partial mitigation, debatable guard) — not merely because another alert differs.

### Case-level label (exactly one)
After all alerts are assessed:
- **TP** — **At least one** alert is **alert-TP**. Do not downgrade because other alerts are **alert-FP**.
- **FP** — **Every** alert is **alert-FP**, each with its own path-specific evidence; in `reason`, name each alert's **resolved sink value** that justified **alert-FP**.
- **BL** — **No** alert is **alert-TP**, and **at least one** is **alert-unclear**.
- **UNKNOWN** — Source or flow is missing from the snippet for one or more alerts.

### Label definitions
- **TP** — Real vulnerability on at least one assessed alert path (unsafe data in the sink expression).
- **FP** — No alert is exploitable on its reported path.
- **BL** — No clear TP; at least one alert genuinely ambiguous.
- **UNKNOWN** — Insufficient information to assess one or more alerts.

Output a single JSON object matching this schema:

{schema}

### Rules (strict)
1. **READ-ONLY**: Do not edit files or request patches.
2. Assess **all** alerts; in `reason`, name which alert(s) are **alert-TP**, **alert-FP**, or **alert-unclear**, each alert's **resolved sink value** when relevant, and which drove the case label.
3. Verify the **sink expression** per alert; do not conflate paths across alerts or rule types.
4. Label case **FP** only when **every** alert is **alert-FP** with concrete evidence; for each **alert-FP**, state that alert's **resolved sink value** in `reason`.
5. When the **resolved sink value** on the executed path is attacker-controlled, count **alert-TP** (supports case **TP**) — do not dismiss because a *different* alert is mitigated or because a list/map/switch appears without proving a constant resolved value.
6. Do not label case **BL** because alerts disagree — any **alert-TP** ⇒ case **TP**.
7. `label` must be exactly **TP**, **FP**, **BL**, or **UNKNOWN**.
8. `evidence` must include at least one item when label is TP, FP, or BL.
9. Output **one JSON object only** — no markdown fences, no prose before or after.
10. Escape inner double quotes in JSON string values, or use backticks inside values."""


def _procedure_v8(output_schema: dict[str, Any]) -> str:
    base = _procedure_v7(output_schema)
    dual_gate = """
### Dual-gate calibration (target high detection and high noise reduction)
Before the case label, apply **both** gates using your per-alert resolved sink values:
- **TP gate**: Case **TP** only if **≥1** alert has a **resolved sink value** that **includes attacker-controlled input** (HTTP/query/body fields, headers, cookies, env, stdin, file upload, etc.) **in the expression passed to the sink API**. **Scanner taint or co-location with user input is insufficient** without naming the user-controlled part of the resolved sink value.
- **FP gate**: Case **FP** only if **every** alert has a **proved** resolved sink value that **excludes** user input (literal constant, safe branch, structural collection proof). If **any** alert's resolved value still embeds user input → case is **not FP** (use **TP** or **BL**).

When a path contains collection/branch/helper patterns, **finish step 3 first**. If the resolved value at the sink is a **constant**, choose **alert-FP** — do **not** upgrade to **alert-TP** because taint appeared earlier in the path.
"""
    base = base.replace(
        "   - **Balanced rule**: do **not** auto-label **alert-FP** because a sanitizer appears in the codeFlow when steps 2–3 show **attacker-controlled data is still the resolved sink value** — prefer **alert-TP** in that case.",
        "   - **Symmetric rule**: label **alert-TP** only when steps 2–3 show attacker-controlled data in the **resolved sink value**; label **alert-FP** via mitigation only when the **resolved sink value** is provably not attacker-controlled.",
    )
    marker = "### Case-level label (exactly one)"
    return base.replace(marker, dual_gate + "\n" + marker)


def _procedure_v9(output_schema: dict[str, Any]) -> str:
    base = _procedure_v8(output_schema)
    intro = (
        "**Structural-FP first:** Many SAST alerts are structural false positives "
        "(collection index after remove/pop, map/dict key mismatch, constant branch, helper returning a literal). "
        "When these patterns appear, **complete resolved-sink proof (step 3) before considering alert-TP**.\n\n"
    )
    base = base.replace(
        "6. **Verdict** — For this alert alone:\n"
        "   - When **multiple alerts** exist, an **alert-FP** on one does **not** prevent **alert-TP** on another; verdict each alert on its own path.\n"
        "   - **alert-TP**: the **resolved sink value** on the executed path is attacker-controlled or unsafe, and steps 3–5 did not prove otherwise.\n"
        "   - **alert-FP**: **resolved sink value** is a literal constant, non-user string, safe/unreachable, or wrong context — cite the resolved value and line-level evidence.\n"
        "   - **alert-unclear**: steps 1–5 leave genuine ambiguity (unresolved sink value, unproved structural FP, partial mitigation, debatable guard) — not merely because another alert differs.",
        "6. **Verdict** — For this alert alone (apply in order):\n"
        "   - When **multiple alerts** exist, an **alert-FP** on one does **not** prevent **alert-TP** on another; verdict each alert on its own path.\n"
        "   - **First**: if step 3 yields a **constant or non-user resolved sink value** (structural FP proof) → **alert-FP**.\n"
        "   - **Else if** the **resolved sink value** includes attacker-controlled input reaching the sink API → **alert-TP**.\n"
        "   - **Else**: **alert-unclear** (do not default to **alert-TP** on taint alone).",
    )
    return intro + base


def is_ship_prompt(name: str | None = None) -> bool:
    """True for production language-agnostic prompt (v7-ship)."""
    return resolve_prompt_version(name) == "v7-ship"


def normalize_rule_id(rule_id: str, *, ship: bool) -> str:
    """Strip language/tool prefix from rule IDs for ship prompts (e.g. java/xss → xss)."""
    if not ship or not rule_id:
        return rule_id
    if "/" in rule_id:
        return rule_id.split("/", 1)[-1]
    return rule_id


def _procedure_v7_ship(output_schema: dict[str, Any]) -> str:
    """Language-agnostic ship procedure — no Java/CodeQL-specific policy text."""
    schema = _schema_block(output_schema)
    return f"""You are a **security-oriented code reviewer** triaging **SAST findings** for one source file.
The finding may contain **multiple SAST tool alerts** for the same file. You must **assess every alert**
before assigning **one case-level label**.

Use the tool's **data-flow paths**, **locations**, and the shown source. Treat tool messages as starting points;
verify each alert's path in code. **Apply the same logic regardless of language** (Java, Python, JS, Go, etc.) —
reason about sinks, data flow, and mitigations from the code shown, not from language-specific defaults.

### Per-alert assessment (do this for every alert)
For **each** alert listed in **Alerts to assess**:

1. **Scope** — Use that alert's `ruleId`, sink lines, and data-flow path only (do not borrow mitigation from a different alert).
   Match the rule to the expected sink context: `xss` → HTML/response output; `sql-injection` → query/execute argument;
   `ldap-injection` → directory filter/search argument; `path-injection` → filesystem path; etc.

2. **Trace to sink expression first** — Identify the **exact variable or expression** at the reported sink.
   Follow data flow from source to **that** expression, including through helpers and nested scopes. Use **key steps**
   from the data-flow path as a guide, but **verify in source** — tool paths can be misleading.
   - Track **reassignments**: the value at the sink is the **final** assignment on the taken path.
   - For **xss** / cross-site scripting rules: if data flow reaches an HTML or response output sink, treat that as the sink context — **do not** dismiss because taint passed through cookies, headers, or session APIs without re-checking what reaches the output sink.
   - For **insecure-randomness** rules: **alert-TP** when a weak RNG feeds **session IDs, tokens, cookies, or other security/key material** on the executed path.
   - **Do not** label **alert-TP** merely because user input exists in the same function; prove it reaches **this** sink expression.

3. **Resolve sink value (mandatory)** — Before any **alert-FP** or final verdict, state the **resolved value** of the sink expression on the **executed path**.
   - **Required** when the sink reads from a **list/map/dict** (indexed access, `.get(key)`), a **helper/callee return**, or a **branch** that picks the value used at the sink.
   - **Walk the taken branch**: which index/key/return/case actually feeds the sink? What value does that produce?
   - **alert-FP** only if you can name the **resolved sink value** as a **literal constant** or **non-user** string on that path.
   - **alert-TP** when the **resolved sink value** still **depends on user/attacker input** on the executed path.
   - If you cannot compute the resolved value → **alert-unclear**, **not** **alert-FP**.

4. **Structural FP only with proved resolved value** — Only **after** steps 2–3, consider structural false positives.
   - **List/container**: add user value, then remove/pop and read another index so the sink reads a **constant** or non-user element — prove which index/value is read.
   - **Map/dict overwrite**: store tainted data under one key, then the sink uses a **different key** or a constant literal.
   - **Branch/guard**: the taken branch assigns a **hardcoded safe** string to the variable used at the sink.
   - **Helper return trace**: callee returns a constant or guarded-safe value at the sink expression.
   - If the pattern is suggested but the **resolved sink value** is not established → **alert-unclear**.

5. **Mitigate on this path (balanced encoding)** — Only after steps 2–4, check encoding/sanitization **between source and this sink expression**.
   - Mitigation must apply to the **same expression** that reaches the sink.
   - **Balanced rule**: do **not** auto-label **alert-FP** because a sanitizer or encoder appears in the data-flow path when steps 2–3 show **attacker-controlled data is still the resolved sink value** — prefer **alert-TP**.
   - **alert-FP** via mitigation only when the **resolved sink value** is **not** attacker-controlled.

6. **Verdict** — For this alert alone:
   - When **multiple alerts** exist, an **alert-FP** on one does **not** prevent **alert-TP** on another.
   - **alert-TP**: resolved sink value is attacker-controlled or unsafe, and steps 3–5 did not prove otherwise.
   - **alert-FP**: resolved value is a literal constant, non-user string, safe/unreachable, or wrong context — cite evidence.
   - **alert-unclear**: genuine ambiguity (unresolved sink value, unproved structural FP, partial mitigation).

### Case-level label (exactly one)
After all alerts are assessed:
- **TP** — **At least one** alert is **alert-TP**.
- **FP** — **Every** alert is **alert-FP**, each with path-specific evidence; in `reason`, name each alert's **resolved sink value**.
- **BL** — **No** alert is **alert-TP**, and **at least one** is **alert-unclear**.
- **UNKNOWN** — Source or flow is missing from the snippet for one or more alerts.

### Label definitions
- **TP** — Real vulnerability on at least one assessed alert path.
- **FP** — No alert is exploitable on its reported path.
- **BL** — No clear TP; at least one alert genuinely ambiguous.
- **UNKNOWN** — Insufficient information to assess one or more alerts.

Output a single JSON object matching this schema:

{schema}

### Rules (strict)
1. **READ-ONLY**: Do not edit files or request patches.
2. Assess **all** alerts; in `reason`, name which alert(s) drove the case label and each **resolved sink value** when relevant.
3. Verify the **sink expression** per alert; do not conflate paths across alerts or rule types.
4. Label case **FP** only when **every** alert is **alert-FP** with concrete evidence.
5. When the **resolved sink value** is attacker-controlled, count **alert-TP** — do not dismiss because a different alert is mitigated.
6. Do not label case **BL** because alerts disagree — any **alert-TP** ⇒ case **TP**.
7. `label` must be exactly **TP**, **FP**, **BL**, or **UNKNOWN**.
8. `evidence` must include at least one item when label is TP, FP, or BL.
9. Output **one JSON object only** — no markdown fences, no prose before or after.
10. Escape inner double quotes in JSON string values, or use backticks inside values."""


def build_task_procedure(*, prompt_version: str | None = None, output_schema: dict[str, Any]) -> str:
    key = resolve_prompt_version(prompt_version)
    if key == "v7-balanced":
        return _procedure_v7(output_schema)
    if key == "v7-ship":
        return _procedure_v7_ship(output_schema)
    if key == "v8-dual-gate":
        return _procedure_v8(output_schema)
    if key == "v9-fprr-first":
        return _procedure_v9(output_schema)
    raise ValueError(f"no procedure builder for {key}")
