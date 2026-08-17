# Project Agent Instructions

Read `AGENT.MD` before changing model integration, tool calling, streaming,
handoffs, structured output, tracing, or guardrails.

Backend architecture notes live under `docs/ai/`. Keep deterministic search,
scoring, POI enrichment, persistence, and event delivery outside the LLM agent
runtime. Do not start a framework migration by rewriting the frontend.
