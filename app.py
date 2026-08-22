import logging
from flask import Flask, request, jsonify

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

app = Flask(__name__)

# Cache known rules across requests: { codename: winning_rule_id }
DISCOVERED_RULES = {}

def get_possible_rules():
    """Returns candidate showdown comparison functions."""
    return {
        "STANDARD": lambda y, c, o: (1 if y == c else 0, y) > (1 if o == c else 0, o),
        "REVERSE": lambda y, c, o: (1 if y == c else 0, y) < (1 if o == c else 0, o),
        "LOW_CARD": lambda y, c, o: (1 if y == c else 0, -y) > (1 if o == c else 0, -o),
        "ODD_BEATS_EVEN": lambda y, c, o: (y % 2, y) > (o % 2, o),
        "EVEN_BEATS_ODD": lambda y, c, o: (1 - (y % 2), y) > (1 - (o % 2), o),
        "NO_PAIRS_HIGH": lambda y, c, o: (0 if y == c else 1, y) > (0 if o == c else 1, o),
        "SUM_CLOSEST_TO_13": lambda y, c, o: -abs((y + (c or 0)) - 13) > -abs((o + (c or 0)) - 13)
    }

def infer_table_rule(codename, recent_hands):
    """
    Deduces which rule governs the match by evaluating past showdowns in recent_hands.
    """
    if codename in DISCOVERED_RULES:
        return DISCOVERED_RULES[codename]

    candidates = get_possible_rules()
    valid_candidates = set(candidates.keys())

    for hand in recent_hands:
        shown = hand.get("shown_numbers", {})
        winners = hand.get("winners", [])
        comm = hand.get("community_number")

        # Evaluate only completed showdowns with 2 revealed hands
        if len(shown) == 2 and comm is not None:
            seats = list(shown.keys())
            p0, p1 = int(seats[0]), int(seats[1])
            num0, num1 = shown[seats[0]], shown[seats[1]]

            for rule_id in list(valid_candidates):
                rule_fn = candidates[rule_id]
                
                # Check if rule predicts seat 0 winning over seat 1
                p0_wins = rule_fn(num0, comm, num1)
                actual_p0_wins = (p0 in winners) and (p1 not in winners)

                if p0_wins != actual_p0_wins:
                    valid_candidates.discard(rule_id)

    if len(valid_candidates) == 1:
        chosen_rule = list(valid_candidates)[0]
        DISCOVERED_RULES[codename] = chosen_rule
        return chosen_rule

    return "STANDARD"  # Default assumption until enough evidence is gathered

def calculate_equity(your_num, comm_num, round_type, rule_id):
    """Calculates approximate win probability against an opponent holding [1..13]."""
    rule_fn = get_possible_rules().get(rule_id, get_possible_rules()["STANDARD"])

    if round_type == "post_reveal":
        wins, ties, total = 0, 0, 13
        for opp_num in range(1, 14):
            if opp_num == your_num:
                total -= 1
                continue
            
            you_win = rule_fn(your_num, comm_num, opp_num)
            opp_win = rule_fn(opp_num, comm_num, your_num)

            if you_win and not opp_win:
                wins += 1
            elif not you_win and not opp_win:
                ties += 1

        return (wins + 0.5 * ties) / total

    # Pre-reveal estimate (averaging over all potential community cards)
    wins = 0
    total_sims = 13 * 13
    for sim_comm in range(1, 14):
        for opp_num in range(1, 14):
            if rule_fn(your_num, sim_comm, opp_num):
                wins += 1

    return wins / total_sims

def make_safe_raise(legal_actions, target_amount, min_raise, max_raise):
    action_type = "raise" if "raise" in legal_actions else ("bet" if "bet" in legal_actions else None)
    if action_type and min_raise is not None and max_raise is not None:
        clamped = max(min_raise, min(target_amount, max_raise))
        return {"action": action_type, "amount": int(clamped)}
    return None

def decide_move(data):
    legal_actions = data.get("legal_actions", [])
    your_num = data.get("your_number")
    comm_num = data.get("community_number")
    round_type = data.get("round")
    to_call = data.get("to_call", 0)
    min_raise = data.get("min_raise_to")
    max_raise = data.get("max_raise_to")
    table_rule = data.get("table_rule", "unknown")
    recent_hands = data.get("recent_hands", [])
    chip_delta = data.get("players", [{}, {}])[0].get("chip_delta", 0)

    # 1. Deduce rule
    active_rule = infer_table_rule(table_rule, recent_hands)

    # 2. Calculate equity based on deduced rule
    equity = calculate_equity(your_num, comm_num, round_type, active_rule)

    # 3. Dynamic adjustment if target (+25 chip delta per leg) is already hit
    target_reached = chip_delta >= 25
    
    # 4. Action decision tree
    if equity >= 0.80:
        # Strong hand: Raise heavily
        raise_amount = min_raise * 2 if min_raise else 12
        move = make_safe_raise(legal_actions, raise_amount, min_raise, max_raise)
        if move:
            return move
        if "call" in legal_actions:
            return {"action": "call"}

    elif equity >= 0.55:
        # Moderate hand: Play passively if target reached, otherwise value bet
        if target_reached and to_call > 6:
            return {"action": "fold"} if "fold" in legal_actions else {"action": "check"}
        
        if to_call == 0:
            return {"action": "check"}
        if to_call <= 10 and "call" in legal_actions:
            return {"action": "call"}

    # Weak hand
    if to_call == 0:
        return {"action": "check"}
    
    # Small call allowance for pot odds
    if to_call <= 2 and equity >= 0.40 and "call" in legal_actions:
        return {"action": "call"}

    return {"action": "fold"} if "fold" in legal_actions else {"action": "check"}

@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok"}), 200

@app.route('/move', methods=['POST'])
def move():
    try:
        data = request.get_json(force=True)
        response = decide_move(data)
        return jsonify(response), 200
    except Exception as e:
        logging.error(f"Error in /move: {str(e)}")
        return jsonify({"action": "check"}), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
