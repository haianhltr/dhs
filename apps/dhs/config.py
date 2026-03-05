"""DHS configuration — all values loaded from environment variables with defaults."""

import os

# Evaluation loop
EVAL_INTERVAL_SECONDS = int(os.environ.get("EVAL_INTERVAL_SECONDS", "30"))

# External services
PROMETHEUS_URL = os.environ.get("PROMETHEUS_URL", "http://prometheus.observability:9090")
SSOT_API_URL = os.environ.get("SSOT_API_URL", "http://ssot-api.ssot:8080")

# Auth
DHS_API_KEY = os.environ.get("DHS_API_KEY", "dhs-secret-key")

# Debounce defaults (seconds)
DEBOUNCE_DEGRADED_SECONDS = int(os.environ.get("DEBOUNCE_DEGRADED_SECONDS", "60"))
DEBOUNCE_UNHEALTHY_SECONDS = int(os.environ.get("DEBOUNCE_UNHEALTHY_SECONDS", "60"))
DEBOUNCE_HEALTHY_SECONDS = int(os.environ.get("DEBOUNCE_HEALTHY_SECONDS", "90"))

# Rules directory
RULES_DIR = os.environ.get("RULES_DIR", "/app/rules")

# Prometheus query timeout (seconds)
PROMETHEUS_QUERY_TIMEOUT = int(os.environ.get("PROMETHEUS_QUERY_TIMEOUT", "5"))
