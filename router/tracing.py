"""OTel tracing -> self-hosted Phoenix (HERMES-ROUTER-001).

Collector at localhost (HTTP 6006 / gRPC 4317).
"""
from __future__ import annotations
import os

PHOENIX_ENDPOINT = os.environ.get("PHOENIX_COLLECTOR_ENDPOINT", "http://localhost:6006")
PROJECT_NAME = os.environ.get("HERMES_ROUTER_PROJECT", "hermes-router")


def get_tracer(project_name: str = PROJECT_NAME):
    from phoenix.otel import register
    tracer_provider = register(
        project_name=project_name,
        endpoint=f"{PHOENIX_ENDPOINT}/v1/traces",
        auto_instrument=False,
    )
    return tracer_provider.get_tracer(__name__)
