# autotriage-distributed

Distributed demo for auto-triage: two VMs, cross-VM calls, and leader/follower agents.

## GitHub push

From your machine (Windows/macOS/Linux), in the repo directory:

```bash
git init
git add .
# So scripts are executable when cloned on Linux (optional but recommended):
# On Linux/macOS: chmod +x deploy/vm1/render_prometheus.sh scripts/vm1/smoke_vm1.sh scripts/vm2/smoke_vm2.sh
# On Windows:     git update-index --chmod=+x deploy/vm1/render_prometheus.sh scripts/vm1/smoke_vm1.sh scripts/vm2/smoke_vm2.sh
git commit -m "initial"
git branch -M main
git remote add origin <GITHUB_URL>
git push -u origin main
```

Then on each Ubuntu VM, follow **[SETUP_ON_VMS.md](SETUP_ON_VMS.md)** for copy-paste setup commands.

## What’s distributed

- **VM1 (node-a)**: gateway, otel-collector, prometheus, grafana, jaeger, autotriage_agent.
- **VM2 (node-b)**: orders, payments, postgres (persistent volume), node_exporter, autotriage_agent.
- **Request path**: client → gateway (VM1) → orders (VM2) → payments (VM2) → back. Gateway calls only orders; orders calls payments on VM2. The cross-VM boundary is gateway ↔ orders.
- **Leader/follower**: One autotriage_agent is elected leader (e.g. via `leader.py`); only the leader runs diagnose/remediate; followers stand by.
- **Autotriage loop**: The leader periodically queries **Prometheus** (SLO-style thresholds on Flask metrics), samples **Jaeger** for error spans, and can call **payments `/admin/reset`** (Bearer `ADMIN_TOKEN`) after simulated incidents.

## Ports

**VM1 (node-a):**
- gateway: 8000
- jaeger: 16686
- prometheus: 9090
- grafana: 3000

**VM2 (node-b):**
- orders: 8000
- payments: 8001
- postgres: **5432** (published for cross-VM leader election; restrict with firewall in real deployments)
- node_exporter: 9100

## Security note (class demo)

All service and admin traffic uses **plain HTTP** and a shared **ADMIN_TOKEN** for `/admin/*` on payments. **Grafana/Jaeger/Prometheus** are also unencrypted. This is intentional for the lab but **not** production-safe; the course report calls out TLS, network policies, and stronger auth as required hardening.

## Why this is distributed

- **Partial failure**: VM2 can fail or be partitioned while VM1 stays up (or the reverse); the agent must reason across nodes.
- **Network delay**: Latency and loss between VM1 and VM2 affect traces and metrics; chaos scripts (netem on VM2) exercise this.
- **Leader failover**: Agents on both VMs participate in leader election; when the leader dies, a follower on the other VM can take over.

## Deployment (reproducible)

Do **not** commit real `.env` files; use the examples and copy locally. On the VMs, if scripts are not executable after clone, run: `chmod +x deploy/vm1/render_prometheus.sh scripts/vm1/smoke_vm1.sh scripts/vm2/smoke_vm2.sh`.

### One-time setup per VM

**On node-b (VM2):**
```bash
cd deploy/vm2
cp .env.example .env
# Edit .env: VM1_IP and ADMIN_TOKEN (same token you set on VM1)
```

**On node-a (VM1):**
```bash
cd deploy/vm1
cp .env.example .env
# Edit .env: VM2_IP and ADMIN_TOKEN (must match VM2)
chmod +x deploy/vm1/render_prometheus.sh   # if not already executable after clone
./render_prometheus.sh   # generates prometheus.yml from prometheus.yml.tmpl
```

### Start stacks

Start **VM2 first**, then VM1 (gateway depends on orders being reachable).

**On node-b (VM2):**
```bash
cd deploy/vm2
docker compose up -d --build
```

**On node-a (VM1):**
```bash
cd deploy/vm1
docker compose up -d --build
```

### URLs (use node-a IP for gateway and observability)

Replace `NODE_A_IP` with your VM1/node-a address (e.g. `192.168.56.101`):

- Gateway: http://NODE_A_IP:8000
- Prometheus: http://NODE_A_IP:9090
- Grafana: http://NODE_A_IP:3000 (admin / admin)
- Jaeger: http://NODE_A_IP:16686

### Smoke checks

From any host with curl (use node-a or node-b IP as needed). If scripts are not executable after clone, run: `chmod +x scripts/vm1/smoke_vm1.sh scripts/vm2/smoke_vm2.sh`.

```bash
# VM1: gateway health and checkout
./scripts/vm1/smoke_vm1.sh http://NODE_A_IP:8000

# VM2: orders and payments health
./scripts/vm2/smoke_vm2.sh http://NODE_B_IP:8000 http://NODE_B_IP:8001
```

## Metrics and traces to watch

- **Prometheus** (node-a:9090): gateway (node-a), orders and payments (node-b:8000, :8001), node_exporter (node-b:9100). Watch rate, error rate, latency when injecting chaos on VM2.
- **Grafana** (node-a:3000): AutoTriage dashboard for rate, errors, p99.
- **Jaeger** (node-a:16686): Traces for /checkout: gateway (node-a) → orders (node-b) → payments (node-b); inspect spans across the boundary and within VM2.

Chaos scripts on VM2: `scripts/vm2/netem_apply.sh`, `netem_clear.sh`, `crash.sh`, `restart.sh`. Load gen on VM1: `scripts/vm1/loadgen.sh`, `run_experiments.sh`.

## Autotriage experiments (payments degradation)

With stacks running and `ADMIN_TOKEN` set the same on VM1/VM2, inject artificial latency/errors on **payments** (from any host that can reach VM2):

```bash
export NODE_B=http://NODE_B_IP:8001
export ADMIN_TOKEN=change-me-class-demo
curl -s -X POST "$NODE_B/admin/degrade" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"delay_ms": 800, "error_rate": 0.35}'
```

Run `./scripts/vm1/loadgen.sh http://NODE_A_IP:8000 120` and watch Grafana / Prometheus. The **leader** autotriage agent should detect elevated 5xx/p99 and POST `/admin/reset` on payments. Check logs: `docker compose logs -f autotriage_agent` on VM1 or VM2.

Clear degradation manually if needed:

```bash
curl -s -X POST "$NODE_B/admin/reset" -H "Authorization: Bearer $ADMIN_TOKEN"
```
