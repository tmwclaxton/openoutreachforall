# linkedin/ml/lead_score.py
"""Claude-based lead prioritisation against the Grantgunner context.

Each lead gets a 0-100 fit score + a one-line reason, derived from the
free-text context in SiteConfig.ai_context. LLM-only (no browser), so it can
run anywhere with the configured model.
"""
from __future__ import annotations

import logging

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class LeadScore(BaseModel):
    score: int = Field(description="Fit score 0-100 (100 = perfect fit)")
    reason: str = Field(description="One concise sentence explaining the score")


def score_lead(lead, context: str) -> dict:
    from pydantic_ai import Agent

    from linkedin.llm import get_llm_model, run_agent_sync

    prompt = (
        "Score how good a LinkedIn lead is for our outreach.\n\n"
        f"OUR CONTEXT (what we sell + ideal customer):\n{context}\n\n"
        "LEAD:\n"
        f"- Name: {lead.first_name} {lead.last_name}\n"
        f"- Title: {lead.title}\n"
        f"- Company: {lead.company}\n"
        f"- Location: {lead.location}\n\n"
        "Return a fit score 0-100 and a one-sentence reason."
    )
    agent = Agent(get_llm_model(), output_type=LeadScore)
    result = run_agent_sync(agent.run(prompt)).output
    return {"score": max(0, min(100, int(result.score))), "reason": result.reason}


def score_pending_leads(limit: int = 15) -> int:
    """Score leads with no ai_score yet, using SiteConfig.ai_context. No context
    set → no-op. Returns the number scored."""
    from crm.models import Lead
    from linkedin.models import SiteConfig

    context = (SiteConfig.load().ai_context or "").strip()
    if not context:
        return 0
    scored = 0
    for lead in Lead.objects.filter(ai_score__isnull=True, disqualified=False)[:limit]:
        try:
            result = score_lead(lead, context)
        except Exception:
            logger.exception("Lead score failed for %s", lead.public_identifier)
            continue
        lead.ai_score = result["score"]
        lead.ai_reason = result["reason"]
        lead.save(update_fields=["ai_score", "ai_reason"])
        scored += 1
    return scored
