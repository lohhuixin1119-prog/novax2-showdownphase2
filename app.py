import base64
import json
import logging
from flask import Flask, request, jsonify

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

app = Flask(__name__)

# Global memory across requests to track showdown results per codename
# Schema: { codename: [ {"player_num": X, "comm_num": Y, "won": True/False}, ... ] }
RULE_KNOWLEDGE = {}

def make_raise(legal_actions, amount, min_raise, max_raise):
    if "raise" in legal_actions or "bet" in legal_actions:
        target_action = "raise" if "raise" in legal_actions else "bet"
        if min_raise is not None and max_raise is not None:
            clamped_amount = max(min_raise, min(amount, max_raise))
            return {"action": target_action, "amount": int(clamped_amount)}
    return None

def analyze_recent_hands(table_rule, recent_hands):
    """Analyzes showdowns in recent_hands to infer if pairs or high numbers win."""
    if table_rule not in RULE_KNOWLEDGE:
        RULE_KNOWLEDGE[table_rule] = []

    for hand in recent_hands:
        shown = hand.get("shown_numbers", {})
        winners = hand.get("winners", [])
        comm = hand.get("community_number")

        # Only evaluate actual showdowns with complete card information
        if len(shown) >= 2 and comm is not None:
            for seat_str, num in shown.items():
                seat = int(seat_str)
                did_win = seat in winners
                entry = {"num": num, "comm": comm, "pair": (num == comm), "won": did_win}
                if entry not in RULE_KNOWLEDGE[table_rule]:
                    RULE_KNOWLEDGE[table_rule].append(entry)

def evaluate_strength(your_num, comm_num, table_rule):
    """
    Returns an estimated hand strength score (0 to 100) based on observed showdowns.
    """
    history = RULE_KNOWLEDGE.get(table_rule, [])
    has_pair = (your_num == comm_num) if comm_num is not None else False

    # Default assumption if insufficient data: Standard Rules
    if len(history) < 3:
        if comm_num is not None:
            return 90 if has_pair else (your_num / 13.0) * 60
        return (your_num / 13.0) * 70

    # Dynamic Analysis based on observed winners
    pair_wins = [h for h in history if h["pair"] and h["won"]]
    pair_losses = [h for h in history if h["pair"] and not h["won"]]
    
    # Check if pairs are good or bad under this codename
    pairs_are_strong = len(pair_wins) >= len(pair_losses)

    if comm_num is not None:
        if has_pair:
            return 95 if pairs_are_strong else 10
        
        # Check high card vs low card trends
        high_card_winners = [h["num"] for h in history if h["won"] and not h["pair"]]
        if high_card_winners:
            avg_win_num = sum(high_card_winners) / len(high_card_winners)
            # Higher numbers winning -> high card rule
            if avg_win_num > 7:
                return (your_num / 13.0) * 80
            else:
                # Lower numbers winning -> low card rule
                return ((14 - your_num) / 13.0) * 80

    return (your_num / 13.0) * 50

def evaluate_showdown_move(data):
    legal_actions = data.get("legal_actions", [])
    your_num = data.get("your_number")
    comm_num = data.get("community_number")
    round_type = data.get("round")
    to_call = data.get("to_call", 0)
    min_raise = data.get("min_raise_to")
    max_raise = data.get("max_raise_to")
    table_rule = data.get("table_rule", "standard")
    recent_hands = data.get("recent_hands", [])

    # Update knowledge base with completed showdowns
    analyze_recent_hands(table_rule, recent_hands)

    strength = evaluate_strength(your_num, comm_num, table_rule)

    # Post-reveal logic
    if round_type == "post_reveal":
        if strength >= 85:
            raise_act = make_raise(legal_actions, min_raise * 2 if min_raise else 10, min_raise, max_raise)
            if raise_act:
                return raise_act
            if "call" in legal_actions:
                return {"action": "call"}

        if to_call == 0:
            if strength >= 60:
                raise_act = make_raise(legal_actions, min_raise, min_raise, max_raise)
                if raise_act:
                    return raise_act
            return {"action": "check"}

        if strength >= 70 and to_call <= 20:
            return {"action": "call"}
        elif strength >= 50 and to_call <= 6:
            return {"action": "call"}

        return {"action": "fold"} if "fold" in legal_actions else {"action": "check"}

    # Pre-reveal logic
    else:
        if your_num >= 11:
            raise_act = make_raise(legal_actions, min_raise, min_raise, max_raise)
            if raise_act:
                return raise_act
            if "call" in legal_actions:
                return {"action": "call"}

        if to_call == 0:
            return {"action": "check"}

        if your_num >= 6 or to_call <= 2:
            if "call" in legal_actions:
                return {"action": "call"}

        return {"action": "fold"} if "fold" in legal_actions else {"action": "check"}

@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok"}), 200

@app.route('/move', methods=['POST'])
def move():
    try:
        data = request.get_json(force=True)
        decision = evaluate_showdown_move(data)
        return jsonify(decision), 200
    except Exception as e:
        logging.error(f"Error processing /move: {str(e)}")
        return jsonify({"action": "check"}), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
