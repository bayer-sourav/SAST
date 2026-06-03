# Re-run required after prompt fix (v2)

Runs produced before **2026-06-01** used `unified-4label-v1` task.md that included:

- `repo_root (host)` paths like `.../BenchmarkJava/tp/test/...` (corpus track leakage)
- `fewshot_3` cells without few-shot text in `task.md` (few-shot was system-only and not persisted)

Fixed in `unified-4label-v2` (+ `-fewshot3` variant).

## Invalidate and re-run

```bash
cd /home/ec2-user/Projects/SAST

# Option A: force re-inference (rebuilds task.md when version mismatches)
PHASE2_FORCE=1 bash benchmark/phases/phase2/run_phase2_matrix.sh

# Option B: delete stale task.md under phase2 runs, then normal resume
find runs/phase2 -name task.md -delete
bash benchmark/phases/phase2/run_phase2_matrix.sh
```

Prior `agent-llm-triage-result.json` files from contaminated prompts should be replaced (`PHASE2_FORCE=1` or delete result JSON too).

Verify one cell:

```bash
head -30 runs/phase2/tp/thinking_off/fewshot_3/qwen3_4b_bnb/llm/BenchmarkTest00021/task.md
# Expect: unified-4label-v2-fewshot3, ## Few-shot examples, NO repo_root line
```
