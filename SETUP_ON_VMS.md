# Setup on Ubuntu VMs (copy-paste commands)

Replace `<GITHUB_URL>` with your repo URL (e.g. `https://github.com/youruser/autotriage-distributed.git`).

IPs used below: **node-a = 192.168.56.101**, **node-b = 192.168.56.102**.

---

## On node-b (VM2)

```bash
# Install git if missing
sudo apt update && sudo apt install -y git

# Clone (replace <GITHUB_URL>)
git clone <GITHUB_URL>
cd autotriage-distributed

# Docker Compose: use plugin if available, else install
docker compose version 2>/dev/null || sudo apt install -y docker-compose-plugin || sudo apt install -y docker-compose

# Env and scripts
cd deploy/vm2
cp .env.example .env
sed -i 's/VM1_IP=.*/VM1_IP=192.168.56.101/' .env
# Set ADMIN_TOKEN in .env to match VM1 (same value on both VMs).
cd ../..
chmod +x deploy/vm1/render_prometheus.sh scripts/vm1/smoke_vm1.sh scripts/vm2/smoke_vm2.sh

# Start VM2 stack first
cd deploy/vm2
docker compose up -d --build
cd ../..
```

---

## On node-a (VM1)

```bash
# Install git if missing
sudo apt update && sudo apt install -y git

# Clone (replace <GITHUB_URL>)
git clone <GITHUB_URL>
cd autotriage-distributed

# Docker Compose: use plugin if available, else install
docker compose version 2>/dev/null || sudo apt install -y docker-compose-plugin || sudo apt install -y docker-compose

# Env, render Prometheus, make scripts executable
cd deploy/vm1
cp .env.example .env
sed -i 's/VM2_IP=.*/VM2_IP=192.168.56.102/' .env
# Set ADMIN_TOKEN in .env to match VM2 (same value on both VMs).
./render_prometheus.sh
cd ../..
chmod +x deploy/vm1/render_prometheus.sh scripts/vm1/smoke_vm1.sh scripts/vm2/smoke_vm2.sh

# Start VM1 stack (after VM2 is up)
cd deploy/vm1
docker compose up -d --build
cd ../..
```

---

## Smoke checks (run from either VM or from Windows with curl)

From repo root:

```bash
# VM1 gateway
./scripts/vm1/smoke_vm1.sh http://192.168.56.101:8000

# VM2 orders + payments
./scripts/vm2/smoke_vm2.sh http://192.168.56.102:8000 http://192.168.56.102:8001
```

---

## Open from Windows (node-a = 192.168.56.101)

- **Gateway:** http://192.168.56.101:8000  
- **Prometheus:** http://192.168.56.101:9090  
- **Grafana:** http://192.168.56.101:3000 (admin / admin)  
- **Jaeger:** http://192.168.56.101:16686  
