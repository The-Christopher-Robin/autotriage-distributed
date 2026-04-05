# autotriage-distributed

Distributed auto-triage system with ML-powered anomaly detection, multi-agent remediation, and real-time ops monitoring. Two VMs, cross-VM calls, leader/follower agents, and a full observability stack.

## Architecture

```
┌─────────────── VM1 (node-a) ───────────────┐     ┌─────────────── VM2 (node-b) ───────────────┐
│                                             │     │                                             │
│  ┌──────────┐   ┌────────────────────────┐  │     │  ┌──────────┐  ┌──────────┐                │
│  │ Gateway   │──▶│ OTel Collector         │  │     │  │ Orders   │──│ Payments │                │
│  │ :8000     │   │ :4317/:4318            │  │     │  │ :8000    │  │ :8001    │                │
│  └────┬──────┘   └────┬──────────────┬────┘  │     │  └────┬─────┘  └────┬─────┘                │
│       │               │              │       │     │       │             │                      │
│       │          ┌─────▼─────┐  ┌────▼────┐  │     │  ┌────▼─────────────▼────┐                │
│       │          │ Prometheus│  │ Jaeger  │  │     │  │   PostgreSQL :5432    │                │
│       │          │ :9090     │  │ :16686  │  │     │  │  (orders, diagnoses,  │                │
│       │          └───────────┘  └─────────┘  │     │  │   remediations,      │                │
│       │               │                      │     │  │   advisory locks)    │                │
│  ┌────▼──────┐  ┌─────▼─────┐                │     │  └──────────────────────┘                │
│  │ Grafana   │  │ AutoTriage│                │     │       │                                   │
│  │ :3000     │  │ Agent     │                │     │  ┌────▼─────────┐  ┌──────────┐          │
│  └───────────┘  │ (leader)  │                │     │  │ AutoTriage   │  │ Node     │          │
│                 └───────────┘                │     │  │ Agent        │  │ Exporter │          │
│  ┌──────────────┐                            │     │  │ (follower)   │  │ :9100    │          │
│  │ Streamlit    │                            │     │  └──────────────┘  └──────────┘          │
│  │ Dashboard    │                            │     │                                          │
│  │ :8501        │                            │     │                                          │
│  └──────────────┘                            │     │                                          │
└─────────────────────────────────────────────┘     └──────────────────────────────────────────┘
```

### Request path
`client → gateway (VM1) → orders (VM2) → payments (VM2) → back`

### Multi-agent architecture
- **Leader election**: PostgreSQL advisory locks ensure exactly one agent runs diagnosis/remediation at a time across both VMs.
- **PyTorch anomaly detection**: A transformer encoder processes sliding windows of `[error_rate, latency_p99, request_rate]` to produce anomaly scores and type classifications (latency spike, error burst, throughput drop).
- **Rule-based diagnosis**: Deterministic rules check Prometheus SLO thresholds and Jaeger error spans for specific remediation recommendations.
- **Combined signals**: The ML model detects *that* something is anomalous; the rules determine *what* to do about it. ML can elevate severity when rules show no SLO breach yet.
- **Alert routing**: Diagnosis results route to configured channels (webhook, Slack, log file, PostgreSQL) with deduplication.
- **Automated remediation**: Leader agent POSTs `/admin/reset` to clear simulated faults, with timing tracked for MTTR.

### Data persistence (PostgreSQL)
- `orders` — real order records created on each `/checkout`
- `diagnosis_log` — every diagnosis with ML anomaly scores and rule results
- `remediation_log` — every remediation action with duration for MTTR tracking
- `alert_log` — all routed alerts with deduplication keys

### Streamlit dashboard
Ops monitoring UI (`http://VM1:8501`) showing:
- Real-time service health status
- Recent diagnoses with ML anomaly scores
- Alert frequency over time
- MTTR (mean time to resolution) charts
- Remediation history
- Live Prometheus error rate and latency graphs

## GitHub push

From your machine (Windows/macOS/Linux), in the repo directory:

```bash
git init
git add .
git commit -m "initial"
git branch -M main
git remote add origin <GITHUB_URL>
git push -u origin main
```

Then on each Ubuntu VM, follow **[SETUP_ON_VMS.md](SETUP_ON_VMS.md)** for copy-paste setup commands.

## What's distributed

- **VM1 (node-a)**: gateway, otel-collector, prometheus, grafana, jaeger, autotriage_agent, streamlit dashboard.
- **VM2 (node-b)**: orders, payments, postgres (persistent volume), node_exporter, autotriage_agent.
- **Request path**: client → gateway (VM1) → orders (VM2) → payments (VM2) → back. Gateway calls only orders; orders calls payments on VM2. The cross-VM boundary is gateway ↔ orders.
- **Leader/follower**: One autotriage_agent is elected leader (e.g. via `leader.py`); only the leader runs diagnose/remediate; followers stand by.
- **Autotriage loop**: The leader periodically queries **Prometheus** (SLO-style thresholds on Flask metrics), runs the **PyTorch transformer** for anomaly detection, samples **Jaeger** for error spans, routes **alerts** to configured channels, and can call **payments `/admin/reset`** (Bearer `ADMIN_TOKEN`) after simulated incidents.

## Ports

**VM1 (node-a):**
- gateway: 8000
- jaeger: 16686
- prometheus: 9090
- grafana: 3000
- streamlit dashboard: 8501

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
- **Streamlit Dashboard**: http://NODE_A_IP:8501

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
- **Streamlit** (node-a:8501): Real-time ops monitoring with diagnosis history, alert frequency, and MTTR charts.

Chaos scripts on VM2: `scripts/vm2/netem_apply.sh`, `netem_clear.sh`, `crash.sh`, `restart.sh`. Load gen on VM1: `scripts/vm1/loadgen.sh`, `run_experiments.sh`.

## Load generator

Sequential (default):
```bash
./scripts/vm1/loadgen.sh http://NODE_A_IP:8000 60
```

Concurrent mode (configurable parallelism):
```bash
./scripts/vm1/loadgen.sh http://NODE_A_IP:8000 60 -c 8
```

## Alert routing

Configure alert channels via environment variables on the autotriage agent:

| Variable | Description |
|---|---|
| `ALERT_WEBHOOK_URL` | Generic HTTP POST endpoint for alerts |
| `ALERT_SLACK_URL` | Slack incoming webhook URL |
| `ALERT_LOG_FILE` | Path to append JSON-line alerts |
| `ALERT_DB_ENABLED` | Set to `1` or `true` to store alerts in PostgreSQL |
| `ALERT_COOLDOWN_SEC` | Deduplication window in seconds (default: 120) |

## MTTR benchmarking

Measure mean time to resolution across multiple fault-injection cycles:

```bash
python benchmarks/mttr_benchmark.py \
  --gateway http://NODE_A_IP:8000 \
  --payments-admin http://NODE_B_IP:8001 \
  --admin-token change-me-class-demo \
  --iterations 5 \
  --output results.json
```

Output includes per-iteration timing and aggregate statistics (mean, median, stdev, min, max).

## ML anomaly detection

The autotriage agent includes a PyTorch transformer-based anomaly classifier (`autotriage_agent/ml_model.py`):

- **Architecture**: `nn.TransformerEncoder` with positional encoding, processing sliding windows of metric time series.
- **Input**: `[error_rate, latency_p99, request_rate]` over 30 timesteps per monitored service.
- **Output**: anomaly probability (0–1) and anomaly type classification (normal, latency_spike, error_burst, throughput_drop).
- **Integration**: ML scores augment the rule-based diagnosis. The model can elevate severity when rules show no SLO breach but the model detects an anomaly pattern.
- **Training**: `generate_synthetic_training_data()` creates labelled data for demo/development. Run `python ml_model.py` to train and save weights.

Set `ML_MODEL_WEIGHTS` to a path to load pre-trained weights; otherwise the model runs in demo mode with random initialisation.

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

Run `./scripts/vm1/loadgen.sh http://NODE_A_IP:8000 120` and watch Grafana / Prometheus / Streamlit Dashboard. The **leader** autotriage agent should detect elevated 5xx/p99 and POST `/admin/reset` on payments. Check logs: `docker compose logs -f autotriage_agent` on VM1 or VM2.

Clear degradation manually if needed:

```bash
curl -s -X POST "$NODE_B/admin/reset" -H "Authorization: Bearer $ADMIN_TOKEN"
```

## Project structure

```
autotriage-distributed/
├── autotriage_agent/
│   ├── agent.py            # Main loop: leader election → diagnose → alert → remediate
│   ├── diagnose.py         # Rule-based + ML-augmented diagnosis
│   ├── ml_model.py         # PyTorch transformer anomaly classifier
│   ├── alert_router.py     # Multi-channel alert routing with deduplication
│   ├── models.py           # PostgreSQL schema and data-access helpers
│   ├── leader.py           # Advisory-lock leader election
│   ├── prom.py             # Prometheus PromQL queries
│   ├── jaeger_callgraph.py # Jaeger trace error sampling
│   ├── remediate.py        # Automated remediation actions
│   ├── Dockerfile
│   └── requirements.txt
├── dashboard/
│   ├── streamlit_app.py    # Streamlit ops monitoring UI
│   ├── Dockerfile
│   └── requirements.txt
├── services/
│   ├── common/             # Shared instrumentation, HTTP client, metrics
│   ├── gateway/            # API gateway (VM1)
│   ├── orders/             # Orders service with PostgreSQL persistence (VM2)
│   └── payments/           # Payments with simulated degradation (VM2)
├── deploy/
│   ├── vm1/                # Docker Compose for VM1
│   └── vm2/                # Docker Compose for VM2
├── scripts/
│   ├── vm1/                # Load generator, smoke tests, experiments
│   └── vm2/                # Chaos scripts (netem, crash, cpu_stress)
├── benchmarks/
│   └── mttr_benchmark.py   # MTTR measurement across fault-injection cycles
├── SETUP_ON_VMS.md
└── README.md
```
