"""Planner, tool executor, and critic for requests the copilot can handle."""
from decimal import Decimal
import http.client
import json
import re

from .equipment import expense_calculator, request_draft
from .handbook import REQUIRED_CITATIONS
from .store import ConcurrentUpdate, RateLimited, checked_session
from .telemetry import MAX_STEPS, StepLimit, Trace

EXTERNAL_ACTION = re.compile(
    r"^\s*(?:(?:please|can you|could you|would you)\s+)?"
    r"(?:approve|submit|send|pay|process|access|open|change|delete|file)\b"
    r"|\b(?:my (?:claim|expense report) status|status of my (?:claim|expense report))\b", re.I,
)
EMAIL = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
RETRYABLE = (OSError, RuntimeError, http.client.HTTPException)
REFUSAL = "I can explain the public policy or prepare a draft for your review. I cannot access private records or submit, approve, or pay an expense."


class EvidenceError(ValueError):
    pass


def plan_equipment(facts, results):
    """Choose the next tool from validated facts and outputs already reviewed."""
    if "handbook_search" not in results:
        return "handbook_search"
    if facts.next_question()[0] or not facts.eligible:
        return None
    if "expense_calculator" not in results:
        return "expense_calculator"
    if facts.draft and Decimal(results["expense_calculator"]["estimate_usd"]) > 0 and "request_draft" not in results:
        return "request_draft"
    return None


def criticize(name, result, facts, results):
    if name == "handbook_search":
        required = {"equipment", "personal_payment"}
        if facts.allowance:
            required.add(facts.allowance)
        links = {source["url"] for source in result}
        if any(REQUIRED_CITATIONS[key] not in links for key in required):
            raise EvidenceError("Missing pinned policy evidence.")
    elif name == "expense_calculator":
        paid, estimate = Decimal(result["paid_usd"]), Decimal(result["estimate_usd"])
        balance = Decimal(facts.remaining)
        if paid + Decimal(facts.credits) != Decimal(facts.price):
            raise EvidenceError("The amount paid does not reconcile.")
        if not (0 <= estimate <= paid and estimate <= balance and estimate in (paid, balance)):
            raise EvidenceError("The estimate does not reconcile with the policy limits.")
    elif name == "request_draft":
        if (result["amount_usd"] != results["expense_calculator"]["estimate_usd"]
                or not result["text"].startswith("Draft for human review")):
            raise EvidenceError("The draft failed review.")


class Copilot:
    def __init__(self, store, handbook, chat=None, tracer=None):
        self.store = store
        self.handbook = handbook
        self.chat = chat
        self.tracer = tracer

    def run(self, session, operation):
        checked_session(session)
        trace = Trace(self.tracer)
        with trace.turn() as span:
            try:
                self.store.reserve(session)
                response = operation(trace)
            except RateLimited as exc:
                response = {"status": "rate_limited", "message": str(exc)}
            except ConcurrentUpdate as exc:
                response = {"status": "conflict", "message": str(exc)}
            except (StepLimit, EvidenceError, KeyError, TypeError, IndexError, ArithmeticError):
                response = {"status": "unverified", "message": "I could not verify the result within the workflow limits."}
            except ValueError as exc:
                # Tool validation errors are wrapped by execute before reaching this boundary.
                response = {"status": "invalid", "message": str(exc)}
            except RETRYABLE:
                response = {"status": "unavailable", "message": "A tool is unavailable. Try again shortly."}
            if span:
                span.set_attribute("copilot.outcome", response["status"])
        response["trace_id"] = self.store.record_trace(session, response["status"], trace.steps)
        response["steps"] = trace.steps
        return response

    @staticmethod
    def execute(trace, name, tool, *, retry=False):
        attempts = 2 if retry else 1
        for attempt in range(attempts):
            try:
                with trace.step("executor", name) as step:
                    if attempt:
                        step["retry"] = True
                    result = tool()
                    if name == "course_chat":
                        for field in ("input_tokens", "output_tokens"):
                            count = result.get(field)
                            if count is not None:
                                if type(count) is not int or count < 0:
                                    raise EvidenceError("Invalid model token count.")
                                step[field] = count
                    return result
            except StepLimit:
                raise
            except RETRYABLE:
                if attempt + 1 == attempts or len(trace.steps) + 2 > MAX_STEPS:
                    raise
            except (ValueError, TypeError, KeyError, IndexError) as exc:
                raise EvidenceError("Malformed tool result.") from exc

    def equipment(self, session, update):
        def operation(trace):
            version, saved = self.store.load(session)
            facts = saved.update(update)
            results = {}
            while name := plan_equipment(facts, results):
                with trace.step("planner", "equipment") as step:
                    step["next_tool"] = name
                tools = {
                    "handbook_search": self.handbook.equipment,
                    "expense_calculator": lambda: expense_calculator(facts),
                    "request_draft": lambda: request_draft(facts, results["expense_calculator"]),
                }
                result = self.execute(trace, name, tools[name], retry=name == "handbook_search")
                with trace.step("critic", name):
                    criticize(name, result, facts, results)
                results[name] = result

            if facts != saved:
                self.store.save(session, version, facts)
            keys = ["equipment", "personal_payment"]
            if facts.allowance:
                keys.append(facts.allowance)
            urls = {REQUIRED_CITATIONS[key] for key in keys}
            sources = [source for source in results["handbook_search"] if source["url"] in urls]
            field, question = facts.next_question()
            if field:
                return {"status": "clarify", "message": question, "next_field": field, "sources": sources}
            if not facts.eligible:
                return {"status": "ineligible", "message": "Based on your confirmation, this allowance does not apply.",
                        "sources": sources}
            estimate = results["expense_calculator"]
            return {
                "status": "complete", "message": (
                    f"Estimated claim: USD {estimate['estimate_usd']}. "
                    f"You paid USD {estimate['paid_usd']} out of pocket and reported "
                    f"USD {facts.remaining} of remaining allowance."
                ),
                "estimate": estimate, "draft": results.get("request_draft"), "sources": sources,
            }

        return self.run(session, operation)

    def policy(self, session, question):
        def operation(trace):
            if not isinstance(question, str) or not (1 <= len(question.strip()) <= 500):
                raise ValueError("Enter a policy question of 1–500 characters.")
            query = SSN.sub("[redacted ID]", EMAIL.sub("[redacted email]", question.strip()))
            with trace.step("planner", "policy") as step:
                if EXTERNAL_ACTION.search(query):
                    step["next_tool"] = "refuse"
                    return {"status": "refused", "message": REFUSAL}
                step["next_tool"] = "handbook_search"
            sources = self.execute(trace, "handbook_search", lambda: self.handbook.search(query), retry=True)
            with trace.step("critic", "handbook_search"):
                if not sources:
                    return {"status": "unverified", "message": "I could not find relevant public handbook evidence."}
            if self.chat is None:
                return {"status": "evidence", "message": "Matching passages from the demo handbook index.", "sources": sources}

            from evaluate_rag import CITE, MAX_TOKENS, PROMPT

            labelled = {f"T1-S{index}": source for index, source in enumerate(sources, 1)}
            payload = json.dumps({"question": query, "handbook_passages": [
                {"source_id": key, "text": source["text"], "citation": source["url"]}
                for key, source in labelled.items()
            ]}, ensure_ascii=False)
            with trace.step("planner", "cited_answer"):
                # Bound the UTF-8 input conservatively, with room for chat formatting and the output cap.
                if len((PROMPT + payload).encode()) + MAX_TOKENS + 256 > 8192:
                    raise StepLimit("The model request would exceed the budget.")
                messages = [{"role": "system", "content": PROMPT}, {"role": "user", "content": payload}]

            reply = self.execute(trace, "course_chat", lambda: self.chat(messages))
            answer = reply["response"]
            input_tokens, output_tokens = reply.get("input_tokens"), reply.get("output_tokens")
            with trace.step("critic", "course_chat"):
                refs = list(dict.fromkeys(CITE.findall(answer)))
                if not refs or any(ref not in labelled for ref in refs):
                    raise EvidenceError("Answer has missing or unknown citations.")
                if (input_tokens is not None and output_tokens is not None
                        and input_tokens + output_tokens > 8192):
                    raise StepLimit("Reported token usage exceeded the budget.")
            return {"status": "complete", "message": answer, "sources": [
                {**labelled[ref], "title": f"[{ref}] {labelled[ref]['title']}"} for ref in refs
            ]}

        return self.run(session, operation)
