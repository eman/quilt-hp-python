"""Tests for the transport layer interceptor."""

from __future__ import annotations

from quilt_hp.const import APP_VERSION, Environment, grpc_host


def test_grpc_host_prod() -> None:
    """PROD endpoint returns the expected host."""
    assert grpc_host(Environment.PROD) == "api.prod.quilt.cloud:443"


def test_grpc_host_staging() -> None:
    """STAGING endpoint returns the expected host."""
    assert grpc_host(Environment.STAGING) == "api.staging.quilt.cloud:443"


def test_app_version() -> None:
    """App version constant is set."""
    assert APP_VERSION == "1.0.25"
