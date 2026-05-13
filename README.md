# CampusCart Microservices 🛒

A production-grade microservices platform for campus marketplace — built with Django, Kubernetes, Helm, Prometheus, Grafana, and GitHub Actions CI/CD.

![CI/CD](https://github.com/bharathMoger18/campuscart-microservices/actions/workflows/auth-service.yml/badge.svg)
![CI/CD](https://github.com/bharathMoger18/campuscart-microservices/actions/workflows/product-service.yml/badge.svg)
![CI/CD](https://github.com/bharathMoger18/campuscart-microservices/actions/workflows/order-service.yml/badge.svg)
![CI/CD](https://github.com/bharathMoger18/campuscart-microservices/actions/workflows/notification-service.yml/badge.svg)

---

## Architecture
┌─────────────────────────────────────────┐
                    │         Nginx Ingress Controller         │
                    │         NodePort 30080                   │
                    └──────────────┬──────────────────────────┘
                                   │
          ┌────────────────────────┼───────────────────────────┐
          │                        │                           │
 ┌────────▼───────┐    ┌───────────▼──────┐    ┌──────────────▼────┐
 │  auth-service  │    │ product-service  │    │  order-service    │
 │  Django + DRF  │    │  Django + DRF    │    │  Django + DRF     │
 │  JWT issuer    │    │  JWT verifier    │    │  Stripe payments  │
 │  Port 8000     │    │  Port 8000       │    │  Port 8000        │
 └────────┬───────┘    └───────────┬──────┘    └──────────────┬────┘
          │                        │                           │
 ┌────────▼───────┐    ┌───────────▼──────┐    ┌──────────────▼────┐
 │   auth-db      │    │   product-db     │    │    order-db       │
 │  PostgreSQL    │    │   PostgreSQL     │    │   PostgreSQL      │
 └────────────────┘    └──────────────────┘    └───────────────────┘

 ┌──────────────────────────┐         ┌──────────────────────────┐
 │  notification-service   │         │         Redis            │
 │  Django Channels        │────────►│   WebSocket broker       │
 │  WebSocket + Push       │         │   Channel Layer          │
 │  Port 8000              │         └──────────────────────────┘
 └──────────────┬──────────┘
                │
 ┌──────────────▼──────────┐
 │     notification-db     │
 │      PostgreSQL         │
 └─────────────────────────┘

 ┌─────────────────────────────────────────────────────────────┐
 │                    Monitoring Stack                         │
 │  Prometheus (20 targets) ──► Grafana (4 dashboards)         │
 │  Alertmanager            ──► 2 alert rules                  │
 └─────────────────────────────────────────────────────────────┘


---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| **Language** | Python 3.10 |
| **Framework** | Django 4.x + Django REST Framework |
| **Real-time** | Django Channels + WebSocket |
| **Auth** | JWT (SimpleJWT) |
| **Payments** | Stripe API |
| **Database** | PostgreSQL (per service) |
| **Cache/Broker** | Redis |
| **Container** | Docker |
| **Orchestration** | Kubernetes 1.29 (kubeadm) |
| **Package Manager** | Helm 3 |
| **Ingress** | Nginx Ingress Controller |
| **Storage** | NFS Persistent Volumes |
| **Monitoring** | Prometheus + Grafana |
| **CI/CD** | GitHub Actions (self-hosted runner) |
| **Registry** | GitHub Container Registry (ghcr.io) |
| **Networking** | Flannel CNI |
| **VM Hypervisor** | KVM/QEMU |

---

## Services Overview

### 1. Auth Service
- User registration and activation
- JWT token issuance (access + refresh tokens)
- User profile management
- Public user info endpoint used by other services for inter-service communication

**Key endpoints:**

POST /api/v1/auth/register/      → Register new user
POST /api/v1/auth/token/         → Login, get JWT
GET  /api/v1/users/me/           → Get own profile (JWT required)
GET  /api/v1/users/public/{id}/  → Get user info (no auth, inter-service use)


### 2. Product Service
- Product CRUD with JWT authentication
- Owner name fetched from auth-service via inter-service HTTP call
- Wishlist management
- Review and rating system with breakdown

**Key endpoints:**


GET  /api/v1/products/      → List products (public)
POST /api/v1/products/      → Create product (JWT required)
POST /api/v1/wishlist/add/  → Add to wishlist
POST /api/v1/reviews/       → Add review with rating

### 3. Order Service
- Cart management with price snapshots
- Order creation with seller_id auto-fetched from product-service
- Stripe PaymentIntent integration
- Complete order status history and audit trail

**Key endpoints:**
POST /api/v1/cart/add/               → Add to cart
GET  /api/v1/cart/                   → View cart
POST /api/v1/orders/create/          → Create order from cart
POST /api/v1/payments/create-intent/ → Create Stripe PaymentIntent

### 4. Notification Service
- Real-time WebSocket chat via Django Channels and Redis
- Web Push notifications with VAPID
- Conversation management between users

**Key endpoints:**
GET  /api/v1/push/public-key/     → VAPID public key
POST /api/v1/chat/conversations/  → Create conversation
WS   /ws/chat/{id}/?token={jwt}   → WebSocket connection

---

## Kubernetes Cluster

### Infrastructure
k8s-master  → 192.168.122.199  (control plane)
k8s-worker1 → 192.168.122.55   (workload node)
k8s-worker2 → 192.168.122.56   (workload node)

- Provisioned with kubeadm on KVM/QEMU VMs running Ubuntu 22.04
- Flannel CNI for pod networking with 10.244.0.0/16 CIDR
- NFS for persistent volume storage across nodes
- Nginx Ingress Controller on NodePort 30080
- Metrics Server enabled for kubectl top support

### Namespaces
campuscart   → all 4 microservices, databases, redis
monitoring   → prometheus, grafana, alertmanager
kube-system  → cluster system components

---

## Helm Charts

Each service has its own Helm chart under `helm/`:
helm/
├── auth-service/
│   ├── Chart.yaml
│   ├── values.yaml
│   └── templates/
│       ├── deployment.yaml
│       └── service.yaml
├── product-service/
├── order-service/
└── notification-service/

**Deploy a service:**
```bash
helm upgrade --install auth helm/auth-service \
  -n campuscart \
  --set image.tag=<git-sha>
```

**Rollback to previous revision:**
```bash
helm rollback auth 11 -n campuscart
```

**View release history:**
```bash
helm history auth -n campuscart
```

---

## CI/CD Pipeline

Each microservice has its own GitHub Actions workflow with path filtering so only the changed service rebuilds and redeploys.

### Pipeline Jobs
Push to main branch
│
├── path filter: only if service files changed
│
▼
Job 1: Build and Test
- Checkout code
- Setup Python 3.10
- Install dependencies
- Run Django system checks
│
▼
Job 2: Build and Push Image
- Build Docker image
- Tag with git commit SHA
- Push to ghcr.io/bharathmoger18/
│
▼
Job 3: Deploy to Kubernetes
- SSH into k8s-master
- helm upgrade with new image tag
- kubectl rollout status to verify
- Print deployment summary

### Self-Hosted Runner
Runner installed directly on k8s-master, giving direct kubectl and helm access without exposing the cluster API server to the internet.

---

## Monitoring and Observability

### Prometheus
- 20 active scrape targets, all UP
- Scrapes all 4 microservices via Kubernetes DNS
- Node metrics via node-exporter on all 3 nodes
- Container metrics via cAdvisor
- Kubernetes object state via kube-state-metrics

**Access:** http://192.168.122.55:30090

### Alert Rules
HighCPUUsage:
rate(process_cpu_seconds_total{job=~".*-service"}[5m]) * 100 > 80
Fires when any microservice exceeds 80% CPU for 5 minutes
PodCrashLooping:
increase(kube_pod_container_status_restarts_total{namespace="campuscart"}[15m]) > 2
Fires when any pod restarts more than twice in 15 minutes

### Grafana Dashboards
- Dashboard 1: CPU usage per service over time
- Dashboard 2: Memory usage per service over time
- Dashboard 3: Pod health and restart counts
- Dashboard 4: HTTP request rates by service and method

**Access:** http://192.168.122.55:30300 (admin / admin123)

---

## Inter-Service Communication

Services communicate via Kubernetes internal DNS over plain HTTP:
product-service  →  http://auth-service:8000/api/v1/users/public/{id}/
order-service    →  http://auth-service:8000/api/v1/users/public/{id}/
order-service    →  http://product-service:8000/api/v1/products/{id}/

JWT verification is stateless — all services share DJANGO_SECRET_KEY and independently verify tokens without calling auth-service per request.

---

## Zero Downtime Deployments

Rolling update strategy on all Deployments:
```yaml
strategy:
  type: RollingUpdate
  rollingUpdate:
    maxSurge: 1
    maxUnavailable: 0
```

Proven with live traffic test: continuous curl loop on /api/v1/products/ showed uninterrupted 200 responses throughout a complete rolling update. Zero 502 or 503 errors recorded.

---

## Key Design Decisions

**Database per service** — each microservice owns its PostgreSQL instance. No shared database means true independence and separate scaling.

**Price snapshots in cart** — order-service stores the price at time of cart addition, not live price. Prevents price manipulation between add-to-cart and checkout.

**Seller ID from product-service** — order-service fetches seller_id from product-service internally. The frontend never sends seller information, preventing fraud.

**Stateless JWT auth** — no shared session store needed. Each service verifies the JWT signature independently using the shared DJANGO_SECRET_KEY.

**Path filtering in CI/CD** — each workflow only triggers when its own service files change. Fixing auth-service does not rebuild product, order, or notification.

**Self-hosted runner** — direct cluster access without exposing the Kubernetes API server publicly. Runner runs as a systemd service on k8s-master.

**Commit SHA image tags** — every Docker image is tagged with the exact git commit SHA. Every running pod is traceable to a specific commit. Rollback means deploying a previous SHA.

---

## Environment Variables

### All Services
| Variable | Description |
|----------|-------------|
| DJANGO_SECRET_KEY | Django secret key, also used as JWT signing key |
| DB_HOST | PostgreSQL hostname |
| DB_NAME | Database name |
| DB_USER | Database username |
| DB_PASSWORD | Database password |
| DEBUG | Django debug mode, False in all environments |
| ALLOWED_HOSTS | Comma-separated list of allowed hostnames |

### Order Service (additional)
| Variable | Description |
|----------|-------------|
| STRIPE_SECRET_KEY | Stripe secret key for PaymentIntent creation |
| STRIPE_PUBLISHABLE_KEY | Stripe publishable key |
| STRIPE_WEBHOOK_SECRET | Stripe webhook signature secret |
| PRODUCT_SERVICE_URL | Internal URL for product-service |

### Notification Service (additional)
| Variable | Description |
|----------|-------------|
| REDIS_URL | Redis connection URL for Django Channels |
| VAPID_PUBLIC_KEY | VAPID public key for Web Push |
| VAPID_PRIVATE_KEY | VAPID private key for Web Push |
| VAPID_EMAIL | VAPID contact email |

---

## What This Project Proves

- Real microservices with independent databases, not a monolith split into routes
- Inter-service HTTP communication proven by owner_name and seller_id fields
- JWT authentication working identically across 4 independent Django services
- WebSocket real-time chat with Redis as channel layer proven with live wscat test
- Stripe PaymentIntent integration calling real external Stripe API from a pod
- Production Kubernetes cluster built from scratch with kubeadm on bare KVM VMs
- Helm managing versioned deployments with full rollback capability
- NFS persistent storage keeping database data across pod restarts
- Prometheus scraping 20 real targets with alert rules that fire on real data
- GitHub Actions CI/CD deploying new images automatically on every push to main
- Zero downtime rolling updates proven with live continuous traffic test
- Every running pod traceable to the exact git commit SHA that built it

---

