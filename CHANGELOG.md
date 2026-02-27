# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]
### Added
- Added `mco doctor` command with human-readable and `--json` outputs to probe provider binary/auth readiness.
- Added `--format markdown-pr` (review-only) to render PR-ready Markdown summaries from aggregated findings.
- Added opt-in `--include-token-usage` to include best-effort provider token usage and aggregate token summary in outputs.

### Changed
- Added deterministic cross-provider findings deduplication in review aggregation and `findings.json`, with merged `detected_by` provenance and max-confidence rollup.

## [0.3.2] - 2026-02-27
### Changed
- Added run-mode answer extraction fields per provider: `final_text`, `response_ok`, and `response_reason`, while keeping `output_text` as raw output for debugging.
- Improved `final_text` extraction quality for event-stream outputs by preferring high-signal answer candidates over trailing low-signal tokens.

## [0.3.1] - 2026-02-27
### Changed
- Made stdout mode truly non-persistent by default: no artifact files are written unless `--save-artifacts` or `--result-mode artifact/both` is used.
- In stdout mode without artifact writes, `artifact_root` and provider `output_path` now return `null`.
- Unified adapter detect/probe binary resolution and environment handling with runtime execution (`shutil.which` + sanitized env) and refined auth probe reason classification (`auth_check_failed`, `probe_config_error`, `probe_unknown_error`).

## [0.3.0] - 2026-02-27
### Changed
- Disabled runtime idempotency/dispatch cache replay; repeated invocations now always re-execute providers.
- Extended stdout payloads and human-readable output to include full per-provider output text (not only excerpt).
- Removed legacy idempotency/state/cache knobs and fields (`--idempotency-key`, `--state-file`, `created_new_task`, `deduped_dispatch`, `dispatch_key`).

## [0.2.1] - 2026-02-26
### Changed
- Changed default CLI delivery mode to stdout-first (`--result-mode stdout`) so agent callers receive results directly without mandatory artifact reads.
- Added `--save-artifacts` to explicitly persist artifact files while keeping stdout result delivery.
- Updated benchmark script to explicitly opt into artifact persistence (`--save-artifacts`).
- Repositioned README (EN/CN) messaging around "Any Prompt. Any Agent. Any IDE." and clarified caller-agent orchestration scenarios.

## [0.2.0] - 2026-02-26
### Changed
- Removed config-file mode from CLI; `mco` now uses built-in defaults with flag-only overrides.
- Removed `--config` from `mco run` / `mco review`; passing it now errors as unsupported.
- Updated benchmark automation to run without config files and to report provider set directly.
- Updated README (EN/CN) to document zero-config usage with CLI flag overrides only.

### Removed
- Removed config file loading path (`load_review_config`) and related YAML/JSON config parsing.
- Removed sample config files (`mco.example.json`, `mco.step3-baseline.json`).

## [0.1.3] - 2026-02-26
### Added
- Added full Simplified Chinese README (`README.zh-CN.md`) with language switch links.
- Added environment sanitization for provider subprocesses to strip `CLAUDECODE`.

### Changed
- Aligned review findings schema and parser contract by making `evidence.line` and `evidence.symbol` optional keys.
- Clarified installation channels in docs: npm available now, PyPI pending Trusted Publisher setup.

### Fixed
- Implemented real retry backoff sleep in runtime retry loop.
- Released adapter run handles in terminal and cancel paths to avoid in-memory handle growth.
- Switched CLI config parsing to fail-fast for invalid `--provider-timeouts` and `--provider-permissions-json`.

## [0.1.2] - 2026-02-26
### Added
- Added packaging metadata (`pyproject.toml`) and `mco` console entrypoint.
- Added npm wrapper package (`@tt-a1i/mco`) for Node-based environments.
- Added publishing workflows for PyPI and npm.

### Changed
- Updated repository naming and distribution identity to `mco`.
- Updated README and release docs for install and usage guidance.

## [0.1.1] - 2026-02-26
### Added
- Added provider permission contract docs.
- Added release governance artifacts (`CODEOWNERS`, release notes updates).

### Fixed
- Hardened npm publish workflow behavior when `NPM_TOKEN` is missing.
- Fixed npm workflow syntax/guard issues for reliable CI execution.

## [0.1.0] - 2026-02-26
### Added
- Initial runnable runtime for multi-provider orchestration (`run` and `review` commands).
- Provider adapters for `claude`, `codex`, `gemini`, `opencode`, and `qwen`.
- Progress-driven timeout handling, retry semantics, idempotent dispatch, and notification dedupe.
- Canonical findings normalization, review decisioning, and artifact outputs (`summary.md`, `decision.md`, `findings.json`, `run.json`).
- Runtime gate, adapter contract tests, and benchmark/probe scripts.
