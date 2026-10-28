"""Reads a statement photo into structured fields, then verifies the numbers with arithmetic.

Readers, in order:
  1. MetaReader   : the Meta Model API with image input (only if BILLCLEAR_MODEL=meta and MODEL_API_KEY is set).
  2. OCR reader   : Tesseract text recognition. Not AI. Needs `tesseract` installed (brew install tesseract).

Whatever reader is used, the result is checked. If the text cannot be understood, or the amounts do not add up,
BillClear refuses and says why. It never guesses a number.
"""
import base64, os, re, shutil, subprocess, tempfile


class ReaderError(Exception):
    pass


MONEY = r"([\d,]+\.\d{2})"


def _m(s: str) -> float:
    return round(float(s.replace(",", "")), 2)


def ocr_text(image: bytes) -> str:
    if not shutil.which("tesseract"):
        raise ReaderError("The OCR reader (Tesseract) is not installed. On a Mac: brew install tesseract")
    with tempfile.NamedTemporaryFile(suffix=".img", delete=False) as f:
        f.write(image); path = f.name
    try:
        r = subprocess.run(["tesseract", path, "stdout", "--psm", "6"], capture_output=True, text=True, timeout=40)
    except subprocess.TimeoutExpired:
        raise ReaderError("Reading the image took too long.")
    finally:
        os.unlink(path)
    if r.returncode != 0:
        raise ReaderError("The image could not be read. Please use a clear PNG or JPG.")
    return r.stdout


def parse_text(text: str) -> dict:
    """Turn statement text into fields. Missing fields stay None so verification can report them."""
    def field(label):
        m = re.search(rf"^\s*{label}\s*:\s*(.+?)\s*$", text, re.I | re.M)
        return m.group(1) if m else None

    def amount(label):
        m = re.search(rf"^\s*{label}\s*:\s*\$?\s?{MONEY}\s*$", text, re.I | re.M)
        return _m(m.group(1)) if m else None

    charges = []
    for line in text.splitlines():
        m = re.match(rf"^\s*([S5]-\d{{3}}|D-\d{{2}})\s+(.*?)\s+\$?\s?{MONEY}\s*$", line)
        if m:
            code = "S" + m.group(1)[1:] if m.group(1)[0] == "5" else m.group(1)
            charges.append({"code": code, "description": m.group(2).strip(), "amount": _m(m.group(3))})
    net = (field("Network status") or "").lower()
    return {
        "provider": field("Provider"),
        "service_date": (re.search(r"\d{4}-\d{2}-\d{2}", field("Service date") or "") or [None])[0],
        "doc_type": "EOB" if "eob" in (field("Document type") or "").lower() else ("BILL" if field("Document type") else None),
        "status": "denied" if "denied" in (field("Claim status") or "").lower() else ("processed" if field("Claim status") else None),
        "in_network": None if not net else (0 if "out" in net else 1),
        "denial_code": field("Denial code"),
        "denial_reason": field("Denial reason"),
        "charges": charges,
        "billed": amount("Total billed"), "plan_discount": amount("Plan discount"), "allowed": amount("Allowed amount"),
        "plan_paid": amount("Plan paid"), "patient_owes": amount("You owe"),
    }


def verify_extraction(f: dict) -> list[str]:
    """Problems that mean the reading cannot be trusted. Empty list means it passed."""
    p = []
    for key, label in [("provider", "provider"), ("service_date", "service date"), ("doc_type", "document type"),
                       ("status", "claim status"), ("in_network", "network status"), ("billed", "total billed"),
                       ("plan_discount", "plan discount"), ("allowed", "allowed amount"), ("plan_paid", "plan paid"),
                       ("patient_owes", "amount you owe")]:
        if f.get(key) is None:
            p.append(f"Could not find the {label}.")
    if not f.get("charges"):
        p.append("Could not find any line items.")
    if p:
        return p
    total = round(sum(c["amount"] for c in f["charges"]), 2)
    if total != f["billed"]:
        p.append(f"The line items add up to ${total:,.2f}, but the total billed reads ${f['billed']:,.2f}. One of them may be misread.")
    if f["status"] == "processed" and round(f["billed"] - f["plan_discount"] - f["plan_paid"], 2) != f["patient_owes"]:
        p.append("The amounts do not add up: total billed minus plan discount minus plan paid should equal what you owe.")
    return p


class MetaReader:
    name = "Meta Model API (vision)"

    def read(self, image: bytes) -> str:
        from . import metaclient
        try:
            return metaclient.chat([
                {"type": "text", "text": "Copy the text of this FICTIONAL sample statement exactly, one line per line, "
                                         "keeping every label and every dollar amount as printed. Do not add, fix or explain anything."},
                metaclient.image_part(image)], max_tokens=3000)
        except metaclient.MetaError as e:
            raise ReaderError(str(e))


def read_statement(image: bytes) -> tuple[dict, str, list[str]]:
    """Returns (fields, reader_name, problems)."""
    meta_problem = None
    wants_meta = os.environ.get("BILLCLEAR_MODEL", "mock").lower() == "meta"
    if wants_meta:
        try:
            fields = parse_text(MetaReader().read(image))
            return fields, MetaReader.name, verify_extraction(fields)
        except ReaderError as e:
            meta_problem = str(e)  # the API failed: fall back to OCR so the app keeps working
    else:
        meta_problem = "The Meta model is switched off in this terminal window (BILLCLEAR_MODEL is not set to meta)."
    try:
        fields = parse_text(ocr_text(image))
    except ReaderError as e:
        raise ReaderError(f"{meta_problem} The backup OCR reader is not available either: {e}")
    return fields, "OCR (Tesseract, not AI)", verify_extraction(fields)
