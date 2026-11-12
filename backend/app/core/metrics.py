from typing import Final

from prometheus_client import Counter, Histogram

STANDARD_HTTP_METHODS: Final[frozenset[str]] = frozenset(
    {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}
)
OTHER_METHOD_LABEL: Final = "OTHER"

HTTP_LATENCY_BUCKETS_SECONDS: Final = (
    0.005,
    0.01,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
    30.0,
)
# A search's queries on one workspace take milliseconds; the upper buckets catch slow plans.
RETRIEVAL_LATENCY_BUCKETS_SECONDS: Final = (
    0.005,
    0.01,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
)
# A model call takes from a fraction of a second up to a minute, the longest timeout.
LLM_LATENCY_BUCKETS_SECONDS: Final = (
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
    30.0,
    60.0,
)

HTTP_REQUESTS = Counter(
    "http_requests_total", "HTTP requests handled by the API.", ["method", "route", "status"]
)
HTTP_REQUEST_DURATION = Histogram(
    "http_request_duration_seconds",
    "Time spent handling HTTP requests.",
    ["method", "route"],
    buckets=HTTP_LATENCY_BUCKETS_SECONDS,
)
RETRIEVAL_DURATION = Histogram(
    "retrieval_duration_seconds",
    "Time spent finding the passages of a search: its queries, rank fusion and snippets.",
    ["mode"],
    buckets=RETRIEVAL_LATENCY_BUCKETS_SECONDS,
)
LLM_REQUEST_DURATION = Histogram(
    "llm_request_duration_seconds",
    "Time spent waiting for calls to AI models, by operation and outcome.",
    ["operation", "outcome"],
    buckets=LLM_LATENCY_BUCKETS_SECONDS,
)


def observe_http_request(method: str, route: str, status: int, duration_seconds: float) -> None:
    label = method if method in STANDARD_HTTP_METHODS else OTHER_METHOD_LABEL
    HTTP_REQUESTS.labels(method=label, route=route, status=str(status)).inc()
    HTTP_REQUEST_DURATION.labels(method=label, route=route).observe(duration_seconds)
