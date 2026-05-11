# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] - 2026-05-10

## [0.1.4] - 2026-05-08

### Fixed
- `boto3.client()` was called synchronously inside async functions, causing a
  blocking HTTP request to the EC2 instance metadata service (IMDS) at
  `169.254.169.254` during credential resolution. This manifested as an
  `HTTPClientError` in Home Assistant's async event loop. The client is now
  created via `loop.run_in_executor()` like the subsequent API calls.

## [0.1.3] - 2026-05-08

### Fixed
- Regenerated gRPC stubs with `grpcio-tools==1.78.0` so the library works
  inside Home Assistant, which hard-pins `grpcio==1.78.0` in its package
  constraints. Previously the stubs were generated with 1.80.0 and raised
  `RuntimeError` at import time on older grpcio versions.

## [0.1.2] - 2026-05-08

## [0.1.1] - 2026-05-08

## [0.1.0]

### Added
- GitHub Actions release automation for SemVer tags (`vX.Y.Z`) that enforces quality gates, creates a GitHub Release, and publishes distribution artifacts to PyPI via trusted publishing
- Initial async client for Quilt cloud gRPC API
- Cognito OTP authentication with token caching
- HomeDatastoreService: spaces, indoor units, comfort settings, schedules
- SystemInformationService: system listing, energy metrics
- NotifierService: real-time streaming subscriptions
- CLI for interactive use (`quilt` command)
