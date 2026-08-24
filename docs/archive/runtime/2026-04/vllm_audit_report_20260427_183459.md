# Karen vLLM Runtime Audit Report
**Generated:** 2026-04-27 22:34:59 UTC
**Auditor:** Karen Runtime Audit Script v1.0

## Executive Summary

This audit verifies that vLLM is wired as a real live response engine in Karen's runtime,
not a degraded-mode label, fake fallback, or UI-only metadata trick.

---

## Audit Results


### Task 1: Runtime Source of Truth

- ✅ **PASS**: ChatOrchestrator found: src/ai_karen_engine/core/runtime/chat_runtime_control_plane.py
