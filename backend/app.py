import os
import json
import random
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS

# --- Flask App Initialization ---
app = Flask(__name__, static_folder='../frontend', static_url_path='')
CORS(app)

# --- Configuration ---
DATA_DIR = "data"
TOURNAMENT_CONFIG_FILE = os.path.join(DATA_DIR, "tournament_config.json")
MATCH_SCHEDULE_FILE = os.path.join(DATA_DIR, "match_schedule.json")
MATCH_RESULTS_FILE = os.path.join(DATA_DIR, "match_results.json")
POINTS_TABLE_FILE = os.path.join(DATA_DIR, "points_table.json")

# --- Helper Functions ---
def ensure_data_dir():
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)

def load_json(filepath):
    try:
        with open(filepath, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None

def save_json(filepath, data):
    with open(filepath, 'w') as f:
        json.dump(data, f, indent=4)

def generate_round_robin_schedule(teams):
    if len(teams) % 2 != 0:
        teams.append("BYE")
    schedule = []
    for i in range(len(teams) - 1):
        for j in range(len(teams) // 2):
            match = (teams[j], teams[len(teams) - 1 - j])
            if "BYE" not in match:
                schedule.append(match)
        teams.insert(1, teams.pop())
    return schedule

def calculate_nrr(runs_for, overs_for, runs_against, overs_against):
    """Calculates Net Run Rate."""
    if overs_for == 0 or overs_against == 0:
        return 0.0
    run_rate_for = runs_for / overs_for
    run_rate_against = runs_against / overs_against
    return round(run_rate_for - run_rate_against, 3)

def simulate_innings_bot(overs):
    """Simulates a single innings and returns a detailed scorecard."""
    scorecard = {
        "runs": 0, "wickets": 0, "balls": 0,
        "extras": {"wides": 0, "noballs": 0, "byes": 0, "legbyes": 0},
        "breakdown": {"0": 0, "1": 0, "2": 0, "3": 0, "4": 0, "6": 0, "wickets": 0}
    }
    outcomes = [0, 1, 2, 3, 4, 6, 'W', 'WD', 'NB', 'B', 'LB']
    weights = [35, 30, 15, 5, 10, 3, 1, 0.5, 0.5, 2, 2]

    for _ in range(overs * 6):
        if scorecard["wickets"] >= 10:
            break
        
        outcome = random.choices(outcomes, weights=weights, k=1)[0]

        if outcome in ['WD', 'NB']:
            scorecard["runs"] += 1
            scorecard["extras"]["wides" if outcome == 'WD' else "noballs"] += 1
            continue

        scorecard["balls"] += 1
        
        if outcome == 'W':
            scorecard["wickets"] += 1
            scorecard["breakdown"]["wickets"] += 1
        elif outcome in ['B', 'LB']:
            scorecard["runs"] += 1
            scorecard["extras"]["byes" if outcome == 'B' else "legbyes"] += 1
        else:
            scorecard["runs"] += outcome
            scorecard["breakdown"][str(outcome)] += 1
            
    return scorecard

# --- API Endpoints ---
@app.route('/')
def serve_frontend():
    return send_from_directory(app.static_folder, 'index.html')

@app.route('/api/status', methods=['GET'])
def get_status():
    config = load_json(TOURNAMENT_CONFIG_FILE)
    return jsonify({"is_setup": config is not None})

@app.route('/api/setup', methods=['POST'])
def setup_tournament():
    data = request.json
    config = {"name": data['name'], "overs": int(data['overs']), "teams": data['teams']}
    save_json(TOURNAMENT_CONFIG_FILE, config)
    schedule = generate_round_robin_schedule(config["teams"].copy())
    save_json(MATCH_SCHEDULE_FILE, schedule)
    
    points_table = {
        team: {
            "played": 0, "won": 0, "lost": 0, "points": 0,
            "runs_for": 0, "overs_for": 0.0, "runs_against": 0, "overs_against": 0.0
        } for team in config["teams"]
    }
    save_json(POINTS_TABLE_FILE, points_table)
    save_json(MATCH_RESULTS_FILE, [])
    return jsonify({"success": True, "message": "Tournament setup successful!"})

@app.route('/api/schedule', methods=['GET'])
def get_schedule():
    schedule = load_json(MATCH_SCHEDULE_FILE)
    return jsonify(schedule or [])

@app.route('/api/simulate_next', methods=['POST'])
def simulate_next_match():
    schedule = load_json(MATCH_SCHEDULE_FILE)
    config = load_json(TOURNAMENT_CONFIG_FILE)
    if not schedule or not config:
        return jsonify({"error": "No tournament set up or no matches left."}), 400

    match = schedule.pop(0)
    team1, team2 = match
    
    scorecard1 = simulate_innings_bot(config["overs"])
    scorecard2 = simulate_innings_bot(config["overs"])
    
    winner = None
    if scorecard1['runs'] > scorecard2['runs']:
        winner = team1
    elif scorecard2['runs'] > scorecard1['runs']:
        winner = team2

    points_table = load_json(POINTS_TABLE_FILE)
    
    points_table[team1]["played"] += 1
    points_table[team1]["runs_for"] += scorecard1['runs']
    points_table[team1]["overs_for"] += scorecard1['balls'] / 6
    points_table[team1]["runs_against"] += scorecard2['runs']
    points_table[team1]["overs_against"] += scorecard2['balls'] / 6
    
    points_table[team2]["played"] += 1
    points_table[team2]["runs_for"] += scorecard2['runs']
    points_table[team2]["overs_for"] += scorecard2['balls'] / 6
    points_table[team2]["runs_against"] += scorecard1['runs']
    points_table[team2]["overs_against"] += scorecard1['balls'] / 6

    if winner:
        points_table[winner]["won"] += 1
        points_table[winner]["points"] += 2
        loser = team2 if winner == team1 else team1
        points_table[loser]["lost"] += 1
    else:
        points_table[team1]["points"] += 1
        points_table[team2]["points"] += 1

    for team in points_table:
        points_table[team]["nrr"] = calculate_nrr(
            points_table[team]["runs_for"], points_table[team]["overs_for"],
            points_table[team]["runs_against"], points_table[team]["overs_against"]
        )
        
    save_json(POINTS_TABLE_FILE, points_table)
    
    results = load_json(MATCH_RESULTS_FILE)
    results.append({
        "team1": team1, "scorecard1": scorecard1,
        "team2": team2, "scorecard2": scorecard2,
        "winner": winner
    })
    save_json(MATCH_RESULTS_FILE, results)
    save_json(MATCH_SCHEDULE_FILE, schedule)

    return jsonify({
        "success": True, 
        "result": {
            "team1": team1, "scorecard1": scorecard1,
            "team2": team2, "scorecard2": scorecard2,
            "winner": winner
        }
    })

@app.route('/api/points_table', methods=['GET'])
def get_points_table():
    points_table = load_json(POINTS_TABLE_FILE)
    config = load_json(TOURNAMENT_CONFIG_FILE)
    if not points_table:
        return jsonify({})
    sorted_teams = sorted(points_table.items(), key=lambda item: (-item[1]['points'], -item[1].get('nrr', 0), item[0]))
    return jsonify({"tournament_name": config.get('name', 'N/A'), "table": sorted_teams})

@app.route('/api/results', methods=['GET'])
def get_results():
    results = load_json(MATCH_RESULTS_FILE)
    return jsonify(results or [])

@app.route('/api/reset', methods=['POST'])
def reset_system():
    """Deletes all tournament data."""
    try:
        files_to_delete = [
            TOURNAMENT_CONFIG_FILE,
            MATCH_SCHEDULE_FILE,
            MATCH_RESULTS_FILE,
            POINTS_TABLE_FILE
        ]
        for f in files_to_delete:
            if os.path.exists(f):
                os.remove(f)
        return jsonify({"success": True, "message": "System has been reset successfully."})
    except Exception as e:
        return jsonify({"error": f"Failed to reset system: {e}"}), 500

# --- Main Runner ---
if __name__ == '__main__':
    ensure_data_dir()
    app.run(host='0.0.0.0', port=5000, debug=True)