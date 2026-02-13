"""Pydantic AI agents for the SRE Copilot.

Multi-Agent Architecture:
- Dispatcher (Claude Sonnet 4.5): Fast triage, decides explanation depth
- Researcher (Claude Opus 4.6): Deep analysis with RAG context

Key Principle: "Rules Decide, AI Explains"
- Health state is determined by deterministic rules in the Health State Machine
- Agents EXPLAIN the state, they do NOT decide or change it
"""

from copilot.agents.dispatcher import (
    DispatcherOutput,
    NeedsDeepExplanation,
    NoExplanationNeeded,
    QuickExplanation,
    build_dispatcher_prompt,
    dispatcher_agent,
)
from copilot.agents.researcher import (
    build_researcher_prompt,
    researcher_agent,
)

__all__ = [
    # Dispatcher
    "dispatcher_agent",
    "build_dispatcher_prompt",
    "DispatcherOutput",
    "NoExplanationNeeded",
    "QuickExplanation",
    "NeedsDeepExplanation",
    # Researcher
    "researcher_agent",
    "build_researcher_prompt",
]
