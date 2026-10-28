"""Measures how well the checker catches wrong numbers.

Builds many invented statements with known-correct numbers, produces explanations with the
mock model (half of them with one injected error), and counts what the checker catches.
IMPORTANT: until a real model is plugged in, the errors are ones WE inject, so this tests the
checker, not the model. Run it again with BILLCLEAR_MODEL=meta later to measure real model mistakes.
Run:  python -m evals.run_eval
"""
import random, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import checker, model

KINDS = ["wrong_owes", "digit_swap", "wrong_paid", "invented", "swap_valid", "no_number"]


def make_claim(rng, i):
    billed = round(rng.choice([140, 220, 340, 560, 900, 1200, 1850, 2400]) + rng.choice([0, 5, 12.5]), 2)
    allowed = round(billed * rng.choice([0.4, 0.5, 0.65, 0.8]), 2)
    paid = round(allowed * rng.choice([0.5, 0.7, 0.8]), 2)
    owes = round(allowed - paid, 2)
    n = rng.choice([1, 2, 3]); parts = [round(billed / n, 2)] * n; parts[-1] = round(billed - sum(parts[:-1]), 2)
    claim = dict(id=f"X{i}", provider="Test Clinic", billed=billed, plan_discount=round(billed - allowed, 2), allowed=allowed,
                 plan_paid=paid, patient_owes=owes, owe_breakdown="Your plan paid part and you pay the rest.", denial_reason=None)
    charges = [dict(code="S-100", amount=a) for a in parts]
    return claim, charges


def main(n=400, seed=7):
    rng, m = random.Random(seed), model.MockModel()
    tp = fn = fp = tn = 0
    missed = []
    by = {k: [0, 0] for k in KINDS}
    for i in range(n):
        claim, charges = make_claim(rng, i)
        corrupt = rng.choice(KINDS) if rng.random() < 0.5 else None
        text = m.explain(claim, charges, corrupt=corrupt, rng=rng)
        flagged = not checker.check_explanation(claim, charges, text)["ok"]
        changed = corrupt is not None and text != m.explain(claim, charges, rng=rng)
        if changed:
            by[corrupt][1] += 1
            by[corrupt][0] += flagged
        if changed and flagged: tp += 1
        elif changed: fn += 1; missed.append((corrupt, text))
        elif flagged: fp += 1
        else: tn += 1
    errs = tp + fn
    print(f"Statements tested: {n}  (seed {seed})")
    print(f"Explanations with an injected error: {errs}")
    print(f"  caught by checker: {tp} ({tp / errs:.0%})   missed: {fn}")
    print(f"Correct explanations: {fp + tn}   wrongly flagged: {fp}")
    print("By error type (caught / total):")
    for k, (c, t) in by.items(): print(f"  {k:12s} {c}/{t}")
    for k, t in missed[:2]: print("  missed example:", k, "|", t[:110])


if __name__ == "__main__":
    main()
