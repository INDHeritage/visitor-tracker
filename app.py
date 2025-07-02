from flask import Flask, render_template, request, redirect, url_for, session, send_file, flash, render_template_string
import requests
import pandas as pd
import os
from datetime import datetime, timezone
import threading
import time
from dotenv import load_dotenv
from pydrive.auth import GoogleAuth
from pydrive.drive import GoogleDrive
import pytz
import tempfile
import shutil
import hashlib
import base64
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.http import HttpRequest
from googleapiclient.http import MediaIoBaseDownload
from flask_mail import Mail, Message
from apscheduler.schedulers.background import BackgroundScheduler


os.environ['TZ'] = 'Asia/Kolkata'

# Load environment variables
load_dotenv()

def write_client_secrets():
    try:
        client_secrets_b64 = os.getenv("CLIENT_SECRETS_BASE64")
        if not client_secrets_b64:
            raise ValueError("Missing CLIENT_SECRETS_BASE64 environment variable.")

        decoded_json = base64.b64decode(client_secrets_b64).decode("utf-8")
        with open("client_secrets.json", "w") as f:
            f.write(decoded_json)
        print("✅ client_secrets.json decoded and written.")
    except Exception as e:
        print(f"❌ Failed to decode client_secrets.json: {e}")

# Call it right after defining
write_client_secrets()



def init_drive():
    try:
        # Decode base64 service account credentials from environment variable
        base64_creds = os.getenv("GOOGLE_CREDS_BASE64")
        if not base64_creds:
            raise ValueError("Missing GOOGLE_CREDS_BASE64 environment variable.")

        creds_json = base64.b64decode(base64_creds).decode("utf-8")

        # Save to temporary file
        with open("service_account.json", "w") as f:
            f.write(creds_json)

        # Define scopes for accessing Google Drive
        SCOPES = ['https://www.googleapis.com/auth/drive']


        # Load credentials and initialize service
        creds = service_account.Credentials.from_service_account_file(
            "service_account.json", scopes=SCOPES
        )

        # ✅ Set default timeout for all Drive API requests (fix timeout errors)
        HttpRequest.DEFAULT_TIMEOUT = 60  # in seconds (adjust if needed)

        # Initialize the Drive service
        service = build('drive', 'v3', credentials=creds)
        print("✅ Google Drive service initialized.")
        return service

    except Exception as e:
        print(f"❌ Failed to initialize Google Drive: {e}")
        return None

# ✅ Initialize Drive
drive_service = init_drive() # ✅ This must match what you're using in upload_to_drive()



app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "default_key")

# ✅ Add this block here
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.getenv("GMAIL_USER")
app.config['MAIL_PASSWORD'] = os.getenv("GMAIL_PASS")
mail = Mail(app)

USERNAME = os.getenv("FLASK_USERNAME")
PASSWORD = os.getenv("FLASK_PASSWORD")

DATA_URL = "https://heritage-flask-app.onrender.com/admin/visits?password=Shad@!admin123"
EXCEL_ALL_FILE = "visitor_data.xlsx"
DATA_FOLDER = "visitor_logs"  # Folder for date-wise Excel files

USER_DATA_URL = "https://heritage-flask-app.onrender.com/admin/users?password=Shad@!admin123"
EXCEL_USERS_FILE = "user_data.xlsx"


# Ensure log folder exists
os.makedirs(DATA_FOLDER, exist_ok=True)

fetched_data = []
fetched_users = []


@app.route("/test")
def test():
    return "✅ App is working!"

def fetch_data():
    try:
        response = requests.get(DATA_URL)
        response.raise_for_status()
        data = response.json()

        ist = pytz.timezone('Asia/Kolkata')
        cleaned = []
        seen = set()

        for d in data:
            try:
                # Normalize timestamp format
                raw_ts = d['timestamp']
                if 'T' in raw_ts:
                    utc_dt = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
                else:
                    utc_dt = datetime.datetime.strptime(raw_ts, "%Y-%m-%d %H:%M:%S")

                ist_dt = utc_dt.astimezone(ist)
                formatted_ts = ist_dt.strftime('%Y-%m-%d %H:%M:%S')

                # Create a deduplication key (email, ip, timestamp, agent)
                key = (d.get("email", "Guest"), d.get("ip", ""), formatted_ts, d.get("user_agent", ""))
                if key not in seen:
                    seen.add(key)
                    cleaned.append({
                        "email": d.get("email", "Guest"),
                        "ip": d.get("ip", ""),
                        "timestamp": formatted_ts,
                        "user_agent": d.get("user_agent", "")
                    })
            except Exception as e:
                print(f"⚠️ Error parsing timestamp: {e}")
        return cleaned
    except Exception as e:
        print(f"❌ Error fetching data: {e}")
        return []

#Users

def fetch_users():
    try:
        response = requests.get(USER_DATA_URL)
        response.raise_for_status()
        users = response.json()

        cleaned_users = []
        for u in users:
            cleaned_users.append({
                "email": u.get("email", ""),
                "name": u.get("name", ""),
                "phone": u.get("phone", ""),
                "role": u.get("role", ""),
                "created_at": u.get("created_at", "")
            })

        return cleaned_users
    except Exception as e:
        print(f"❌ Error fetching users: {e}")
        return []


def save_users_to_excel(data):
    df = pd.DataFrame(data)
    df.drop_duplicates(inplace=True)
    safe_write_excel(df, EXCEL_USERS_FILE)
    time.sleep(0.2)
    upload_to_drive(EXCEL_USERS_FILE)



@app.route("/download-users")
def download_users():
    if "user" not in session:
        return redirect(url_for("login"))
    if os.path.exists(EXCEL_USERS_FILE):
        return send_file(EXCEL_USERS_FILE, as_attachment=True)
    return "No user file found", 404


def safe_write_excel(df, path):
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
            tmp_path = tmp.name
        df.to_excel(tmp_path, index=False)  # Write after closing the file context
        shutil.move(tmp_path, path)
    except Exception as e:
        print(f"❌ Failed writing Excel safely: {e}")



def is_valid_excel(file_path):
    try:
        pd.read_excel(file_path, nrows=1)
        return True
    except Exception:
        return False



def save_to_excel(data):
    df_new = pd.DataFrame(data)
    df_new.drop_duplicates(inplace=True)

    # Safe full data save
    if os.path.exists(EXCEL_ALL_FILE) and is_valid_excel(EXCEL_ALL_FILE):
        df_existing = pd.read_excel(EXCEL_ALL_FILE)
        combined = pd.concat([df_existing, df_new], ignore_index=True).drop_duplicates()
    else:
        combined = df_new

    safe_write_excel(combined, EXCEL_ALL_FILE)
    time.sleep(0.2)
    upload_to_drive(EXCEL_ALL_FILE)

    # Save date-wise files (collect unique paths first)
    date_file_paths = set()

    for item in data:
        try:
            ts = datetime.strptime(item['timestamp'], "%Y-%m-%d %H:%M:%S")
            y, m, d = ts.strftime("%Y"), ts.strftime("%m"), ts.strftime("%d")
            path = os.path.join(DATA_FOLDER, y, m)
            os.makedirs(path, exist_ok=True)
            file_path = os.path.join(path, f"visitor_{d}.xlsx")  # changed name here

            df_day = pd.DataFrame([item])
            if os.path.exists(file_path) and is_valid_excel(file_path):
                df_existing = pd.read_excel(file_path)
                df_day = pd.concat([df_existing, df_day], ignore_index=True).drop_duplicates()
            safe_write_excel(df_day, file_path)

            date_file_paths.add(file_path)  # collect path for upload
        except Exception as e:
            print(f"❌ Error saving daily log: {e}")

    # ✅ Upload only once per file
    for path in date_file_paths:
        time.sleep(0.2)
        upload_to_drive(path)

def send_daily_report():
    if not os.path.exists(EXCEL_ALL_FILE):
        print("No file to send.")
        return
    try:
        msg = Message(subject="📊 Daily Visitor Report",
                      sender=os.getenv("GMAIL_USER"),
                      recipients=["your_email@example.com"])
        msg.body = "Attached is the visitor report for today."

        with app.open_resource(EXCEL_ALL_FILE) as fp:
            msg.attach("visitor_data.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", fp.read())

        mail.send(msg)
        print("✅ Email sent successfully.")
    except Exception as e:
        print(f"❌ Failed to send email: {e}")

scheduler = BackgroundScheduler()
scheduler.add_job(send_daily_report, 'cron', hour=19, minute=30)  # Sends at 7:30 PM daily
scheduler.start()



def continuous_fetch():
    global fetched_data
    global fetched_users  # 👈 ADD THIS

    last_uploaded = None
    while True:
        print("⏳ Auto-fetching visitor data...")
        data = fetch_data()
        if data and data != fetched_data:
            fetched_data = data
            save_to_excel(fetched_data)

            # ✅ Upload visitors data to Google Drive
            try:
                upload_to_drive(EXCEL_ALL_FILE)
                today = datetime.today().strftime("%Y/%m/%d")
                day_file = os.path.join(DATA_FOLDER, *today.split("/"), f"visitor_{today.split('/')[-1]}.xlsx")
                if os.path.exists(day_file):
                    upload_to_drive(day_file)
            except Exception as e:
                print(f"❌ Upload failed: {e}")

        # ✅ FETCH USERS DATA AND SAVE TO GLOBAL
        users = fetch_users()
        if users:
            fetched_users = users  # 👈 UPDATE GLOBAL VARIABLE HERE
            save_users_to_excel(users)
            try:
                upload_to_drive(EXCEL_USERS_FILE)
            except Exception as e:
                print(f"❌ Failed to upload users Excel: {e}")

        time.sleep(60)

def download_from_drive(file_name):
    try:
        query = f"name='{file_name}' and trashed=false"
        results = drive_service.files().list(q=query, fields="files(id)").execute()
        files = results.get('files', [])
        if not files:
            print(f"⚠️ File not found on Drive: {file_name}")
            return

        file_id = files[0]['id']
        request = drive_service.files().get_media(fileId=file_id)
        fh = io.FileIO(file_name, 'wb')
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            status, done = downloader.next_chunk()
        print(f"⬇️ Downloaded from Drive: {file_name}")
    except Exception as e:
        print(f"❌ Failed to download {file_name}: {e}")


@app.route("/dashboard")
def dashboard():
    if "user" not in session:
        return redirect(url_for("login"))

    # ✅ Sync latest files from Google Drive
    download_from_drive("visitor_data.xlsx")
    download_from_drive("user_data.xlsx")

    # ✅ Load visitors from Excel
    visits = []
    if os.path.exists(EXCEL_ALL_FILE):
        try:
            visits = pd.read_excel(EXCEL_ALL_FILE).to_dict(orient='records')
        except Exception as e:
            print(f"❌ Could not read visitor file: {e}")

    # ✅ Load users from Excel
    users = []
    if os.path.exists(EXCEL_USERS_FILE):
        try:
            users = pd.read_excel(EXCEL_USERS_FILE).to_dict(orient='records')
        except Exception as e:
            print(f"❌ Could not read user file: {e}")

    total_visits = len(visits)
    total_users = len(users)

    # ✅ Device type breakdown
    device_counts = {"Desktop": 0, "Mobile": 0, "Other": 0}
    for visit in visits:
        agent = str(visit.get("user_agent", "")).lower()
        if "mobile" in agent:
            device_counts["Mobile"] += 1
        elif "windows" in agent or "macintosh" in agent or "linux" in agent:
            device_counts["Desktop"] += 1
        else:
            device_counts["Other"] += 1

    today_date = datetime.now(pytz.timezone("Asia/Kolkata")).strftime('%Y-%m-%d')
    return render_template(
        "dashboard.html",
        data=visits,
        total_visits=total_visits,
        total_users=total_users,
        device_counts=device_counts,
        current_time=get_kolkata_time(),
        today_date=today_date  # 👈 ADD THIS
    )



def load_user_excel():
    try:
        if os.path.exists(EXCEL_USERS_FILE):
            return pd.read_excel(EXCEL_USERS_FILE)
    except Exception as e:
        print(f"❌ Could not read user file: {e}")
    return None


def get_kolkata_time():
    india_tz = pytz.timezone("Asia/Kolkata")
    return datetime.now(india_tz).strftime('%Y-%m-%d %H:%M:%S')


@app.route("/", methods=["GET"])
def index():
    if "user" not in session:
        return redirect(url_for("login"))

    # 🧮 Count total visits
    total_visits = len(fetched_data)

    # 📱 Device breakdown
    device_counts = {"Desktop": 0, "Mobile": 0, "Other": 0}
    for visit in fetched_data:
        agent = visit.get("user_agent", "").lower()
        if "mobile" in agent:
            device_counts["Mobile"] += 1
        elif "windows" in agent or "macintosh" in agent or "linux" in agent:
            device_counts["Desktop"] += 1
        else:
            device_counts["Other"] += 1

    # ✅ Convert timestamps to strings (if needed)
    for visit in fetched_data:
        ts = visit.get("timestamp")
        if isinstance(ts, datetime):
            visit["timestamp"] = ts.strftime("%Y-%m-%d %H:%M:%S")

    return render_template("index.html", 
        data=fetched_data,
        total_visits=total_visits,
        total_users=len(fetched_users),
        device_counts=device_counts,
        current_time=get_kolkata_time(),
        today_date=datetime.now().strftime("%Y-%m-%d")  # ✅ Add this
    )



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

FOLDER_ID = "1BrpKgvd2i5LSM7lmRbfb4KTyaC78gwXc"  # Your visitor_logs folder ID

def file_checksum(path):
    with open(path, 'rb') as f:
        return hashlib.md5(f.read()).hexdigest()

last_uploaded_checksums = {}

def upload_to_drive(file_path):
    if drive_service is None:
        print("❌ Google Drive not initialized.")
        return

    try:
        if not os.path.isfile(file_path):
            print(f"❌ File not found: {file_path}")
            return

        file_name = os.path.basename(file_path)
        current_checksum = file_checksum(file_path)

        # Skip if file content hasn't changed
        if last_uploaded_checksums.get(file_name) == current_checksum:
            print(f"🔁 Skipped (unchanged): {file_path}")
            return

        # Search for the file in the specific folder only
        query = f"'{FOLDER_ID}' in parents and name='{file_name}' and trashed=false"
        response = drive_service.files().list(q=query, fields="files(id)").execute()
        files = response.get('files', [])
        media = MediaFileUpload(file_path, resumable=True)

        if files:
            # Update existing file
            file_id = files[0]['id']
            drive_service.files().update(fileId=file_id, media_body=media).execute()
            print(f"♻️ Updated: {file_path} (ID: {file_id})")
        else:
            # Upload new file to specified folder
            uploaded = drive_service.files().create(
                body={'name': file_name, 'parents': [FOLDER_ID]},
                media_body=media,
                fields='id'
            ).execute()
            print(f"✅ Uploaded: {file_path} (ID: {uploaded.get('id')})")

        last_uploaded_checksums[file_name] = current_checksum

    except Exception as e:
        print(f"❌ Upload to Drive failed: {e}")




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
