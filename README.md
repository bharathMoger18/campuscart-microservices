# CampusCart Microservices 🛒

A production-grade microservices platform for campus marketplace — built with Django, Kubernetes, Helm, Prometheus, Grafana, Alertmanager, and GitHub Actions CI/CD.

## Architecture

```
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

 ┌─────────────────────────────────────────────────────────────────────┐
 │                       Monitoring Stack                              │
 │                                                                     │
 │  Prometheus (:30090) ──────────────────► Grafana (:30300)          │
 │  12 alert rules                          1 production dashboard     │
 │  20+ scrape targets                      18 panels                  │
 │       │                                                             │
 │       ▼                                                             │
 │  Alertmanager (:30093)                                              │
 │  Slack: #alerts-critical + #alerts-warning                         │
 └─────────────────────────────────────────────────────────────────────┘
```

---

## Tech Stack

| Layer               | Technology                                         |
| ------------------- | -------------------------------------------------- |
| **Language**        | Python 3.10                                        |
| **Framework**       | Django 4.x + Django REST Framework                 |
| **Real-time**       | Django Channels + WebSocket                        |
| **Auth**            | JWT (SimpleJWT)                                    |
| **Payments**        | Stripe API (PaymentIntent + Webhooks)              |
| **Database**        | PostgreSQL (per service)                           |
| **Cache/Broker**    | Redis                                              |
| **Container**       | Docker                                             |
| **Orchestration**   | Kubernetes 1.29 (kubeadm)                          |
| **Package Manager** | Helm 3                                             |
| **Ingress**         | Nginx Ingress Controller                           |
| **Storage**         | NFS Persistent Volumes                             |
| **Metrics**         | Prometheus + django-prometheus + prometheus_client |
| **Dashboards**      | Grafana                                            |
| **Alerting**        | Alertmanager + Slack                               |
| **CI/CD**           | GitHub Actions (self-hosted runner)                |
| **Registry**        | GitHub Container Registry (ghcr.io)                |
| **Networking**      | Flannel CNI                                        |
| **VM Hypervisor**   | KVM/QEMU                                           |

---

## Services Overview

### 1. Auth Service

- User registration and email verification
- JWT token issuance (access + refresh tokens)
- User profile management
- Password reset flow
- Public user info endpoint for inter-service communication

**Custom Metrics:**

- `auth_login_attempts_total{status}` — login success/failure rate
- `auth_user_registrations_total{status}` — registration success/failure
- `auth_jwt_tokens_issued_total{token_type}` — token issuance rate
- `auth_operation_duration_seconds{operation}` — auth operation latency histogram
- `auth_active_users_estimated` — estimated active users gauge

**Key endpoints:**

```
POST /api/v1/auth/register/      → Register new user
POST /api/v1/auth/token/         → Login, get JWT
POST /api/v1/auth/token/refresh/ → Refresh JWT
GET  /api/v1/users/me/           → Get own profile (JWT required)
GET  /api/v1/users/public/{id}/  → Get user info (no auth, inter-service use)
```

---

### 2. Product Service

- Product CRUD with JWT authentication
- Owner name fetched from auth-service via inter-service HTTP call
- Wishlist management
- Review and rating system with breakdown
- Soft delete (products are hidden, not destroyed)

**Custom Metrics:**

- `product_views_total{category}` — product detail views by category
- `product_searches_total{has_results}` — search/filter query rate
- `product_search_duration_seconds{filter_type}` — search latency histogram
- `product_listed_total{category,status}` — new product listings
- `product_active_listings_current` — active catalog size gauge

**Key endpoints:**

```
GET  /api/v1/products/           → List products (public)
POST /api/v1/products/           → Create product (JWT required)
GET  /api/v1/products/{id}/      → Product detail (public)
POST /api/v1/wishlist/add/       → Add to wishlist
POST /api/v1/reviews/            → Add review with rating
```

---

### 3. Order Service

- Cart management with price snapshots at add-to-cart time
- Order creation grouped by seller from cart contents
- Stripe PaymentIntent + Checkout Session integration
- Stripe webhook handling with idempotency (event-ID deduplication)
- Complete order status history and audit trail
- Refund request workflow with seller approval

**Custom Metrics:**

- `order_orders_created_total{status}` — orders created counter
- `order_payment_attempts_total{status}` — Stripe payment attempts
- `order_payment_failures_total{error_code,decline_code}` — payment failure reasons
- `order_stripe_api_duration_seconds{operation}` — Stripe API latency histogram
- `order_checkout_total_duration_seconds` — end-to-end checkout duration histogram
- `order_cart_items_added_total` — items added to carts
- `order_cart_abandonments_total` — cart clear-all abandonment signal
- `order_active_carts_current` — live carts with items gauge
- `order_status_transitions_total{from_status,to_status}` — order lifecycle tracking
- `order_refund_requests_total{reason,status}` — refund request tracking

**Key endpoints:**

```
POST /api/v1/cart/add/                      → Add to cart
GET  /api/v1/cart/                          → View cart
POST /api/v1/orders/create/                 → Create order from cart
POST /api/v1/orders/{id}/simulate_payment/  → Simulate payment (dev)
POST /api/v1/payments/create-intent/        → Create Stripe PaymentIntent
POST /api/v1/payments/create-checkout-session/ → Stripe Checkout Session
POST /webhooks/stripe/                      → Stripe webhook handler
```

---

### 4. Notification Service

- Real-time WebSocket chat via Django Channels and Redis channel layer
- Web Push notifications via pywebpush (VAPID)
- Conversation management between buyers and sellers
- Message delivery and read receipt broadcasting
- Daphne ASGI server (not gunicorn — WebSocket requires ASGI)

**Custom Metrics:**

- `notification_ws_connections_active{connection_type}` — live WS connection gauge
- `notification_ws_connect_total{connection_type}` — total connections established
- `notification_ws_disconnect_total{connection_type,close_code}` — disconnects by close code
- `notification_messages_sent_total{message_type}` — chat messages sent
- `notification_message_delivery_seconds` — message delivery latency histogram
- `notification_redis_channel_publish_total{channel_type,status}` — Redis publish rate
- `notification_redis_channel_receive_total{channel_type}` — Redis receive rate
- `notification_push_sent_total{status}` — Web Push delivery rate
- `notification_push_failures_total{error_type}` — push failure reasons

**Key endpoints:**

```
GET  /api/v1/push/public-key/        → VAPID public key
POST /api/v1/push/subscribe/         → Register push subscription
POST /api/v1/chat/conversations/     → Create conversation
WS   /ws/chat/{id}/?token={jwt}      → WebSocket connection
```

---

## Kubernetes Cluster

### Infrastructure

```
k8s-master  → 192.168.122.199  (control plane)
k8s-worker1 → 192.168.122.55   (workload node)
k8s-worker2 → 192.168.122.56   (workload node)
```

- Provisioned with kubeadm on KVM/QEMU VMs running Ubuntu 22.04
- Flannel CNI for pod networking with 10.244.0.0/16 CIDR
- NFS for persistent volume storage across nodes
- Nginx Ingress Controller on NodePort 30080
- Metrics Server enabled for `kubectl top` support

### Namespaces

```
campuscart   → 4 microservices, 4 PostgreSQL databases, Redis, Redis Exporter
monitoring   → Prometheus, Grafana, Alertmanager, Node Exporter, kube-state-metrics
kube-system  → CoreDNS, kube-proxy, NFS provisioner, Metrics Server
```

---

## Helm Charts

Each service has its own Helm chart under `helm/`:

```
helm/
├── auth-service/
├── product-service/
├── order-service/
└── notification-service/
```

Monitoring stack managed via `prometheus-community/prometheus` Helm chart with custom values in `monitoring/prometheus-values.yaml`.

```bash
# Deploy a service
helm upgrade --install auth helm/auth-service \
  -n campuscart \
  --set image.tag=<git-sha>

# Upgrade Prometheus with custom values
helm upgrade prometheus ~/prometheus \
  -n monitoring \
  -f ~/monitoring/prometheus-values.yaml

# Rollback to previous revision
helm rollback auth 11 -n campuscart

# View release history
helm history auth -n campuscart
```

---

## CI/CD Pipeline

Each microservice has its own GitHub Actions workflow with path filtering so only the changed service rebuilds and redeploys.

### Pipeline Jobs

```
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
```

### Self-Hosted Runner

Runner installed directly on k8s-master, giving direct kubectl and helm access without exposing the cluster API server to the internet.

---

## Monitoring and Observability

### Prometheus

- 20+ active scrape targets, all UP
- Scrapes all 4 microservices every 15s via Kubernetes DNS
- Node metrics via Node Exporter on all 3 nodes (DaemonSet)
- Container metrics via cAdvisor (built into kubelet)
- Kubernetes object state via kube-state-metrics
- Redis metrics via redis-exporter (oliver006/redis_exporter)
- **Prometheus Multiprocess Mode** enabled on all gunicorn services — metrics correctly aggregate across all worker PIDs

**Access:** `http://192.168.122.199:30090`

---

### Alert Rules (12 total, across 4 groups)

#### campuscart-alerts

| Alert                                | Expression                        | Severity |
| ------------------------------------ | --------------------------------- | -------- |
| HighCPUUsage                         | CPU > 80% for 2m                  | warning  |
| PodCrashLooping                      | restarts > 2 in 15m               | critical |
| RedisMemoryHigh                      | redis_memory > 400MB for 5m       | warning  |
| RedisEvictions                       | eviction rate > 0 for 1m          | critical |
| NotificationWSAbnormalDisconnectRate | close_code=1006 rate > 5/s for 2m | warning  |
| RedisExporterDown                    | redis-exporter target down for 2m | critical |

#### campuscart.services

| Alert                   | Expression                 | Severity |
| ----------------------- | -------------------------- | -------- |
| CampusCartServiceDown   | any service up == 0 for 1m | critical |
| CampusCartHighErrorRate | 5xx rate > 5% for 2m       | critical |
| CampusCartHighLatency   | p99 latency > 2s for 5m    | warning  |

#### campuscart.infrastructure

| Alert                | Expression               | Severity |
| -------------------- | ------------------------ | -------- |
| NodeMemoryPressure   | memory > 85% for 5m      | warning  |
| DiskWillFillIn4Hours | predict_linear < 0 in 4h | critical |

#### campuscart.watchdog

| Alert              | Expression               | Severity |
| ------------------ | ------------------------ | -------- |
| MonitoringWatchdog | vector(1) — always fires | info     |

---

### Alertmanager

- Routes `critical` alerts → Slack `#alerts-critical`
- Routes `warning` alerts → Slack `#alerts-warning`
- `MonitoringWatchdog` routes to null-receiver (dead man's switch)
- Inhibition rules: suppress symptom alerts when `CampusCartServiceDown` fires
- Repeat interval: 30m for critical, 1h for warning

**Access:** `http://192.168.122.199:30093`

---

### Grafana — CampusCart Production Dashboard

Single comprehensive production dashboard with 18 panels organized by the SRE RED + USE methods.

**Row 1 — Health Overview (Stat panels)**
| Panel | Query |
|-------|-------|
| Services UP | `count(up{job=~".*-service"} == 1)` |
| Total Requests/sec | Sum of all service request rates |
| Active Users | `sum(auth_active_users_estimated)` |
| Redis Memory | `redis_memory_used_bytes / 1024 / 1024` |

**Row 2 — RED Method (Time Series)**
| Panel | Method |
|-------|--------|
| p99 Latency | histogram_quantile(0.99, ...) |
| 5xx Error Rate | 5xx responses / total responses × 100 |
| Request Rate — All Services | sum by(job)(rate(...)) |
| Redis Memory Trend | redis_memory_used_bytes / 1024 / 1024 |

**Row 3 — Business Metrics (Time Series + Stat)**
| Panel | Metric |
|-------|--------|
| Login Attempts | `auth_login_attempts_total{status}` |
| Product Views by Category | `product_views_total{category}` |
| Cart Activity | items added vs abandonments |
| Active Carts | `sum(order_active_carts_current)` |
| p99 Checkout Duration | `order_checkout_total_duration_seconds` |

**Row 4 — Kubernetes + Infrastructure**
| Panel | Type |
|-------|------|
| Pod Restarts — Last 1 Hour | Table |
| CPU Usage — All Nodes | Gauge (3 nodes) |
| Memory Usage — All Nodes | Gauge (3 nodes) |
| Disk Usage — All Nodes | Gauge (3 nodes) |
| DB Queries/sec | Time Series |
| Top 5 Slowest Endpoints (p99) | Table |

**Access:** `http://192.168.122.199:30300` (admin / admin123)

---

## Inter-Service Communication

Services communicate via Kubernetes internal DNS over plain HTTP:

```
product-service  →  http://auth-service:8000/api/v1/users/public/{id}/
order-service    →  http://auth-service:8000/api/v1/users/public/{id}/
order-service    →  http://product-service:8000/api/v1/products/{id}/
order-service    →  http://notification-service:8000/api/v1/push/notify/
```

JWT verification is stateless — all services share `DJANGO_SECRET_KEY` and independently verify tokens without calling auth-service per request.

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

Proven with live traffic test: continuous curl loop on `/api/v1/products/` showed uninterrupted 200 responses throughout a complete rolling update.

---

## Key Design Decisions

**Database per service** — each microservice owns its PostgreSQL instance. No shared database means true independence and separate scaling.

**Price snapshots in cart** — order-service stores the price at time of cart addition, not live price. Prevents price manipulation between add-to-cart and checkout.

**Seller ID from product-service** — order-service fetches seller_id from product-service internally. The frontend never sends seller information, preventing fraud.

**Stateless JWT auth** — no shared session store needed. Each service verifies the JWT signature independently using the shared `DJANGO_SECRET_KEY`.

**Path filtering in CI/CD** — each workflow only triggers when its own service files change. Fixing auth-service does not rebuild product, order, or notification.

**Self-hosted runner** — direct cluster access without exposing the Kubernetes API server publicly. Runner runs as a systemd service on k8s-master.

**Commit SHA image tags** — every Docker image is tagged with the exact git commit SHA. Every running pod is traceable to a specific commit. Rollback means deploying a previous SHA.

**Prometheus multiprocess mode** — all gunicorn services export `PROMETHEUS_MULTIPROC_DIR` so metrics from all 3 workers are aggregated correctly. Without this, only 1 of 3 workers' counters would be visible per scrape.

**Stripe webhook idempotency** — Stripe delivers webhooks "at least once". Each webhook event ID is stored in Django's cache for 3 days. Duplicate events are detected and skipped before any counter increments, preventing double-counting of payment metrics.

**Bounded label cardinality** — all custom metrics use bounded label values (e.g. category from a fixed list, not free text like product_id or user_email). Prevents metric explosion in Prometheus TSDB.

**Helm-managed alert rules** — all alert rules and Alertmanager config live in `monitoring/prometheus-values.yaml`, not in raw kubectl edits. A `helm upgrade` will never silently wipe custom alerts.

---

## Environment Variables

### All Services

| Variable                   | Description                                          |
| -------------------------- | ---------------------------------------------------- |
| `DJANGO_SECRET_KEY`        | Django secret key, also used as JWT signing key      |
| `DB_HOST`                  | PostgreSQL hostname                                  |
| `DB_NAME`                  | Database name                                        |
| `DB_USER`                  | Database username                                    |
| `DB_PASSWORD`              | Database password                                    |
| `DEBUG`                    | Django debug mode, False in production               |
| `ALLOWED_HOSTS`            | Comma-separated list of allowed hostnames            |
| `PROMETHEUS_MULTIPROC_DIR` | Shared directory for multiprocess prometheus metrics |

### Order Service (additional)

| Variable                 | Description                                  |
| ------------------------ | -------------------------------------------- |
| `STRIPE_SECRET_KEY`      | Stripe secret key for PaymentIntent creation |
| `STRIPE_PUBLISHABLE_KEY` | Stripe publishable key                       |
| `STRIPE_WEBHOOK_SECRET`  | Stripe webhook signature secret              |
| `PRODUCT_SERVICE_URL`    | Internal URL for product-service             |

### Notification Service (additional)

| Variable            | Description                              |
| ------------------- | ---------------------------------------- |
| `REDIS_URL`         | Redis connection URL for Django Channels |
| `VAPID_PUBLIC_KEY`  | VAPID public key for Web Push            |
| `VAPID_PRIVATE_KEY` | VAPID private key for Web Push           |
| `VAPID_EMAIL`       | VAPID contact email                      |

---

## What This Project Proves

- Real microservices with independent databases — not a monolith split into routes
- Inter-service HTTP communication proven by `owner_name` and `seller_id` fields in API responses
- JWT authentication working identically across 4 independent Django services without a shared session store
- WebSocket real-time chat with Redis as channel layer proven with live wscat test
- Stripe PaymentIntent integration calling real external Stripe API from inside a Kubernetes pod
- Stripe webhook handling with HMAC signature verification and event-ID-based idempotency
- Production Kubernetes cluster built from scratch with kubeadm on bare KVM VMs
- Helm managing versioned deployments for all 4 services and the full monitoring stack with full rollback capability
- NFS persistent storage keeping database data across pod restarts and node reboots
- Prometheus scraping 20+ real targets including custom business metrics from all 4 services
- 12 alert rules covering service health, Redis, infrastructure, and security (brute force detection)
- Alertmanager routing critical vs warning alerts to separate Slack channels with inhibition rules
- Dead man's switch (MonitoringWatchdog) — if Prometheus itself fails, the absence of heartbeat alerts
- Grafana production dashboard with 18 panels covering RED metrics, USE metrics, and business KPIs
- Custom business metrics with bounded label cardinality — orders, payments, cart activity, product views, login attempts
- Prometheus multiprocess mode correctly aggregating metrics across all gunicorn worker PIDs
- GitHub Actions CI/CD deploying new images automatically on every push to main with path filtering
- Zero downtime rolling updates proven with live continuous traffic test
- Every running pod traceable to the exact git commit SHA that built it
