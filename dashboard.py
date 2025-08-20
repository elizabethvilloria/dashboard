from flask import Flask, jsonify, render_template, request
import json
import datetime
from collections import defaultdict
import os

app = Flask(__name__)

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

@app.route('/')
def index():
    update_historical_summary()
    return render_template('index.html')

@app.route('/data')
def data():
    return jsonify(get_passenger_counts())

@app.route('/historical-data')
def historical_data():
    # Always update historical data when requested
    update_historical_summary()
    if not os.path.exists(HISTORICAL_FILE):
        return jsonify({"daily": [], "weekly": [], "monthly": []})
    with open(HISTORICAL_FILE, 'r') as f:
        return jsonify(json.load(f))

@app.route('/passenger-details')
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

@app.route('/shutdown', methods=['POST'])
def shutdown():
    shutdown_server = request.environ.get('werkzeug.server.shutdown')
    if shutdown_server is None:
        raise RuntimeError('Not running with the Werkzeug Server')
    shutdown_server()
    return 'Server shutting down...'

if __name__ == '__main__':
    print("Dashboard is running on http://127.0.0.1:5001/")
    app.run(debug=True, port=5001) 