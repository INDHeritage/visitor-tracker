from flask import Flask, render_template, request, redirect, url_for, session, send_file, flash, render_template_string
import requests
import pandas as pd
import datetime
import os
import threading
import time
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "default_key")
USERNAME = os.getenv("FLASK_USERNAME")
PASSWORD = os.getenv("FLASK_PASSWORD")

DATA_URL = "https://heritage-flask-app.onrender.com/admin/visits?password=Shad@!admin123"
EXCEL_ALL_FILE = "visitor_data.xlsx"
DATA_FOLDER = "visitor_logs"  # Folder for date-wise Excel files

# Ensure log folder exists
os.makedirs(DATA_FOLDER, exist_ok=True)

fetched_data = []

@app.route("/test")
def test():
    return "✅ App is working!"

def fetch_data():
    try:
        response = requests.get(DATA_URL)
        response.raise_for_status()
        data = response.json()

        for d in data:
            try:
                dt = datetime.datetime.fromisoformat(d['timestamp'])
                d['timestamp'] = dt.strftime('%Y-%m-%d %H:%M:%S')
            except:
                pass
        return data
    except Exception as e:
        print(f"Error fetching data: {e}")
        return []

def save_to_excel(data):
    # Save full data
    df = pd.DataFrame(data)
    df.to_excel(EXCEL_ALL_FILE, index=False)

    # Save date-wise
    for item in data:
        try:
            ts = datetime.datetime.strptime(item['timestamp'], "%Y-%m-%d %H:%M:%S")
            y, m, d = ts.strftime("%Y"), ts.strftime("%m"), ts.strftime("%d")
            path = os.path.join(DATA_FOLDER, y, m)
            os.makedirs(path, exist_ok=True)
            file_path = os.path.join(path, f"{d}.xlsx")

            df_day = pd.DataFrame([item])
            if os.path.exists(file_path):
                df_existing = pd.read_excel(file_path)
                df_day = pd.concat([df_existing, df_day], ignore_index=True)
            df_day.to_excel(file_path, index=False)
        except Exception as e:
            print(f"Error saving daily log: {e}")


def continuous_fetch():
    global fetched_data
    while True:
        print("⏳ Auto-fetching visitor data...")
        data = fetch_data()
        if data and data != fetched_data:
            fetched_data = data
            save_to_excel(fetched_data)
        time.sleep(60)


@app.route("/dashboard")
def dashboard():
    if "user" not in session:
        return redirect(url_for("login"))

    # Compute total visits
    total_visits = len(fetched_data)

    # Count by device type
    device_counts = {"Desktop": 0, "Mobile": 0, "Other": 0}

    for visit in fetched_data:
        agent = visit.get("user_agent", "").lower()
        if "mobile" in agent:
            device_counts["Mobile"] += 1
        elif "windows" in agent or "macintosh" in agent or "linux" in agent:
            device_counts["Desktop"] += 1
        else:
            device_counts["Other"] += 1

    return render_template("dashboard.html",
                           total_visits=total_visits,
                           device_counts=device_counts)



@app.route("/", methods=["GET"])
@app.route("/", methods=["GET"])
def index():
    if "user" not in session:
        return redirect(url_for("login"))

    total_visits = len(fetched_data)

    # Count by device type
    device_counts = {"Desktop": 0, "Mobile": 0, "Other": 0}
    for visit in fetched_data:
        agent = visit.get("user_agent", "").lower()
        if "mobile" in agent:
            device_counts["Mobile"] += 1
        elif "windows" in agent or "macintosh" in agent or "linux" in agent:
            device_counts["Desktop"] += 1
        else:
            device_counts["Other"] += 1

    return render_template("index.html", data=fetched_data,
                           total_visits=total_visits,
                           device_counts=device_counts)


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = request.form["username"]
        pw = request.form["password"]
        if user == USERNAME and pw == PASSWORD:
            session["user"] = user
            return redirect(url_for("index"))
        else:
            flash("Invalid username or password", "danger")
            return redirect(url_for("login"))
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.pop("user", None)
    return redirect(url_for("login"))

@app.route("/download", methods=["GET", "POST"])
def download_excel():
    if "user" not in session:
        return redirect(url_for("login"))

    if request.method == "POST":
        year = request.form.get("year")
        month = request.form.get("month")
        day = request.form.get("day")
        file_path = os.path.join(DATA_FOLDER, year, month, f"{day}.xlsx")

        if os.path.exists(file_path):
            return send_file(file_path, as_attachment=True)
        else:
            flash("No data found for selected date", "warning")
            return redirect(url_for("download_excel"))

    # Collect year/month/day options
    years = sorted(os.listdir(DATA_FOLDER)) if os.path.exists(DATA_FOLDER) else []
    months = []
    days = []
    if years:
        months_path = os.path.join(DATA_FOLDER, years[-1])
        if os.path.exists(months_path):
            months = sorted(os.listdir(months_path))
            if months:
                days_path = os.path.join(months_path, months[-1])
                if os.path.exists(days_path):
                    days = [f.replace(".xlsx", "") for f in os.listdir(days_path)]

    return render_template_string("""
    <!DOCTYPE html>
    <html>
    <head>
      <title>Download Visitors by Date</title>
      <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css">
    </head>
    <body class="bg-light">
      <div class="container mt-5">
        <h3 class="mb-4">📥 Download Visitor Data</h3>
        {% with messages = get_flashed_messages(with_categories=true) %}
          {% if messages %}
            {% for category, message in messages %}
              <div class="alert alert-{{ category }}">{{ message }}</div>
            {% endfor %}
          {% endif %}
        {% endwith %}
        <form method="POST" class="border p-4 bg-white shadow-sm rounded">
          <div class="row mb-3">
            <div class="col-md-4">
              <label>Year</label>
              <select name="year" class="form-select" required>
                {% for y in years %}
                  <option value="{{ y }}">{{ y }}</option>
                {% endfor %}
              </select>
            </div>
            <div class="col-md-4">
              <label>Month</label>
              <select name="month" class="form-select" required>
                {% for m in months %}
                  <option value="{{ m }}">{{ m }}</option>
                {% endfor %}
              </select>
            </div>
            <div class="col-md-4">
              <label>Day</label>
              <select name="day" class="form-select" required>
                {% for d in days %}
                  <option value="{{ d }}">{{ d }}</option>
                {% endfor %}
              </select>
            </div>
          </div>
          <button type="submit" class="btn btn-primary">Download Excel</button>
          <a href="/" class="btn btn-secondary ms-2">Back to Dashboard</a>
        </form>

        <hr />
        <a href="/download-all" class="btn btn-success">⬇️ Download All Visitors</a>
      </div>
    </body>
    </html>
    """, years=years, months=months, days=days)

@app.route("/download-all")
def download_all():
    if "user" not in session:
        return redirect(url_for("login"))
    if os.path.exists(EXCEL_ALL_FILE):
        return send_file(EXCEL_ALL_FILE, as_attachment=True)
    return "File not found", 404

# Start background fetch thread
threading.Thread(target=continuous_fetch, daemon=True).start()

if __name__ == "__main__":
    app.run(debug=True)
