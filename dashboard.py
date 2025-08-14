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
                                file_max_ts = max(entry.get('timestamp', 0) for entry in log_data)
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
    Checks if a day, week, or month has passed and updates the historical summary log.
    This is a simplified implementation that triggers on dashboard load.
    """
    today = get_latest_log_time()
    
    # Ensure historical file exists
    if not os.path.exists(HISTORICAL_FILE):
        with open(HISTORICAL_FILE, 'w') as f:
            json.dump({"daily": [], "weekly": [], "monthly": [], "last_run": today.isoformat()}, f, indent=4)

    with open(HISTORICAL_FILE, 'r+') as f:
        summary_data = json.load(f)
        last_run = datetime.datetime.fromisoformat(summary_data.get("last_run", "1970-01-01"))

        # --- Check for Daily Summary ---
        if today.date() > last_run.date():
            day_to_summarize = today.date() - datetime.timedelta(days=1)
            # Check if this day is already summarized
            already_summarized = any(d.get('date') == day_to_summarize.strftime("%Y-%m-%d") for d in summary_data.get('daily', []))

            if not already_summarized:
                log_path = os.path.join(LOG_DIR, str(day_to_summarize.year), str(day_to_summarize.month), f"{day_to_summarize.day}.json")
                if os.path.exists(log_path):
                    daily_totals = defaultdict(int)
                    with open(log_path, 'r') as log_file:
                        try:
                            log_data = json.load(log_file)
                            for entry in log_data:
                                p_type = entry.get("type", "Adult")
                                daily_totals[p_type] += 1
                                daily_totals['total'] += 1
                        except json.JSONDecodeError:
                            pass # Ignore corrupted log files
                    
                    if daily_totals['total'] > 0:
                        summary_data.setdefault("daily", []).append({
                            "date": day_to_summarize.strftime("%Y-%m-%d"),
                            "totals": dict(daily_totals)
                        })


        # --- Check for Weekly Summary ---
        # If today is a new week (e.g., Monday) and last run was in the previous week
        if today.weekday() < last_run.weekday() or (today - last_run).days >= 7:
            # Calculate for the previous week
            end_of_last_week = today - datetime.timedelta(days=today.weekday() + 1)
            start_of_last_week = end_of_last_week - datetime.timedelta(days=6)
            
            weekly_totals = defaultdict(int)
            for i in range(7):
                current_day = start_of_last_week + datetime.timedelta(days=i)
                log_path = os.path.join(LOG_DIR, str(current_day.year), str(current_day.month), f"{current_day.day}.json")
                if os.path.exists(log_path):
                    with open(log_path, 'r') as log_file:
                        try:
                            log_data = json.load(log_file)
                            for entry in log_data:
                                p_type = entry.get("type", "Adult")
                                weekly_totals[p_type] += 1
                                weekly_totals['total'] += 1
                        except json.JSONDecodeError:
                            continue
            
            # Avoid adding empty records
            if weekly_totals['total'] > 0:
                summary_data["weekly"].append({
                    "week_of": start_of_last_week.strftime("%Y-%m-%d"),
                    "totals": dict(weekly_totals)
                })

        # --- Check for Monthly Summary ---
        if today.month != last_run.month or today.year != last_run.year:
            # Calculate for the previous month
            first_day_of_this_month = today.replace(day=1)
            last_day_of_last_month = first_day_of_this_month - datetime.timedelta(days=1)
            year, month = last_day_of_last_month.year, last_day_of_last_month.month
            
            monthly_totals = defaultdict(int)
            month_log_dir = os.path.join(LOG_DIR, str(year), str(month))
            if os.path.exists(month_log_dir):
                 for day_file in os.listdir(month_log_dir):
                    if day_file.endswith('.json'):
                        with open(os.path.join(month_log_dir, day_file), 'r') as log_file:
                            try:
                                log_data = json.load(log_file)
                                for entry in log_data:
                                    p_type = entry.get("type", "Adult")
                                    monthly_totals[p_type] += 1
                                    monthly_totals['total'] += 1
                            except json.JSONDecodeError:
                                continue

            # Avoid adding empty records
            if monthly_totals['total'] > 0:
                 summary_data["monthly"].append({
                    "month_of": f"{year}-{month:02d}",
                    "totals": dict(monthly_totals)
                })

        # Update last run timestamp and save
        summary_data["last_run"] = today.isoformat()
        f.seek(0)
        json.dump(summary_data, f, indent=4)
        f.truncate()


def get_passenger_counts():
    """Calculates passenger counts for different time periods."""
    now = get_latest_log_time()
    counts = defaultdict(lambda: defaultdict(int)) # Nested defaultdict for types

    # Hourly and Daily
    today_log_path = os.path.join(LOG_DIR, str(now.year), str(now.month), f"{now.day}.json")
    if os.path.exists(today_log_path):
        with open(today_log_path, 'r') as f:
            try:
                log_data = json.load(f)
                for entry in log_data:
                    passenger_type = entry.get("type", "Adult") # Default to adult if type is missing
                    
                    # Daily counts
                    counts['daily'][passenger_type] += 1
                    counts['daily']['total'] += 1

                    # Hourly counts (rolling)
                    entry_time = datetime.datetime.fromtimestamp(entry['timestamp'])
                    if (now - entry_time).total_seconds() <= 3600:
                        counts['hourly'][passenger_type] += 1
                        counts['hourly']['total'] += 1
                        
            except json.JSONDecodeError:
                pass

    # Weekly
    start_of_week = now - datetime.timedelta(days=now.weekday())
    for i in range(7):
        current_day = start_of_week + datetime.timedelta(days=i)
        week_log_path = os.path.join(LOG_DIR, str(current_day.year), str(current_day.month), f"{current_day.day}.json")
        if os.path.exists(week_log_path):
            with open(week_log_path, 'r') as f:
                try:
                    log_data = json.load(f)
                    for entry in log_data:
                        passenger_type = entry.get("type", "Adult")
                        counts['weekly'][passenger_type] += 1
                        counts['weekly']['total'] += 1
                except json.JSONDecodeError:
                    pass
    
    # Monthly
    month_log_dir = os.path.join(LOG_DIR, str(now.year), str(now.month))
    if os.path.exists(month_log_dir):
        for day_file in os.listdir(month_log_dir):
            if day_file.endswith('.json'):
                day_path = os.path.join(month_log_dir, day_file)
                with open(day_path, 'r') as f:
                    try:
                        log_data = json.load(f)
                        for entry in log_data:
                            passenger_type = entry.get("type", "Adult")
                            counts['monthly'][passenger_type] += 1
                            counts['monthly']['total'] += 1
                    except json.JSONDecodeError:
                        pass


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
    if not os.path.exists(HISTORICAL_FILE):
        return jsonify({"daily": [], "weekly": [], "monthly": []})
    with open(HISTORICAL_FILE, 'r') as f:
        return jsonify(json.load(f))

@app.route('/shutdown', methods=['POST'])
def shutdown():
    shutdown_server = request.environ.get('werkzeug.server.shutdown')
    if shutdown_server is None:
        raise RuntimeError('Not running with the Werkzeug Server')
    shutdown_server()
    return 'Server shutting down...'

if __name__ == '__main__':
    print("Dashboard is running on http://127.0.0.1:5000/")
    app.run(debug=True) 