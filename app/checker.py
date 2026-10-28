"""Checks an AI explanation against the statement it explains.

Models can write fluent text with wrong numbers. This module does not trust the text:
it pulls every dollar amount out of the explanation and compares it with the statement.
Plain code, no model, so it is predictable and testable.
"""
import re

AMOUNT = re.compile(r"\$\s?(\d[\d,]*(?:\.\d{1,2})?)")
KEYWORDS = {
    "billed": r"billed|charged",
    "allowed": r"allowed",
    "plan_paid": r"paid|covered",
    "patient_owes": r"you owe|your share|you pay|you are asked to pay",
}


def label_amounts(text: str):
    """Pair a dollar amount with a label only when the keyword sits right in front of it.

    Strict on purpose: a false alarm on a correct explanation is worse than a miss.
    Also reads the pattern "$450.00 as the allowed amount".
    """
    out = []
    for m in AMOUNT.finditer(text):
        start = max(text.rfind("$", 0, m.start()), text.rfind(". ", 0, m.start()))
        before = text[start + 1:m.start()].strip().lower()
        after = text[m.end():m.end() + 30].lower()
        label = None
        if re.match(r"\s*(?:each|per|apiece)\b", after):
            continue  # a per-item amount such as "billed at $110 each"; the line items are checked separately
        if re.search(r"(?:above|over|beyond|below|than)\s+(?:the\s+)?(?:allowed|billed)", before):
            continue  # a comparison such as "$750 above the allowed amount: $975", not the allowed amount itself
        for field, kw in KEYWORDS.items():
            if re.search(r"(?:" + kw + r")(?:\s+(?:amount|total|of|is|was|at|about))*[\s:]*$", before):
                label = field
        if label is None and re.match(r"\s*(?:as|is|was)\s+(?:the\s+)?allowed", after):
            label = "allowed"
        if label:
            out.append((label, _num(m.group(1))))
    return out


def _num(s: str) -> float:
    return round(float(s.replace(",", "")), 2)


def allowed_amounts(claim: dict, charges: list[dict]) -> set[float]:
    """Every number the statement itself supports, including simple differences and sums."""
    vals = {claim["billed"], claim["plan_discount"], claim["allowed"], claim["plan_paid"], claim["patient_owes"],
            round(claim["billed"] - claim["allowed"], 2), round(claim["allowed"] - claim["plan_paid"], 2)}
    vals |= {c["amount"] for c in charges}
    vals.add(round(sum(c["amount"] for c in charges), 2))
    for text in (claim.get("owe_breakdown"), claim.get("denial_reason")):
        vals |= {_num(m) for m in AMOUNT.findall(text or "")}
    return {round(v, 2) for v in vals}


def check_statement_math(claim: dict, charges: list[dict]) -> list[str]:
    """Problems in the statement itself, such as line items that do not add up to the billed total."""
    problems = []
    total = round(sum(c["amount"] for c in charges), 2)
    if charges and total != round(claim["billed"], 2):
        problems.append(f"Line items add up to ${total:,.2f} but the statement says billed ${claim['billed']:,.2f}.")
    return problems


def check_explanation(claim: dict, charges: list[dict], text: str) -> dict:
    ok_vals = allowed_amounts(claim, charges)
    mismatches = []
    for raw in AMOUNT.findall(text):
        v = _num(raw)
        if v not in ok_vals:
            mismatches.append({"kind": "unknown_amount", "amount": v,
                               "message": f"${v:,.2f} does not appear anywhere on the statement."})
    for field, v in label_amounts(text):
        if v != round(claim[field], 2):
            mismatches.append({"kind": "wrong_value", "field": field, "amount": v, "expected": round(claim[field], 2),
                               "message": f"The explanation says {field.replace('_', ' ')} is ${v:,.2f}, "
                                          f"but the statement says ${claim[field]:,.2f}."})
    if claim["patient_owes"] > 0 and re.search(r"owe (?:nothing|no money|zero)|nothing (?:is )?owed|no balance", text, re.I):
        mismatches.append({"kind": "wrong_claim", "amount": 0.0, "expected": round(claim["patient_owes"], 2),
                           "message": f"The explanation says nothing is owed, but the statement says ${claim['patient_owes']:,.2f}."})
    seen, unique = set(), []
    for x in mismatches:
        k = (x["kind"], x.get("field"), x["amount"])
        if k not in seen:
            seen.add(k); unique.append(x)
    return {"ok": not unique, "mismatches": unique, "statement_problems": check_statement_math(claim, charges)}
