"""Creates the SAMPLE statement images in static/samples. Every name, amount and code is invented."""
import os
from PIL import Image, ImageDraw, ImageFilter, ImageFont

OUT = os.path.join(os.path.dirname(__file__), "..", "static", "samples")
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"

SAMPLES = {
    "duplicate": dict(provider="Maple Street Clinic", date="2026-10-02", doc="Bill", net="In network", status="Processed",
        items=[("S-100", "Office visit, established patient", 120.00), ("S-120", "Lab blood draw", 45.00), ("S-120", "Lab blood draw", 45.00)],
        discount=70.00, paid=84.00),
    "out_of_network": dict(provider="Harbor Imaging Center", date="2026-10-05", doc="Bill", net="Out of network", status="Processed",
        items=[("S-410", "MRI scan, one body area", 1500.00)], discount=0.00, allowed=500.00, paid=250.00),
    "denied": dict(provider="Cedar Diagnostics Lab", date="2026-10-08", doc="EOB", net="In network", status="Denied",
        items=[("S-210", "Comprehensive blood panel", 280.00)], discount=0.00, paid=0.00,
        denial=("D-14", "Prior approval was not on file for this service.")),
    "clear": dict(provider="Oak Pediatrics", date="2026-10-12", doc="Bill", net="In network", status="Processed",
        items=[("S-100", "Office visit, established patient", 200.00)], discount=70.00, paid=104.00),
}


def render(key, s, blur=False):
    billed = round(sum(a for _, _, a in s["items"]), 2)
    allowed = s.get("allowed", round(billed - s["discount"], 2))
    if s["status"] == "Denied":
        allowed, owes = 0.0, 0.0
    else:
        owes = round(billed - s["discount"] - s["paid"], 2)
    lines = [("NORTHFIELD HEALTH PLAN (SAMPLE)", True), ("SAMPLE STATEMENT - NOT A REAL BILL", True), ("", False),
             (f"Provider: {s['provider']}", False), (f"Service date: {s['date']}", False), (f"Document type: {s['doc']}", False),
             (f"Network status: {s['net']}", False), (f"Claim status: {s['status']}", False)]
    if "denial" in s:
        lines += [(f"Denial code: {s['denial'][0]}", False), (f"Denial reason: {s['denial'][1]}", False)]
    lines += [("", False), ("CHARGES", True)]
    lines += [(f"{c} {d} ${a:,.2f}", False) for c, d, a in s["items"]]
    lines += [("", False), (f"Total billed: ${billed:,.2f}", False), (f"Plan discount: ${s['discount']:,.2f}", False),
              (f"Allowed amount: ${allowed:,.2f}", False), (f"Plan paid: ${s['paid']:,.2f}", False), (f"You owe: ${owes:,.2f}", True)]
    f, fb = ImageFont.truetype(FONT, 30), ImageFont.truetype(BOLD, 30)
    img = Image.new("RGB", (1500, 60 + 46 * len(lines) + 40), "white")
    d = ImageDraw.Draw(img)
    for i, (t, b) in enumerate(lines):
        d.text((50, 40 + 46 * i), t, fill="black", font=fb if b else f)
    if blur:
        img = img.filter(ImageFilter.GaussianBlur(3.2)).resize((520, int(img.height * 520 / 1500))).resize(img.size)
    img.save(os.path.join(OUT, f"{key}.png"))


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    for k, s in SAMPLES.items():
        render(k, s)
    render("blurry", SAMPLES["duplicate"], blur=True)   # a poor photo, to show the app refusing to guess
    print("done")
