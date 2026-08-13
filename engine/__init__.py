"""Deterministic layer: projections, start/sit grading, calibration, behavior.

No LLM calls live in this package (CLAUDE.md architecture) and nothing here
touches the network — every input comes from the Phase 1 cache in ``data/raw/``.
"""
