from prometheus_client import Counter, Histogram, Gauge

# ── FILE STRUCTURE ─────────────────────────────────────────────────────────────
# Define all custom metrics in a dedicated metrics.py module
# Import from this module wherever you need to record observations
# Never define metrics inside views.py — they'd be re-created on every import
# Metrics must be module-level singletons registered once in the process

# ── USER REGISTRATION COUNTER ─────────────────────────────────────────────────
# Counter: a value that only increases, resets on pod restart
# Naming convention: namespace_subsystem_name_unit_total
# "auth" = service name, "users" = subsystem, "registrations" = what we count
user_registrations_total = Counter(
    name="auth_user_registrations_total",
    documentation="Total number of user registration attempts",
    labelnames=["status"],           # labels: "success" or "failure"
)
# Usage in views.py:
#   user_registrations_total.labels(status="success").inc()
#   user_registrations_total.labels(status="failure").inc()

# ── LOGIN ATTEMPT COUNTER ─────────────────────────────────────────────────────
login_attempts_total = Counter(
    name="auth_login_attempts_total",
    documentation="Total number of login attempts",
    labelnames=["status"],           # "success", "invalid_credentials", "account_locked"
)
# PromQL: rate(auth_login_attempts_total{status="invalid_credentials"}[5m])
# Alert: fire when invalid credential rate > 10/min (brute force detection)

# ── JWT TOKEN ISSUED COUNTER ──────────────────────────────────────────────────
jwt_tokens_issued_total = Counter(
    name="auth_jwt_tokens_issued_total",
    documentation="Total number of JWT access tokens issued",
    labelnames=["token_type"],       # "access" or "refresh"
)
# PromQL: rate(auth_jwt_tokens_issued_total{token_type="access"}[5m])
# Useful for tracking active session creation rate

# ── PASSWORD RESET COUNTER ────────────────────────────────────────────────────
password_resets_total = Counter(
    name="auth_password_resets_total",
    documentation="Total number of password reset requests",
    labelnames=["status"],           # "requested", "completed", "expired"
)

# ── EMAIL VERIFICATION COUNTER ────────────────────────────────────────────────
email_verifications_total = Counter(
    name="auth_email_verifications_total",
    documentation="Total number of email verification attempts",
    labelnames=["status"],           # "success", "expired_token", "already_verified"
)

# ── ACTIVE SESSIONS GAUGE ─────────────────────────────────────────────────────
# Gauge: a value that can go up AND down
# Tracks how many JWT access tokens are currently "in flight"
# This is an approximation — actual session tracking requires Redis
active_users_gauge = Gauge(
    name="auth_active_users_estimated",
    documentation="Estimated number of users with valid JWT tokens in the last 60 minutes",
)
# Update this periodically, not per-request:
# In a management command or celery task:
#   active_users_gauge.set(User.objects.filter(last_login__gte=now()-timedelta(hours=1)).count())

# ── AUTH OPERATION LATENCY HISTOGRAM ──────────────────────────────────────────
# Histogram: records duration of operations for p50/p95/p99 calculation
# buckets: the latency boundaries in seconds
auth_operation_duration_seconds = Histogram(
    name="auth_operation_duration_seconds",
    documentation="Duration of authentication operations in seconds",
    labelnames=["operation"],        # "login", "register", "verify_email", "refresh_token"
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
    # 5ms, 10ms, 25ms, 50ms, 100ms, 250ms, 500ms, 1s, 2.5s, 5s
    # Auth operations should be < 100ms normally (JWT verify is fast)
    # > 500ms suggests database issues or bcrypt config problems
)
# Usage: with auth_operation_duration_seconds.labels(operation="login").time():
#            ... login logic ...