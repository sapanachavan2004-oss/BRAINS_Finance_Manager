import os
import sqlite3
from datetime import datetime
from io import BytesIO
import matplotlib
matplotlib.use("Agg")   # Use non-GUI backend
from matplotlib import pyplot as plt
from flask import (Flask, flash, redirect, render_template, request, send_file, url_for)
from matplotlib import pyplot as plt
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas as pdf_canvas
from flask import Flask, render_template, request, redirect, url_for, session, flash

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(APP_DIR, "college_finance.db")

# Ensure DB exists and has table
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
    CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event TEXT NOT NULL,
        type TEXT NOT NULL,
        amount REAL NOT NULL,
        description TEXT,
        date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        year INTEGER 
    )
    ''')
    
    # ✅ Check if 'year' column already exists
    c.execute("PRAGMA table_info(transactions)")
    columns = [col[1] for col in c.fetchall()]

    if "year" not in columns:
        # ❌ Can't use strftime default here — must use constant NULL or similar
        c.execute("ALTER TABLE transactions ADD COLUMN year INTEGER")
        print("✅ 'year' column added to existing database")

        # Optionally fill existing rows with the current year
        current_year = datetime.now().year
        c.execute("UPDATE transactions SET year = ?", (current_year,))
        print(f"✅ Existing records updated with year = {current_year}")

        
    conn.commit()
    conn.close()

init_db()

# Predefined events/descriptions (kept from original)
EVENT_DESCRIPTIONS = {
    "TechFest": ["Registration", "Sponsorship", "Equipment", "Catering", "Miscellaneous"],
    "CulturalNight": ["Tickets", "Performers", "Decorations", "Refreshments", "Miscellaneous"],
    "SportsDay": ["Entry Fee", "Prizes", "Equipment", "Refreshments", "Miscellaneous"],
}

# Flask app
app = Flask(__name__, static_folder="static", template_folder="templates")
app.secret_key = "replace_with_a_strong_secret"

# Helpers
def get_db_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def fetch_events():
    conn = get_db_conn()
    rows = conn.execute("SELECT DISTINCT event FROM transactions").fetchall()
    conn.close()
    known = set([r["event"] for r in rows]).union(EVENT_DESCRIPTIONS.keys())
    return sorted(known)

def calc_summary_for_event(event):
    conn = get_db_conn()
    cur = conn.cursor()
    cur.execute("SELECT type, SUM(amount) as total FROM transactions WHERE event=? GROUP BY type", (event,))
    res = {row[0]: row[1] for row in cur.fetchall()}
    conn.close()
    income = res.get("income", 0) or 0
    expense = res.get("expense", 0) or 0
    remaining = income - expense
    return income, expense, remaining

# Routes
#@app.route("/")
#def index():
 #   events = fetch_events()
  #  return render_template("index.html", events=events, event_descriptions=EVENT_DESCRIPTIONS)
@app.route("/")
def index():
    events = fetch_events()
    conn = get_db_conn()
    cur = conn.cursor()
    cur.execute("SELECT type, SUM(amount) FROM transactions GROUP BY type")
    totals = {row[0]: row[1] for row in cur.fetchall()}
    conn.close()

    total_income = totals.get("income", 0) or 0
    total_expense = totals.get("expense", 0) or 0
    total_balance = total_income - total_expense
    default_event = events[0] if events else None

    return render_template(
    "index.html",
    events=events,
    total_income=total_income,
    total_expense=total_expense,
    total_balance=total_balance,
    default_event=default_event,
    current_year=datetime.now().year,
    event_descriptions=EVENT_DESCRIPTIONS,
    body_class="dashboard-content"  # <--- Add this
)

@app.route("/add", methods=["POST"])
def add_transaction():
    event = request.form.get("event_select") or request.form.get("event_new")
    ttype = request.form.get("type")
    amount_raw = request.form.get("amount", "0")
    description = request.form.get("description", "").strip()
    year = request.form.get("year")

    try:
        amount = float(amount_raw)
    except ValueError:
        flash("Please enter a valid amount.", "danger")
        return redirect(url_for("index"))

    if not event or amount <= 0 or not description:
        flash("Please fill all fields correctly.", "danger")
        return redirect(url_for("index"))

    conn = get_db_conn()
    conn.execute("INSERT INTO transactions (event, type, amount, description, year) VALUES (?, ?, ?, ?, ?)", (event, ttype, amount, description, year))
    conn.commit()
    conn.close()

    flash(f"{ttype.capitalize()} of ₹{amount:.2f} added to '{event}'  for year {year}", "success")
    return redirect(url_for("index"))


@app.route("/event/<event_name>")
def view_event(event_name):
    year = request.args.get("year")
    if not year:
        year = datetime.now().year  # Default to current year

    conn = sqlite3.connect("college_finance.db")
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # ✅ Get transactions filtered by event and year
    c.execute(
        "SELECT * FROM transactions WHERE event=? AND year=? ORDER BY date DESC",
        (event_name, year)
    )
    rows = c.fetchall()

    # ✅ Compute totals (income, expense)
    c.execute(
        "SELECT type, SUM(amount) FROM transactions WHERE event=? AND year=? GROUP BY type",
        (event_name, year)
    )
    totals = dict(c.fetchall())

    income = totals.get("income", 0) or 0
    expense = totals.get("expense", 0) or 0
    remaining = income - expense   # ✅ This fixes 'remaining' undefined

    # ✅ Determine financial health
    if remaining > 0:
        health = "Healthy"
        health_level = "text-success"
    elif remaining < 0:
        health = "Deficit"
        health_level = "text-danger"
    else:
        health = "Balanced"
        health_level = "text-secondary"

    conn.close()

    # ✅ Pass everything needed to template
    return render_template(
        "event.html",
        event=event_name,
        rows=rows,
        year=int(year),
        current_year=datetime.now().year,
        income=income,
        expense=expense,
        remaining=remaining,       # ✅ added
        health=health,              # ✅ added
        health_level=health_level   # ✅ added
    )


@app.route("/transaction/<int:txn_id>/edit", methods=["GET","POST"])
def edit_transaction(txn_id):
    conn = get_db_conn()
    if request.method == "POST":
        amount_raw = request.form.get("amount", "0")
        description = request.form.get("description", "").strip()
        try:
            amount = float(amount_raw)
        except ValueError:
            flash("Invalid amount", "danger")
            return redirect(request.url)
        if amount <= 0 or not description:
            flash("Provide valid amount and description", "danger")
            return redirect(request.url)
        conn.execute("UPDATE transactions SET amount=?, description=? WHERE id=?", (amount, description, txn_id))
        conn.commit()
        conn.close()
        flash("Transaction updated", "success")
        # get event to redirect
        return_event = request.form.get("return_event") or url_for("index")
        return redirect(url_for("view_event", event_name=return_event))
    else:
        row = conn.execute("SELECT * FROM transactions WHERE id=?", (txn_id,)).fetchone()
        conn.close()
        if not row:
            flash("Transaction not found", "danger")
            return redirect(url_for("index"))
        return render_template("edit_transaction.html", row=row)
    
@app.route("/chart/expense_breakdown/<event_name>.png")
def chart_expense_breakdown(event_name):
    year = request.args.get("year", datetime.now().year)
    conn = get_db_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT description, SUM(amount) 
        FROM transactions 
        WHERE event=? AND type='expense' AND year=?
        GROUP BY description
    """, (event_name, int(year)))
    data = cur.fetchall()
    conn.close()

    # Create figure
    fig, ax = plt.subplots(figsize=(6, 4), dpi=120)
    if data:
        labels = [r[0] for r in data]
        values = [r[1] for r in data]
        colors = plt.cm.tab20.colors[:len(values)]
        wedges, texts, autotexts = ax.pie(
            values,
            labels=labels,
            autopct='%1.1f%%',
            startangle=90,
            colors=colors,
            textprops={'color': "black", 'fontsize': 9}
        )
        ax.set_title(f"Expense Breakdown ({year})", fontsize=12, pad=15)
        ax.axis("equal")
    else:
        ax.text(0.5, 0.5, f"No Expense Data for {year}", ha="center", va="center", fontsize=12)
        ax.axis("off")

    buf = BytesIO()
    fig.tight_layout()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return send_file(buf, mimetype="image/png")


@app.route("/chart/income_vs_expense/<event_name>.png")
def chart_income_vs_expense(event_name):
    year = request.args.get("year", datetime.now().year)
    conn = get_db_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT 
            SUM(CASE WHEN type='income' THEN amount ELSE 0 END) AS total_income,
            SUM(CASE WHEN type='expense' THEN amount ELSE 0 END) AS total_expense
        FROM transactions
        WHERE event=? AND year=?
    """, (event_name, int(year)))
    row = cur.fetchone()
    conn.close()

    income = row[0] or 0
    expense = row[1] or 0

    fig, ax = plt.subplots(figsize=(6, 4), dpi=120)
    bars = ax.bar(
        ["Income", "Expense"],
        [income, expense],
        color=["#4CAF50", "#F44336"],
        width=0.4
    )

    for bar in bars:
        height = bar.get_height()
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            height + (max(income, expense) * 0.02 if (income or expense) else 20),
            f"₹{height:.2f}",
            ha='center', va='bottom', fontsize=10
        )

    ax.set_title(f"Income vs Expense ({year})", fontsize=12, pad=15)
    ax.set_ylabel("Amount (₹)")
    ax.set_ylim(0, max(income, expense) * 1.2 if (income or expense) else 1000)
    ax.grid(axis='y', linestyle='--', alpha=0.6)

    buf = BytesIO()
    fig.tight_layout()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return send_file(buf, mimetype="image/png")




@app.route("/pdf/<event_name>")
def generate_pdf(event_name):
    year = request.args.get("year", datetime.now().year)
    conn = get_db_conn()
    cur = conn.cursor()

    # Get data filtered by event and year
    cur.execute("""
        SELECT type, description, SUM(amount)
        FROM transactions
        WHERE event=? AND year=?
        GROUP BY type, description
    """, (event_name, year))
    detailed_data = cur.fetchall()

    cur.execute("""
        SELECT type, SUM(amount)
        FROM transactions
        WHERE event=? AND year=?
        GROUP BY type
    """, (event_name, year))
    totals = {row[0]: row[1] for row in cur.fetchall()}
    conn.close()

    if not detailed_data:
        flash(f"No transactions to generate PDF for {event_name} ({year})", "info")
        return redirect(url_for("view_event", event_name=event_name, year=year))

    filename = f"{event_name.replace(' ', '')}_Summary_{year}.pdf"
    filepath = os.path.join(APP_DIR, "generated_reports", filename)
    os.makedirs(os.path.dirname(filepath), exist_ok=True)

    width, height = A4
    c = pdf_canvas.Canvas(filepath, pagesize=A4)

    # ✅ Correct header image path
    header_img = os.path.join(APP_DIR, "static", "image", "header.jpg")

    # ✅ Draw logo if available
    if os.path.exists(header_img):
        try:
            c.drawImage(header_img, 40, height - 90, width=90, height=80, preserveAspectRatio=True, mask='auto')
        except Exception as e:
            print("⚠️ Error loading logo:", e)
    else:
        print(f"⚠️ Logo not found at: {header_img}")

    # Header text
    c.setFont("Helvetica-Bold", 14)
    c.drawCentredString(width / 2, height - 40, "GHARDA INSTITUTE OF TECHNOLOGY")
    c.setFont("Helvetica-Bold", 12)
    c.drawCentredString(width / 2, height - 60, "Department Of Computer Science and Engineering (AIML)")
    c.drawCentredString(width / 2, height - 80, f"BRAINS Finance Report ({year})")
    c.line(50, height - 110, width - 50, height - 110)

    c.setFont("Helvetica-Bold", 16)
    c.drawCentredString(width / 2, height - 140, f"Finance Report: {event_name}")

    # Table
    y = height - 180
    c.setFont("Helvetica-Bold", 12)
    c.drawString(50, y, "Type")
    c.drawString(150, y, "Description")
    c.drawString(400, y, "Amount")
    y -= 20
    c.setFont("Helvetica", 11)

    for typ, desc, amt in detailed_data:
        c.drawString(50, y, typ.capitalize())
        c.drawString(150, y, str(desc))
        c.drawRightString(480, y, f"₹{amt:.2f}")
        y -= 20
        if y < 100:
            c.showPage()
            y = height - 100

    # Totals
    income = totals.get("income", 0) or 0
    expense = totals.get("expense", 0) or 0
    remaining = income - expense

    y -= 30
    c.setFont("Helvetica-Bold", 12)
    c.drawString(50, y, "Total Income:")
    c.drawRightString(480, y, f"₹{income:.2f}")
    y -= 20
    c.drawString(50, y, "Total Expense:")
    c.drawRightString(480, y, f"₹{expense:.2f}")
    y -= 20
    c.drawString(50, y, "Remaining Balance:")
    c.drawRightString(480, y, f"₹{remaining:.2f}")

    # Footer
    y = 100
    c.line(50, y + 150, width - 50, y + 150)
    c.setFont("Helvetica", 11)
    c.drawString(70, y + 60, "Sagar Kudkar")
    c.drawString(240, y + 60, "Dr. Arun R Dhang")
    c.drawString(410, y + 60, "Prof. Sachin D Latkar")
    c.drawString(70, y + 40, "President")
    c.drawString(240, y + 40, "BRAINS Staff Coordinator")
    c.drawString(410, y + 40, "HOD CSEAIML")

    c.save()
    return send_file(filepath, as_attachment=True)



# Simple delete route (optional)
@app.route("/transaction/<int:txn_id>/delete", methods=["POST"])
def delete_transaction(txn_id):
    conn = get_db_conn()
    conn.execute("DELETE FROM transactions WHERE id=?", (txn_id,))
    conn.commit()
    conn.close()
    flash("Transaction deleted", "success")
    return redirect(url_for("index"))

@app.context_processor
def inject_events():
    return dict(fetch_events=fetch_events)

app.secret_key = "super_secret_key"

DB_FILE = "admin.db"

def init_db():
    if not os.path.exists(DB_FILE):
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute('''CREATE TABLE admin (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        username TEXT UNIQUE NOT NULL,
                        password TEXT NOT NULL
                    )''')
        conn.commit()
        conn.close()

init_db()
@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        try:
            c.execute("INSERT INTO admin (username, password) VALUES (?, ?)", (username, password))
            conn.commit()
            flash(f"Admin '{username}' created! Please login.", "success")
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            flash("Username already exists!", "danger")
        finally:
            conn.close()
    
    return render_template("signup.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT * FROM admin WHERE username=? AND password=?", (username, password))
        admin = c.fetchone()
        conn.close()

        if admin:
            session["admin_logged_in"] = True
            session["admin_username"] = username

            # Redirect to default event (first in the list)
            events = fetch_events()
            default_event = events[0] if events else None
            if default_event:
                return redirect(url_for("view_event", event_name=default_event))
            else:
                return redirect(url_for("index"))  # fallback if no events exist
        else:
            flash("Invalid credentials", "error")
            return redirect(url_for("login"))

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out successfully.", "info")
    return redirect(url_for("login"))
@app.before_request
def require_login():
    allowed_routes = ["login", "signup","forgot_password", "static"]
    if request.endpoint not in allowed_routes and "admin_logged_in" not in session:
        return redirect(url_for("login"))
@app.route("/forgot-password", methods=["GET", "POST"])

def forgot_password():
    if request.method == "POST":
        username = request.form.get("username")
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT * FROM admin WHERE username=?", (username,))
        admin = c.fetchone()
        conn.close()
        
        if admin:
            flash(f"Reset link sent to '{username}'.", "success")
        else:
            flash(f"Username '{username}' not found. You can sign up.", "info")
            return redirect(url_for("signup"))
        
        return redirect(url_for("login"))
    
    return render_template("forgot_password.html")

if __name__ == "__main__":
    app.run(debug=True) 