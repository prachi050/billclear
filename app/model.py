"""The 'AI' behind the explanation. Two interchangeable providers.

MockModel  : no AI. Fills a template, and can inject a wrong number on purpose so the
             checker can be tested. Always labeled "mock" in the UI.
MetaModel  : calls the Meta Model API (see app/metaclient.py).

Settings (environment variables on your computer, never in code, never in the browser):
  BILLCLEAR_MODEL=mock | meta        (default: mock)
  MODEL_API_KEY=...                  (needed for meta)
"""
import os
import random


def _money(x: float) -> str:
    return f"${x:,.2f}"


class MockModel:
    name = "mock (no AI)"

    def explain(self, claim: dict, charges: list[dict], corrupt: str | None = None, rng: random.Random | None = None) -> str:
        rng = rng or random.Random(1)
        owes, paid, allowed, billed = claim["patient_owes"], claim["plan_paid"], claim["allowed"], claim["billed"]
        if corrupt == "wrong_owes":
            owes = round(owes + rng.choice([10, 25, 50, 100, 130]), 2)
        elif corrupt == "digit_swap":
            s = f"{owes:.2f}".replace(".", "")
            owes = round(float(s[::-1][:-2] + "." + s[::-1][-2:]) if len(s) > 2 and s != s[::-1] else owes + 9, 2)
        elif corrupt == "wrong_paid":
            paid = round(paid + rng.choice([20, 45, 60]), 2)
        elif corrupt == "swap_valid":      # a wrong but real-looking number taken from elsewhere on the statement
            owes = allowed if allowed != owes else billed
        elif corrupt == "invented":
            pass
        text = (f"{claim['provider']} billed {_money(billed)}. Your plan counted {_money(allowed)} as the allowed amount "
                f"and the plan paid {_money(paid)}. You owe {_money(owes)}. {claim.get('owe_breakdown') or ''}")
        if corrupt == "no_number":         # a wrong claim that contains no number at all
            text = text.replace(f"You owe {_money(owes)}.", "You owe nothing.")
        if corrupt == "invented":
            text += f" A late fee of {_money(round(rng.uniform(15, 80), 2))} was also added."
        return text.strip()


class MetaModel:
    name = "Meta Model API"

    def explain(self, claim: dict, charges: list[dict], corrupt=None, rng=None) -> str:
        from . import metaclient
        facts = {k: claim[k] for k in ("provider", "service_date", "doc_type", "status", "billed", "plan_discount",
                                       "allowed", "plan_paid", "patient_owes", "in_network", "denial_reason") if k in claim}
        prompt = ("You explain a FICTIONAL sample medical statement to a patient in plain, calm words, in under 110 words.\n"
                  "Rules: use only dollar amounts that appear in the data below. Do not calculate new amounts. "
                  "Say what was billed, what the plan allowed and paid, and what the patient owes. "
                  "Do not give medical, legal or financial advice.\n"
                  f"Statement: {facts}\nLine items: {[(c['code'], c['description'], c['amount']) for c in charges]}")
        return metaclient.chat(prompt, max_tokens=2500)


def get_model():
    use_meta = os.environ.get("BILLCLEAR_MODEL", "mock").lower() == "meta"
    return MetaModel() if use_meta else MockModel()
