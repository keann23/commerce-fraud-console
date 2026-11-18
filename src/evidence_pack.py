"""One-click PDF evidence pack for representing a friendly fraud dispute."""
from datetime import datetime

from fpdf import FPDF


def _row(pdf: FPDF, label: str, value: str):
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(60, 7, label)
    pdf.set_font("Helvetica", "", 10)
    pdf.multi_cell(0, 7, value, new_x="LMARGIN", new_y="NEXT")


def _table(pdf: FPDF, headers: list[str], rows: list[list], widths: list[int]):
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_fill_color(240, 240, 240)
    for h, w in zip(headers, widths):
        pdf.cell(w, 7, h, border=1, fill=True)
    pdf.ln()
    pdf.set_font("Helvetica", "", 9)
    for row in rows:
        for v, w in zip(row, widths):
            pdf.cell(w, 6, str(v)[:40], border=1)
        pdf.ln()


def build_evidence_pdf(case: dict, prior: list[dict], usage: list[dict], logins: list[dict]) -> bytes:
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, "Dispute representment: evidence pack", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "I", 9)
    pdf.cell(0, 6, f"Generated {datetime.now():%Y-%m-%d %H:%M}. SYNTHETIC DATA: portfolio demo, not a real case.",
             new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    _row(pdf, "Dispute", f"{case['dispute_id']} - reason: unauthorized - filed {case['filed_ts']:%Y-%m-%d}")
    _row(pdf, "Disputed charge", f"{case['txn_id']} - ${case['amount']:,.2f} on {case['txn_ts']:%Y-%m-%d %H:%M}")
    _row(pdf, "Account", f"{case['user_id']} - customer for {case['tenure_days_at_purchase']} days at purchase")
    _row(pdf, "Purchase device / IP", f"{case['device_id']} / {case['ip']}")
    _row(pdf, "Friendly fraud score", f"{case['risk_score']} / 100")
    pdf.ln(2)

    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "Summary of evidence", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    points = [
        f"The disputed charge was made from device {case['device_id']}, used for "
        f"{case['prior_same_device']} earlier undisputed purchases on this account.",
        f"It came from IP {case['ip']}, used for {case['prior_same_ip']} earlier undisputed purchases.",
        f"The account had {case['prior_approved_charges']} approved charges before this one and no earlier disputes.",
        f"After the purchase the customer used the product for {case['minutes_after']:,} minutes across "
        f"{case['active_days_after']} days, before filing the dispute.",
        f"The same device logged into the account {case['logins_same_device_after']} times after the purchase.",
    ]
    for p in points:
        pdf.multi_cell(0, 6, f"- {p}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "Earlier approved purchases", new_x="LMARGIN", new_y="NEXT")
    _table(pdf, ["Date", "Amount", "Device", "IP", "Disputed"],
           [[f"{r['ts']:%Y-%m-%d}", f"${r['amount']:,.2f}", r["device_id"], r["ip"], r["disputed"]] for r in prior],
           [30, 25, 35, 45, 25])
    pdf.ln(3)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "Product usage after the purchase", new_x="LMARGIN", new_y="NEXT")
    _table(pdf, ["Date", "App", "Sessions", "Minutes"],
           [[str(r["date"]), r["app"], r["sessions"], r["minutes"]] for r in usage], [35, 45, 30, 30])
    pdf.ln(3)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "Logins after the purchase", new_x="LMARGIN", new_y="NEXT")
    _table(pdf, ["Time", "Device", "IP", "Country"],
           [[f"{r['ts']:%Y-%m-%d %H:%M}", r["device_id"], r["ip"], r["country"] or ""] for r in logins],
           [40, 35, 45, 25])
    return bytes(pdf.output())
