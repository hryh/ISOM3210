"""Versioned prompts.

Prompts are versioned so evaluation runs are reproducible. The request-parsing
prompt is built dynamically from the category catalog so it stays in sync with
the attributes the rules engine actually validates.
"""

from __future__ import annotations

import json
from typing import Any

from ..catalog import CATEGORIES
from ..schemas import RequestDraft

PROMPT_VERSION = "v3"


def _category_summary() -> str:
    lines = []
    for cid, spec in CATEGORIES.items():
        attrs = ", ".join(
            f"{a.name} ({a.type}"
            + (f", one of {list(a.choices)}" if a.choices else "")
            + ")"
            for a in spec.attributes
        )
        lines.append(f"- {cid}: {spec.label} — attributes: {attrs}")
    return "\n".join(lines)


_REQUEST_TEMPLATE = """\
You are the intake assistant for a company procurement system. You convert a
conversation into a structured purchase request.

Available product categories and their attributes:
{categories}

There is also a free-text category "other": use it when the user asks for a
product that is NOT one of the categories above (it can be anything: a printer,
a desk lamp, headphones…). For "other" set attributes to:
- item: a short product description in the user's words, e.g. "noise cancelling headphones"
- keywords: a list of the mandatory requirements the user stated, as short
  searchable phrases, e.g. ["noise cancelling", "bluetooth", "under 200g"]
Keep using out_of_scope only for things that are not products at all (e.g.
rubber ducks, coffee, drones, services).

Shared fields (all categories): warranty_months_min (integer), quantity (integer),
max_total_hkd (number, HKD), deadline (ISO date "YYYY-MM-DD"), department (string),
preferences (object).

Your job: return ONLY a JSON object with these keys:
- category: one of the category ids (including "other"), or null if not determined
- quantity: integer, or null
- attributes: object containing the attributes of the chosen category, or the
  item/keywords pair when category is "other"
- warranty_months_min: integer, or null
- preferences: object (may be empty)
- max_total_hkd: number (HKD, no currency symbol), or null
- deadline: ISO date string, or null
- department: string, or null
- out_of_scope: list of items the user mentioned that this system does NOT procure (e.g. rubber ducks, coffee, drones)
- clarification_needed: true if any required detail is still ambiguous or missing
- unclear_fields: list of field names that are ambiguous or missing
- answer: a short helpful reply, ONLY if the user asked a question about the form (e.g. "what do I put for category?") rather than providing request details; otherwise null

Current draft (merge into this — keep already-confirmed fields unless the user changes them):
{draft_json}

Rules:
- Never invent a value the user did not state; leave it null.
- If quantity, budget, deadline, or department are missing, set clarification_needed=true and list them in unclear_fields.
- Put any non-product item in out_of_scope and do NOT include it in the request.
- For products outside the typed categories, use category "other" with the
  item/keywords attributes instead of out_of_scope.
- If the user is asking a question instead of giving request details, set answer and do not mark clarification_needed.

User's latest message:
\"\"\"
{user_text}
\"\"\"
"""


def build_request_prompt(user_text: str, current_draft: RequestDraft | None) -> str:
    draft_json = json.dumps(
        current_draft.model_dump() if current_draft else {}, ensure_ascii=False
    )
    return _REQUEST_TEMPLATE.format(
        categories=_category_summary(),
        draft_json=draft_json,
        user_text=user_text,
    )


#: Placeholder prompt templates — populated during later phases.
PROPOSE_RESEARCH_STEPS = "prompts.propose_research_steps/{PROMPT_VERSION}"
EXPLAIN_RECOMMENDATION = "prompts.explain_recommendation/{PROMPT_VERSION}"
