"""SQLite database and synthetic sample data for BillClear.

Everything here is made up: the insurer, the clinics, the patient, the codes and
the amounts. Nothing is real medical information and no real insurer is imitated.
The service codes (S-100 etc.) are invented for this demo; real billing codes
differ, and some real code sets are licensed, so they are not copied here.
"""
import os
import sqlite3
from contextlib import contextmanager

DB_PATH = os.environ.get("BILLCLEAR_DB", os.path.join(os.path.dirname(__file__), "..", "billclear.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS claims (
    id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    service_date TEXT NOT NULL,
    doc_type TEXT NOT NULL,            -- 'EOB' (not a bill) or 'BILL'
    status TEXT NOT NULL,              -- processed | denied
    billed REAL NOT NULL,
    plan_discount REAL NOT NULL DEFAULT 0,
    allowed REAL NOT NULL,
    plan_paid REAL NOT NULL,
    patient_owes REAL NOT NULL,
    in_network INTEGER NOT NULL DEFAULT 1,
    denial_code TEXT,
    denial_reason TEXT,
    owe_breakdown TEXT,                -- plain-language note on how patient_owes is made up
    due_date TEXT,
    paid INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS charges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_id TEXT NOT NULL REFERENCES claims(id),
    code TEXT NOT NULL,
    description TEXT NOT NULL,
    service_date TEXT NOT NULL,
    amount REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS code_explanations (
    code TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    plain TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS appeals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_id TEXT NOT NULL REFERENCES claims(id),
    reason TEXT NOT NULL,
    body TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',   -- draft | approved | sent
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    approved_at TEXT,
    sent_at TEXT
);
"""

CLAIMS = [
    # id, provider, date, doc_type, status, billed, discount, allowed, plan_paid, owes, in_network, denial_code, denial_reason, breakdown
    ("CLM-1001", "Riverside Family Clinic", "2026-08-12", "EOB", "processed",
     220.00, 80.00, 140.00, 112.00, 28.00, 1, None, None,
     "Your plan pays 80% of the allowed amount ($112.00). You pay the other 20% ($28.00)."),
    ("CLM-1002", "St. Marlow Hospital", "2026-08-20", "BILL", "processed",
     1850.00, 900.00, 950.00, 520.00, 430.00, 1, None, None,
     "Your plan first applied $300.00 to your deductible. Of the remaining $650.00 it paid 80% ($520.00), "
     "and you pay 20% ($130.00). $300.00 + $130.00 = $430.00."),
    ("CLM-1003", "Lakeview Diagnostics Lab", "2026-09-02", "EOB", "denied",
     340.00, 0.00, 0.00, 0.00, 0.00, 1, "D-14", "Prior approval was not on file for this service.",
     "Nothing is owed on this statement right now. If the denial stands, the lab may bill you for $340.00."),
    ("CLM-1004", "Evergreen Imaging Center", "2026-09-10", "BILL", "processed",
     1200.00, 0.00, 450.00, 225.00, 975.00, 0, None, None,
     "This center is out of network. Your plan only counts $450.00 as the allowed amount and pays 50% ($225.00). "
     "You owe the other $225.00 plus the $750.00 above the allowed amount: $975.00."),
    ("CLM-1005", "Riverside Family Clinic", "2026-09-18", "BILL", "processed",
     135.00, 45.00, 90.00, 72.00, 18.00, 1, None, None,
     "Your plan paid 80% of the allowed amount. The same lab draw appears twice, so part of this may be a billing mistake."),
]

CHARGES = [
    ("CLM-1001", "S-100", "Office visit, established patient", "2026-08-12", 220.00),
    ("CLM-1002", "S-310", "Facility fee, outpatient procedure", "2026-08-20", 1400.00),
    ("CLM-1002", "S-311", "Surgical supplies", "2026-08-20", 250.00),
    ("CLM-1002", "S-312", "Anesthesia services", "2026-08-20", 200.00),
    ("CLM-1003", "S-210", "Comprehensive blood panel", "2026-09-02", 340.00),
    ("CLM-1004", "S-410", "MRI scan, one body area", "2026-09-10", 1200.00),
    ("CLM-1005", "S-120", "Lab blood draw", "2026-09-18", 45.00),
    ("CLM-1005", "S-120", "Lab blood draw", "2026-09-18", 45.00),
    ("CLM-1005", "S-100", "Office visit, established patient", "2026-09-18", 45.00),
]

# Invented due dates (sample data). Only statements that are real bills have one.
DUE_DATES = {"CLM-1002": "2026-11-05", "CLM-1004": "2026-10-28", "CLM-1005": "2026-10-30"}

CODE_EXPLANATIONS = [
    ("S-100", "Office visit", "A regular visit with a doctor or nurse practitioner. Most plans charge a copay or a share of the cost."),
    ("S-120", "Blood draw", "Taking a small blood sample so a lab can test it. The test itself is billed separately."),
    ("S-210", "Blood panel", "A group of blood tests run together, such as cholesterol and blood sugar."),
    ("S-310", "Facility fee", "The charge for using the hospital room, equipment and staff for a procedure. It is separate from the doctor's fee."),
    ("S-311", "Surgical supplies", "Items used during the procedure, like sterile tools and dressings."),
    ("S-312", "Anesthesia", "The medicine and monitoring that keep you comfortable or asleep during a procedure. It is billed by the anesthesia team."),
    ("S-410", "MRI scan", "An imaging scan that takes detailed pictures inside the body, without radiation."),
    ("D-14", "Denial: no prior approval", "Your plan wanted to approve this service in advance and did not have an approval on file. Sometimes the provider can send the approval later, so it is worth asking."),
]


@contextmanager
def conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init_db(reset: bool = False) -> None:
    with conn() as c:
        if reset:
            c.executescript("DROP TABLE IF EXISTS appeals; DROP TABLE IF EXISTS code_explanations; "
                            "DROP TABLE IF EXISTS charges; DROP TABLE IF EXISTS claims;")
        c.executescript(SCHEMA)
        # Small migration so an older billclear.db keeps working.
        have = {r["name"] for r in c.execute("PRAGMA table_info(claims)")}
        if "due_date" not in have:
            c.execute("ALTER TABLE claims ADD COLUMN due_date TEXT")
        if "paid" not in have:
            c.execute("ALTER TABLE claims ADD COLUMN paid INTEGER NOT NULL DEFAULT 0")
        if c.execute("SELECT COUNT(*) FROM claims").fetchone()[0] == 0:
            c.executemany("INSERT INTO claims (id, provider, service_date, doc_type, status, billed, plan_discount, "
                          "allowed, plan_paid, patient_owes, in_network, denial_code, denial_reason, owe_breakdown) "
                          "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", CLAIMS)
            for cid, due in DUE_DATES.items():
                c.execute("UPDATE claims SET due_date = ? WHERE id = ?", (due, cid))
            c.executemany("INSERT INTO charges (claim_id, code, description, service_date, amount) VALUES (?,?,?,?,?)", CHARGES)
            c.executemany("INSERT INTO code_explanations VALUES (?,?,?)", CODE_EXPLANATIONS)
        else:
            for cid, due in DUE_DATES.items():
                c.execute("UPDATE claims SET due_date = ? WHERE id = ? AND due_date IS NULL", (due, cid))
