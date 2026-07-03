# GitHub Advisory Triage

Advisory AI triage for **CodeQL** findings on GitHub Enterprise. Posts informational check-run annotations and PR summaries. **Does not** dismiss alerts or block merges.

## Inference config (language-agnostic)

Uses **Stage 2 quality intent** with a **language-agnostic** prompt:

| Knob | Value |
|------|-------|
| Model | Qwen3.5-9B (base — no LoRA) |
| Prompt | `v7-ship` |
| Thinking | on |
| Few-shot | 0 |

Source: `integrations/github/MANIFEST.json`

## Architecture

```
CodeQL workflow → SARIF artifact → GitHub App webhook
    → SQS job queue → GPU worker (vLLM)
    → SARIF → cases (multi-file snippets) → inference
    → GitHub publisher (neutral check run + PR comment)
```

## Quick start (local CLI)

```bash
cd /path/to/SAST
source integrations/github/github_env.sh
pip install -r integrations/github/requirements.txt

# SARIF + repo clone → case JSON (multi-file source→sink snippets)
python -m integrations.github.sarif_to_case \
  --sarif /tmp/results.sarif \
  --repo /tmp/my-repo \
  --owner acme --repo-name myapp \
  --out /tmp/cases/

# Run inference (requires vLLM + model loaded)
python -m integrations.github.triage_worker \
  --cases /tmp/cases --out /tmp/advisory/

# Publish (dry-run)
python -m integrations.github.github_publish \
  --advisory /tmp/advisory/job.json \
  --owner acme --repo myapp \
  --commit abc123 --installation-id 12345 \
  --pr 42 --dry-run
```

## GitHub App setup

### 1. Create the App

**Option A — manifest (recommended)**

1. Edit `integrations/github/app/manifest.yml` — set `hook_attributes.url` to your ALB URL + `/webhook/github`.
2. Create a manifest conversion URL in GitHub Enterprise settings, or use:

```bash
# Encode manifest and open GitHub App creation flow (Enterprise Server docs vary)
cat integrations/github/app/manifest.yml
```

**Option B — manual**

| Setting | Value |
|---------|-------|
| Name | SAST Advisory Triage |
| Webhook URL | `https://<ALB_DNS>/webhook/github` |
| Webhook secret | Strong random string (store in Secrets Manager) |
| Permissions | Contents **Read**, Actions **Read**, Checks **Write**, PRs **Write**, Metadata **Read** |
| Events | **Workflow run** |
| Where | Only on this account |

**Do not** grant `security_events: write` (no auto-dismiss).

### 2. Install the App

Install on target org/repos. Note the **Installation ID** (visible in webhook payloads or API).

### 3. Generate a private key

App settings → **Generate a private key** → store PEM in AWS Secrets Manager (`deploy/cloudformation` creates `…/github-app-private-key`).

### 4. Customer CodeQL workflow

Add a fixed artifact name the service expects:

```yaml
- name: Upload SARIF for triage
  uses: actions/upload-artifact@v4
  with:
    name: codeql-sarif
    path: results/*.sarif
    retention-days: 7
```

Workflow name must contain `CodeQL` (configurable in `MANIFEST.json` → `codeql_workflow_name_filter`).

## AWS deployment (CloudFormation)

```bash
aws cloudformation deploy \
  --template-file deploy/cloudformation/triage-stack.yaml \
  --stack-name sast-advisory \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
    VpcId=vpc-xxx \
    PublicSubnetIds=subnet-a,subnet-b \
    PrivateSubnetIds=subnet-c,subnet-d \
    ContainerImage=123456789012.dkr.ecr.us-east-1.amazonaws.com/sast-advisory:latest \
    AcmCertificateArn=arn:aws:acm:... \
    GitHubWebhookSecret=... \
    TriageApiHmacSecret=... \
    GitHubAppId=123456 \
    KeyPairName=my-key
```

After deploy, set the stack output `WebhookUrl` in your GitHub App.

### Build & push container

```bash
aws ecr create-repository --repository-name sast-advisory
docker build -f services/triage_api/Dockerfile -t sast-advisory .
docker tag sast-advisory:latest $ECR_URI:latest
docker push $ECR_URI:latest
```

GPU worker EC2 instances poll SQS and run `services.triage_api.worker`. **vLLM must be running** on the GPU host (Deep Learning AMI + model weights). Point `ModelArtifactS3Uri` at merged weights if not baked into the AMI.

## Webhook server (dev)

```bash
export GITHUB_WEBHOOK_SECRET=...
export GITHUB_APP_ID=...
export GITHUB_APP_PRIVATE_KEY_PATH=/path/to.pem
uvicorn integrations.github.app.webhook_server:app --host 0.0.0.0 --port 8080
```

With `TRIAGE_QUEUE_URL` unset, webhooks process **inline** (single-node dev).

## Multi-file CodeQL reports

Each SARIF result becomes one case. `snippet_extract.py` walks `codeFlows` and `locations` across **all files** in the source→sink path and injects numbered snippets into the triage prompt (see `benchmark/make_task.py` → `code_snippets`).

## Tests

```bash
python -m unittest integrations.github.tests.test_sarif_to_case
```

## Files

| Path | Purpose |
|------|---------|
| `sarif_to_case.py` | SARIF → benchmark case JSON |
| `snippet_extract.py` | Multi-file source→sink snippets |
| `pipeline.py` | End-to-end job orchestration |
| `triage_worker.py` | Batch inference |
| `github_publish.py` | Check runs + PR comments |
| `app/webhook_server.py` | GitHub webhook receiver |
| `services/triage_api/` | REST API + SQS worker |
| `deploy/cloudformation/triage-stack.yaml` | AWS stack |
