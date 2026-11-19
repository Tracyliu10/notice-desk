import hmac
import json
import os
import re
import secrets
import sqlite3
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from zoneinfo import ZoneInfo

from flask import Flask, abort, flash, g, redirect, render_template, request, send_file, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from pdf_forms import CLAUSES, DELIVERY, ENTITY, FILES, FORMS, OA_BREACH_CLAUSES, OA_BREACH_REASONS, OA_GROUNDS, RTA_GROUNDS, STATEMENT, render

ROOT = Path(__file__).parent
app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get("NOTICE_SECRET") or secrets.token_hex(32),
    DATABASE=os.environ.get("NOTICE_DB", str(ROOT / "notice.sqlite3")),
    SESSION_COOKIE_SECURE=os.environ.get("NOTICE_HTTPS") == "1",
    SESSION_COOKIE_SAMESITE="Lax",
    MAX_CONTENT_LENGTH=64 * 1024,
)
SYDNEY = ZoneInfo("Australia/Sydney")
KEYS = ("tenant", "address", "address2", "postcode", "date", "due", "delivery",
        "other", "ground", "details", "provision", "action", "amount", "current",
        "period", "evidence", "days", "lease_term", "lease_end", "agreement_days", "provision_text", "service_date", "oa_reason", "oa_other_reason", "manual_vacate")
TITLES = {kind: filename.split("-", 1)[1].removesuffix(".pdf")
          for kind, filename in FILES.items()}
TITLES["rta-end"] = "Notice to Terminate Tenancy Agreement"


def db():
    if "db" not in g:
        g.db = sqlite3.connect(app.config["DATABASE"], timeout=10)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_error):
    if "db" in g:
        g.db.close()


with app.app_context():
    db().executescript("""
    CREATE TABLE IF NOT EXISTS user (
        id INTEGER PRIMARY KEY, username TEXT UNIQUE COLLATE NOCASE NOT NULL,
        name TEXT NOT NULL, password TEXT NOT NULL, role TEXT NOT NULL,
        phone TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS notice (
        id INTEGER PRIMARY KEY, kind TEXT NOT NULL, author INTEGER NOT NULL REFERENCES user,
        cm INTEGER REFERENCES user, status TEXT NOT NULL DEFAULT 'draft', data TEXT NOT NULL,
        pdf BLOB, previous INTEGER REFERENCES notice, revision INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS event (
        id INTEGER PRIMARY KEY, notice INTEGER NOT NULL REFERENCES notice,
        actor INTEGER NOT NULL REFERENCES user, at TEXT NOT NULL,
        action TEXT NOT NULL, detail TEXT NOT NULL, snapshot TEXT
    );
    """)


MEMBER_ROLES = {"junior": "Junior CM", "cm": "CM"}


def create_account(role, username, name, phone, password):
    username, name, phone = username.strip(), name.strip(), phone.strip()
    if role not in (*MEMBER_ROLES, "admin"):
        raise ValueError("Choose a valid role.")
    if not username or not name or len(password) < 12:
        raise ValueError("Enter a username, full name and password of at least 12 characters.")
    if role == "cm" and (not re.fullmatch(r"[+() .0-9-]{6,24}", phone)
                         or sum(char.isdigit() for char in phone) < 6):
        raise ValueError("Enter a valid CM phone number.")
    try:
        with db():
            db().execute("INSERT INTO user (username,name,password,role,phone) VALUES (?,?,?,?,?)",
                         (username, name, generate_password_hash(password), role, phone if role == "cm" else ""))
    except sqlite3.IntegrityError as error:
        raise ValueError("Username already exists.") from error


@app.cli.command("add-user")
def add_user():
    import click
    role = click.prompt("Role", type=click.Choice([*MEMBER_ROLES, "admin"]))
    username = click.prompt("Username")
    name = click.prompt("Full name")
    phone = click.prompt("CM contact phone") if role == "cm" else ""
    password = click.prompt("Password", hide_input=True, confirmation_prompt=True)
    try:
        create_account(role, username, name, phone, password)
    except ValueError as error:
        raise click.ClickException(str(error)) from error
    click.echo("Account created.")


@app.before_request
def authenticate():
    if request.endpoint == "static":
        return
    g.user = db().execute("SELECT * FROM user WHERE id=?", (session.get("user"),)).fetchone()
    if request.method == "POST":
        expected = session.get("csrf", "").encode()
        if not expected or not hmac.compare_digest(expected, request.form.get("csrf", "").encode()):
            abort(400)
    session.setdefault("csrf", secrets.token_urlsafe(32))
    if g.user is None and request.endpoint != "login":
        return redirect(url_for("login"))


@app.context_processor
def common():
    return dict(csrf=session.get("csrf"), titles=TITLES, entities=ENTITY)


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = db().execute("SELECT * FROM user WHERE username=?", (request.form.get("username", "").strip(),)).fetchone()
        if user and check_password_hash(user["password"], request.form.get("password", "")):
            session.clear()
            session["user"] = user["id"]
            return redirect(url_for("home"))
        flash("Username or password is incorrect.")
    return render_template("login.html")


@app.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.get("/")
def home():
    if g.user["role"] == "admin":
        return redirect(url_for("members"))
    column = "author" if g.user["role"] == "junior" else "cm"
    rows = db().execute(f"SELECT * FROM notice WHERE {column}=? AND status != 'deleted' ORDER BY id DESC", (g.user["id"],))
    notices = [(row, json.loads(row["data"])) for row in rows
               if g.user["role"] == "junior" or row["status"] not in ("draft", "returned")]
    return render_template("home.html", notices=notices)


@app.route("/admin/members", methods=["GET", "POST"])
def members():
    if g.user["role"] != "admin":
        abort(403)
    form = {key: request.form.get(key, "") for key in ("role", "username", "name", "phone")}
    if request.method == "POST":
        try:
            if form["role"] not in MEMBER_ROLES:
                raise ValueError("Choose Junior CM or CM.")
            password = request.form.get("password", "")
            if password != request.form.get("confirmation", ""):
                raise ValueError("The passwords do not match.")
            create_account(**form, password=password)
        except ValueError as error:
            flash(str(error))
        else:
            flash(f'Account created for {form["username"].strip()}.', "success")
            return redirect(url_for("members"), code=303)
    accounts = db().execute(
        "SELECT username, name, role, phone FROM user WHERE role IN ('junior','cm') ORDER BY name COLLATE NOCASE"
    ).fetchall()
    return render_template("members.html", accounts=accounts, form=form, roles=MEMBER_ROLES)


def record(notice_id):
    row = db().execute("SELECT * FROM notice WHERE id=?", (notice_id,)).fetchone()
    if row is None or row["status"] == "deleted":
        abort(404)
    if g.user["role"] == "junior":
        allowed = row["author"] == g.user["id"]
    elif g.user["role"] == "cm":
        allowed = row["cm"] == g.user["id"] and row["status"] not in ("draft", "returned")
    else:
        allowed = False
    if not allowed:
        abort(404)
    return row


def event(notice_id, action, detail="", snapshot=None):
    db().execute("INSERT INTO event (notice,actor,at,action,detail,snapshot) VALUES (?,?,?,?,?,?)",
                 (notice_id, g.user["id"], datetime.now(timezone.utc).isoformat(), action, detail, snapshot))


def blank():
    data = dict.fromkeys(KEYS, "")
    data.update(date=datetime.now(SYDNEY).date().isoformat(), clauses=[])
    return data


@app.post("/new")
def new():
    kind = request.form.get("kind")
    if g.user["role"] != "junior":
        abort(403)
    if kind not in FILES or kind.split("-")[0] != request.form.get("entity"):
        flash("Choose an entity and notice type.")
        return redirect(url_for("home"))
    with db():
        cursor = db().execute("INSERT INTO notice(kind,author,data) VALUES (?,?,?)",
                              (kind, g.user["id"], json.dumps(blank())))
        event(cursor.lastrowid, "Created")
    return redirect(url_for("detail", notice_id=cursor.lastrowid))


NOTICE_DAYS = (0, 1, 3, 7, 14, 28, 30, 60, 90)


RTA_END_DAYS = {"0": 30, "6": 14, "7": 14, "9": 0, "10": 0}
OA_END_DAYS = {"0": 0, "1": 1, "2": 3, "3": 7, "4": 14, "5": 28}
TERM_DEPENDENT = ("1", "2", "3", "4", "5")


def notice_period(kind, data):
    if kind == "rta-rent":
        return 60
    if kind == "oa-rent":
        return 28
    if kind == "rta-breach":
        return None
    if kind == "oa-end":
        return OA_END_DAYS.get(data["ground"])
    if kind == "rta-end":
        ground = data["ground"]
        if ground in RTA_END_DAYS:
            return RTA_END_DAYS[ground]
        if ground in TERM_DEPENDENT:
            return {"short": 60, "long": 90, "periodic": 90}.get(data.get("lease_term"))
        if ground == "8":
            contractual_days = data.get("agreement_days", "")
            return max(30, int(contractual_days)) if re.fullmatch(r"[0-9]{1,4}", contractual_days) else None
        return None
    days = data.get("days", "")
    if not days:
        return None
    if days not in {str(value) for value in NOTICE_DAYS}:
        raise ValueError("Choose a listed notice period.")
    return int(days)


def requires_lease_end(kind, data):
    return (kind == "rta-end" and data["ground"] in ("0", *TERM_DEPENDENT)
            and data.get("lease_term") in ("short", "long"))


def delivered_date(kind, data):
    if kind.startswith("rta") and data["delivery"] == "1":
        return data.get("service_date", "")
    return data["date"]


def calculate_due(kind, data):
    if kind == "oa-end" and data.get("manual_vacate") == "yes":
        return
    days = notice_period(kind, data)
    if days is None and not kind.endswith("-end"):
        return
    data["due"] = ""
    try:
        if days is None:
            return
        due = date.fromisoformat(delivered_date(kind, data)) + timedelta(days=days)
        if requires_lease_end(kind, data):
            due = max(due, date.fromisoformat(data.get("lease_end", "")))
        data["due"] = due.isoformat()
    except (ValueError, OverflowError):
        pass


def load_notice(row):
    data = json.loads(row["data"])
    for key in KEYS:
        data.setdefault(key, "")
    data["address"] = ", ".join(line.strip() for line in data["address"].splitlines() if line.strip())
    if data["address2"]:
        data["address"] = ", ".join(filter(None, (data["address"], data["address2"])))
        data["address2"] = ""
    if row["kind"].startswith("rta") and data["provision"]:
        data["provision_text"] = " — ".join(filter(None, (data["provision"], data["provision_text"])))
        data["provision"] = ""
    return data


def read_signature(raw):
    try:
        strokes = json.loads(raw)
        if not isinstance(strokes, list) or not 1 <= len(strokes) <= 100:
            raise ValueError
        points = []
        for stroke in strokes:
            if not isinstance(stroke, list) or not 1 <= len(stroke) <= 2400:
                raise ValueError
            for point in stroke:
                if (not isinstance(point, list) or len(point) != 2
                        or any(type(value) not in (int, float) or not 0 <= value <= 1 for value in point)):
                    raise ValueError
                points.append(point)
        if len(points) > 2400 or max(max(p[i] for p in points) - min(p[i] for p in points) for i in (0, 1)) < .025:
            raise ValueError
    except (ValueError, RecursionError):
        raise ValueError("Draw your signature before confirming.") from None
    return strokes


def selections(kind):
    delivery = ["Hand to tenant", "Post", "Tenant's letterbox", "Hand to person over 16 at premises", "Email"]
    return (delivery if kind in ("rta-rent", "rta-end") else DELIVERY,
            RTA_GROUNDS if kind == "rta-end" else OA_GROUNDS)


class InvalidFields(ValueError):
    def __init__(self, fields):
        self.fields = fields
        super().__init__(" ".join(fields.values()))


def validate(kind, data, cm, *, submitting=False):
    errors = {}
    is_rta = kind.startswith("rta")
    notice_type = kind.split("-")[1]
    delivery, grounds = selections(kind)
    for key, message in {
        "tenant": "Enter the full name.", "address": "Enter the property address.",
        "date": "Enter the issue or delivery date.",
    }.items():
        if not data[key]:
            errors[key] = message
    if not cm:
        errors["cm"] = "Choose a reviewing CM."
    if not re.fullmatch(r"\d{4}", data["postcode"]):
        errors["postcode"] = "Enter the four-digit postcode."
    if data["delivery"] not in {str(index) for index in range(len(delivery))}:
        errors["delivery"] = "Choose a delivery method."
    elif delivery[int(data["delivery"])] == "Other" and not data["other"]:
        errors["other"] = "Describe the delivery method."
    if is_rta and data["delivery"] == "1":
        try:
            if date.fromisoformat(delivered_date(kind, data)) <= date.fromisoformat(data["date"]):
                raise ValueError
        except ValueError:
            errors["service_date"] = "Enter a postal delivery date after the posting date."
    if notice_type == "end":
        if data["ground"] not in {str(index) for index in range(len(grounds))}:
            errors["ground"] = "Choose the ground for termination."
        if not is_rta and not data["details"]:
            errors["details"] = "Enter the reason details."
    if kind == "rta-end":
        if data["ground"] in ("0", *TERM_DEPENDENT) and data.get("lease_term") not in ("short", "long", "periodic"):
            errors["lease_term"] = "Choose the tenancy term."
        if requires_lease_end(kind, data) and not data.get("lease_end"):
            errors["lease_end"] = "Enter the fixed-term agreement end date."
        if data["ground"] == "8" and not re.fullmatch(r"[0-9]{1,4}", data.get("agreement_days", "")):
            errors["agreement_days"] = "Enter the contractual notice period. Use 0 if none is specified."

    delivery_date, due_date = None, None
    if data["date"]:
        try:
            delivery_date = date.fromisoformat(data["date"])
        except ValueError:
            errors["date"] = "Enter a valid issue or delivery date."
    if data["due"]:
        try:
            due_date = date.fromisoformat(data["due"])
        except ValueError:
            errors["due"] = "Enter a valid effective date or deadline."
    elif not any(key in errors for key in ("date", "service_date", "ground", "lease_term", "lease_end", "agreement_days")):
        errors["due"] = "Enter the effective date or deadline."
    if due_date and delivery_date and due_date < delivery_date:
        errors["due"] = "Use a date on or after the issue or delivery date."

    if notice_type == "rent":
        for field in (["amount"] if is_rta else ["current", "amount"]):
            if not re.fullmatch(r"\d{1,8}(\.\d{1,2})?", data[field]) or Decimal(data[field]) <= 0:
                errors[field] = "Enter a positive amount in AUD."
        if is_rta and data["period"] not in ("week", "fortnight"):
            errors["period"] = "Choose the rent period."
        if not is_rta and "amount" not in errors and "current" not in errors and Decimal(data["amount"]) <= Decimal(data["current"]):
            errors["amount"] = "The new fee must exceed the current fee."
    if kind == "rta-breach" or (kind == "rta-end" and data["ground"] == "6"):
        if not data["details"]:
            errors["details"] = "Describe what happened."
        if not (data["clauses"] or data["provision_text"]):
            errors["clauses"] = "Select at least one applicable clause."
        if any(not code[0].isdigit() for code in data["clauses"]) and not data["provision_text"]:
            errors["provision_text"] = "Enter the applicable clause number and wording."
    if notice_type == "breach" and not data["action"]:
        errors["action"] = "Enter the action required to remedy the breach."
    if kind == "oa-breach":
        if not data["provision"]:
            errors["provision"] = "Enter the OA clause or house rule."
        if not data["details"]:
            errors["details"] = "Describe what happened."
        if submitting and data["oa_reason"] not in OA_BREACH_REASONS:
            errors["oa_reason"] = "Choose the breach reason."
        if submitting and data["oa_reason"] == "other" and not data["oa_other_reason"]:
            errors["oa_other_reason"] = "Describe the other breach reason."
    if errors:
        raise InvalidFields(errors)


@app.route("/notice/<int:notice_id>", methods=["GET", "POST"])
def detail(notice_id):
    row = record(notice_id)
    kind, data = row["kind"], load_notice(row)
    if row["status"] != "confirmed":
        calculate_due(kind, data)
    junior = g.user["role"] == "junior"
    editable = junior and row["status"] in ("draft", "returned")
    managers = db().execute("SELECT id,name,phone FROM user WHERE role='cm' ORDER BY name").fetchall()
    cm = next((manager for manager in managers if manager["id"] == row["cm"]), None)
    field_errors = {}
    if request.method == "POST":
        action = request.form.get("command")
        try:
            with db():
                db().execute("BEGIN IMMEDIATE")
                current = record(notice_id)
                if str(current["revision"]) != request.form.get("revision") or current["revision"] != row["revision"]:
                    raise ValueError("This notice changed. Reload it and try again.")
                if action in ("save", "submit") and editable:
                    data = {key: request.form.get(key, "").strip() for key in KEYS}
                    data["clauses"] = [key for key in CLAUSES if key in request.form.getlist("clauses")]
                    if kind == "oa-breach" and not data["provision"]:
                        data["provision"] = OA_BREACH_CLAUSES.get(data["oa_reason"], "")
                    calculate_due(kind, data)
                    cm = next((manager for manager in managers if str(manager["id"]) == request.form.get("cm")), None)
                    status = row["status"]
                    if action == "submit":
                        validate(kind, data, cm, submitting=True)
                        render(kind, data, cm["phone"])
                        status = "pending"
                        event(notice_id, "Submitted", snapshot=json.dumps(data))
                    db().execute("UPDATE notice SET data=?,cm=?,status=?,revision=revision+1 WHERE id=?",
                                 (json.dumps(data), cm["id"] if cm else None, status, notice_id))
                elif action == "delete" and junior and row["status"] in ("draft", "pending", "returned"):
                    db().execute("UPDATE notice SET status='deleted',revision=revision+1 WHERE id=?", (notice_id,))
                    event(notice_id, "Deleted", snapshot=row["data"])
                    flash("Notice deleted.")
                elif action == "revise" and junior and row["status"] == "confirmed":
                    cursor = db().execute("INSERT INTO notice(kind,author,cm,data,previous) VALUES (?,?,?,?,?)",
                                          (kind, row["author"], row["cm"], row["data"], notice_id))
                    event(cursor.lastrowid, "Revision created", f"Original notice #{notice_id}")
                    return redirect(url_for("detail", notice_id=cursor.lastrowid))
                elif not junior and row["status"] == "pending" and action in ("return", "confirm"):
                    if action == "return":
                        reason = request.form.get("reason", "").strip()
                        if not reason:
                            raise ValueError("Enter the changes required.")
                        db().execute("UPDATE notice SET status='returned',revision=revision+1 WHERE id=?", (notice_id,))
                        event(notice_id, "Returned", reason)
                    else:
                        signature = read_signature(request.form.get("signature", ""))
                        validate(kind, data, cm)
                        pdf = render(kind, data, g.user["phone"], signature)
                        snapshot = json.dumps(data)
                        db().execute("UPDATE notice SET status='confirmed',pdf=?,data=?,revision=revision+1 WHERE id=?",
                                     (pdf, snapshot, notice_id))
                        event(notice_id, "Signed and confirmed", g.user["phone"], snapshot)
                else:
                    abort(403)
            if action == "save":
                return redirect(url_for("detail", notice_id=notice_id, saved=1, _anchor="preview-draft"), code=303)
            return redirect(url_for("home" if action in ("return", "delete") else "detail", **(
                {} if action in ("return", "delete") else {"notice_id": notice_id})))
        except InvalidFields as error:
            if editable:
                field_errors = error.fields
                flash("Review the highlighted fields before submitting.")
            else:
                flash(str(error))
        except ValueError as error:
            flash(str(error))
    returned = None
    if row["status"] == "returned":
        returned = db().execute(
            "SELECT detail FROM event WHERE notice=? AND action='Returned' ORDER BY id DESC LIMIT 1",
            (notice_id,)).fetchone()
    delivery, grounds = selections(kind)
    return render_template("detail.html", row=row, kind=kind, data=data, cm=cm, managers=managers,
                           editable=editable, junior=junior, returned=returned, clauses=CLAUSES, field_errors=field_errors,
                           delivery=delivery, grounds=grounds, notice_days=NOTICE_DAYS,
                           term_dependent=TERM_DEPENDENT, oa_breach_reasons=OA_BREACH_REASONS,
                           oa_breach_clauses=OA_BREACH_CLAUSES,
                           fixed_ground_days=OA_END_DAYS if kind == "oa-end" else RTA_END_DAYS)


@app.get("/notice/<int:notice_id>/pdf")
def download(notice_id):
    row = record(notice_id)
    if row["status"] == "confirmed":
        return send_file(BytesIO(row["pdf"]), mimetype="application/pdf", as_attachment=True,
                         download_name=f'{row["kind"]}-{notice_id}.pdf')
    cm = db().execute("SELECT phone FROM user WHERE id=?", (row["cm"],)).fetchone()
    data = load_notice(row)
    try:
        calculate_due(row["kind"], data)
        validate(row["kind"], data, cm)
        pdf = render(row["kind"], data, cm["phone"])
    except ValueError as error:
        flash(str(error))
        return redirect(url_for("detail", notice_id=notice_id, _anchor="preview-draft"))
    return send_file(BytesIO(pdf), mimetype="application/pdf", download_name=f"draft-{notice_id}.pdf")


@app.get("/notice/<int:notice_id>/statement")
def statement(notice_id):
    row = record(notice_id)
    if row["kind"] != "rta-end" or row["status"] != "confirmed":
        abort(404)
    return send_file(FORMS / STATEMENT, as_attachment=True, download_name="Termination Information Statement.pdf")


@app.after_request
def headers(response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    return response
