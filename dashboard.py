
from flask import Flask, jsonify, render_template, request, session, redirect, url_for, flash, send_file
from flask_socketio import SocketIO, emit
import json
import datetime
from collections import defaultdict
import os
import hashlib
from reportlab.lib.pagesizes import letter, A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import inch
import io
import threading
import time

app = Flask(__name__)
app.secret_key = 'etrike-secret-key-change-this'  # Change this to a random string
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# Simple authentication (in production, use proper user database)
USERS = {
    'admin': hashlib.sha256('1010'.encode()).hexdigest()
}

LOG_DIR = "logs"
HISTORICAL_FILE = "historical_summary.json"

# Global variable to track when Pi devices last sent heartbeat
last_pi_heartbeat_time = 0

# Global variable to control the background thread
gps_broadcast_thread = None
stop_broadcast = False

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
        # Convert timestamp to local time
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
    
    # Get weekly data for the last 4 weeks
    for week_offset in range(4):
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
    
    # Get monthly data for the last 6 months
    for month_offset in range(6):
        # Calculate the month start date for each month offset
        current_month = today.month
        current_year = today.year
        
        # Calculate target month and year
        target_month = current_month - month_offset
        target_year = current_year
        
        # Handle year rollover
        while target_month <= 0:
            target_month += 12
            target_year -= 1
        
        month_start = datetime.datetime(target_year, target_month, 1)
        
        month_total = 0
        current_day = month_start
        while current_day.month == month_start.month and current_day.year == month_start.year:
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
                    # Convert timestamp to local time
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

def broadcast_gps_updates():
    """Background thread to broadcast GPS updates via WebSocket"""
    global stop_broadcast
    while not stop_broadcast:
        try:
            # Get current vehicle locations
            vehicles = get_vehicle_locations_data()
            if vehicles:
                # Broadcast to all connected clients
                socketio.emit('gps_update', {'vehicles': vehicles}, namespace='/')
            time.sleep(1)  # Update every 1 second
        except Exception as e:
            print(f"GPS broadcast error: {e}")
            time.sleep(5)  # Wait 5 seconds on error

def get_vehicle_locations_data():
    """Get vehicle locations data (extracted from the route function)"""
    try:
        gps_log_path = os.path.join(LOG_DIR, 'gps_data.json')
        if not os.path.exists(gps_log_path):
            return []

        with open(gps_log_path, 'r') as f:
            gps_data = json.load(f)

        # Get latest location for each Pi device
        latest_locations = {}
        for entry in gps_data:
            pi_id = entry['pi_id']
            entry_time = datetime.datetime.fromisoformat(entry['received_at'])
            
            if pi_id not in latest_locations or entry_time > datetime.datetime.fromisoformat(latest_locations[pi_id]['received_at']):
                latest_locations[pi_id] = entry

        # Convert to vehicle format
        vehicles = []
        pi_assignments = load_pi_assignments()
        
        for pi_id, location in latest_locations.items():
            assignment = pi_assignments.get(pi_id, {})
            # Check if vehicle is offline (no data for 5 minutes)
            pi_timestamp = location.get('timestamp', 0)
            if pi_timestamp:
                # Convert UTC timestamp to CET timezone
                import pytz
                utc_time = datetime.datetime.fromtimestamp(pi_timestamp, tz=pytz.UTC)
                last_update = utc_time.astimezone(pytz.timezone('Europe/Madrid'))
                time_since_update = (datetime.datetime.now(pytz.timezone('Europe/Madrid')) - last_update).total_seconds()
            else:
                last_update = datetime.datetime.fromisoformat(location['received_at'])
                time_since_update = (datetime.datetime.now() - last_update).total_seconds()
            
            is_offline = time_since_update > 300  # 5 minutes = 300 seconds
            is_parked = False
            if not is_offline and location.get('speed', 0) == 0:
                is_parked = time_since_update > 600  # 10 minutes = 600 seconds
            
            if is_offline:
                status = 'offline'
            elif is_parked:
                status = 'parked'
            else:
                status = 'active'
            
            if pi_timestamp:
                last_update_str = last_update.isoformat()
            else:
                last_update_str = location['received_at']
            
            vehicle = {
                'id': assignment.get('etrike_id', f'pi-{pi_id}'),
                'name': f"E-Trike {assignment.get('etrike_id', pi_id)}",
                'lat': location['latitude'],
                'lng': location['longitude'],
                'speed': location.get('speed', 0),
                'heading': location.get('heading', 0),
                'status': status,
                'passengers': 0,
                'toda': assignment.get('toda_id', ''),
                'pi': pi_id,
                'last_update': last_update_str
            }
            vehicles.append(vehicle)
        
        return vehicles
        
    except Exception as e:
        print(f"Vehicle locations error: {e}")
        return []

@socketio.on('connect')
def handle_connect():
    """Handle client connection"""
    print(f'Client connected: {request.sid}')
    # Start broadcast thread if not already running
    global gps_broadcast_thread, stop_broadcast
    if gps_broadcast_thread is None or not gps_broadcast_thread.is_alive():
        stop_broadcast = False
        gps_broadcast_thread = threading.Thread(target=broadcast_gps_updates, daemon=True)
        gps_broadcast_thread.start()
        print("GPS broadcast thread started")

@socketio.on('disconnect')
def handle_disconnect():
    """Handle client disconnection"""
    print(f'Client disconnected: {request.sid}')

@socketio.on('request_gps_update')
def handle_gps_request():
    """Handle client request for immediate GPS update"""
    vehicles = get_vehicle_locations_data()
    emit('gps_update', {'vehicles': vehicles})

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
        <title>E-Trike Dashboard Login</title>
        <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css" rel="stylesheet">
        <style>
            body { 
                font-family: 'Segoe UI', Arial, sans-serif; 
                background-image: url('/static/etrike-background.png');
                background-size: cover;
                background-position: center;
                background-repeat: no-repeat;
                background-attachment: fixed;
                display: flex; 
                justify-content: flex-end; 
                align-items: center; 
                height: 100vh; 
                margin: 0; 
                position: relative;
            }
            

            
            .login-box { 
                background: rgba(255, 255, 255, 0.95); 
                padding: 2rem 2rem; 
                border-radius: 10px; 
                box-shadow: 0 15px 35px rgba(0,0,0,0.3); 
                backdrop-filter: blur(10px);
                border: 1px solid rgba(255, 255, 255, 0.3);
                min-width: 300px;
                max-width: 350px;
                position: relative;
                z-index: 2;
                margin-right: 15rem;
            }
            .logo {
                text-align: center;
                margin-bottom: 1.5rem;
            }
            .logo h1 {
                color: #059669;
                font-size: 1.6rem;
                font-weight: 700;
                margin: 0;
                text-shadow: 0 2px 4px rgba(0,0,0,0.1);
            }
            .logo p {
                color: #0d9488;
                font-size: 0.85rem;
                margin: 0.3rem 0 0 0;
                font-weight: 500;
            }
            .input-group {
                position: relative;
                margin: 0.6rem 0;
            }
            
            input { 
                width: 100%; 
                padding: 0.8rem; 
                padding-right: 3.5rem;
                border: 2px solid #e5e7eb; 
                border-radius: 10px; 
                font-size: 1rem;
                transition: border-color 0.3s ease;
                box-sizing: border-box;
            }
            input:focus {
                outline: none;
                border-color: #059669;
                box-shadow: 0 0 0 3px rgba(5, 150, 105, 0.1);
            }
            
            .password-toggle {
                position: absolute;
                right: 0.8rem;
                top: 50%;
                transform: translateY(-50%);
                background: none;
                border: none;
                cursor: pointer;
                color: #374151;
                font-size: 1rem;
                padding: 0.2rem;
                z-index: 10;
                display: none;
                align-items: center;
                justify-content: center;
                width: 20px;
                height: 20px;
                margin-top: -1px;
            }
            
            .password-toggle.show {
                display: flex;
            }
            
            .password-toggle:hover,
            .password-toggle:focus,
            .password-toggle:active {
                outline: none;
                color: #374151;
                background: none;
                transform: translateY(-50%);
            }
            button { 
                width: 100%; 
                padding: 0.8rem; 
                background: linear-gradient(135deg, #059669, #0d9488); 
                color: white; 
                border: none; 
                border-radius: 10px; 
                cursor: pointer; 
                font-size: 1rem;
                font-weight: 600;
                margin-top: 0.8rem;
                transition: all 0.3s ease;
            }
            button:hover { 
                background: linear-gradient(135deg, #047857, #0f766e); 
                transform: translateY(-2px);
                box-shadow: 0 8px 25px rgba(5, 150, 105, 0.3);
            }
            .error { 
                color: #dc2626; 
                margin: 1rem 0; 
                padding: 0.75rem;
                background: rgba(220, 38, 38, 0.1);
                border-radius: 8px;
                text-align: center;
                font-weight: 500;
            }
        </style>
    </head>
    <body>
        <div class="login-box">
            <div class="logo">
                <h1>E-Trike</h1>
                <p>Passenger Dashboard</p>
            </div>
            <form method="POST" id="loginForm">
                <input type="text" name="username" placeholder="Username" required>
                <div class="input-group">
                    <input type="password" name="password" id="password" placeholder="Password" required>
                    <button type="button" class="password-toggle" id="passwordToggle" onclick="togglePassword()">
                        <i class="fas fa-eye" id="eyeIcon"></i>
                    </button>
                </div>
                <button type="submit">Log In</button>
                <div class="error" id="errorMessage" style="display: none;"></div>
            </form>
        </div>
        
        <script>
            // Password visibility toggle function
            function togglePassword() {
                const passwordInput = document.getElementById('password');
                const eyeIcon = document.getElementById('eyeIcon');
                
                if (passwordInput.type === 'password') {
                    passwordInput.type = 'text';
                    eyeIcon.className = 'fas fa-eye-slash';
                } else {
                    passwordInput.type = 'password';
                    eyeIcon.className = 'fas fa-eye';
                }
            }
            
            // Show/hide password toggle based on input content
            function togglePasswordVisibility() {
                const passwordInput = document.getElementById('password');
                const passwordToggle = document.getElementById('passwordToggle');
                
                if (passwordInput.value.length > 0) {
                    passwordToggle.classList.add('show');
                } else {
                    passwordToggle.classList.remove('show');
                }
            }
            
            // Add event listeners when page loads
            document.addEventListener('DOMContentLoaded', function() {
                const passwordInput = document.getElementById('password');
                passwordInput.addEventListener('input', togglePasswordVisibility);
                passwordInput.addEventListener('keyup', togglePasswordVisibility);
                passwordInput.addEventListener('paste', function() {
                    // Small delay to allow paste content to be processed
                    setTimeout(togglePasswordVisibility, 10);
                });
            });
            
            document.getElementById('loginForm').addEventListener('submit', function(e) {
                e.preventDefault();
                
                // Clear any previous error messages
                document.getElementById('errorMessage').style.display = 'none';
                
                // Get form data
                const formData = new FormData(this);
                
                // Submit form via fetch to handle errors
                fetch('/login', {
                    method: 'POST',
                    body: formData
                })
                .then(response => {
                    if (response.redirected) {
                        // Successful login, redirect
                        window.location.href = response.url;
                    } else {
                        // Check if there's an error response
                        return response.text();
                    }
                })
                .then(html => {
                    if (html && html.includes('Invalid credentials')) {
                        // Show error message
                        const errorDiv = document.getElementById('errorMessage');
                        errorDiv.textContent = 'Invalid username or password. Please try again.';
                        errorDiv.style.display = 'block';
                    }
                })
                .catch(error => {
                    console.error('Error:', error);
                });
            });
        </script>
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
    # Set default city if not already set
    if 'city' not in session:
        session['city'] = 'manila'
    
    update_historical_summary()
    return render_template('index.html')

@app.route('/gps-map')
@login_required
def gps_map():
    # Set default city if not already set
    if 'city' not in session:
        session['city'] = 'manila'
    
    return render_template('gps_map.html')

@app.route('/options')
@login_required
def options():
    # Set default city if not already set
    if 'city' not in session:
        session['city'] = 'manila'
    
    return render_template('options.html')


@app.route('/clear-selection', methods=['POST'])
@login_required
def clear_selection():
    # Clear selection from session
    session.pop('city', None)
    session.pop('toda', None)
    session.pop('etrike', None)
    return jsonify({'success': True})

@app.route('/change-city', methods=['POST'])
@login_required
def change_city():
    """Change the selected city"""
    data = request.get_json()
    city = data.get('city')
    
    if city:
        session['city'] = city
        # Clear TODA and e-trike when city changes
        session.pop('toda', None)
        session.pop('etrike', None)
        return jsonify({'success': True})
    
    return jsonify({'success': False, 'error': 'No city provided'})

@app.route('/get-todas')
@login_required
def get_todas():
    """Get available TODAs for the selected city"""
    city = request.args.get('city') or session.get('city', 'manila')
    
    # Mock data - in real implementation, this would come from a database
    if city == 'manila':
        todas = [
            {'id': 'bltmpc', 'name': 'BLTMPC', 'full_name': 'Barangay Laging Tapat Motorcycle and Pedicab Cooperative'},
            {'id': 'mtmpc', 'name': 'MTMPC', 'full_name': 'Manila Tricycle and Motorcycle Operators Cooperative'},
            {'id': 'stmpc', 'name': 'STMPC', 'full_name': 'San Miguel Tricycle and Motorcycle Operators Cooperative'}
        ]
    elif city == 'quezon_city':
        todas = [
            {'id': 'qctmpc', 'name': 'QCTMPC', 'full_name': 'Quezon City Tricycle and Motorcycle Operators Cooperative'},
            {'id': 'qctoda', 'name': 'QCTODA', 'full_name': 'Quezon City TODA Association'},
            {'id': 'qctrans', 'name': 'QCTRANS', 'full_name': 'Quezon City Transport Cooperative'}
        ]
    elif city == 'muntinlupa':
        todas = [
            {'id': 'mntmpc', 'name': 'MNTMPC', 'full_name': 'Muntinlupa Tricycle and Motorcycle Operators Cooperative'},
            {'id': 'mntoda', 'name': 'MNTODA', 'full_name': 'Muntinlupa TODA Association'},
            {'id': 'mntrans', 'name': 'MNTRANS', 'full_name': 'Muntinlupa Transport Cooperative'}
        ]
    elif city == 'pasay':
        todas = [
            {'id': 'pstmpc', 'name': 'PSTMPC', 'full_name': 'Pasay Tricycle and Motorcycle Operators Cooperative'},
            {'id': 'pstoda', 'name': 'PSTODA', 'full_name': 'Pasay TODA Association'},
            {'id': 'pstrans', 'name': 'PSTRANS', 'full_name': 'Pasay Transport Cooperative'}
        ]
    elif city == 'lipa':
        todas = [
            {'id': 'lptmpc', 'name': 'LPTMPC', 'full_name': 'Lipa Tricycle and Motorcycle Operators Cooperative'},
            {'id': 'lptoda', 'name': 'LPTODA', 'full_name': 'Lipa TODA Association'},
            {'id': 'lptrans', 'name': 'LPTRANS', 'full_name': 'Lipa Transport Cooperative'}
        ]
    else:
        todas = []
    
    return jsonify({'todas': todas})

@app.route('/get-etrikes')
@login_required
def get_etrikes():
    """Get available e-trikes for the selected TODA"""
    toda = request.args.get('toda', '')
    city = session.get('city', 'manila')
    
    if not toda:
        return jsonify({'etikes': []})
    
    # Mock data - in real implementation, this would come from a database
    # All e-trikes removed - no mock data
    etikes = []
    
    return jsonify({'etikes': etikes})

# Pi Registration System
@app.route('/pi-registration')
@login_required
def pi_registration():
    """Pi registration page"""
    return render_template('pi_registration.html')

@app.route('/register-pi', methods=['POST'])
@login_required
def register_pi():
    """Register a new Pi device"""
    pi_id = request.form.get('pi_id')
    toda_id = request.form.get('toda_id')
    etrike_id = request.form.get('etrike_id')
    city = request.form.get('city')
    
    if not all([pi_id, toda_id, etrike_id, city]):
        return jsonify({'success': False, 'message': 'All fields are required'})
    
    # Store Pi registration in a simple JSON file
    pi_assignments = load_pi_assignments()
    pi_assignments[pi_id] = {
        'toda_id': toda_id,
        'etrike_id': etrike_id,
        'city': city,
        'status': 'active',
        'registered_at': datetime.datetime.now().isoformat(),
        'last_seen': None
    }
    save_pi_assignments(pi_assignments)
    
    return jsonify({
        'success': True, 
        'message': f'Pi {pi_id} registered successfully for {toda_id.upper()} - {etrike_id}'
    })

@app.route('/get-pi-assignments')
@login_required
def get_pi_assignments():
    """Get all Pi device assignments"""
    return jsonify(load_pi_assignments())

@app.route('/remove-pi', methods=['POST'])
@login_required
def remove_pi():
    """Remove a Pi device"""
    try:
        data = request.get_json()
        pi_id = data.get('pi_id')
        
        if not pi_id:
            return jsonify({'success': False, 'message': 'Pi ID is required'})
        
        pi_assignments = load_pi_assignments()
        
        if pi_id not in pi_assignments:
            return jsonify({'success': False, 'message': 'Pi device not found'})
        
        # Remove the Pi device
        del pi_assignments[pi_id]
        save_pi_assignments(pi_assignments)
        
        return jsonify({
            'success': True, 
            'message': f'Pi device {pi_id} has been removed successfully'
        })
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/get-filtered-data')
@login_required
def get_filtered_data_route():
    """Get filtered passenger data based on selection"""
    toda_id = request.args.get('toda_id', '')
    etrike_id = request.args.get('etrike_id', '')
    pi_id = request.args.get('pi_id', '')
    
    # Convert empty strings to None for filtering
    if not toda_id:
        toda_id = None
    if not etrike_id:
        etrike_id = None
    if not pi_id:
        pi_id = None
    
    filtered_data = get_filtered_data(toda_id, etrike_id, pi_id)
    
    # Count total passengers
    total_count = len(filtered_data)
    
    return jsonify({
        'total': total_count,
        'filtered_data': filtered_data
    })

def load_pi_assignments():
    """Load Pi assignments from JSON file"""
    try:
        if os.path.exists('pi_assignments.json'):
            with open('pi_assignments.json', 'r') as f:
                return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        pass
    return {}

def save_pi_assignments(assignments):
    """Save Pi assignments to JSON file"""
    with open('pi_assignments.json', 'w') as f:
        json.dump(assignments, f, indent=4)

def get_filtered_data(toda_id=None, etrike_id=None, pi_id=None):
    """
    Get filtered passenger data based on TODA, E-Trike, or Pi device selection.
    Returns data that matches the filter criteria.
    """
    today = datetime.datetime.now()
    filtered_data = []
    
    # Get data for the last 7 days
    for i in range(7):
        check_date = today.date() - datetime.timedelta(days=i)
        log_path = os.path.join(LOG_DIR, str(check_date.year), str(check_date.month), f"{check_date.day}.json")
        if os.path.exists(log_path):
            try:
                with open(log_path, 'r') as f:
                    log_data = json.load(f)
                    for entry in log_data:
                        # Check if entry matches filter criteria
                        matches_filter = True
                        
                        if toda_id and entry.get('toda_id') != toda_id:
                            matches_filter = False
                        if etrike_id and entry.get('etrike_id') != etrike_id:
                            matches_filter = False
                        if pi_id and entry.get('pi_id') != pi_id:
                            matches_filter = False
                        
                        if matches_filter:
                            filtered_data.append(entry)
            except (json.JSONDecodeError, FileNotFoundError):
                continue
    
    return filtered_data

@app.route('/data')
@login_required
def data():
    return jsonify(get_passenger_counts())

@app.route('/pi-heartbeat', methods=['POST'])
def pi_heartbeat():
    """Pi device heartbeat to maintain connection status"""
    global last_pi_heartbeat_time
    last_pi_heartbeat_time = datetime.datetime.now().timestamp()
    return jsonify({'status': 'ok'})

@app.route('/pi-live-status')
@login_required
def pi_live_status():
    """Check if Pi devices are connected (heartbeat within last 15 seconds)"""
    global last_pi_heartbeat_time
    current_time = datetime.datetime.now().timestamp()
    
    # Consider live if Pi devices sent heartbeat recently
    is_live = (current_time - last_pi_heartbeat_time) <= 15  # 15 seconds threshold
    
    return jsonify({'is_live': is_live, 'last_heartbeat': last_pi_heartbeat_time})

@app.route('/gps-data', methods=['POST'])
def receive_gps_data():
    """Receive GPS data from Pi devices"""
    try:
        data = request.get_json()
        
        # Validate required fields
        required_fields = ['pi_id', 'latitude', 'longitude', 'timestamp']
        for field in required_fields:
            if field not in data:
                return jsonify({'error': f'Missing required field: {field}'}), 400
        
        # Store GPS data
        gps_entry = {
            'pi_id': data['pi_id'],
            'latitude': float(data['latitude']),
            'longitude': float(data['longitude']),
            'speed': float(data.get('speed', 0)),
            'heading': float(data.get('heading', 0)),
            'timestamp': data['timestamp'],
            'received_at': datetime.datetime.now().isoformat()
        }
        
        # Save to GPS log file
        gps_log_path = os.path.join(LOG_DIR, 'gps_data.json')
        gps_data = []
        
        if os.path.exists(gps_log_path):
            try:
                with open(gps_log_path, 'r') as f:
                    gps_data = json.load(f)
            except (json.JSONDecodeError, FileNotFoundError):
                gps_data = []
        
        gps_data.append(gps_entry)
        
        # Keep only last 1000 entries to prevent file from growing too large
        if len(gps_data) > 1000:
            gps_data = gps_data[-1000:]
        
        with open(gps_log_path, 'w') as f:
            json.dump(gps_data, f, indent=2)
        
        # Update Pi heartbeat
        global last_pi_heartbeat_time
        last_pi_heartbeat_time = datetime.datetime.now().timestamp()
        
        return jsonify({'status': 'success', 'message': 'GPS data received'})
        
    except Exception as e:
        print(f"GPS data error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/vehicle-locations')
@login_required
def get_vehicle_locations():
    """Get current vehicle locations for map display"""
    try:
        gps_log_path = os.path.join(LOG_DIR, 'gps_data.json')
        if not os.path.exists(gps_log_path):
            return jsonify({'vehicles': []})
        
        with open(gps_log_path, 'r') as f:
            gps_data = json.load(f)
        
        # Get latest location for each Pi device
        latest_locations = {}
        for entry in gps_data:
            pi_id = entry['pi_id']
            entry_time = datetime.datetime.fromisoformat(entry['received_at'])
            
            if pi_id not in latest_locations or entry_time > datetime.datetime.fromisoformat(latest_locations[pi_id]['received_at']):
                latest_locations[pi_id] = entry
        
        # Convert to vehicle format
        vehicles = []
        pi_assignments = load_pi_assignments()
        
        for pi_id, location in latest_locations.items():
            assignment = pi_assignments.get(pi_id, {})
            # Check if vehicle is offline (no data for 5 minutes)
            # Use Pi's timestamp for offline detection to avoid timezone issues
            pi_timestamp = location.get('timestamp', 0)
            if pi_timestamp:
                # Convert UTC timestamp to CET timezone
                import pytz
                utc_time = datetime.datetime.fromtimestamp(pi_timestamp, tz=pytz.UTC)
                last_update = utc_time.astimezone(pytz.timezone('Europe/Madrid'))
                time_since_update = (datetime.datetime.now(pytz.timezone('Europe/Madrid')) - last_update).total_seconds()
            else:
                # Fallback to received_at if no Pi timestamp
                last_update = datetime.datetime.fromisoformat(location['received_at'])
                time_since_update = (datetime.datetime.now() - last_update).total_seconds()
            
            is_offline = time_since_update > 300  # 5 minutes = 300 seconds
            
            # Check if vehicle is parked (stationary for 10+ minutes)
            # We'll determine this by checking if the last position is the same as current
            # For now, we'll use a simple heuristic: if speed is 0 and not offline, consider it parked
            is_parked = False
            if not is_offline and location.get('speed', 0) == 0:
                # Check if we have previous position data to compare
                # This is a simplified check - in a real system you'd compare coordinates
                is_parked = time_since_update > 600  # 10 minutes = 600 seconds
            
            # Determine status
            if is_offline:
                status = 'offline'
            elif is_parked:
                status = 'parked'
            else:
                status = 'active'
            
            # Use the same timestamp for display
            if pi_timestamp:
                last_update_str = last_update.isoformat()
            else:
                last_update_str = location['received_at']
            
            vehicle = {
                'id': assignment.get('etrike_id', f'pi-{pi_id}'),
                'name': f"E-Trike {assignment.get('etrike_id', pi_id)}",
                'lat': location['latitude'],
                'lng': location['longitude'],
                'speed': location.get('speed', 0),
                'heading': location.get('heading', 0),
                'status': status,
                'passengers': 0,  # This would come from passenger data
                'toda': assignment.get('toda_id', ''),
                'pi': pi_id,
                'last_update': last_update_str
            }
            vehicles.append(vehicle)
        
        return jsonify({'vehicles': vehicles})
        
    except Exception as e:
        print(f"Vehicle locations error: {e}")
        return jsonify({'vehicles': []})

@app.route('/population-data')
@login_required
def population_data():
    """Get 30-minute interval population data for the current day"""
    today = datetime.datetime.now()
    interval_data = []
    
    # Initialize 48 intervals (every 30 minutes) with 0 counts
    for hour in range(24):
        for minute in [0, 30]:
            interval_data.append({
                'hour': f"{hour:02d}:{minute:02d}",
                'count': 0,
                'timestamp': hour * 60 + minute
            })
    
    # Get today's log data
    today_log_path = os.path.join(LOG_DIR, str(today.year), str(today.month), f"{today.day}.json")
    if os.path.exists(today_log_path):
        try:
            with open(today_log_path, 'r') as f:
                log_data = json.load(f)
                
                # Count passengers by 30-minute intervals
                for entry in log_data:
                    # Use Pi's local time directly (no timezone conversion)
                    entry_time = datetime.datetime.fromtimestamp(entry['entry_timestamp'])
                    hour = entry_time.hour
                    minute = entry_time.minute
                    
                    # Determine which 30-minute interval
                    interval_minute = 0 if minute < 30 else 30
                    interval_index = hour * 2 + (0 if minute < 30 else 1)
                    
                    if 0 <= interval_index < len(interval_data):
                        interval_data[interval_index]['count'] += 1
                    
        except (json.JSONDecodeError, FileNotFoundError):
            pass
    
    return jsonify({
        'date': today.strftime('%Y-%m-%d'),
        'hourly_data': interval_data
    })

@app.route('/historical-population-data')
@login_required
def historical_population_data():
    """Get historical 30-minute interval population data for a specific date"""
    date_str = request.args.get('date')
    if not date_str:
        return jsonify({'error': 'Date parameter required'}), 400
    
    try:
        target_date = datetime.datetime.strptime(date_str, '%Y-%m-%d')
        interval_data = []
        
        # Initialize 48 intervals (every 30 minutes) with 0 counts
        for hour in range(24):
            for minute in [0, 30]:
                interval_data.append({
                    'hour': f"{hour:02d}:{minute:02d}",
                    'count': 0,
                    'timestamp': hour * 60 + minute
                })
        
        # Get the specific date's log data
        log_path = os.path.join(LOG_DIR, str(target_date.year), str(target_date.month), f"{target_date.day}.json")
        if os.path.exists(log_path):
            try:
                with open(log_path, 'r') as f:
                    log_data = json.load(f)
                    
                    # Count passengers by 30-minute intervals
                    for entry in log_data:
                        # Convert UTC timestamp to CET timezone
                        import pytz
                        utc_time = datetime.datetime.fromtimestamp(entry['entry_timestamp'], tz=pytz.UTC)
                        entry_time = utc_time.astimezone(pytz.timezone('Europe/Madrid'))
                        hour = entry_time.hour
                        minute = entry_time.minute
                        
                        # Determine which 30-minute interval
                        interval_minute = 0 if minute < 30 else 30
                        interval_index = hour * 2 + (0 if minute < 30 else 1)
                        
                        if 0 <= interval_index < len(interval_data):
                            interval_data[interval_index]['count'] += 1
                        
            except (json.JSONDecodeError, FileNotFoundError):
                pass
        
        return jsonify({
            'date': date_str,
            'hourly_data': interval_data
        })
        
    except ValueError:
        return jsonify({'error': 'Invalid date format'}), 400

@app.route('/historical-data')
@login_required
def historical_data():
    # Always update historical data when requested
    update_historical_summary()
    if not os.path.exists(HISTORICAL_FILE):
        return jsonify({"daily": [], "weekly": [], "monthly": []})
    with open(HISTORICAL_FILE, 'r') as f:
        return jsonify(json.load(f))

@app.route('/historical-data-filtered')
@login_required
def historical_data_filtered():
    """Get filtered historical data based on selected date and period"""
    date_str = request.args.get('date')
    period = request.args.get('period', 'daily')
    
    if not date_str:
        return jsonify({"error": "Date parameter required"}), 400
    
    try:
        # Parse the selected date
        selected_date = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
        
        # Initialize result structure
        result = {"daily": [], "weekly": [], "monthly": []}
        
        if period == 'daily':
            # Get data for the specific day
            log_path = os.path.join(LOG_DIR, str(selected_date.year), str(selected_date.month), f"{selected_date.day}.json")
            if os.path.exists(log_path):
                try:
                    with open(log_path, 'r') as f:
                        log_data = json.load(f)
                        daily_total = len(log_data)
                        if daily_total > 0:
                            result["daily"].append({
                                "date": selected_date.strftime("%Y-%m-%d"),
                                "total": daily_total
                            })
                except (json.JSONDecodeError, FileNotFoundError):
                    pass
                    
        elif period == 'weekly':
            # Get data for the week containing the selected date
            start_of_week = selected_date - datetime.timedelta(days=selected_date.weekday())
            weekly_total = 0
            
            for i in range(7):
                check_date = start_of_week + datetime.timedelta(days=i)
                log_path = os.path.join(LOG_DIR, str(check_date.year), str(check_date.month), f"{check_date.day}.json")
                if os.path.exists(log_path):
                    try:
                        with open(log_path, 'r') as f:
                            log_data = json.load(f)
                            weekly_total += len(log_data)
                    except (json.JSONDecodeError, FileNotFoundError):
                        continue
            
            if weekly_total > 0:
                result["weekly"].append({
                    "week_of": start_of_week.strftime("%Y-%m-%d"),
                    "total": weekly_total
                })
                
        elif period == 'monthly':
            # Get data for the month containing the selected date
            month_start = selected_date.replace(day=1)
            month_total = 0
            current_day = month_start
            
            while current_day.month == month_start.month and current_day.year == month_start.year:
                log_path = os.path.join(LOG_DIR, str(current_day.year), str(current_day.month), f"{current_day.day}.json")
                if os.path.exists(log_path):
                    try:
                        with open(log_path, 'r') as f:
                            log_data = json.load(f)
                            month_total += len(log_data)
                    except (json.JSONDecodeError, FileNotFoundError):
                        pass
                current_day += datetime.timedelta(days=1)
            
            if month_total > 0:
                result["monthly"].append({
                    "month_of": month_start.strftime("%Y-%m"),
                    "total": month_total
                })
        
        return jsonify(result)
        
    except ValueError:
        return jsonify({"error": "Invalid date format"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500

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
            
            # Update the last Pi heartbeat time
            global last_pi_heartbeat_time
            last_pi_heartbeat_time = datetime.datetime.now().timestamp()
            
            print(f"✅ Data package received and extracted")
            return jsonify({'message': 'Data uploaded successfully'}), 200
        
        return jsonify({'error': 'Invalid file format'}), 400
        
    except Exception as e:
        print(f"❌ Upload error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/export-pdf', methods=['POST'])
@login_required
def export_pdf():
    """Export historical data to PDF"""
    try:
        data = request.get_json()
        period = data.get('period')
        date_str = data.get('date')
        city = data.get('city', 'manila')
        currency = data.get('currency', 'PHP')
        
        if not period or not date_str:
            return jsonify({'error': 'Missing required parameters'}), 400
        
        # Get the data based on period and date
        if period == 'daily':
            target_date = datetime.datetime.strptime(date_str, '%Y-%m-%d')
            log_file = os.path.join(LOG_DIR, str(target_date.year), str(target_date.month), f"{target_date.day}.json")
            if os.path.exists(log_file):
                with open(log_file, 'r') as f:
                    passengers = json.load(f)
            else:
                passengers = []
            title = f"Daily Report - {target_date.strftime('%B %d, %Y')}"
            
        elif period == 'weekly':
            # Handle both YYYY-W## format and YYYY-MM-DD format
            if 'W' in date_str:
                # Convert YYYY-W## format to first day of week
                year, week = date_str.split('-W')
                year = int(year)
                week = int(week)
                # Calculate first day of the week
                first_day_of_year = datetime.datetime(year, 1, 1)
                # Find the first Monday of the year
                days_to_first_monday = (7 - first_day_of_year.weekday()) % 7
                if days_to_first_monday == 0:
                    days_to_first_monday = 7
                first_monday = first_day_of_year + datetime.timedelta(days=days_to_first_monday)
                # Calculate start of the requested week
                start_of_week = first_monday + datetime.timedelta(weeks=week-1)
            else:
                # Regular date format
                target_date = datetime.datetime.strptime(date_str, '%Y-%m-%d')
                start_of_week = target_date - datetime.timedelta(days=target_date.weekday())
            
            passengers = []
            for i in range(7):
                day = start_of_week + datetime.timedelta(days=i)
                log_file = os.path.join(LOG_DIR, str(day.year), str(day.month), f"{day.day}.json")
                if os.path.exists(log_file):
                    with open(log_file, 'r') as f:
                        day_passengers = json.load(f)
                        passengers.extend(day_passengers)
            
            # Calculate end of week (6 days after start)
            end_of_week = start_of_week + datetime.timedelta(days=6)
            title = f"Weekly Report - {start_of_week.strftime('%B %d, %Y')} to {end_of_week.strftime('%B %d, %Y')}"
            
        elif period == 'monthly':
            target_date = datetime.datetime.strptime(date_str, '%Y-%m')
            month_dir = os.path.join(LOG_DIR, str(target_date.year), str(target_date.month))
            passengers = []
            if os.path.exists(month_dir):
                for day_file in os.listdir(month_dir):
                    if day_file.endswith('.json'):
                        day_path = os.path.join(month_dir, day_file)
                        with open(day_path, 'r') as f:
                            day_passengers = json.load(f)
                            passengers.extend(day_passengers)
            
            # Calculate first and last day of month
            first_day_of_month = target_date.replace(day=1)
            if target_date.month == 12:
                last_day_of_month = target_date.replace(year=target_date.year + 1, month=1, day=1) - datetime.timedelta(days=1)
            else:
                last_day_of_month = target_date.replace(month=target_date.month + 1, day=1) - datetime.timedelta(days=1)
            
            title = f"Monthly Report - {first_day_of_month.strftime('%B %d, %Y')} to {last_day_of_month.strftime('%B %d, %Y')}"
        
        # Create PDF
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=72, leftMargin=72, topMargin=72, bottomMargin=72)
        
        # Styles
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=18,
            spaceAfter=30,
            alignment=1,  # Center alignment
            textColor=colors.HexColor('#059669')
        )
        
        # Content
        story = []
        
        # Title
        story.append(Paragraph("E-Trike Passenger Dashboard", title_style))
        story.append(Paragraph(title, styles['Heading2']))
        story.append(Spacer(1, 20))
        
        # City fare information
        city_fares = {
            'manila': 20,
            'quezon_city': 25,
            'muntinlupa': 15,
            'pasay': 20,
            'lipa': 12
        }
        
        # Summary
        total_passengers = len(passengers)
        fare_per_passenger = city_fares.get(city, 20)  # Default to 20 if city not found
        revenue = total_passengers * fare_per_passenger
        
        # Calculate average passengers per day for weekly and monthly reports
        avg_passengers_per_day = 0
        if period == 'weekly':
            avg_passengers_per_day = total_passengers / 7
        elif period == 'monthly':
            # Calculate number of days in the month
            if target_date.month == 12:
                next_month = target_date.replace(year=target_date.year + 1, month=1, day=1)
            else:
                next_month = target_date.replace(month=target_date.month + 1, day=1)
            days_in_month = (next_month - target_date.replace(day=1)).days
            avg_passengers_per_day = total_passengers / days_in_month
        
        # Currency conversion
        currency_symbols = {'PHP': 'PHP', 'USD': 'USD', 'EUR': 'EUR'}
        currency_rates = {'PHP': 1.0, 'USD': 0.018, 'EUR': 0.016}
        converted_revenue = revenue * currency_rates.get(currency, 1.0)
        symbol = currency_symbols.get(currency, 'PHP')
        
        summary_data = [
            ['Total Passengers:', str(total_passengers)],
            ['City:', city.replace('_', ' ').title()],
            ['City Fare:', f"PHP {fare_per_passenger} per passenger"]
        ]
        
        # Add average passengers per day for weekly and monthly reports
        if period in ['weekly', 'monthly']:
            summary_data.append(['Average Passengers/Day:', f"{int(avg_passengers_per_day)}"])
        
        summary_data.append(['Revenue:', f"{symbol} {converted_revenue:.2f}"])
        
        # Calculate table width to use full page (A4 width minus margins)
        page_width = A4[0] - 144  # 72pt margins on each side
        summary_table = Table(summary_data, colWidths=[page_width * 0.4, page_width * 0.6])
        summary_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f8f9fa')),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('FONTNAME', (1, 0), (1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 11),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
            ('LEFTPADDING', (0, 0), (-1, -1), 8),
            ('RIGHTPADDING', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        
        story.append(summary_table)
        story.append(Spacer(1, 30))
        
        # Passenger details table (show all passengers)
        if len(passengers) > 0:  # Show details if there are any passengers
            story.append(Paragraph("Passenger Details", styles['Heading3']))
            story.append(Spacer(1, 12))
            
            # Prepare table data
            table_data = [['#', 'Entry Time', 'Exit Time', 'Dwell Time (min)']]
            for i, passenger in enumerate(passengers, 1):  # Show all passengers
                entry_time = passenger.get('entry_timestamp', 0)
                exit_time = passenger.get('exit_timestamp', 0)
                dwell_time = passenger.get('dwell_time_minutes', 0)
                
                # Convert timestamp to local time
                entry_str = datetime.datetime.fromtimestamp(entry_time).strftime('%H:%M:%S') if entry_time else 'N/A'
                exit_str = datetime.datetime.fromtimestamp(exit_time).strftime('%H:%M:%S') if exit_time else 'N/A'
                dwell_str = f"{dwell_time:.1f}" if dwell_time else 'N/A'
                
                table_data.append([str(i), entry_str, exit_str, dwell_str])
            
            # Calculate column widths for full page usage
            col_widths = [
                page_width * 0.1,  # # column
                page_width * 0.3,  # Entry Time
                page_width * 0.3,  # Exit Time
                page_width * 0.3   # Dwell Time
            ]
            passenger_table = Table(table_data, colWidths=col_widths)
            passenger_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#059669')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
                ('FONTSIZE', (0, 0), (-1, -1), 10),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
                ('LEFTPADDING', (0, 0), (-1, -1), 8),
                ('RIGHTPADDING', (0, 0), (-1, -1), 8),
                ('TOPPADDING', (0, 0), (-1, -1), 10),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8f9fa')])
            ]))
            
            story.append(passenger_table)
        else:
            story.append(Paragraph("No passenger data available for the selected period.", styles['Normal']))
        
        # Build PDF with footer
        def add_footer(canvas, doc):
            canvas.saveState()
            canvas.setFont('Helvetica', 8)
            canvas.setFillColor(colors.grey)
            
            # Footer text
            footer_text = "Generated by E-Trike Passenger Dashboard"
            page_text = f"Page {doc.page}"
            
            # Get page dimensions
            page_width = doc.pagesize[0]
            page_height = doc.pagesize[1]
            
            # Draw footer line
            canvas.setStrokeColor(colors.grey)
            canvas.line(72, 50, page_width - 72, 50)
            
            # Add footer text (left side)
            canvas.drawString(72, 35, footer_text)
            
            # Add page number (right side)
            canvas.drawRightString(page_width - 72, 35, page_text)
            
            canvas.restoreState()
        
        doc.build(story, onFirstPage=add_footer, onLaterPages=add_footer)
        buffer.seek(0)
        
        return send_file(
            buffer,
            as_attachment=True,
            download_name=f"E-Trike-{period}-Report-{date_str}.pdf",
            mimetype='application/pdf'
        )
        
    except Exception as e:
        print(f"PDF export error: {e}")
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
    
    try:
        # Try HTTPS first
        if os.path.exists(cert_path) and os.path.exists(key_path):
            context = ssl.SSLContext(ssl.PROTOCOL_TLS)  # Use TLS instead of TLSv1_2
            context.load_cert_chain(cert_path, key_path)
            print("🚀 Dashboard with WebSocket running on https://etrikedashboard.com:5001/")
            socketio.run(app, debug=False, host='0.0.0.0', port=443, ssl_context=context)
        else:
            # Fall back to HTTP
            print("🚀 Dashboard with WebSocket running on http://localhost:5001/")
            socketio.run(app, debug=False, host='0.0.0.0', port=5001)
    except Exception as e:
        print(f"⚠️  SSL Error: {e}")
        print("🔄 Falling back to HTTP mode...")
        socketio.run(app, debug=False, host='0.0.0.0', port=5001) 