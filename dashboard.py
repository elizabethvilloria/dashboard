from flask import Flask, jsonify, render_template, request, session, redirect, url_for, flash
import json
import datetime
from collections import defaultdict
import os
import hashlib

app = Flask(__name__)
app.secret_key = 'etrike-secret-key-change-this'  # Change this to a random string

# Simple authentication (in production, use proper user database)
USERS = {
    'admin': hashlib.sha256('password123'.encode()).hexdigest(),  # Change this password
    'user': hashlib.sha256('etrike2025'.encode()).hexdigest()
}

LOG_DIR = "logs"
HISTORICAL_FILE = "historical_summary.json"

def get_latest_log_time():
    """Finds the timestamp of the most recent log entry."""
    latest_time = None
    latest_timestamp = 0

    if not os.path.exists(LOG_DIR):
        return datetime.datetime.now()

    for year_dir in os.listdir(LOG_DIR):
        year_path = os.path.join(LOG_DIR, year_dir)
        if not os.path.isdir(year_path): continue
        for month_dir in os.listdir(year_path):
            month_path = os.path.join(year_path, month_dir)
            if not os.path.isdir(month_path): continue
            for day_file in os.listdir(month_path):
                if day_file.endswith('.json'):
                    try:
                        day_date = datetime.datetime(int(year_dir), int(month_dir), int(day_file.split('.')[0]))
                        if latest_time is None or day_date.date() > latest_time.date():
                            log_path = os.path.join(month_path, day_file)
                            with open(log_path, 'r') as f:
                                log_data = json.load(f)
                                if not log_data: continue
                                # Find the max timestamp in the latest day's file
                                file_max_ts = max(entry.get('entry_timestamp', 0) for entry in log_data)
                                if file_max_ts > latest_timestamp:
                                    latest_timestamp = file_max_ts
                                    latest_time = day_date

                    except (ValueError, json.JSONDecodeError):
                        continue
    
    if latest_timestamp > 0:
        return datetime.datetime.fromtimestamp(latest_timestamp)
    
    return datetime.datetime.now()


def update_historical_summary():
    """
    Updates the historical summary with current data.
    This function now runs every time and provides real-time historical data.
    """
    today = datetime.datetime.now()
    
    # Ensure historical file exists
    if not os.path.exists(HISTORICAL_FILE):
        with open(HISTORICAL_FILE, 'w') as f:
            json.dump({"daily": [], "weekly": [], "monthly": [], "last_run": today.isoformat()}, f, indent=4)

    # Always update with current data
    daily_data = []
    weekly_data = []
    monthly_data = []
    
    # Get daily data for the last 7 days
    for i in range(7):
        check_date = today.date() - datetime.timedelta(days=i)
        log_path = os.path.join(LOG_DIR, str(check_date.year), str(check_date.month), f"{check_date.day}.json")
        if os.path.exists(log_path):
            try:
                with open(log_path, 'r') as log_file:
                    log_data = json.load(log_file)
                    daily_total = len(log_data)
                    if daily_total > 0:
                        daily_data.append({
                            "date": check_date.strftime("%Y-%m-%d"),
                            "total": daily_total
                        })
            except (json.JSONDecodeError, FileNotFoundError):
                continue
    
    # Get weekly data (current week and last week)
    for week_offset in range(2):
        week_start = today.date() - datetime.timedelta(days=today.weekday() + (week_offset * 7))
        weekly_total = 0
        for i in range(7):
            check_date = week_start + datetime.timedelta(days=i)
            log_path = os.path.join(LOG_DIR, str(check_date.year), str(check_date.month), f"{check_date.day}.json")
            if os.path.exists(log_path):
                try:
                    with open(log_path, 'r') as log_file:
                        log_data = json.load(log_file)
                        weekly_total += len(log_data)
                except (json.JSONDecodeError, FileNotFoundError):
                    continue
        
        if weekly_total > 0:
            weekly_data.append({
                "week_of": week_start.strftime("%Y-%m-%d"),
                "total": weekly_total
            })
    
    # Get monthly data (current month and last month)
    for month_offset in range(2):
        if month_offset == 0:
            # Current month
            month_start = today.replace(day=1)
            month_total = 0
            current_day = month_start
            while current_day.month == month_start.month:
                log_path = os.path.join(LOG_DIR, str(current_day.year), str(current_day.month), f"{current_day.day}.json")
                if os.path.exists(log_path):
                    try:
                        with open(log_path, 'r') as log_file:
                            log_data = json.load(log_file)
                            month_total += len(log_data)
                    except (json.JSONDecodeError, FileNotFoundError):
                        pass
                current_day += datetime.timedelta(days=1)
            
            if month_total > 0:
                monthly_data.append({
                    "month_of": month_start.strftime("%Y-%m"),
                    "total": month_total
                })
        else:
            # Last month
            last_month = today.replace(day=1) - datetime.timedelta(days=1)
            month_start = last_month.replace(day=1)
            month_total = 0
            current_day = month_start
            while current_day.month == month_start.month:
                log_path = os.path.join(LOG_DIR, str(current_day.year), str(current_day.month), f"{current_day.day}.json")
                if os.path.exists(log_path):
                    try:
                        with open(log_path, 'r') as log_file:
                            log_data = json.load(log_file)
                            month_total += len(log_data)
                    except (json.JSONDecodeError, FileNotFoundError):
                        pass
                current_day += datetime.timedelta(days=1)
            
            if month_total > 0:
                monthly_data.append({
                    "month_of": month_start.strftime("%Y-%m"),
                    "total": month_total
                })
    
    # Save updated data
    summary_data = {
        "daily": daily_data,
        "weekly": weekly_data,
        "monthly": monthly_data,
        "last_run": today.isoformat()
    }
    
    with open(HISTORICAL_FILE, 'w') as f:
        json.dump(summary_data, f, indent=4)


def get_passenger_counts():
    """Calculates passenger counts for different time periods."""
    now = get_latest_log_time()
    counts = defaultdict(int) # Simple defaultdict for totals

    # Hourly and Daily
    today_log_path = os.path.join(LOG_DIR, str(now.year), str(now.month), f"{now.day}.json")
    if os.path.exists(today_log_path):
        with open(today_log_path, 'r') as f:
            try:
                log_data = json.load(f)
                # Daily count
                counts['daily'] = len(log_data)
                
                # Hourly count (rolling)
                hourly_count = 0
                for entry in log_data:
                    entry_time = datetime.datetime.fromtimestamp(entry['entry_timestamp'])
                    if (now - entry_time).total_seconds() <= 3600:
                        hourly_count += 1
                counts['hourly'] = hourly_count
                        
            except json.JSONDecodeError:
                pass

    # Weekly
    start_of_week = now - datetime.timedelta(days=now.weekday())
    weekly_total = 0
    for i in range(7):
        current_day = start_of_week + datetime.timedelta(days=i)
        week_log_path = os.path.join(LOG_DIR, str(current_day.year), str(current_day.month), f"{current_day.day}.json")
        if os.path.exists(week_log_path):
            with open(week_log_path, 'r') as f:
                try:
                    log_data = json.load(f)
                    weekly_total += len(log_data)
                except json.JSONDecodeError:
                    pass
    counts['weekly'] = weekly_total
    
    # Monthly
    month_log_dir = os.path.join(LOG_DIR, str(now.year), str(now.month))
    monthly_total = 0
    if os.path.exists(month_log_dir):
        for day_file in os.listdir(month_log_dir):
            if day_file.endswith('.json'):
                day_path = os.path.join(month_log_dir, day_file)
                with open(day_path, 'r') as f:
                    try:
                        log_data = json.load(f)
                        monthly_total += len(log_data)
                    except json.JSONDecodeError:
                        pass
    counts['monthly'] = monthly_total

    return dict(counts)

def login_required(f):
    """Decorator to require login for routes"""
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        password_hash = hashlib.sha256(password.encode()).hexdigest()
        
        if username in USERS and USERS[username] == password_hash:
            session['logged_in'] = True
            session['username'] = username
            return redirect(url_for('index'))
        else:
            flash('Invalid credentials')
    
    return '''
    <!DOCTYPE html>
    <html>
    <head>
        <title>E-Trike Login</title>
        <style>
            body { font-family: Arial; background: linear-gradient(135deg, #667eea, #764ba2); 
                   display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; }
            .login-box { background: white; padding: 2rem; border-radius: 10px; box-shadow: 0 4px 15px rgba(0,0,0,0.2); }
            input { width: 100%; padding: 0.5rem; margin: 0.5rem 0; border: 1px solid #ddd; border-radius: 5px; }
            button { width: 100%; padding: 0.75rem; background: #667eea; color: white; border: none; border-radius: 5px; cursor: pointer; }
            button:hover { background: #5a6fd8; }
            .error { color: red; margin: 0.5rem 0; }
        </style>
    </head>
    <body>
        <div class="login-box">
            <h2>E-Trike Dashboard Login</h2>
            {% with messages = get_flashed_messages() %}
                {% if messages %}
                    {% for message in messages %}
                        <div class="error">{{ message }}</div>
                    {% endfor %}
                {% endif %}
            {% endwith %}
            <form method="POST">
                <input type="text" name="username" placeholder="Username" required>
                <input type="password" name="password" placeholder="Password" required>
                <button type="submit">Login</button>
            </form>
            <p><small>Default: admin/password123 or user/etrike2025</small></p>
        </div>
    </body>
    </html>
    '''

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/')
@login_required
def index():
    update_historical_summary()
    return render_template('index.html')

@app.route('/data')
@login_required
def data():
    return jsonify(get_passenger_counts())

@app.route('/historical-data')
@login_required
def historical_data():
    # Always update historical data when requested
    update_historical_summary()
    if not os.path.exists(HISTORICAL_FILE):
        return jsonify({"daily": [], "weekly": [], "monthly": []})
    with open(HISTORICAL_FILE, 'r') as f:
        return jsonify(json.load(f))

@app.route('/passenger-details')
@login_required
def passenger_details():
    """Get individual passenger records for a specific date."""
    date = request.args.get('date')
    period = request.args.get('period', 'daily')
    
    if not date:
        return jsonify({'error': 'Date parameter required'}), 400
    
    try:
        # Parse the date
        if period == 'daily':
            target_date = datetime.datetime.strptime(date, '%Y-%m-%d')
            log_file = os.path.join(LOG_DIR, str(target_date.year), str(target_date.month), f"{target_date.day}.json")
            
            if os.path.exists(log_file):
                with open(log_file, 'r') as f:
                    passengers = json.load(f)
                    return jsonify({'passengers': passengers})
            else:
                return jsonify({'passengers': []})
                
        elif period == 'weekly':
            # For weekly, we need to get all days in that week
            target_date = datetime.datetime.strptime(date, '%Y-%m-%d')
            start_of_week = target_date - datetime.timedelta(days=target_date.weekday())
            all_passengers = []
            
            for i in range(7):
                day = start_of_week + datetime.timedelta(days=i)
                log_file = os.path.join(LOG_DIR, str(day.year), str(day.month), f"{day.day}.json")
                if os.path.exists(log_file):
                    with open(log_file, 'r') as f:
                        day_passengers = json.load(f)
                        all_passengers.extend(day_passengers)
            
            return jsonify({'passengers': all_passengers})
            
        elif period == 'monthly':
            # For monthly, get all days in that month
            target_date = datetime.datetime.strptime(date, '%Y-%m')
            month_dir = os.path.join(LOG_DIR, str(target_date.year), str(target_date.month))
            all_passengers = []
            
            if os.path.exists(month_dir):
                for day_file in os.listdir(month_dir):
                    if day_file.endswith('.json'):
                        day_path = os.path.join(month_dir, day_file)
                        with open(day_path, 'r') as f:
                            day_passengers = json.load(f)
                            all_passengers.extend(day_passengers)
            
            return jsonify({'passengers': all_passengers})
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    
    return jsonify({'passengers': []})

@app.route('/upload-data', methods=['POST'])
def upload_data():
    """Receive data package from Raspberry Pi"""
    try:
        if 'data_package' not in request.files:
            return jsonify({'error': 'No data package provided'}), 400
        
        file = request.files['data_package']
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        if file and file.filename.endswith('.zip'):
            # Save the uploaded zip file temporarily
            import tempfile
            import zipfile
            
            with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as temp_file:
                file.save(temp_file.name)
                
                # Extract the zip file
                with zipfile.ZipFile(temp_file.name, 'r') as zip_ref:
                    # Extract all files to current directory
                    zip_ref.extractall('.')
                
                # Clean up temp file
                os.remove(temp_file.name)
            
            print(f"✅ Data package received and extracted at {datetime.datetime.now()}")
            return jsonify({'message': 'Data uploaded successfully'}), 200
        
        return jsonify({'error': 'Invalid file format'}), 400
        
    except Exception as e:
        print(f"❌ Upload error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/shutdown', methods=['POST'])
def shutdown():
    shutdown_server = request.environ.get('werkzeug.server.shutdown')
    if shutdown_server is None:
        raise RuntimeError('Not running with the Werkzeug Server')
    shutdown_server()
    return 'Server shutting down...'

if __name__ == '__main__':
    import ssl
    import os
    
    # Check if SSL certificates exist
    cert_path = '/etc/letsencrypt/live/etrikedashboard.com/fullchain.pem'
    key_path = '/etc/letsencrypt/live/etrikedashboard.com/privkey.pem'
    
    if os.path.exists(cert_path) and os.path.exists(key_path):
        # Run with HTTPS
        context = ssl.SSLContext(ssl.PROTOCOL_TLSv1_2)
        context.load_cert_chain(cert_path, key_path)
        print("Dashboard is running on https://etrikedashboard.com:5001/")
        app.run(debug=False, host='0.0.0.0', port=5001, ssl_context=context)
    else:
        # Fall back to HTTP
        print("Dashboard is running on http://0.0.0.0:5001/")
        print("For HTTPS, install SSL certificates with: sudo certbot --nginx -d etrikedashboard.com")
        app.run(debug=True, host='0.0.0.0', port=5001) 