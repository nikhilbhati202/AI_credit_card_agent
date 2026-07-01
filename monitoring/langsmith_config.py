"""LangSmith tracing (guide Section 19 - listed as a Must Have from Phase 1 onward).

No code is needed here: LangChain and LangGraph auto-detect LANGCHAIN_TRACING_V2 and
LANGCHAIN_API_KEY from the environment and trace every LLM call and graph run automatically
once both are set (see .env.example). This module exists as the named, documented home for
that fact (Section 5's folder structure) rather than a place with actual logic - wiring in a
whole tracing SDK by hand would duplicate what the environment variables already do for free.

To enable: set LANGCHAIN_TRACING_V2=true and LANGCHAIN_API_KEY=<your LangSmith key> in .env.
Optionally set LANGCHAIN_PROJECT to group traces under a named project.
"""
