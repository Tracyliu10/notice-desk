"""Render completed notices onto the original PDF templates."""
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

from pypdf import PdfReader, PdfWriter
from pypdf.generic import FloatObject
from reportlab.pdfgen.canvas import Canvas
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

FORMS = Path(__file__).parent / "forms"
FILES = {
    "rta-rent": "RTA-Notice of Rent Increase.pdf",
    "rta-breach": "RTA-Notice to Remedy Breach.pdf",
    "rta-end": "RTA-Notice-to Terminate Tenancy Agreement.pdf",
    "oa-rent": "OA-Notice of Occupancy Fee Increase.pdf",
    "oa-breach": "OA-Notice to Remedy Breach.pdf",
    "oa-end": "OA-Notice of Termination.pdf",
}
STATEMENT = "RTA-Termination Information Statement.pdf"
ENTITY = {"rta": "Inndeavor Leasing Pty Ltd", "oa": "A&R Co-living Pty Ltd"}
CLAUSES = {
    "3.1": "The tenant agrees to pay rent on time.",
    "16.2": "The tenant agrees not to cause or permit a nuisance.",
    "16.3": "The tenant agrees not to interfere, or cause or permit interference, with the reasonable peace, comfort or privacy of neighbours.",
    "16.4": "The tenant agrees not to intentionally or negligently cause or permit any damage to the residential premises.",
    "17.1": "The tenant agrees to keep the residential premises reasonably clean.",
    "17.2": "The tenant agrees to notify the landlord as soon as practicable of any damage to the residential premises.",
    "18.3": "When the agreement ends and before giving vacant possession, the tenant agrees to leave the residential premises reasonably clean, having regard to its condition at the commencement of the tenancy.",
    "53.1–53.2": "The landlord and the tenant agree that the tenant may keep an animal at the residential premises with the landlord’s consent. An application for consent to keep an animal at the premises must be made jointly by all co-tenants using the Fair Trading approved form and the landlord must respond in writing to the application using that form.",
    "Smoking": "Smoking — include the applicable clause in Other Clause.",
    "Balcony laundry": "Balcony laundry — include the applicable clause in Other Clause.",
    "Other": "Other — include the applicable wording in Other Clause.",
}
RTA_GROUNDS = [
    "Actual sale (s 87D)", "Proposed sale (s 87E)", "Significant renovations (s 87F)",
    "Demolition (s 87G)", "Change of use (s 87L)", "Landlord or family moving in (s 87M)",
    "Breach of tenancy agreement (s 87C)", "Non-payment (s 88)",
    "Employee or caretaker agreement (s 87N)", "Agreement frustrated (s 109)",
    "Death of sole tenant (s 108)",
]
OA_GROUNDS = [
    "Violence or threats", "Wilful damage or illegal use",
    "Continuing serious breach after warning", "Continuing minor breach after warning",
    "Non-payment of occupancy fee", "Other reason under the agreement",
]
OA_BREACH_REASONS = {
    "nonpayment": "Non-payment of occupancy fee",
    "cleanliness": "Cleaning or upkeep",
    "damage": "Damage to the premises",
    "disturbance": "Noise or disturbance",
    "house-rule": "Other house rule breach",
    "other": "Other",
}
OA_BREACH_CLAUSES = {
    "nonpayment": "Term of Contract — Occupancy Fee and payment frequency; clause 11 — Non-payment",
    "cleanliness": "Clause 2 — House Rules",
    "damage": "Clause 12 — Use of the Premises: no wilful or negligent damage",
    "disturbance": "Clause 12 — Use of the Premises: respect other residents’ quiet enjoyment",
    "house-rule": "Clause 2 — House Rules",
}
OFFICIAL_DELIVERY = [
    "Delivering to tenant in person at premises", "Mailing to tenant",
    "Personally putting in tenant's letterbox",
    "Delivering in person to someone over 16 at premises", "Emailing to tenant",
]
DELIVERY = ["Hand", "Post", "Email", "Other"]


def display_date(value):
    return "/".join(reversed(value.split("-")))


def split_address(address):
    if "\n" in address:
        first, second = address.split("\n", 1)
        return first.strip(), ", ".join(second.splitlines()).strip()
    if stringWidth(address, "Helvetica", 10) <= 415:
        return address, ""
    words = address.split()
    for index in range(len(words) - 1, 0, -1):
        first = " ".join(words[:index])
        if stringWidth(first, "Helvetica", 10) <= 415:
            return first, " ".join(words[index:])
    return address, ""


def oa_breach_details(data):
    reason = OA_BREACH_REASONS.get(data.get("oa_reason"))
    if data.get("oa_reason") == "other":
        reason = data.get("oa_other_reason")
    return "\n".join(filter(None, (reason, data["details"])))


def field_values(kind, data, phone, signature):
    entity = ENTITY[kind.split("-")[0]]
    tenant = data["tenant"]
    property_address = data["address"]
    address = ", ".join(filter(None, (property_address, data["postcode"])))
    line1, line2 = split_address(property_address)
    date = display_date(data["date"])
    due = display_date(data["due"])
    deadline = due
    delivery = int(data["delivery"])
    clauses = ", ".join([code for code in data["clauses"] if code[0].isdigit()]
                        + (["Other (see attachment)"] if data.get("provision_text") else []))
    if kind == "rta-rent":
        return dict(zip(
            ["Name of tenant/s", "Address of premises line 1", "Address of premises line 2",
             "Postcode", "Date payable from", "New rent amount", "Signature Field 1",
             "Date supplied to tenant", "Name of landlord or agent",
             "Contact phone number of landlord or agent", OFFICIAL_DELIVERY[delivery]],
            [tenant, line1, line2, data["postcode"], due,
             data["amount"], signature, date, entity, phone, True],
        ))
    if kind == "rta-end":
        fields = {f"Text field 1.{index}": value for index, value in
                  enumerate([tenant, line1, line2, data["postcode"], due], 1)}
        ground = int(data["ground"])
        fields.update({
            "Reason for termination": f"/{ground}", f"Check Box 1.{12 + delivery}": True,
            "Signature Field 1": signature, "Text field 2.1": date,
            "Text field 2.2": entity, "Text field 2.3": phone,
        })
        if ground == 6:
            fields.update({"Text field 1.17": f"The tenant has breached clause(s) {clauses} of the residential tenancy agreement.", "Text field 1.16": data["details"]})
        return fields
    if kind == "rta-breach":
        values = [tenant, address, data["details"], clause_text(data), f'{data["action"]} by {deadline}',
                  data["other"], date, entity, phone, signature]
    else:
        specific = {
            "oa-rent": [data["current"], data["amount"], due, data["details"]],
            "oa-breach": [data["provision"], oa_breach_details(data), data["action"], deadline],
            "oa-end": [deadline, data["details"]],
        }[kind]
        values = [tenant, address, *specific, entity, phone, data["other"], date, signature]
    fields = {f"field_{index:02}": value for index, value in enumerate(values, 1)}
    fields[f"delivery_{delivery}"] = True
    if kind == "oa-end":
        fields[f'ground_{data["ground"]}'] = True
    return fields


def wrapped_lines(value, width, size):
    lines = []
    for paragraph in value.splitlines():
        line = ""
        for word in paragraph.split():
            candidate = f"{line} {word}".strip()
            if line and stringWidth(candidate, "Helvetica", size) > width:
                lines.append(line)
                line = word
            else:
                line = candidate
        lines.append(line)
    return lines


def draw_text(canvas, value, rect, baseline=None):
    left, bottom, right, top = rect
    width = right - left - 6
    for size in (10, 9, 8, 7):
        lines = wrapped_lines(value, width, size)
        if (len(lines) * (size + 2) <= top - bottom - 2
                and all(stringWidth(line, "Helvetica", size) <= width for line in lines)):
            canvas.setFont("Helvetica", size)
            for index, line in enumerate(lines):
                canvas.drawString(left + 3, (top - size - 2 if baseline is None else baseline) - index * (size + 2), line)
            return
    raise ValueError("An entry is too long for the PDF. Shorten it and preview again.")


def clause_entries(data):
    entries = [(code, CLAUSES[code]) for code in data["clauses"] if code[0].isdigit()]
    if data.get("provision_text"):
        entries.append(("Other clause", data["provision_text"]))
    return entries


def clause_text(data):
    return "\n".join(f"{code} — {wording}" for code, wording in clause_entries(data))


def expand_remedy_clause_box(page, text):
    # The supplied one-page template positions its text with Tm and its box outlines with re.
    # Expand the clause box and move the content on either side without altering its labels.
    extra = max(36, len(wrapped_lines(text, 505, 10)) * 12 + 4 - 16)
    lower = min(62, extra)
    upper = extra - lower
    if upper:
        page.mediabox.upper_right = (page.mediabox.right, float(page.mediabox.top) + upper)

    content = page.get_contents()
    for operands, operator in content.operations:
        if operator == b"Tm":
            y = float(operands[5])
            operands[5] = FloatObject(y + upper if y >= 500 else y - lower)
        elif operator == b"re":
            y = float(operands[1])
            height = float(operands[3])
            if 500 <= y < 501:  # Clause field outline.
                operands[1] = FloatObject(y - lower)
                operands[3] = FloatObject(height + extra)
            else:
                operands[1] = FloatObject(y + upper if y >= 500 else y - lower)
    page.replace_contents(content)
    return lower, upper


RENT_BASELINES = {
    "Name of tenant/s": 620.1,
    "Address of premises line 1": 556.6,
    "Address of premises line 2": 524.1,
    "Postcode": 524.1,
    "Date payable from": 491.6,
    "New rent amount": 492.6,
    "Date supplied to tenant": 267,
    "Name of landlord or agent": 217.6,
    "Contact phone number of landlord or agent": 186.3,
}


END_BASELINES = {
    "Text field 1.1": 633.7,
    "Text field 1.2": 573,
    "Text field 1.3": 553,
    "Text field 1.4": 553,
    "Text field 1.5": 526,
    "Text field 1.17": 632,
    "Text field 2.1": 528,
    "Text field 2.2": 473,
    "Text field 2.3": 431,
}


def draw_choice(canvas, rect, checked):
    left, bottom, right, top = rect
    x, y = (left + right) / 2, (bottom + top) / 2
    canvas.setStrokeColorRGB(.15, .2, .26)
    canvas.setLineWidth(.75)
    canvas.rect(x - 4.6, y - 4.6, 9.2, 9.2, fill=0)
    if checked:
        path = canvas.beginPath()
        path.moveTo(x - 2.9, y - .1)
        path.lineTo(x - .6, y - 2.4)
        path.lineTo(x + 3.1, y + 2.9)
        canvas.setLineWidth(1.15)
        canvas.drawPath(path)


def draw_signature(canvas, strokes, rect, center=False):
    left, bottom, right, top = rect
    min_x = min(x for stroke in strokes for x, _ in stroke)
    max_x = max(x for stroke in strokes for x, _ in stroke)
    min_y = min(y for stroke in strokes for _, y in stroke)
    max_y = max(y for stroke in strokes for _, y in stroke)
    scale = min((right - left - 8) / max(max_x - min_x, .01),
                (top - bottom - 8) / max((max_y - min_y) / 3, .01))
    origin_x = (left + right - (max_x - min_x) * scale) / 2 if center else left + 4
    origin_y = (top + bottom + (max_y - min_y) * scale / 3) / 2 if center else top - 4

    def position(point):
        x, y = point
        return origin_x + (x - min_x) * scale, origin_y - (y - min_y) * scale / 3
    canvas.setStrokeColorRGB(.06, .12, .22)
    canvas.setFillColorRGB(.06, .12, .22)
    canvas.setLineWidth(.9)
    canvas.setLineCap(1)
    canvas.setLineJoin(1)
    for stroke in strokes:
        if len(stroke) == 1:
            canvas.circle(*position(stroke[0]), .55, stroke=0, fill=1)
            continue
        path = canvas.beginPath()
        path.moveTo(*position(stroke[0]))
        for point in stroke[1:]:
            path.lineTo(*position(point))
        canvas.drawPath(path)


def replace_label(canvas, y, label, width=255, size=9.2):
    canvas.setFillColorRGB(1, 1, 1)
    canvas.rect(41, y - 2, width, size + 3, fill=1, stroke=0)
    canvas.setFillColorRGB(.1, .16, .22)
    canvas.setFont("Helvetica", size)
    canvas.drawString(42, y, label)


def clause_appendix(data, draft):
    styles = getSampleStyleSheet()
    entries = clause_entries(data)
    content = [Paragraph("Residential Tenancy Agreement — Clauses Cited", styles["Title"]),
               Paragraph(escape(data["tenant"]), styles["Normal"]),
               Paragraph(escape(data["address"] + ", " + data["postcode"]), styles["Normal"]),
               Spacer(1, 14)]
    for code, wording in entries:
        content.append(Paragraph(f"<b>{escape(code)}</b> · {escape(wording).replace(chr(10), '<br/>')}",
                                 styles["BodyText"]))
    def mark_draft(canvas, _doc):
        if draft:
            canvas.setFont("Helvetica-Bold", 11)
            canvas.drawCentredString(canvas._pagesize[0] / 2, 20, "DRAFT - FOR REVIEW")
    output = BytesIO()
    SimpleDocTemplate(output).build(content, onFirstPage=mark_draft, onLaterPages=mark_draft)
    output.seek(0)
    return PdfReader(output)


def render(kind, data, phone, signature=None):
    values = field_values(kind, data, phone, signature)
    writer = PdfWriter(clone_from=FORMS / FILES[kind])
    for page_number, page in enumerate(writer.pages):
        lower, upper = (expand_remedy_clause_box(page, values["field_04"])
                        if kind == "rta-breach" else (0, 0))
        layer = BytesIO()
        canvas = Canvas(layer, pagesize=(float(page.mediabox.width), float(page.mediabox.height)))
        annotations = page.get("/Annots", [])
        for ref in annotations:
            widget = ref.get_object()
            if widget.get("/Subtype") != "/Widget":
                continue
            parent = widget.get("/Parent")
            parent_name = parent.get_object().get("/T", "") if parent else ""
            key = ".".join(filter(None, [parent_name, widget.get("/T")]))
            value = values.get(key)
            rect = tuple(map(float, widget["/Rect"]))
            if kind == "rta-breach":
                left, bottom, right, top = rect
                if key == "field_04":
                    rect = left, bottom - lower, right, top + upper
                else:
                    offset = upper if bottom >= 500 else -lower
                    rect = left, bottom + offset, right, top + offset
            official = kind in ("rta-rent", "rta-end")
            widget_type = widget.get("/FT") or (parent.get_object().get("/FT") if parent else None)
            canvas.saveState()
            if official and widget_type == "/Btn":
                checked = value is True or (
                    key == "Reason for termination" and value in widget["/AP"]["/N"])
                draw_choice(canvas, rect, checked)
            elif key == "Text field 1.16" and data["ground"] == "6":
                left, bottom, right, top = rect
                canvas.setStrokeColorRGB(.36, .43, .51)
                canvas.setLineWidth(.75)
                canvas.rect(left, bottom, right - left, top - bottom, stroke=1, fill=0)
                if value:
                    draw_text(canvas, value, rect)
            elif not value:
                canvas.restoreState()
                continue
            elif value is True:
                draw_choice(canvas, rect, True)
            elif value is signature:
                draw_signature(canvas, signature, rect, center=kind == "rta-breach")
            else:
                baseline = (RENT_BASELINES if kind == "rta-rent" else END_BASELINES
                            if kind == "rta-end" else {}).get(key)
                if key == "Name of landlord or agent":
                    rect = (rect[0] - 60, *rect[1:])
                elif key == "Text field 1.17":
                    canvas.setFillColorRGB(1, 1, 1)
                    canvas.rect(56, 629, 498, 14, fill=1, stroke=0)
                    canvas.setFillColorRGB(0, 0, 0)
                    rect = (54, 628, 554, 645)
                draw_text(canvas, value, rect, baseline)
            canvas.restoreState()
        if kind == "rta-rent" and page_number == 0:
            # Mark the selected unit in the printed week/fortnight label.
            start, end = (491, 510) if data["period"] == "week" else (512, 560)
            canvas.setStrokeColorRGB(0, 0, 0)
            canvas.setLineWidth(.65)
            canvas.line(start, 490, end, 490)
        if kind in ("oa-breach", "oa-end") and page_number == 0:
            if kind == "oa-breach":
                replace_label(canvas, 379, "Deadline to remedy")
            else:
                replace_label(canvas, 526, "Date to vacate")
                replace_label(canvas, 694, "The proprietor gives you written notice to leave the premises and give vacant possession by the date",
                              width=510, size=10.2)
        if not signature:
            canvas.setFillGray(0.35)
            canvas.setFont("Helvetica-Bold", 11)
            canvas.drawCentredString(float(page.mediabox.width) / 2, 20, "DRAFT - FOR REVIEW")
        canvas.showPage()
        canvas.save()
        page.merge_page(PdfReader(layer).pages[0])
    writer.remove_annotations(subtypes="/Widget")
    writer.root_object.pop("/AcroForm", None)
    if kind == "rta-end" and data["ground"] == "6":
        writer.append(clause_appendix(data, draft=not signature), import_outline=False)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()
