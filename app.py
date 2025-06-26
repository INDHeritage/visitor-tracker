from flask import Flask, render_template, request, redirect, url_for, session, send_file, flash
import requests
import pandas as pd
import datetime
import os
import threading
import time
from dotenv import load_dotenv


load_dotenv()



app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "default_key")


USERNAME = os.getenv("FLASK_USERNAME")
PASSWORD = os.getenv("FLASK_PASSWORD")

# External data source
DATA_URL = "https://heritage-flask-app.onrender.com/admin/visits?password=Shad@!admin123"
EXCEL_FILE = "visitor_data.xlsx"

# Global storage for visitor data
fetched_data = []

@app.route("/test")
def test():
    return "✅ App is working!"

# Fetch data from API
def fetch_data():
    try:
        response = requests.get(DATA_URL)
        response.raise_for_status()
        data = response.json()

        # Format timestamps
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

# Save to Excel file
def save_to_excel(data):
    df = pd.DataFrame(data)
    df.to_excel(EXCEL_FILE, index=False)

# Background thread to auto-fetch data every 60 seconds
def continuous_fetch():
    global fetched_data
    while True:
        print("⏳ Auto-fetching visitor data...")
        data = fetch_data()
        if data and data != fetched_data:
            fetched_data = data
            save_to_excel(fetched_data)
        time.sleep(60)

# Routes
@app.route("/", methods=["GET"])
def index():
    if "user" not in session:
        return redirect(url_for("login"))
    return render_template("index.html", data=fetched_data)

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

@app.route("/download")
def download_excel():
    if "user" not in session:
        return redirect(url_for("login"))
    if os.path.exists(EXCEL_FILE):
        return send_file(EXCEL_FILE, as_attachment=True)
    return "File not found", 404

# Start background thread always (works in Gunicorn too)
threading.Thread(target=continuous_fetch, daemon=True).start()

if __name__ == "__main__":
    app.run(debug=True)
