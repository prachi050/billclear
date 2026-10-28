"""Rule-based helpers: flags, plain-language summaries, next-step questions, appeal drafts.

BillClear never decides that something is definitely wrong. It says what a
statement shows, what looks unusual, and what the person may want to ask.
It gives no medical, legal or financial advice.
"""
from collections import Counter

SAMPLE_NOTICE = ("SAMPLE: This draft was generated from synthetic demo data. It is not sent anywhere "
                 "and does not refer to a real insurer, provider or person.")

MEMBER = {"name": "Alex Rivera (sample)", "member_id": "SAMPLE-0001", "plan": "Northfield Health Plan (fictional)"}


def money(x: float) -> str:
    return f"${x:,.2f}"


def compute_flags(claim: dict, charges: list[dict]) -> list[dict]:
    flags = []
    if claim["doc_type"] == "EOB":
        flags.append({
            "type": "not_a_bill", "severity": "info",
            "title": "This is not a bill",
            "detail": "An Explanation of Benefits shows how your plan handled a claim. You usually pay "
                      "the provider only when you receive a separate bill.",
        })
    if claim["status"] == "denied":
        flags.append({
            "type": "denied", "severity": "action",
            "title": "Claim denied",
            "detail": f"Reason {claim['denial_code']}: {claim['denial_reason']} A denial is often worth asking about.",
        })
    if not claim["in_network"]:
        gap = round(claim["billed"] - claim["allowed"], 2)
        flags.append({
            "type": "out_of_network", "severity": "action",
            "title": "Out-of-network provider",
            "detail": f"Your plan counted only {money(claim['allowed'])} of the {money(claim['billed'])} billed. "
                      f"The {money(gap)} difference is part of what you are asked to pay.",
        })
    counts = Counter((c["code"], c["service_date"], round(c["amount"], 2)) for c in charges)
    for (code, date, amount), n in counts.items():
        if n > 1:
            flags.append({
                "type": "duplicate", "severity": "action",
                "title": "Possible duplicate charge",
                "detail": f"{code} on {date} for {money(amount)} appears {n} times. "
                          "It may be an error, or two real services. Worth confirming.",
                "code": code, "date": date, "amount": amount,
            })
    return flags


def summarize_owed(claim: dict) -> dict:
    return {
        "billed": claim["billed"],
        "plan_discount": claim["plan_discount"],
        "allowed": claim["allowed"],
        "plan_paid": claim["plan_paid"],
        "you_owe": claim["patient_owes"],
        "why": claim["owe_breakdown"],
    }


def next_steps(claim: dict, flags: list[dict]) -> list[str]:
    steps = ["Ask the provider for an itemized bill, so you can compare every line with this statement."]
    types = {f["type"] for f in flags}
    if "not_a_bill" in types:
        steps.append("Wait for the provider's bill before paying, then check it against this statement.")
    if "duplicate" in types:
        steps.append("Ask the provider whether the repeated charge was one service billed twice.")
    if "denied" in types:
        steps.append("Ask your plan how to appeal this denial and what the deadline is.")
        steps.append("Ask the provider whether the missing approval can be sent after the fact.")
    if "out_of_network" in types:
        steps.append("Ask your plan whether this provider was out of network and whether an exception can be reviewed.")
    if claim["patient_owes"] > 0:
        steps.append("Ask the provider whether a payment plan or financial assistance is available.")
    steps.append("These are questions to ask, not guarantees. For medical, legal or financial advice, "
                 "talk to your plan, your provider or a qualified adviser.")
    return steps


def draft_appeal_text(claim: dict, flags: list[dict], reason: str | None = None) -> tuple[str, str]:
    """Return (reason_label, letter_body)."""
    types = [f["type"] for f in flags]
    if "duplicate" in types:
        f = next(f for f in flags if f["type"] == "duplicate")
        label = "Possible duplicate charge"
        ask = (f"Line item {f['code']} on {f['date']} for {money(f['amount'])} appears more than once on this claim. "
               "Please review whether it was billed in error and, if so, correct the claim and my balance.")
    elif "denied" in types:
        label = "Request to review a denial"
        ask = (f"This claim was denied with reason {claim['denial_code']}: {claim['denial_reason']} "
               "Please review the denial, tell me what documents are needed, and explain how to appeal and by when.")
    elif "out_of_network" in types:
        label = "Request to review out-of-network payment"
        ask = (f"This claim was paid as out-of-network, with an allowed amount of {money(claim['allowed'])}. "
               "Please review whether an in-network exception applies and confirm how my share was calculated.")
    else:
        label = "Request for an explanation"
        ask = "Please explain how my share of this claim was calculated and confirm that it is correct."
    if reason:
        ask += f"\n\nAdditional note from me: {reason}"
    body = (
        f"Date: [today's date]\n"
        f"To: Appeals Department, {MEMBER['plan']}\n"
        f"Member: {MEMBER['name']}   Member ID: {MEMBER['member_id']}\n"
        f"Claim: {claim['id']}   Provider: {claim['provider']}   Service date: {claim['service_date']}\n\n"
        f"Re: {label}\n\n"
        f"Hello,\n\n{ask}\n\n"
        f"Billed: {money(claim['billed'])}   Plan paid: {money(claim['plan_paid'])}   "
        f"Amount I am asked to pay: {money(claim['patient_owes'])}\n\n"
        f"Thank you for your help.\n\n{MEMBER['name']}\n\n"
        f"{SAMPLE_NOTICE}"
    )
    return label, body
