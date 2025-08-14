import cv2
import time
import datetime
from ultralytics import YOLO
import os
import torch
import math
import json
from collections import defaultdict

# Optional: Picamera2 for Raspberry Pi camera support
try:
    from picamera2 import Picamera2
    PICAMERA2_AVAILABLE = True
except Exception:
    PICAMERA2_AVAILABLE = False

CONFIG_FILE = "config.json"
LOG_DIR = "logs"

def log_passenger_entry(person_id, passenger_type):
    """Logs a passenger entry event with a timestamp and type."""
    now = datetime.datetime.now()
    log_dir = os.path.join(LOG_DIR, str(now.year), str(now.month))
    os.makedirs(log_dir, exist_ok=True)
    
    log_file = os.path.join(log_dir, f"{now.day}.json")
    
    new_entry = {"person_id": person_id, "type": passenger_type, "timestamp": now.timestamp()}
    
    # Read existing data and append the new entry
    try:
        if os.path.exists(log_file) and os.path.getsize(log_file) > 0:
            with open(log_file, 'r') as f:
                logs = json.load(f)
        else:
            logs = []
    except (json.JSONDecodeError, FileNotFoundError):
        logs = [] # Reset if file is corrupted or not found
        
    logs.append(new_entry)
    
    with open(log_file, 'w') as f:
        json.dump(logs, f, indent=4)

def classify_passenger(person_keypoints, box_height):
    """Classifies a passenger as 'Adult' or 'Child' based on bounding box height."""
    height_threshold = 125  # Pixels
    if box_height < height_threshold:
        return "Child"
    else:
        return "Adult"


def draw_skeleton(frame, keypoints, color=(255, 0, 255)):
    """Draws skeleton keypoints and connections."""
    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = 0.4
    font_thickness = 1
    
    # Standard COCO keypoint connections
    skeleton_connections = [
        # Head
        (0, 1), (0, 2), (1, 3), (2, 4),
        # Body
        (5, 6), (5, 11), (6, 12), (11, 12),
        # Arms
        (5, 7), (7, 9), (6, 8), (8, 10),
        # Legs
        (11, 13), (13, 15), (12, 14), (14, 16)
    ]

    for i, kp in enumerate(keypoints):
        x, y = int(kp[0]), int(kp[1])
        if x > 0 and y > 0:
            cv2.circle(frame, (x, y), 3, color, -1)
            # cv2.putText(frame, str(i), (x, y - 5), font, font_scale, color, font_thickness) # Uncomment to see keypoint indices

    for start_idx, end_idx in skeleton_connections:
        start_kp = keypoints[start_idx]
        end_kp = keypoints[end_idx]
        
        start_pos = (int(start_kp[0]), int(start_kp[1]))
        end_pos = (int(end_kp[0]), int(end_kp[1]))

        if start_pos[0] > 0 and start_pos[1] > 0 and end_pos[0] > 0 and end_pos[1] > 0:
            cv2.line(frame, start_pos, end_pos, color, 1)

def draw_person_circle(frame, keypoints, color=(255, 0, 255)):
    """Draws a single circle to represent the person (at nose or centroid)."""
    # Prefer nose (index 0) if visible
    nose = keypoints[0]
    if nose[0] > 0 and nose[1] > 0:
        center = (int(nose[0]), int(nose[1]))
    else:
        visible = [kp for kp in keypoints if kp[0] > 0 and kp[1] > 0]
        if not visible:
            return
        avg_x = int(sum(kp[0] for kp in visible) / len(visible))
        avg_y = int(sum(kp[1] for kp in visible) / len(visible))
        center = (avg_x, avg_y)
    cv2.circle(frame, center, 10, color, 2)

def classify_posture(keypoints, posture_threshold):
    """Classifies posture as 'Standing' or 'Sitting' based on relative keypoint positions."""
    # Keypoint indices from COCO model
    left_shoulder_idx, right_shoulder_idx = 5, 6
    left_hip_idx, right_hip_idx = 11, 12
    left_knee_idx, right_knee_idx = 13, 14

    # Get keypoint coordinates
    left_shoulder = keypoints[left_shoulder_idx]
    right_shoulder = keypoints[right_shoulder_idx]
    left_hip = keypoints[left_hip_idx]
    right_hip = keypoints[right_hip_idx]
    left_knee = keypoints[left_knee_idx]
    right_knee = keypoints[right_knee_idx]

    # --- Check for visibility and calculate average positions ---
    # We need at least one shoulder, one hip, and one knee to make a guess.
    
    # Calculate average shoulder y-coordinate
    if left_shoulder[1] > 0 and right_shoulder[1] > 0:
        shoulder_y = (left_shoulder[1] + right_shoulder[1]) / 2
    elif left_shoulder[1] > 0:
        shoulder_y = left_shoulder[1]
    elif right_shoulder[1] > 0:
        shoulder_y = right_shoulder[1]
    else:
        return "Unknown" # Not enough data

    # Calculate average hip y-coordinate
    if left_hip[1] > 0 and right_hip[1] > 0:
        hip_y = (left_hip[1] + right_hip[1]) / 2
    elif left_hip[1] > 0:
        hip_y = left_hip[1]
    elif right_hip[1] > 0:
        hip_y = right_hip[1]
    else:
        return "Unknown"

    # Calculate average knee y-coordinate
    if left_knee[1] > 0 and right_knee[1] > 0:
        knee_y = (left_knee[1] + right_knee[1]) / 2
    elif left_knee[1] > 0:
        knee_y = left_knee[1]
    elif right_knee[1] > 0:
        knee_y = right_knee[1]
    else:
        return "Unknown"
        
    # --- Heuristic Logic ---
    # Normalize distances by torso height to make it scale-invariant.
    torso_height = abs(hip_y - shoulder_y)
    if torso_height == 0:
        return "Unknown"

    # Calculate vertical distance between hip and knee.
    vertical_hip_knee_dist = abs(knee_y - hip_y)
    
    # The threshold determines the switch from sitting to standing.
    # If the vertical distance between the hip and knee is small compared to the torso height,
    # the person is likely sitting.
    # This value (0.55) might need tuning for your specific camera angle.
    
    if (vertical_hip_knee_dist / torso_height) < posture_threshold:
        return "Sitting"
    else:
        return "Standing"


def load_config():
    """Load configuration from a JSON file."""
    try:
        with open(CONFIG_FILE, 'r') as f:
            config = json.load(f)
        
        # For backward compatibility, rename 'zone_margin' to 'side_margin'
        if 'zone_margin' in config:
            config['side_margin'] = config.pop('zone_margin')

    except (FileNotFoundError, json.JSONDecodeError):
        # Default config if file is missing or invalid
        config = {
            "camera_index": 1,
            "side_margin": 100,
            "bottom_margin": 100,
            "line_thickness": 2,
            "font_scale": 0.7,
            "font_thickness": 2,
            "colors": {
                "exit_red": [0, 0, 255],
                "inside_green": [0, 100, 0],
                "person_id_green": [0, 255, 0],
                "info_text_white": [255, 255, 255],
                "hover_yellow": [0, 255, 255] # Hover color
            },
            "posture_threshold": 0.55 # Default posture threshold
        }
    
    # Ensure bottom_margin exists in case of old config file
    if 'bottom_margin' not in config:
        config['bottom_margin'] = 100

    # Convert color lists to tuples for OpenCV
    for key, value in config["colors"].items():
        config["colors"][key] = tuple(value)
    return config

def save_config(config_to_save):
    """Save configuration to a JSON file."""
    # Create a modifiable copy for saving (colors as lists)
    config_copy = config_to_save.copy()
    config_copy['colors'] = config_copy['colors'].copy()
    for key, value in config_copy["colors"].items():
        config_copy["colors"][key] = list(value)
    
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config_copy, f, indent=4)

def run_detection(model):
    # Load configuration
    config = load_config()
    
    # --- State for Mouse Interaction ---
    shared_state = {
        'side_margin': config['side_margin'],
        'bottom_margin': config.get('bottom_margin', 100), # Default if not in config
        'dragging_line': None,  # 'left', 'right', 'bottom', or None
        'hovering_on': None,  # 'left', 'right', 'bottom', or None
        'shadow_position': None, # X or Y coordinate for the shadow line
        'feedback_message': '', # Message like "Saving..." or "Saved!"
        'feedback_timestamp': 0 # Timestamp for feedback message
    }
    
    # --- Posture Detection Threshold ---
    # Load this from config to allow for easy tuning.
    posture_threshold = config.get('posture_threshold', 0.55)

    # Initialize video capture (try OpenCV indices, then fall back to Picamera2 on Raspberry Pi)
    cap = None
    picam2 = None
    use_picamera2 = False

    def try_opencv_indices(indices):
        for idx in indices:
            temp_cap = cv2.VideoCapture(idx)
            if not temp_cap.isOpened():
                temp_cap.release()
                continue
            ok, temp_frame = temp_cap.read()
            if ok and temp_frame is not None:
                return temp_cap, temp_frame, idx
            temp_cap.release()
        return None, None, None

    preferred_index = int(config.get("camera_index", 0))
    scan_order = [preferred_index] + [i for i in range(4) if i != preferred_index]
    cap, frame, used_index = try_opencv_indices(scan_order)

    if cap is None or frame is None:
        # Fallback to Picamera2 if available (Raspberry Pi)
        if PICAMERA2_AVAILABLE:
            try:
                picam2 = Picamera2()
                # Use a modest resolution for performance on Pi
                video_config = picam2.create_video_configuration(main={"size": (640, 480)})
                picam2.configure(video_config)
                picam2.start()
                time.sleep(0.5)  # warm-up
                frame = picam2.capture_array()
                # Picamera2 returns RGB; convert to BGR for OpenCV drawing consistency
                frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
                if frame is None:
                    print("Error: Picamera2 started but returned an empty frame.")
                    return
                use_picamera2 = True
                print("Info: Using Picamera2 backend for frames.")
            except Exception as e:
                print(f"Error: Could not initialize Picamera2. {e}")
                print("Hint: On Raspberry Pi OS, install Picamera2: sudo apt update && sudo apt install -y python3-picamera2 libcamera-apps")
                return
        else:
            print("Error: Could not read frame from any OpenCV camera index (0-3).")
            print("If you're on Raspberry Pi, install Picamera2 (sudo apt install -y python3-picamera2 libcamera-apps) or check camera connections.")
            return
    else:
        print(f"Info: Using OpenCV VideoCapture index {used_index}.")

    frame_height, frame_width, _ = frame.shape

    # --- Mouse Callback for Zone Adjustment ---
    def adjust_zones_callback(event, x, y, flags, param):
        nonlocal shared_state, config
        
        # Click sensitivity for easier line grabbing
        click_sensitivity = 20
        is_near_left = abs(x - shared_state['side_margin']) < click_sensitivity
        is_near_right = abs(x - (frame_width - shared_state['side_margin'])) < click_sensitivity
        is_near_bottom = abs(y - (frame_height - shared_state['bottom_margin'])) < click_sensitivity

        # Handle mouse hover for visual feedback
        if event == cv2.EVENT_MOUSEMOVE:
            if shared_state['dragging_line'] is None: # Update hover only when not dragging
                if is_near_left:
                    shared_state['hovering_on'] = 'left'
                elif is_near_right:
                    shared_state['hovering_on'] = 'right'
                elif is_near_bottom:
                    shared_state['hovering_on'] = 'bottom'
                else:
                    shared_state['hovering_on'] = None

        if event == cv2.EVENT_LBUTTONDOWN:
            if is_near_left:
                shared_state['dragging_line'] = 'left'
                shared_state['shadow_position'] = x
            elif is_near_right:
                shared_state['dragging_line'] = 'right'
                shared_state['shadow_position'] = x
            elif is_near_bottom:
                shared_state['dragging_line'] = 'bottom'
                shared_state['shadow_position'] = y

        elif event == cv2.EVENT_MOUSEMOVE:
            if shared_state['dragging_line'] == 'left':
                if 20 < x < (frame_width / 2) - 20:
                    shared_state['shadow_position'] = x
            elif shared_state['dragging_line'] == 'right':
                if (frame_width / 2) + 20 < x < frame_width:
                     shared_state['shadow_position'] = x
            elif shared_state['dragging_line'] == 'bottom':
                if (frame_height / 2) + 20 < y < frame_height:
                     shared_state['shadow_position'] = y
        
        elif event == cv2.EVENT_LBUTTONUP:
            if shared_state['dragging_line'] == 'left':
                shared_state['side_margin'] = shared_state['shadow_position']
            elif shared_state['dragging_line'] == 'right':
                shared_state['side_margin'] = frame_width - shared_state['shadow_position']
            elif shared_state['dragging_line'] == 'bottom':
                shared_state['bottom_margin'] = frame_height - shared_state['shadow_position']

            if shared_state['dragging_line'] is not None:
                # Show "Saving..." message
                shared_state['feedback_message'] = 'Saving...'
                
                # Update config and save
                config['side_margin'] = shared_state['side_margin']
                config['bottom_margin'] = shared_state['bottom_margin']
                save_config(config)
                print(f"New side margin ({config['side_margin']}) and bottom margin ({config['bottom_margin']}) saved to config.json")
                
                # Show "Saved!" message
                shared_state['feedback_message'] = 'Configuration Saved!'
                shared_state['feedback_timestamp'] = time.time()
                
            shared_state['dragging_line'] = None
            shared_state['shadow_position'] = None

    # --- Colors from Config ---
    exit_red = config["colors"]["exit_red"]
    inside_green = config["colors"]["inside_green"]
    person_id_green = config["colors"]["person_id_green"]
    info_text_white = config["colors"]["info_text_white"]
    hover_yellow = config["colors"]["hover_yellow"]
    shadow_line_gray = config["colors"].get("shadow_line_gray", (200, 200, 200))
    adult_text_blue = config["colors"].get("adult_text_blue", (255, 0, 0))
    child_text_orange = config["colors"].get("child_text_orange", (0, 165, 255))

    # --- Zone Definitions ---
    side_margin = shared_state['side_margin']
    bottom_margin = shared_state['bottom_margin']
    # Left exit zone
    left_exit_zone = (0, 0, side_margin, frame_height)
    # Right exit zone
    right_exit_zone = (frame_width - side_margin, 0, frame_width, frame_height)
    # Bottom exit zone
    bottom_exit_zone = (0, frame_height - bottom_margin, frame_width, frame_height)
    # Area between exit zones
    inside_zone = (side_margin, 0, frame_width - side_margin, frame_height - bottom_margin)

    # --- Passenger Counting ---
    person_last_zone = {}
    passenger_entry_times = {}
    # Cache for skipped frames to avoid flicker
    latest_boxes = []  # list of ((x1, y1), (x2, y2))
    last_passengers_in_trike_count = 0

    # --- Main Loop ---
    frame_idx = 0
    # Camera flip settings from config
    flip_horizontal = bool(config.get('flip_horizontal', False))
    flip_vertical = bool(config.get('flip_vertical', False))
    # FPS tracking
    last_frame_time = time.time()
    smoothed_fps = 0.0
    while True:
        if use_picamera2:
            frame = picam2.capture_array()
            frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
            ret = frame is not None
        else:
            ret, frame = cap.read()

        if not ret:
            break

        # Apply flips as configured
        if flip_horizontal and flip_vertical:
            frame = cv2.flip(frame, -1)
        elif flip_horizontal:
            frame = cv2.flip(frame, 1)
        elif flip_vertical:
            frame = cv2.flip(frame, 0)

        # Update FPS (EMA smoothing)
        now_t = time.time()
        dt = now_t - last_frame_time
        if dt > 0:
            inst_fps = 1.0 / dt
            smoothed_fps = (0.9 * smoothed_fps) + (0.1 * inst_fps) if smoothed_fps > 0 else inst_fps
        last_frame_time = now_t

        frame_idx += 1

        # Get current time
        current_time = datetime.datetime.now().strftime("%m-%d-%y %H:%M")

        passengers_in_trike_count = 0

        # Pause AI model during drag to keep UI responsive
        # Also skip every other frame to reduce CPU load
        did_infer = False
        if shared_state['dragging_line'] is None and (frame_idx % 2 == 0):
            # Run YOLOv8 tracking on the frame with smaller inference size
            results = model.track(
                frame,
                persist=True,
                verbose=False,
                device="cpu",
                tracker="bytetrack.yaml",
                imgsz=320,
                conf=0.5,
                max_det=10
            )
            did_infer = True

            if results and results[0].boxes is not None and results[0].boxes.id is not None:
                boxes = results[0].boxes.xywh.cpu()
                track_ids = results[0].boxes.id.int().cpu().tolist()
                all_keypoints = results[0].keypoints.xy.cpu().numpy()
                new_boxes = []
                for i, person_keypoints in enumerate(all_keypoints):
                    nose_x, nose_y = person_keypoints[0]
                    person_id = track_ids[i]

                    # Determine person's current zone by nose position
                    current_zone = None
                    if nose_x > 0 and nose_y > 0:
                        if left_exit_zone[0] <= nose_x < left_exit_zone[2]:
                            current_zone = "left_exit"
                        elif right_exit_zone[0] <= nose_x < right_exit_zone[2]:
                            current_zone = "right_exit"
                        elif bottom_exit_zone[1] <= nose_y < bottom_exit_zone[3]:
                            current_zone = "bottom_exit"
                        elif inside_zone[0] <= nose_x < inside_zone[2] and nose_y < inside_zone[3]:
                            current_zone = "inside"
                            passengers_in_trike_count += 1

                    # --- Bounding box, classification, drawing, and logging ---
                    visible_keypoints = [kp for kp in person_keypoints if kp[0] > 0 and kp[1] > 0]
                    
                    if visible_keypoints:
                        min_x = int(min(kp[0] for kp in visible_keypoints))
                        min_y = int(min(kp[1] for kp in visible_keypoints))
                        max_x = int(max(kp[0] for kp in visible_keypoints))
                        max_y = int(max(kp[1] for kp in visible_keypoints))
                        
                        # Add some padding
                        padding = 10
                        start_point = (min_x - padding, min_y - padding)
                        end_point = (max_x + padding, max_y + padding)

                        # Draw a rectangle (bounding box) to represent the person for better accuracy
                        cv2.rectangle(frame, start_point, end_point, (255, 0, 255), 2)
                        # Cache box for skipped frames
                        new_boxes.append((start_point, end_point))

                        # Minimal classification to keep logging working
                        box_height = end_point[1] - start_point[1]
                        passenger_type = classify_passenger(person_keypoints, box_height)
                        posture = classify_posture(person_keypoints, posture_threshold)

                        # --- Passenger Counting ---
                        if current_zone is not None:
                            last_zone = person_last_zone.get(person_id)

                            if current_zone == "inside" and last_zone != "inside":
                                log_passenger_entry(person_id, passenger_type)
                                passenger_entry_times[person_id] = time.time()
                            elif current_zone != "inside" and last_zone == "inside":
                                if person_id in passenger_entry_times:
                                    dwell_time = time.time() - passenger_entry_times.pop(person_id)
                                    print(f"Passenger {person_id} was onboard for {dwell_time:.2f} seconds.")
                    
                    # Update person's last known zone
                    if current_zone is not None:
                        person_last_zone[person_id] = current_zone

                # Save caches after processing all people this frame
                latest_boxes = new_boxes
                last_passengers_in_trike_count = passengers_in_trike_count

        # If we skipped inference this frame, draw last known boxes to avoid flicker
        if not did_infer and latest_boxes:
            for (sp, ep) in latest_boxes:
                cv2.rectangle(frame, sp, ep, (255, 0, 255), 2)

        # --- Draw Zones ---
        side_margin = shared_state['side_margin'] # Use updated margin
        bottom_margin = shared_state['bottom_margin']
        left_exit_zone = (0, 0, side_margin, frame_height - bottom_margin)
        right_exit_zone = (frame_width - side_margin, 0, frame_width, frame_height - bottom_margin)
        bottom_exit_zone = (side_margin, frame_height - bottom_margin, frame_width - side_margin, frame_height)
        inside_zone = (side_margin, 0, frame_width - side_margin, frame_height - bottom_margin)

        # --- Clear Feedback Message ---
        if shared_state['feedback_message'] == 'Configuration Saved!' and \
           time.time() - shared_state['feedback_timestamp'] > config.get('saved_confirmation_duration_sec', 2):
            shared_state['feedback_message'] = ''

        line_thickness = config["line_thickness"]
        # Set line colors based on hover state
        left_line_color = hover_yellow if shared_state['hovering_on'] == 'left' else inside_green
        right_line_color = hover_yellow if shared_state['hovering_on'] == 'right' else inside_green
        bottom_line_color = hover_yellow if shared_state['hovering_on'] == 'bottom' else inside_green
        
        # "Inside" zone lines (vertical)
        cv2.rectangle(frame, (side_margin, 0), (side_margin + line_thickness - 1, frame_height - bottom_margin), left_line_color, -1)
        cv2.rectangle(frame, (frame_width - side_margin - line_thickness, 0), (frame_width - side_margin - 1, frame_height - bottom_margin), right_line_color, -1)
        # "Inside" zone line (horizontal)
        cv2.rectangle(frame, (side_margin, frame_height - bottom_margin), (frame_width - side_margin, frame_height - bottom_margin + line_thickness - 1), bottom_line_color, -1)
        
        # --- Draw shadow lines when dragging ---
        if shared_state['dragging_line'] and shared_state['shadow_position'] is not None:
            overlay = frame.copy()
            alpha = 0.5
            
            if shared_state['dragging_line'] in ['left', 'right']:
                shadow_x = shared_state['shadow_position']
                mirrored_shadow_x = frame_width - shadow_x
                # Primary shadow line
                cv2.rectangle(overlay, (shadow_x, 0), (shadow_x + line_thickness - 1, frame_height), shadow_line_gray, -1)
                # Mirrored shadow line
                cv2.rectangle(overlay, (mirrored_shadow_x, 0), (mirrored_shadow_x + line_thickness - 1, frame_height), shadow_line_gray, -1)
            
            elif shared_state['dragging_line'] == 'bottom':
                shadow_y = shared_state['shadow_position']
                cv2.rectangle(overlay, (0, shadow_y), (frame_width, shadow_y + line_thickness - 1), shadow_line_gray, -1)

            frame = cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0)
            
        # Outer boundaries of exit zones
        cv2.rectangle(frame, (0, 0), (line_thickness - 1, frame_height), exit_red, -1)
        cv2.rectangle(frame, (frame_width - line_thickness, 0), (frame_width - 1, frame_height), exit_red, -1)
        cv2.rectangle(frame, (0, frame_height - line_thickness), (frame_width, frame_height), exit_red, -1)


        # --- Zone Labels ---
        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = config["font_scale"]
        font_thickness = config["font_thickness"]
        exit_text = "Exit"
        text_size = cv2.getTextSize(exit_text, font, font_scale, font_thickness)[0]

        # Center "Exit" in left zone
        left_text_x = (side_margin - text_size[0]) // 2
        cv2.putText(frame, exit_text, (left_text_x, 30), font, font_scale, exit_red, font_thickness)

        # Center "Exit" in right zone
        right_text_x = (frame_width - side_margin) + ((side_margin - text_size[0]) // 2)
        cv2.putText(frame, exit_text, (right_text_x, 30), font, font_scale, exit_red, font_thickness)
        
        # Center "Exit" in bottom zone
        bottom_text_x = (frame_width - text_size[0]) // 2
        bottom_text_y = frame_height - (bottom_margin - text_size[1]) // 2
        cv2.putText(frame, exit_text, (bottom_text_x, bottom_text_y), font, font_scale, exit_red, font_thickness)

        cv2.putText(frame, "Inside E-Trike", (inside_zone[0] + 10, 30), font, font_scale, inside_green, font_thickness)

        # Display clock and counters (use config font scale/thickness)
        cv2.putText(frame, current_time, (side_margin + 10, 70), cv2.FONT_HERSHEY_SIMPLEX, config["font_scale"], info_text_white, config["font_thickness"], cv2.LINE_AA)
        display_count = passengers_in_trike_count if did_infer else last_passengers_in_trike_count
        cv2.putText(frame, f"Passengers Inside: {display_count}", (side_margin + 10, 110), cv2.FONT_HERSHEY_SIMPLEX, config["font_scale"], info_text_white, config["font_thickness"], cv2.LINE_AA)
        # FPS display
        cv2.putText(frame, f"FPS: {smoothed_fps:.1f}", (side_margin + 10, 150), cv2.FONT_HERSHEY_SIMPLEX, config["font_scale"], info_text_white, config["font_thickness"], cv2.LINE_AA)
        
        # Add instruction or feedback text
        if shared_state['feedback_message']:
            # Display centered feedback message
            feedback_text = shared_state['feedback_message']
            font_face = cv2.FONT_HERSHEY_DUPLEX
            font_scale_feedback = 1.2
            font_thickness_feedback = 2

            # Center text
            text_size = cv2.getTextSize(feedback_text, font_face, font_scale_feedback, font_thickness_feedback)[0]
            text_x = (frame_width - text_size[0]) // 2
            text_y = (frame_height + text_size[1]) // 2
            
            # Add semi-transparent background
            box_padding = 20
            box_coords = ((text_x - box_padding, text_y - text_size[1] - box_padding), (text_x + text_size[0] + box_padding, text_y + box_padding))
            overlay = frame.copy()
            cv2.rectangle(overlay, box_coords[0], box_coords[1], (0, 0, 0), -1)
            alpha = 0.6 # Transparency
            frame = cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0)
            
            # Draw centered text
            cv2.putText(frame, feedback_text, (text_x, text_y), font_face, font_scale_feedback, info_text_white, font_thickness_feedback, cv2.LINE_AA)
        
        else:
            # Display adjustment instructions
            if shared_state['dragging_line']:
                drag_text = f"Dragging {shared_state['dragging_line']} zone..."
            else:
                drag_text = "Hover over a zone line, then click and drag to adjust."
            cv2.putText(frame, drag_text, (side_margin + 10, frame_height - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, info_text_white, 1, cv2.LINE_AA)


        # Display the frame
        window_name = 'E-Trike Passenger Counter'
        cv2.imshow(window_name, frame)
        cv2.setMouseCallback(window_name, adjust_zones_callback)


        # Press 'q' to exit
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    if use_picamera2 and picam2 is not None:
        try:
            picam2.stop()
        except Exception:
            pass
    elif cap is not None:
        cap.release()
    cv2.destroyAllWindows()

if __name__ == '__main__':
    # Load the YOLOv8 pose estimation model
    model = YOLO('yolov8n-pose.pt')
    run_detection(model) 