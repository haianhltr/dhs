"""DHS configuration — all values loaded from environment variables with defaults."""

import os

# Evaluation loop
EVAL_INTERVAL_SECONDS = int(os.environ.get("EVAL_INTERVAL_SECONDS", "30"))

# External services
PROMETHEUS_URL = os.environ.get("PROMETHEUS_URL", "http://prometheus.observability:9090")
SSOT_API_URL = os.environ.get("SSOT_API_URL", "http://ssot-api.ssot:8080")
LOKI_URL = os.environ.get("LOKI_URL", "http://loki.observability.svc.cluster.local:3100")

# Loki query timeout (seconds)
LOKI_QUERY_TIMEOUT = int(os.environ.get("LOKI_QUERY_TIMEOUT", "5"))

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

# Kafka
KAFKA_BOOTSTRAP_SERVERS = os.environ.get(
    "KAFKA_BOOTSTRAP_SERVERS", "kafka.calculator.svc.cluster.local:9092"
)
KAFKA_TOPIC = os.environ.get("KAFKA_TOPIC", "health.transition.v1")

# Cooldown + flap detection
COOLDOWN_SECONDS = int(os.environ.get("COOLDOWN_SECONDS", "60"))
FLAP_WINDOW_SECONDS = int(os.environ.get("FLAP_WINDOW_SECONDS", "600"))
FLAP_THRESHOLD = int(os.environ.get("FLAP_THRESHOLD", "3"))
