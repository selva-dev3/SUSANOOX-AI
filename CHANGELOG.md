# Changelog

All notable changes to Susanoox will be documented here.

## Unreleased

- Make automatic project context opt-in by default while preserving explicit runtime, CLI, global,
  and project-level enablement.
- Initial package, Textual interface, secure onboarding, and streaming conversation implementation.
- Add explicit plan mode with approval, revision, cancellation, and persisted plan state.
- Add bounded, explainable automatic project-context selection with ignore and secret protections.
- Add versioned SQLite sessions and rolling structured conversation summaries.
- Add bounded, observable retry handling for transient, context-overflow, and empty-output failures.
- Preserve reduced project context during overflow recovery and strictly bound compacted context.
- Add durable task checklists, validated task DAGs, bounded sub-agents, resource-aware parallel
  scheduling, background task lifecycle management, crash interruption, and bounded recovery.
- Keep approved UI plans explicitly non-executable, enforce worker tool access through centralized
  capabilities, route worker models under bounded leases, and harden cancellation and recovery.
