import os, tempfile
os.environ["BILLCLEAR_DB"] = os.path.join(tempfile.mkdtemp(), "test.db")

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def setup_function(_):
    client.post("/api/reset")


def test_lists_five_sample_claims():
    r = client.get("/api/claims").json()
    assert r["sample_data"] is True and len(r["claims"]) == 5


def test_flags_match_each_scenario():
    flags = lambda cid: {f["type"] for f in client.get(f"/api/claims/{cid}").json()["flags"]}
    assert flags("CLM-1001") == {"not_a_bill"}
    assert flags("CLM-1002") == set()
    assert flags("CLM-1003") >= {"denied", "not_a_bill"}
    assert flags("CLM-1004") == {"out_of_network"}
    assert flags("CLM-1005") == {"duplicate"}


def test_unknown_claim_404():
    assert client.get("/api/claims/NOPE").status_code == 404


def test_cannot_submit_without_approval():
    a = client.post("/api/appeals/draft", json={"claim_id": "CLM-1005"}).json()
    assert a["status"] == "draft" and "SAMPLE" in a["body"]
    assert client.post(f"/api/appeals/{a['id']}/submit").status_code == 409


def test_approve_then_submit_then_no_resend():
    a = client.post("/api/appeals/draft", json={"claim_id": "CLM-1003"}).json()
    assert client.post(f"/api/appeals/{a['id']}/approve").status_code == 200
    assert client.post(f"/api/appeals/{a['id']}/submit").json()["status"] == "sent"
    assert client.post(f"/api/appeals/{a['id']}/submit").status_code == 409


def test_editing_cancels_approval():
    a = client.post("/api/appeals/draft", json={"claim_id": "CLM-1004"}).json()
    client.post(f"/api/appeals/{a['id']}/approve")
    client.put(f"/api/appeals/{a['id']}", json={"body": "changed"})
    assert client.post(f"/api/appeals/{a['id']}/submit").status_code == 409


def test_code_explanation():
    assert "Facility" in client.get("/api/codes/S-310").json()["title"]


def test_summary_and_paid():
    s = client.get("/api/summary").json()
    assert s["total_due"] == 430 + 975 + 18 and s["bills_due"] == 3
    assert client.post("/api/claims/CLM-1002/paid", json={"paid": True}).status_code == 200
    assert client.get("/api/summary").json()["total_due"] == 975 + 18
    assert client.post("/api/claims/CLM-1001/paid", json={"paid": True}).status_code == 409


def test_ai_explain_checks_numbers():
    ok = client.get("/api/claims/CLM-1004/ai-explain").json()
    assert ok["check"]["ok"] is True and "$975.00" in ok["explanation"]
    bad = client.get("/api/claims/CLM-1004/ai-explain?corrupt=wrong_owes").json()
    assert bad["check"]["ok"] is False


def test_checker_catches_each_error_type_and_no_false_alarm():
    from app import checker, model
    with __import__("app.db", fromlist=["conn"]).conn() as c:
        claim = dict(c.execute("SELECT * FROM claims WHERE id='CLM-1002'").fetchone())
        ch = [dict(r) for r in c.execute("SELECT * FROM charges WHERE claim_id='CLM-1002'")]
    m = model.MockModel()
    assert checker.check_explanation(claim, ch, m.explain(claim, ch))["ok"]
    for k in ["wrong_owes", "digit_swap", "wrong_paid", "invented", "swap_valid", "no_number"]:
        assert not checker.check_explanation(claim, ch, m.explain(claim, ch, corrupt=k))["ok"], k


# ---- Reader and upload ----
import shutil, pytest
from app import reader

needs_ocr = pytest.mark.skipif(shutil.which("tesseract") is None, reason="Tesseract is not installed")

GOOD = """Provider: Test Clinic
Service date: 2026-10-01
Document type: Bill
Network status: In network
Claim status: Processed
S-100 Office visit, established patient $200.00
Total billed: $200.00
Plan discount: $70.00
Allowed amount: $130.00
Plan paid: $104.00
You owe: $26.00
"""


def test_parse_and_verify_good_text():
    f = reader.parse_text(GOOD)
    assert f["billed"] == 200.0 and f["charges"][0]["code"] == "S-100"
    assert reader.verify_extraction(f) == []


def test_verify_catches_a_misread_number():
    f = reader.parse_text(GOOD.replace("You owe: $26.00", "You owe: $28.00"))
    assert reader.verify_extraction(f)           # amounts no longer add up
    f = reader.parse_text(GOOD.replace("Total billed: $200.00", "Total billed: $280.00"))
    assert reader.verify_extraction(f)           # line items no longer match the total


def test_verify_reports_missing_fields():
    assert reader.verify_extraction(reader.parse_text("hello world"))


def test_ocr_confusion_s_and_5_is_fixed():
    f = reader.parse_text(GOOD.replace("S-100", "5-100"))
    assert f["charges"][0]["code"] == "S-100"


@needs_ocr
def test_upload_each_sample_end_to_end():
    expect = {"duplicate": "duplicate", "out_of_network": "out_of_network", "denied": "denied", "clear": None}
    for name, flag in expect.items():
        r = client.post(f"/api/upload-sample/{name}").json()
        assert r["ok"], (name, r["problems"])
        d = client.get(f"/api/claims/{r['claim_id']}").json()
        types = {f["type"] for f in d["flags"]}
        assert (flag in types) if flag else (types == set()), (name, types)
        assert client.get(f"/api/claims/{r['claim_id']}/ai-explain").json()["check"]["ok"]


@needs_ocr
def test_blurry_photo_is_refused_not_guessed():
    before = len(client.get("/api/claims").json()["claims"])
    r = client.post("/api/upload-sample/blurry").json()
    assert r["ok"] is False and r["problems"]
    assert len(client.get("/api/claims").json()["claims"]) == before


def test_upload_rejects_non_images():
    assert client.post("/api/upload", content=b"hi", headers={"content-type": "text/plain"}).status_code == 415
    assert client.post("/api/upload-sample/../../etc/passwd").status_code in (404, 405)


# ---- Meta Model API client (fake HTTP, no key needed) ----
import json
from app import metaclient


class _Resp:
    def __init__(self, code, body): self.status_code, self._b, self.text = code, body, json.dumps(body)
    def json(self): return self._b


def test_meta_client_sends_the_documented_request(monkeypatch):
    seen = {}
    def fake_post(url, json=None, timeout=None, headers=None):
        seen.update(url=url, body=json, headers=headers)
        return _Resp(200, {"choices": [{"message": {"content": "You owe $975.00."}}]})
    monkeypatch.setenv("MODEL_API_KEY", "test-key")
    monkeypatch.setattr(metaclient.httpx, "post", fake_post)
    out = metaclient.chat([{"type": "text", "text": "hi"}, metaclient.image_part(b"\x89PNG\r\n\x1a\nxx")])
    assert out == "You owe $975.00."
    assert seen["url"] == "https://api.meta.ai/v1/chat/completions"
    assert seen["headers"]["Authorization"] == "Bearer test-key"
    assert seen["body"]["model"] == "muse-spark-1.3"
    part = seen["body"]["messages"][0]["content"][1]
    assert part["type"] == "image_url" and part["image_url"]["url"].startswith("data:image/png;base64,")


def test_meta_errors_are_readable_and_never_leak_the_key(monkeypatch):
    monkeypatch.setenv("MODEL_API_KEY", "secret-123")
    monkeypatch.setattr(metaclient.httpx, "post", lambda *a, **k: _Resp(401, {}))
    with pytest.raises(metaclient.MetaError) as e:
        metaclient.chat("hi")
    assert "secret-123" not in str(e.value)


def test_app_falls_back_when_the_model_fails(monkeypatch):
    monkeypatch.setenv("BILLCLEAR_MODEL", "meta"); monkeypatch.setenv("MODEL_API_KEY", "k")
    monkeypatch.setattr(metaclient.httpx, "post", lambda *a, **k: _Resp(429, {}))
    r = client.get("/api/claims/CLM-1004/ai-explain").json()
    assert "could not be reached" in r["explanation"] and r["check"]["ok"]


def test_a_wrong_number_from_the_real_model_is_caught(monkeypatch):
    monkeypatch.setenv("BILLCLEAR_MODEL", "meta"); monkeypatch.setenv("MODEL_API_KEY", "k")
    bad = "Evergreen billed $1,200.00. The plan allowed $450.00 and paid $225.00. You owe $795.00."
    monkeypatch.setattr(metaclient.httpx, "post", lambda *a, **k: _Resp(200, {"choices": [{"message": {"content": bad}}]}))
    r = client.get("/api/claims/CLM-1004/ai-explain").json()
    assert r["model"] == "Meta Model API" and r["check"]["ok"] is False


def test_error_names_both_readers_when_nothing_works(monkeypatch):
    monkeypatch.delenv("BILLCLEAR_MODEL", raising=False)
    monkeypatch.setattr(reader.shutil, "which", lambda _: None)
    r = client.post("/api/upload", content=b"\x89PNG\r\n\x1a\nxx", headers={"content-type": "image/png"}).json()
    assert r["ok"] is False and "switched off" in r["problems"][0] and "not available" in r["problems"][0]


def test_per_item_amount_is_not_mistaken_for_the_total():
    from app import checker
    claim = {"billed": 220.0, "plan_discount": 132.0, "allowed": 88.0, "plan_paid": 61.6, "patient_owes": 26.4, "owe_breakdown": "", "denial_reason": ""}
    ch = [{"amount": 110.0}, {"amount": 110.0}]
    good = "Two Visit line items billed at $110.0 each, for a total billed of $220. The plan paid $61.6. You owe $26.4."
    assert checker.check_explanation(claim, ch, good)["ok"]
    bad = "Two Visit line items billed at $110.0 each, for a total billed of $200. You owe $26.4."
    assert not checker.check_explanation(claim, ch, bad)["ok"]
