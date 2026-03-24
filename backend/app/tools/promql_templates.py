"""PromQL template constants and a safe renderer that prevents label-value injection.

All templates use Python brace-style placeholders.  Call ``render(TEMPLATE, **kwargs)``
to substitute — invalid or missing placeholder values raise ``ValueError`` before
any string substitution occurs.

Placeholder vocabulary
----------------------
``{namespace}``   k8s namespace    — must match ``[a-z0-9][a-z0-9\\-]*``
``{service}``     service / app    — same pattern
``{window}``      Prometheus range — must match ``\\d+[smhdw]`` (e.g. ``5m``, ``1h``)
``{container}``   container name   — alphanumeric + ``_-``
``{resource}``    resource name    — alphanumeric + ``_-``
``{quantile}``    float 0..1       — e.g. ``0.99``
"""

from __future__ import annotations

import re
import string

# ---------------------------------------------------------------------------
# Validators — keyed by placeholder name
# ---------------------------------------------------------------------------

_SAFE_LABEL_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_\-\.]*$")
_SAFE_DURATION_RE = re.compile(r"^\d+[smhdw]$")
_SAFE_QUANTILE_RE = re.compile(r"^0\.\d{1,4}$|^1\.0$|^0$|^1$")
_SAFE_INT_RE = re.compile(r"^\d+$")

_VALIDATORS: dict[str, re.Pattern[str]] = {
    "namespace": _SAFE_LABEL_RE,
    "service": _SAFE_LABEL_RE,
    "window": _SAFE_DURATION_RE,
    "container": _SAFE_LABEL_RE,
    "resource": _SAFE_LABEL_RE,
    "quantile": _SAFE_QUANTILE_RE,
    "step_seconds": _SAFE_INT_RE,
}

# ---------------------------------------------------------------------------
# Topology discovery
# ---------------------------------------------------------------------------

SERVICES_INFO = 'kube_service_info{{namespace="{namespace}"}}'

DEPLOYMENT_REPLICAS_CURRENT = (
    'kube_deployment_status_replicas{{namespace="{namespace}"}}'
)
DEPLOYMENT_REPLICAS_DESIRED = (
    'kube_deployment_spec_replicas{{namespace="{namespace}"}}'
)
POD_CPU_LIMITS = (
    'kube_pod_container_resource_limits{{'
    'namespace="{namespace}",resource="cpu",container!=""}}'
)
POD_MEMORY_LIMITS = (
    'kube_pod_container_resource_limits{{'
    'namespace="{namespace}",resource="memory",container!=""}}'
)
POD_CPU_REQUESTS = (
    'kube_pod_container_resource_requests{{'
    'namespace="{namespace}",resource="cpu",container!=""}}'
)
POD_MEMORY_REQUESTS = (
    'kube_pod_container_resource_requests{{'
    'namespace="{namespace}",resource="memory",container!=""}}'
)
HPA_MAX_REPLICAS = (
    'kube_horizontalpodautoscaler_spec_max_replicas{{namespace="{namespace}"}}'
)
HPA_MIN_REPLICAS = (
    'kube_horizontalpodautoscaler_spec_min_replicas{{namespace="{namespace}"}}'
)

# ---------------------------------------------------------------------------
# Health checks — per service
# ---------------------------------------------------------------------------

# CPU: ratio of usage to limit across all pods for the service (0.0 – 1.0)
CPU_USAGE_RATIO = (
    'sum(rate(container_cpu_usage_seconds_total{{'
    'namespace="{namespace}",pod=~"{service}-[a-z0-9]+-[a-z0-9]+",'
    'container!="",container!="POD"}}[{window}]))'
    ' / '
    'sum(kube_pod_container_resource_limits{{'
    'namespace="{namespace}",pod=~"{service}-[a-z0-9]+-[a-z0-9]+",'
    'resource="cpu",container!=""}})'
)

# Memory: ratio of working-set to limit
MEMORY_USAGE_RATIO = (
    'sum(container_memory_working_set_bytes{{'
    'namespace="{namespace}",pod=~"{service}-[a-z0-9]+-[a-z0-9]+",'
    'container!="",container!="POD"}})'
    ' / '
    'sum(kube_pod_container_resource_limits{{'
    'namespace="{namespace}",pod=~"{service}-[a-z0-9]+-[a-z0-9]+",'
    'resource="memory",container!=""}})'
)

# Pod restarts over window
POD_RESTART_COUNT = (
    'sum(increase(kube_pod_container_status_restarts_total{{'
    'namespace="{namespace}",pod=~"{service}-[a-z0-9]+-[a-z0-9]+"}}[{window}]))'
)

# OOMKill events: any pod that was last terminated due to OOMKilled
OOMKILL_EVENTS = (
    'sum(kube_pod_container_status_last_terminated_reason{{'
    'namespace="{namespace}",pod=~"{service}-[a-z0-9]+-[a-z0-9]+",'
    'reason="OOMKilled"}}) or vector(0)'
)

# HTTP error rate via Istio (falls back gracefully if metric absent)
HTTP_ERROR_RATE_ISTIO = (
    'sum(rate(istio_requests_total{{'
    'namespace="{namespace}",destination_service_name=~"{service}.*",'
    'response_code=~"5.."}}[{window}]))'
    ' / '
    'sum(rate(istio_requests_total{{'
    'namespace="{namespace}",destination_service_name=~"{service}.*"}}[{window}]))'
)

# HTTP error rate via nginx ingress
HTTP_ERROR_RATE_NGINX = (
    'sum(rate(nginx_ingress_controller_requests{{'
    'namespace="{namespace}",service="{service}",status=~"5.."}}[{window}]))'
    ' / '
    'sum(rate(nginx_ingress_controller_requests{{'
    'namespace="{namespace}",service="{service}"}}[{window}]))'
)

# p99 response latency (milliseconds) via Istio
HTTP_P99_LATENCY_ISTIO = (
    'histogram_quantile(0.99,'
    ' sum by (le) (rate(istio_request_duration_milliseconds_bucket{{'
    'namespace="{namespace}",destination_service_name=~"{service}.*"'
    '}}[{window}])))'
)

# p99 latency via kube-state / custom histogram
HTTP_P99_LATENCY_CUSTOM = (
    'histogram_quantile(0.99,'
    ' sum by (le) (rate(http_request_duration_seconds_bucket{{'
    'namespace="{namespace}",service="{service}"'
    '}}[{window}]))) * 1000'
)

# Request queue depth (nginx)
REQUEST_QUEUE_DEPTH = (
    'sum(nginx_ingress_controller_requests_current_count{{'
    'namespace="{namespace}",service="{service}"}})'
)

# ---------------------------------------------------------------------------
# Anomaly detection range queries (for use with /api/v1/query_range)
# ---------------------------------------------------------------------------

CPU_USAGE_RATE_BY_SERVICE = (
    'sum by (pod) (rate(container_cpu_usage_seconds_total{{'
    'namespace="{namespace}",container!="",container!="POD"'
    '}}[{window}]))'
)

MEMORY_USAGE_BY_SERVICE = (
    'sum by (pod) (container_memory_working_set_bytes{{'
    'namespace="{namespace}",container!="",container!="POD"'
    '}})'
)

HTTP_ERROR_RATE_BY_SERVICE = (
    'sum by (destination_service_name) ('
    'rate(istio_requests_total{{'
    'namespace="{namespace}",response_code=~"5.."'
    '}}[{window}])) / sum by (destination_service_name) ('
    'rate(istio_requests_total{{'
    'namespace="{namespace}"'
    '}}[{window}]))'
)

REQUEST_RATE_BY_SERVICE = (
    'sum by (destination_service_name) ('
    'rate(istio_requests_total{{'
    'namespace="{namespace}"'
    '}}[{window}]))'
)

# ---------------------------------------------------------------------------
# Safe renderer
# ---------------------------------------------------------------------------


def render(template: str, **kwargs: str) -> str:
    """Substitute ``**kwargs`` into ``template`` after validation.

    Raises
    ------
    ValueError
        If a placeholder value fails its regex validator, or if any
        placeholder referenced in the template has no supplied value.
    KeyError
        If an undeclared placeholder name appears in the template.

    Examples
    --------
    >>> render(SERVICES_INFO, namespace="prod")
    'kube_service_info{namespace="prod"}'

    >>> render(CPU_USAGE_RATIO, namespace="prod", service="api", window="5m")
    '...'

    >>> render(SERVICES_INFO, namespace="prod; DROP TABLE")
    ValueError: Unsafe value for placeholder 'namespace': 'prod; DROP TABLE'
    """
    # 1. Identify placeholders actually used in this template
    formatter = string.Formatter()
    used: set[str] = set()
    for _, field_name, _, _ in formatter.parse(template):
        if field_name is not None:
            used.add(field_name)

    # 2. Check all used placeholders are provided
    missing = used - kwargs.keys()
    if missing:
        raise ValueError(f"Missing placeholder(s): {sorted(missing)}")

    # 3. Validate each provided value
    for key, value in kwargs.items():
        validator = _VALIDATORS.get(key)
        if validator is not None and not validator.match(value):
            raise ValueError(
                f"Unsafe value for placeholder {key!r}: {value!r} "
                f"(must match {validator.pattern!r})"
            )

    return template.format(**kwargs)
