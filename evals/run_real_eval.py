"""Measures the REAL model. Needs MODEL_API_KEY. Uses a small number of calls (about 25), so it costs very little credit.

  export MODEL_API_KEY=...        (in your terminal only)
  python -m evals.run_real_eval

Part A: the model explains invented statements. The checker looks for wrong numbers.
        Every flagged case is printed so YOU can look at it: a flag may be a model mistake or a checker false alarm.
Part B: the model reads the sample statement images. We compare what it read with the known correct values.
"""
import os, random, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "samples"))
from app import checker, metaclient, model, reader
from evals.run_eval import make_claim
import make_samples

N_EXPLAIN = int(os.environ.get("N_EXPLAIN", 20))


def part_a():
    rng, m = random.Random(11), model.MetaModel()
    flagged, errors, shown = 0, 0, 0
    for i in range(N_EXPLAIN):
        claim, charges = make_claim(rng, i)
        for c in charges: c.setdefault("description", "Visit")
        try:
            text = m.explain(claim, charges)
        except metaclient.MetaError as e:
            errors += 1; print("  API problem:", e); continue
        res = checker.check_explanation(claim, charges, text)
        if not res["ok"]:
            flagged += 1
            if shown < 5:
                shown += 1; print(f"\\n  FLAGGED #{i}: {text}\\n    why: {[x['message'] for x in res['mismatches']]}\\n    truth: billed {claim['billed']}, allowed {claim['allowed']}, paid {claim['plan_paid']}, owes {claim['patient_owes']}")
    done = N_EXPLAIN - errors
    print(f"\\nPart A: {done} explanations, checker flagged {flagged}. Read the flagged ones above and decide which are real model mistakes.")


def truth(s):
    billed = round(sum(a for _, _, a in s["items"]), 2)
    owes = 0.0 if s["status"] == "Denied" else round(billed - s["discount"] - s["paid"], 2)
    return {"provider": s["provider"], "billed": billed, "patient_owes": owes, "n": len(s["items"])}


def part_b():
    ok = 0
    for key, s in make_samples.SAMPLES.items():
        img = open(os.path.join(os.path.dirname(__file__), "..", "static", "samples", f"{key}.png"), "rb").read()
        try:
            text = reader.MetaReader().read(img)
        except reader.ReaderError as e:
            print(f"  {key}: API problem: {e}"); continue
        f, t = reader.parse_text(text), truth(s)
        problems = reader.verify_extraction(f)
        match = f["provider"] == t["provider"] and f["billed"] == t["billed"] and f["patient_owes"] == t["patient_owes"] and len(f["charges"]) == t["n"]
        ok += match and not problems
        print(f"  {key}: {'correct' if match else 'WRONG'}; verification: {problems or 'passed'}")
    print(f"\\nPart B: {ok} of {len(make_samples.SAMPLES)} sample images read correctly and verified.")


if __name__ == "__main__":
    if not metaclient.configured():
        sys.exit("Set MODEL_API_KEY first.")
    print("Part A: explanations"); part_a()
    print("\\nPart B: reading images"); part_b()
