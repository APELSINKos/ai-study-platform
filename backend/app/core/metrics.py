from typing import Final

from prometheus_client import Counter, Histogram

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

HTTP_REQUESTS = Counter(
    "http_requests_total", "HTTP requests handled by the API.", ["method", "route", "status"]
)
HTTP_REQUEST_DURATION = Histogram(
    "http_request_duration_seconds",
    "Time spent handling HTTP requests.",
    ["method", "route"],
    buckets=HTTP_LATENCY_BUCKETS_SECONDS,
)


def observe_http_request(method: str, route: str, status: int, duration_seconds: float) -> None:
    HTTP_REQUESTS.labels(method=method, route=route, status=str(status)).inc()
    HTTP_REQUEST_DURATION.labels(method=method, route=route).observe(duration_seconds)
