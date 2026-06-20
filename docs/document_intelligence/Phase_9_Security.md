# Phase 9 — Security & Compliance (Optional)
**Depends on: none (can be applied to any completed phase)**
**Status: Not started. Decide whether to apply before running on real private data.**

---

## Goal
Harden the data path because documents are **private petroleum data** and VLM/MinerU
processing runs on **rented third-party hardware**.  This phase is self-contained —
nothing in Phases 0–8 depends on it — but it must be applied before handling
export-restricted or contract-restricted documents on rented nodes.

---

## Decision checklist (do this first)

Before implementing any sub-phase, answer:
1. Are any documents export-controlled (e.g. ITAR, EAR)?  If yes, rented third-party
   hardware may be prohibited — confirm with legal.
2. Does the data-processing agreement with the GPU provider permit storing private
   petroleum data on their infrastructure?
3. What is the required encryption standard (AES-256-GCM at rest, TLS 1.3 in transit)?

Record the decision and provider choice in `docs/COMPLIANCE_DECISIONS.md`.

---

## P9.1 — Private network + TLS

### Goal
The VLM and MinerU endpoints must only be reachable from the application server —
never from the public internet.

### Implementation options (choose one)

**Option A — Private network via Tailscale:**
1. Install Tailscale on the app server and the rented GPU node.
2. Use the Tailscale IP of the node as `OPENAI_BASE_URL` instead of its public IP.
3. No firewall change needed on the node — the public port can be closed.

**Option B — WireGuard VPN:**
1. Set up a WireGuard peer on the app server.
2. On the GPU node, start a WireGuard interface and configure the app server as a peer.
3. Use the WireGuard interface IP in `OPENAI_BASE_URL`.

**Option C — Provider private networking (if supported):**
Some GPU providers (Lambda Labs, CoreWeave) support private VPC networking.
Prefer this if available — no VPN software to maintain.

### TLS

If using Tailscale or WireGuard, connections already travel over an encrypted
tunnel and the VLM endpoint can listen on HTTP internally (the tunnel encrypts).
If the endpoint is reachable without a VPN for any reason, add TLS to vLLM:

```bash
vllm serve ... \
    --ssl-certfile /etc/ssl/certs/vlm.crt \
    --ssl-keyfile  /etc/ssl/private/vlm.key
```

### Acceptance check

From the public internet, `curl http://<node-public-ip>:8000/v1/models` must time out
or be refused.  From the app server (via VPN), it must succeed.

---

## P9.2 — At-rest encryption + scoped credentials

### Encrypt weights and artifacts in object storage

If using S3/MinIO, enable server-side encryption (SSE-S3 or SSE-KMS):

```python
# In storage_keys.py upload_bytes:
_client().put_object(
    Bucket=BUCKET, Key=key, Body=data,
    ServerSideEncryption="aws:kms",
    SSEKMSKeyId=os.getenv("S3_KMS_KEY_ID"),
)
```

Use a separate KMS key for the `porsa-models/` prefix (weights) and the
`documents/` prefix (artifacts), so credentials to read weights cannot read documents
and vice versa.

### Scoped credentials for the GPU node

Give each rented node a short-lived IAM/MinIO service account that can ONLY:
- `s3:GetObject` on `porsa-models/<model_slug>/` (to download weights).
- `s3:GetObject` + `s3:PutObject` on `documents/*/di/` (to read/write DI artifacts).
- Nothing else.

Revoke the credential at the end of the rented day (or automatically on expiry).

```python
# infra/scripts/create_node_credentials.py
# Run this locally before booting the node:

import boto3, datetime

iam = boto3.client("iam")
expiry = datetime.datetime.utcnow() + datetime.timedelta(hours=24)

# Create a temporary STS token scoped to the model and document prefixes
sts = boto3.client("sts")
response = sts.get_federation_token(
    Name=f"di-node-{node_id}",
    Policy=json.dumps({
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": ["s3:GetObject"],
                "Resource": f"arn:aws:s3:::porsa-models/{model_slug}/*",
            },
            {
                "Effect": "Allow",
                "Action": ["s3:GetObject", "s3:PutObject"],
                "Resource": "arn:aws:s3:::porsa-assets/documents/*/di/*",
            },
        ],
    }),
    DurationSeconds=86400,  # 24 hours
)
```

Print the credentials to pass to the node via the provider's `user_data`/env injection.

### Acceptance check

A credential issued for node A cannot `s3:GetObject` on `documents/*/mineru/` or on
any other prefix.  Attempting to do so returns `AccessDenied`.

---

## P9.3 — NVMe wipe checklist

Rented node disks are not wiped by the provider between customers.  Before you
stop the node, wipe the local weight cache and any document artifacts:

### Wipe script

`infra/scripts/wipe_nvme.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

echo "=== DI Node NVMe Wipe ==="
echo "This will delete all model weights and document artifacts from local disk."
echo "Run this before stopping/releasing the rented node."
read -p "Proceed? [y/N] " confirm
[[ "$confirm" == "y" ]] || { echo "Aborted."; exit 1; }

# Kill the serving process first
pkill -f "vllm serve" || true
pkill -f "magic_pdf.service" || true

# Wipe model weights
MODEL_CACHE="/mnt/nvme/models"
if [ -d "$MODEL_CACHE" ]; then
    echo "Wiping $MODEL_CACHE ..."
    rm -rf "$MODEL_CACHE"
    sync
fi

# Wipe any local document/artifact cache
DOC_CACHE="/tmp/di_artifacts"
if [ -d "$DOC_CACHE" ]; then
    echo "Wiping $DOC_CACHE ..."
    rm -rf "$DOC_CACHE"
    sync
fi

# Optional: secure wipe with shred (much slower, use only when required)
# find /mnt/nvme -type f -exec shred -u {} \;

echo "Wipe complete. Node is safe to release."
```

### Runbook step

Add to the Fleet Manager's "safe to shut down" notification:

```
⚠️  BEFORE STOPPING THE NODE:
  1. SSH into the node.
  2. Run: bash /entrypoint/wipe_nvme.sh
  3. Confirm the script prints "Wipe complete."
  4. Then stop/release the node in the provider dashboard.
```

### Acceptance check

After running the wipe script on a test node, `ls /mnt/nvme/models` returns
"No such file or directory".  No customer data remains on the node's local disk.

---

## Provider terms note

Before first use, verify that the selected provider's Terms of Service permit
storing private industrial/petroleum data on their infrastructure.  Preferred
providers for this use case:
- Providers offering dedicated (non-shared) bare metal.
- Providers that sign a Data Processing Agreement (DPA) on request.
- Providers whose nodes are in a region that matches your data-residency requirements.

Record the provider, DPA status, and data-residency region in `docs/COMPLIANCE_DECISIONS.md`.

---

## Acceptance checklist

- [ ] VLM endpoint is unreachable from the public internet; app server can reach it via VPN.
- [ ] Object-storage objects for the `porsa-models/` and `documents/*/di/` prefixes are server-side encrypted.
- [ ] Node credentials are time-limited (24 h max) and scoped to the two allowed S3 prefixes only.
- [ ] A leaked node credential cannot access `documents/*/mineru/` or other prefixes.
- [ ] `wipe_nvme.sh` exists in `infra/scripts/` and removes model weights and artifacts.
- [ ] Fleet Manager "safe to shut down" message includes the wipe runbook step.
- [ ] `docs/COMPLIANCE_DECISIONS.md` records provider, DPA status, and data-residency region.
