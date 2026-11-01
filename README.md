# BillClear (demo)

A medical-statement helper that works for people and for browser AI agents through WebMCP.

**Sample data only.** The insurer, clinics, patient, service codes and amounts are all invented.
Do not enter real medical information. This is a portfolio prototype, not a service for real records.

## What it does
- Explains a statement in plain words: what was billed, what the plan allowed, and why you owe what you owe.
- Flags: not a bill (EOB), possible duplicate charge, out-of-network, denied claim.
- Suggests questions to ask (not advice).
- Dashboard with total still due, items needing a look, and due dates. Mark bills as paid. Filter by All, Needs attention, Paid.
- Drafts an appeal letter. **You must read and approve it yourself** before the demo "sends" it. Nothing is ever transmitted. You can download the letter and see your appeal history.

## The full flow
1. **Photo in.** Upload a photo of a SAMPLE statement, or pick a bundled sample.
2. **Read.** A reader turns the image into fields. Today that is OCR (Tesseract, not AI). The hackathon model plugs in as a better reader (`app/reader.py`, untested).
3. **Verify.** The line items must add up to the total, and billed minus discount minus plan paid must equal what you owe. If not, BillClear refuses and says why. It never guesses.
4. **Explain and flag.** Plain-words explanation, plus flags: duplicate charge, out of network, denied, not a bill.
5. **Check the AI.** Every number in the explanation is checked against the statement.
6. **Draft and approve.** An agent (WebMCP) or you drafts an appeal. Nothing is "sent" until you approve it.

Needs Tesseract for uploads: `brew install tesseract` (Mac). Everything except uploads works without it.
Sample images are made by `python samples/make_samples.py`. Every name and amount is invented.

## Run it
```
python -m venv .venv && source .venv/bin/activate
pip install fastapi uvicorn
uvicorn app.main:app --reload
```
Open http://127.0.0.1:8000

## Test
```
pip install pytest httpx
python -m pytest
```

## Meta Model API
BillClear calls the Meta Model API (OpenAI-compatible Chat Completions at `https://api.meta.ai/v1`, default model `muse-spark-1.3`).
It does two jobs: **read** a statement image, and **explain** it in plain words. Plain code then verifies both.

Set it up in your own terminal. Never put the key in a file, in code, or on GitHub:
```
export MODEL_API_KEY="your-key"
export BILLCLEAR_MODEL=meta
export META_REASONING=low         # avoids empty replies from the model spending its budget on reasoning
python scripts/check_meta.py          # tests the connection step by step
python -m uvicorn app.main:app --port 8010
```
Without a key, or if the API fails, BillClear falls back to the mock explainer and OCR, so it never breaks.

## Checks and measurements
- **Number checker** (`app/checker.py`): pulls every dollar amount out of the explanation and compares it with the statement.
- **Reading verification** (`app/reader.py`): line items must add up to the total, and billed minus discount minus plan paid must equal what you owe. If not, BillClear refuses instead of guessing.
- `python -m evals.run_eval`: tests the checker on 400 invented statements with errors **we inject**. This tests the checker, not a model.
- `python -m evals.run_real_eval`: measures the **real model** (about 25 calls). Read the flagged cases yourself before quoting any number. One run on invented sample data: 20 explanations with 0 flagged by the checker, and 4 of 4 sample images read and verified. This is a small test, not a claim about real bills.

## Try the WebMCP tools
WebMCP is experimental. In a recent Chrome, turn on `chrome://flags/#enable-webmcp-testing`, restart,
and open the page. The header line shows how many tools registered. To drive them with an agent,
use Chrome's Model Context Tool Inspector or the Example Agentic Chrome Extension (needs your own model API key).
Without WebMCP the page works normally.

Tools: `get_claims`, `load_sample_statement`, `get_claim_detail`, `explain_charge`, `draft_appeal`, `submit_appeal`.
`submit_appeal` is marked `consequentialHint` and refuses unless the person clicked Approve on the page.

## Design choices
- Rules, not an LLM, produce flags and letters, so results are predictable and need no API key.
- The agent can only do what a person can do in the UI; approval lives in the page, not in a tool.
- Editing a letter cancels its approval.

## Disclosure
BillClear started before the hackathon as a sample-data demo. During the hackathon I added the Meta Model API reader and explanations, the number checker with measurements, and the WebMCP agent tools. Much of the code was written with AI coding tools. I designed the product, the safety rules and the decisions, and I reviewed and tested the result.
