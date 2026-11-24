"""Typed facts and deterministic equipment tools for the pinned GitLab policy."""
from dataclasses import dataclass, fields, replace
from decimal import Decimal
import re

ITEMS = ("monitor", "desk", "chair", "headset", "external keyboard", "external mouse", "webcam", "laptop stand")
ALLOWANCES = {"new_hire": Decimal("1500.00"), "annual_refresh": Decimal("500.00")}
NAVAN_ITEM_LIMIT = Decimal("5000.00")
MONEY_FIELDS = ("price", "credits", "remaining")
QUESTIONS = {
    "item": "Which supported home-office item did you buy?",
    "allowance": "Are you using the new-hire stipend or the annual equipment refresh?",
    "eligible": {
        "new_hire": "Was the purchase within your first year at GitLab?",
        "annual_refresh": "Were you employed by GitLab for the entire calendar year before the purchase year?",
    },
    "price": "What was the total purchase price in USD?",
    "credits": "How much was covered by gift cards, discounts, or other credits in USD? Enter 0 if none.",
    "remaining": "How much of the selected allowance was available before this purchase, in USD?",
}
MONEY = re.compile(r"[0-9]{1,7}(?:\.[0-9]{1,2})?")


@dataclass(frozen=True)
class Equipment:
    item: str | None = None
    allowance: str | None = None
    eligible: bool | None = None
    price: str | None = None
    credits: str | None = None
    remaining: str | None = None
    draft: bool = False

    def update(self, values):
        if not isinstance(values, dict) or values.keys() - {field.name for field in fields(self)}:
            raise ValueError("Enter a JSON object with supported equipment fields.")
        values = dict(values)
        for name in MONEY_FIELDS:
            if name in values:
                value = values[name]
                if not isinstance(value, str) or not MONEY.fullmatch(value):
                    raise ValueError(f"{name} must be a USD amount such as 180.00.")
                values[name] = format(Decimal(value), ".2f")
        if "item" in values and values["item"] not in ITEMS:
            raise ValueError("Choose a supported item. A monitor here means a standard monitor.")
        if "allowance" in values and values["allowance"] not in tuple(ALLOWANCES):
            raise ValueError("Choose the new-hire stipend or the annual refresh.")
        for name in ("eligible", "draft"):
            if name in values and type(values[name]) is not bool:
                raise ValueError(f"{name} must be true or false.")
        if "allowance" in values and values["allowance"] != self.allowance:
            # Eligibility and available balance apply to a specific allowance.
            values.setdefault("eligible", None)
            values.setdefault("remaining", None)
        updated = replace(self, **values)
        if updated.price is not None:
            price = Decimal(updated.price)
            if price > NAVAN_ITEM_LIMIT:
                raise ValueError("Check the procurement process for a single item above USD 5,000.")
            if updated.credits is not None and Decimal(updated.credits) > price:
                raise ValueError("Credits cannot exceed the purchase price.")
        if updated.remaining is not None and updated.allowance and Decimal(updated.remaining) > ALLOWANCES[updated.allowance]:
            raise ValueError("The available balance exceeds the limit for this allowance.")
        return updated

    def next_question(self):
        for name, prompt in QUESTIONS.items():
            if getattr(self, name) is None:
                return name, prompt[self.allowance] if name == "eligible" else prompt
            if name == "eligible" and not self.eligible:
                break
        return None, None


def expense_calculator(facts):
    if facts.next_question()[0] or not facts.eligible:
        raise ValueError("The calculator requires confirmed eligibility and purchase amounts.")
    paid = Decimal(facts.price) - Decimal(facts.credits)
    estimate = min(paid, Decimal(facts.remaining))
    return {"paid_usd": format(paid, ".2f"), "estimate_usd": format(estimate, ".2f")}


def request_draft(facts, estimate):
    category = (
        "Work From Home – New Hire Stipend" if facts.allowance == "new_hire"
        else "annual home-office equipment refresh"
    )
    return {
        "amount_usd": estimate["estimate_usd"],
        "text": (
            f"Draft for human review\n\nNavan expense: {category}\n"
            f"Item: {facts.item}\nPurchase date: [fill in]\nVendor: [fill in]\n"
            f"Purchase price: USD {facts.price}\nCredits applied: USD {facts.credits}\n"
            f"Paid out of pocket: USD {estimate['paid_usd']}\n"
            f"Estimated claim: USD {estimate['estimate_usd']}\n"
            "Business purpose: [fill in]\nReceipt or supporting document: [attach before submitting]"
        ),
    }
