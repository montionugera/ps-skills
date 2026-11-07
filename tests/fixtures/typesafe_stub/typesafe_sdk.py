"""Offline stand-in for the paid typesafe_sdk System-1 model, so jev-gate tests are hermetic (CI has no API key).

Answers are keyword-driven; the tests exercise jev-gate's own routing/override logic, not the remote model.
"""
import re
from types import SimpleNamespace as NS

_RISKY = re.compile(r"\b(sso|jwt|auth|migration|security|payments?)\b", re.I)
_REVIEW = re.compile(r"\b(audit|review|falsif\w*)\b", re.I)


class Choice:
    def __init__(self, **kw):
        pass


Noul = Score = Choice


class TypeSafeClient:
    def __init__(self, api_key=None, timeout=None):
        pass

    def system_one(self, model, state, questions):
        text = state.get("subagent_prompt", "")
        risky = bool(_RISKY.search(text))
        review = bool(_REVIEW.search(text))
        answers = {
            "route": NS(choice="agy_argon" if risky else "agy_flash", confidence=0.95),
            "is_reviewer": NS(noul=0.9 if review else 0.05),
            "is_scouting": NS(noul=0.05),
            "cloud_compatible": NS(noul=0.1),
            "touches_risky_surface": NS(noul=0.9 if risky else 0.05),
            "complexity": NS(score=2.5 if risky else 0.5),
        }
        return NS(model="stub", answers=answers, usage=NS(input_tokens=len(text)))
