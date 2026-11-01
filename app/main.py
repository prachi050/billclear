"""BillClear: a demo medical-bill helper with a WebMCP-ready interface.

SAMPLE DATA ONLY. Do not enter real medical information.
Run:  uvicorn app.main:app --reload
"""
import os
from datetime import date
from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import checker, db, logic, model, reader

STATIC_DIR = os.path.join(os.path.dirname(__file__), "..", "static")

app = FastAPI(title="BillClear (demo)", description="Synthetic sample data only.")


@app.on_event("startup")
def _startup() -> None:
    db.init_db()


def _claim_or_404(c, claim_id: str) -> dict:
    row = c.execute("SELECT * FROM claims WHERE id = ?", (claim_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Claim not found")
    return dict(row)


def _charges(c, claim_id: str) -> list[dict]:
    rows = c.execute("SELECT * FROM charges WHERE claim_id = ? ORDER BY id", (claim_id,)).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/claims")
def list_claims():
    with db.conn() as c:
        out = []
        for row in c.execute("SELECT * FROM claims ORDER BY service_date DESC").fetchall():
            claim = dict(row)
            flags = logic.compute_flags(claim, _charges(c, claim["id"]))
            out.append({
                "id": claim["id"], "provider": claim["provider"], "service_date": claim["service_date"],
                "doc_type": claim["doc_type"], "status": claim["status"],
                "billed": claim["billed"], "patient_owes": claim["patient_owes"],
                "due_date": claim["due_date"], "paid": bool(claim["paid"]),
                "flag_types": [f["type"] for f in flags],
            })
        return {"sample_data": True, "claims": out}


@app.get("/api/summary")
def summary():
    """Totals for the dashboard. Only unpaid bills count as money still due."""
    today = date.today().isoformat()
    with db.conn() as c:
        rows = [dict(r) for r in c.execute("SELECT * FROM claims").fetchall()]
        attention = 0
        for r in rows:
            fl = logic.compute_flags(r, _charges(c, r["id"]))
            if any(f["severity"] == "action" for f in fl) and not r["paid"]:
                attention += 1
        due = [r for r in rows if r["doc_type"] == "BILL" and not r["paid"]]
        return {
            "sample_data": True,
            "total_due": round(sum(r["patient_owes"] for r in due), 2),
            "bills_due": len(due),
            "overdue": sum(1 for r in due if r["due_date"] and r["due_date"] < today),
            "needs_attention": attention,
            "paid_total": round(sum(r["patient_owes"] for r in rows if r["paid"]), 2),
            "next_due": min((r["due_date"] for r in due if r["due_date"]), default=None),
        }


class PaidIn(BaseModel):
    paid: bool


@app.post("/api/claims/{claim_id}/paid")
def mark_paid(claim_id: str, body: PaidIn):
    with db.conn() as c:
        claim = _claim_or_404(c, claim_id)
        if claim["doc_type"] != "BILL":
            raise HTTPException(409, "This is a statement, not a bill, so there is nothing to mark as paid")
        c.execute("UPDATE claims SET paid = ? WHERE id = ?", (int(body.paid), claim_id))
        return {"id": claim_id, "paid": body.paid}


@app.get("/api/claims/{claim_id}")
def get_claim(claim_id: str):
    with db.conn() as c:
        claim = _claim_or_404(c, claim_id)
        charges = _charges(c, claim_id)
        flags = logic.compute_flags(claim, charges)
        return {
            "sample_data": True,
            "claim": claim,
            "charges": charges,
            "flags": flags,
            "owed": logic.summarize_owed(claim),
            "next_steps": logic.next_steps(claim, flags),
        }


@app.get("/api/claims/{claim_id}/ai-explain")
def ai_explain(claim_id: str, corrupt: str | None = None):
    """Explain a statement with the model, then verify every number. `corrupt` is for demos and tests (mock only)."""
    with db.conn() as c:
        claim = _claim_or_404(c, claim_id)
        charges = _charges(c, claim_id)
    m = model.MockModel() if corrupt else model.get_model()
    try:
        text = m.explain(claim, charges, corrupt=corrupt)
    except Exception as e:  # model unavailable: fall back so the page never breaks
        m = model.MockModel()
        text = m.explain(claim, charges)
        text = "(The AI model could not be reached, so this is the basic explanation.) " + text
    label = "Demo: a deliberately wrong sentence, not from Meta" if corrupt else m.name
    return {"model": label, "explanation": text, "check": checker.check_explanation(claim, charges, text)}


SAMPLES = {"duplicate", "out_of_network", "denied", "clear", "blurry"}


def _ingest(image: bytes) -> dict:
    """Photo in, claim out. Refuses (and says why) when the reading cannot be trusted."""
    try:
        f, reader_name, problems = reader.read_statement(image)
    except reader.ReaderError as e:
        return {"ok": False, "reader": None, "problems": [str(e)], "found": {}}
    if problems:
        return {"ok": False, "reader": reader_name, "problems": problems, "found": f}
    with db.conn() as c:
        n = c.execute("SELECT COUNT(*) FROM claims WHERE id LIKE 'UP-%'").fetchone()[0] + 1
        cid = f"UP-{n:04d}"
        if f["status"] == "denied":
            why = (f"Nothing is owed on this statement right now. If the denial stands, the provider may bill you for ${f['billed']:,.2f}.")
        else:
            why = (f"The plan paid ${f['plan_paid']:,.2f}. After the ${f['plan_discount']:,.2f} plan discount, "
                   f"the statement shows ${f['patient_owes']:,.2f} left for you to pay.")
        c.execute("INSERT INTO claims (id, provider, service_date, doc_type, status, billed, plan_discount, allowed, plan_paid, "
                  "patient_owes, in_network, denial_code, denial_reason, owe_breakdown) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (cid, f["provider"], f["service_date"], f["doc_type"], f["status"], f["billed"], f["plan_discount"], f["allowed"],
                   f["plan_paid"], f["patient_owes"], f["in_network"], f["denial_code"], f["denial_reason"], why))
        for ch in f["charges"]:
            c.execute("INSERT INTO charges (claim_id, code, description, service_date, amount) VALUES (?,?,?,?,?)",
                      (cid, ch["code"], ch["description"], f["service_date"], ch["amount"]))
        if f["doc_type"] == "BILL":
            from datetime import date, timedelta
            c.execute("UPDATE claims SET due_date = ? WHERE id = ?", ((date.today() + timedelta(days=21)).isoformat(), cid))
    return {"ok": True, "claim_id": cid, "reader": reader_name, "problems": [], "found": f}


@app.post("/api/upload")
async def upload(request: Request):
    """Body is the raw image. Sample data only: the page tells people not to upload real bills."""
    data = await request.body()
    if not data or len(data) > 6_000_000:
        raise HTTPException(413, "Please upload an image under 6 MB.")
    if not (request.headers.get("content-type", "").startswith("image/")):
        raise HTTPException(415, "Please upload a PNG or JPG image.")
    return await run_in_threadpool(_ingest, data)


@app.post("/api/upload-sample/{name}")
async def upload_sample(name: str):
    if name not in SAMPLES:
        raise HTTPException(404, "Unknown sample")
    with open(os.path.join(STATIC_DIR, "samples", f"{name}.png"), "rb") as fh:
        return await run_in_threadpool(_ingest, fh.read())


@app.get("/api/charges/{charge_id}/explain")
def explain_charge(charge_id: int):
    with db.conn() as c:
        ch = c.execute("SELECT * FROM charges WHERE id = ?", (charge_id,)).fetchone()
        if not ch:
            raise HTTPException(404, "Charge not found")
        ex = c.execute("SELECT * FROM code_explanations WHERE code = ?", (ch["code"],)).fetchone()
        return {
            "charge": dict(ch),
            "title": ex["title"] if ex else ch["description"],
            "plain": ex["plain"] if ex else "No plain-language note is available for this code yet.",
        }


@app.get("/api/codes/{code}")
def explain_code(code: str):
    with db.conn() as c:
        ex = c.execute("SELECT * FROM code_explanations WHERE code = ?", (code,)).fetchone()
        if not ex:
            raise HTTPException(404, "Code not found")
        return dict(ex)


class DraftIn(BaseModel):
    claim_id: str
    note: str | None = None


@app.post("/api/appeals/draft")
def draft_appeal(body: DraftIn):
    with db.conn() as c:
        claim = _claim_or_404(c, body.claim_id)
        flags = logic.compute_flags(claim, _charges(c, body.claim_id))
        label, text = logic.draft_appeal_text(claim, flags, body.note)
        cur = c.execute("INSERT INTO appeals (claim_id, reason, body) VALUES (?,?,?)",
                        (body.claim_id, label, text))
        return {"id": cur.lastrowid, "claim_id": body.claim_id, "reason": label,
                "body": text, "status": "draft"}


class EditIn(BaseModel):
    body: str


@app.put("/api/appeals/{appeal_id}")
def edit_appeal(appeal_id: int, edit: EditIn):
    with db.conn() as c:
        row = c.execute("SELECT * FROM appeals WHERE id = ?", (appeal_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Appeal not found")
        if row["status"] == "sent":
            raise HTTPException(409, "This appeal was already sent")
        # Editing after approval resets approval: the person must approve the final text.
        c.execute("UPDATE appeals SET body = ?, status = 'draft', approved_at = NULL WHERE id = ?",
                  (edit.body, appeal_id))
        return {"id": appeal_id, "status": "draft"}


@app.post("/api/appeals/{appeal_id}/approve")
def approve_appeal(appeal_id: int):
    with db.conn() as c:
        row = c.execute("SELECT * FROM appeals WHERE id = ?", (appeal_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Appeal not found")
        if row["status"] == "sent":
            raise HTTPException(409, "This appeal was already sent")
        c.execute("UPDATE appeals SET status = 'approved', approved_at = datetime('now') WHERE id = ?", (appeal_id,))
        return {"id": appeal_id, "status": "approved"}


@app.post("/api/appeals/{appeal_id}/submit")
def submit_appeal(appeal_id: int):
    """Marks the appeal as sent in the demo. Refuses unless the person approved it first."""
    with db.conn() as c:
        row = c.execute("SELECT * FROM appeals WHERE id = ?", (appeal_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Appeal not found")
        if row["status"] == "sent":
            raise HTTPException(409, "This appeal was already sent")
        if row["status"] != "approved":
            raise HTTPException(409, "The person must approve this appeal before it can be sent")
        c.execute("UPDATE appeals SET status = 'sent', sent_at = datetime('now') WHERE id = ?", (appeal_id,))
        return {"id": appeal_id, "status": "sent", "note": "Demo only: nothing was transmitted anywhere."}


@app.get("/api/appeals")
def list_appeals():
    with db.conn() as c:
        rows = c.execute("SELECT * FROM appeals ORDER BY id DESC").fetchall()
        return {"appeals": [dict(r) for r in rows]}


@app.post("/api/reset")
def reset_demo():
    db.init_db(reset=True)
    return {"ok": True}


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))
