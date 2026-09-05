"""LLM explanation layer — provider abstraction with a deterministic fallback.

CRITICAL invariant: the LLM (real or templated) is only ever handed numbers
that were already computed by deterministic code (detectors, root-cause
engine, money-at-risk engine). It classifies/summarizes/phrases; it never
invents a rupee figure, a transaction id, or a root cause of its own.

If ANTHROPIC_API_KEY is set, real Claude calls are used to *phrase* the
explanation (still constrained to the given facts via a strict system
prompt). Otherwise a deterministic template produces the same shape of
output — the product works fully with zero external credentials.
"""
import os
from abc import ABC, abstractmethod


class LLMProvider(ABC):
    @abstractmethod
    def explain(self, facts: dict) -> str:
        ...

    @abstractmethod
    def answer(self, question: str, context_facts: dict) -> str:
        ...


class DeterministicTemplateProvider(LLMProvider):
    def explain(self, facts: dict) -> str:
        etype = facts["exception_type"].replace("_", " ")
        amount = facts["money_at_risk"]
        recoverable = facts.get("recoverable_amount", 0)
        classification = facts["final_classification"].replace("_", " ")
        confidence = facts["confidence"]
        calc = facts.get("calculations", {})

        lines = [f"₹{amount:,.0f} is currently at risk from {etype}."]
        if calc:
            parts = [f"₹{v:,.0f} {k.replace('_', ' ')}" for k, v in calc.items()
                     if isinstance(v, (int, float)) and v > 0 and k != "total_variance"]
            if parts:
                lines.append("Breakdown: " + ", ".join(parts) + ".")
        lines.append(f"Root cause classified as {classification} with {confidence:.0%} confidence.")
        if recoverable > 0:
            lines.append(f"₹{recoverable:,.0f} of this is calculated as recoverable.")
        action = facts.get("recommended_action", "").replace("_", " ")
        if action:
            lines.append(f"Recommended action: {action}.")
        return " ".join(lines)

    def answer(self, question: str, context_facts: dict) -> str:
        total_risk = context_facts.get("total_money_at_risk", 0)
        n_open = context_facts.get("open_exceptions", 0)
        top = context_facts.get("top_exceptions", [])
        lines = [f"₹{total_risk:,.0f} is currently at risk across {n_open} open exceptions."]
        for t in top[:3]:
            lines.append(f"- {t['exception_type'].replace('_',' ')} on {t['merchant_name']}: "
                          f"₹{t['money_at_risk']:,.0f} ({t['confidence']:.0%} confidence)")
        return "\n".join(lines)


class AnthropicProvider(LLMProvider):
    """Thin wrapper — only used if ANTHROPIC_API_KEY is configured. Falls
    back to the deterministic provider on any failure so the product never
    hard-depends on network access."""

    SYSTEM_PROMPT = (
        "You are a financial control narration assistant. You will be given "
        "a JSON object of ALREADY-COMPUTED facts (amounts, confidences, root "
        "causes). Rephrase them clearly for a finance operator in 2-4 "
        "sentences. Do NOT introduce any number, transaction id, or cause "
        "that is not present in the JSON. Do NOT state certainty beyond the "
        "given confidence score."
    )

    def __init__(self):
        import anthropic  # imported lazily; optional dependency
        self._client = anthropic.Anthropic()
        self._fallback = DeterministicTemplateProvider()

    def explain(self, facts: dict) -> str:
        try:
            import json
            msg = self._client.messages.create(
                model="claude-sonnet-5",
                max_tokens=300,
                system=self.SYSTEM_PROMPT,
                messages=[{"role": "user", "content": json.dumps(facts, default=str)}],
            )
            return msg.content[0].text
        except Exception:
            return self._fallback.explain(facts)

    def answer(self, question: str, context_facts: dict) -> str:
        try:
            import json
            msg = self._client.messages.create(
                model="claude-sonnet-5",
                max_tokens=300,
                system=self.SYSTEM_PROMPT,
                messages=[{"role": "user", "content": f"Question: {question}\nFacts: {json.dumps(context_facts, default=str)}"}],
            )
            return msg.content[0].text
        except Exception:
            return self._fallback.answer(question, context_facts)


_provider = None


def get_llm_provider() -> LLMProvider:
    global _provider
    if _provider is not None:
        return _provider
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            _provider = AnthropicProvider()
            return _provider
        except Exception:
            pass
    _provider = DeterministicTemplateProvider()
    return _provider
