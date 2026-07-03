"""Triage API — enqueue advisory jobs and query status."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

_SAST = Path(__file__).resolve().parents[2]
if str(_SAST) not in sys.path:
    sys.path.insert(0, str(_SAST))

from integrations.github.pipeline import process_advisory_job  # noqa: E402
from integrations.github.sarif_to_case import load_sarif, sarif_to_cases, write_cases  # noqa: E402
from services.triage_api.job_store import JobStore  # noqa: E402

app = FastAPI(title="SAST Triage API", version="1.0.0")
store = JobStore()


class RepositoryRef(BaseModel):
    owner: str
    name: str
    clone_url: str | None = None


class AdvisoryRequest(BaseModel):
    delivery_id: str | None = None
    repository: RepositoryRef
    commit_sha: str
    pr_number: int | None = None
    installation_id: int | None = None
    sarif_b64: str | None = Field(default=None, description="Base64-encoded SARIF JSON")
    sarif_path: str | None = Field(default=None, description="Local path (dev only)")


def _verify_hmac(body: bytes, signature: str | None) -> None:
    secret = os.environ.get("TRIAGE_API_HMAC_SECRET")
    if not secret:
        return
    if not signature or not signature.startswith("sha256="):
        raise HTTPException(status_code=401, detail="missing signature")
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(f"sha256={expected}", signature):
        raise HTTPException(status_code=401, detail="invalid signature")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/advisory")
async def create_advisory(
    req: AdvisoryRequest,
    x_signature_sha256: str | None = Header(default=None),
) -> dict[str, Any]:
    raw = req.model_dump_json().encode("utf-8")
    _verify_hmac(raw, x_signature_sha256)

    payload = req.model_dump()
    job_id = store.create(payload)

    queue_url = os.environ.get("TRIAGE_QUEUE_URL")
    if queue_url:
        import boto3

        boto3.client("sqs").send_message(
            QueueUrl=queue_url,
            MessageBody=json.dumps({"job_id": job_id, **payload}),
        )
        return {"job_id": job_id, "status": "queued"}

    # Inline processing
    store.update(job_id, status="running")
    try:
        result = _process_inline(req)
        store.update(job_id, status="completed", result=result)
        return {"job_id": job_id, "status": "completed", "summary": result.get("summary")}
    except Exception as exc:  # noqa: BLE001
        store.update(job_id, status="failed", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/v1/advisory/{job_id}")
def get_advisory(job_id: str) -> dict[str, Any]:
    item = store.get(job_id)
    if not item:
        raise HTTPException(status_code=404, detail="job not found")
    out = {
        "job_id": job_id,
        "status": item.get("status"),
        "created_at": item.get("created_at"),
        "updated_at": item.get("updated_at"),
    }
    if item.get("result"):
        result = item["result"]
        out["summary"] = result.get("summary")
        out["findings"] = result.get("findings")
    if item.get("error"):
        out["error"] = item["error"]
    return out


def _process_inline(req: AdvisoryRequest) -> dict[str, Any]:
    if req.sarif_b64:
        sarif = json.loads(base64.b64decode(req.sarif_b64))
        work = Path(tempfile.mkdtemp(prefix="sast-advisory-"))
        sarif_path = work / "input.sarif"
        sarif_path.write_text(json.dumps(sarif), encoding="utf-8")
    elif req.sarif_path:
        sarif_path = Path(req.sarif_path)
        work = sarif_path.parent
    else:
        raise ValueError("sarif_b64 or sarif_path required")

    repo_path = work / "repo"
    repo_path.mkdir(exist_ok=True)
    if req.repository.clone_url:
        from integrations.github.github_auth import installation_token  # noqa: E402
        from integrations.github.github_client import GitHubClient  # noqa: E402

        token = installation_token(req.installation_id) if req.installation_id else None
        GitHubClient(token or "unused").clone_repo_at_sha(
            req.repository.clone_url,
            req.commit_sha,
            repo_path,
            token=token,
        )

    return process_advisory_job(
        owner=req.repository.owner,
        repo=req.repository.name,
        commit_sha=req.commit_sha,
        sarif_path=sarif_path,
        repo_clone_path=repo_path,
        work_dir=work,
        installation_id=req.installation_id,
        pr_number=req.pr_number,
        publish=req.installation_id is not None,
        sast_root=_SAST,
    )


def main() -> None:
    import uvicorn

    uvicorn.run(
        "services.triage_api.main:app",
        host=os.environ.get("API_HOST", "0.0.0.0"),
        port=int(os.environ.get("API_PORT", "8090")),
    )


if __name__ == "__main__":
    main()
