import os
import logging
from flask import Flask, request, jsonify

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

app = Flask(__name__)

class RobustShowdownBot:
    def __init__(self):
        self.current_match_id = None
        self.current_leg = None
        self.table_rule = None

    def reset_leg(self, match_id, leg_number, table_rule):
        self.current_match_id = match_id
        self.current_leg = leg_number
        self.table_rule = table_rule
        logging.info(f"Resetting state: match={match_id}, leg={leg_number}, rule={table_rule}")

    def evaluate_move(self, data):
        match_id = data.get("match_id")
        leg_number = data.get("leg_number")
        table_rule = data.get("table_rule", "standard")

        # Handle Leg / Match transitions
        if match_id != self.current_match_id or leg_number != self.current_leg:
            self.reset_leg(match_id, leg_number, table_rule)

        legal_actions = data.get("legal_actions", [])
        your_num = data.get("your_number")
        comm_num = data.get("community_number")
        round_type = data.get("round")
        to_call = data.get("to_call", 0)
        min_raise = data.get("min_raise_to")
        max_raise = data.get("max_raise_to")

        # Helper for valid bets/raises
        def safe_raise(target_amount):
            if ("raise" in legal_actions or "bet" in legal_actions) and min_raise is not None and max_raise is not None:
                act = "raise" if "raise" in legal_actions else "bet"
                clamped = max(min_raise, min(target_amount, max_raise))
                return {"action": act, "amount": int(clamped)}
            return None

        # 1. Post-Reveal Strategy
        if round_type == "post_reveal":
            is_pair = (your_num == comm_num)

            if is_pair:
                raise_move = safe_raise(min_raise * 2 if min_raise else 10)
                if raise_move:
                    return raise_move
                if "call" in legal_actions:
                    return {"action": "call"}

            if to_call == 0:
                if your_num >= 10:
                    raise_move = safe_raise(min_raise)
                    if raise_move:
                        return raise_move
                if "check" in legal_actions:
                    return {"action": "check"}

            if your_num >= 10 and to_call <= 15:
                if "call" in legal_actions:
                    return {"action": "call"}

            return {"action": "fold"} if "fold" in legal_actions else {"action": "check"}

        # 2. Pre-Reveal Strategy
        else:
            if your_num >= 11:
                raise_move = safe_raise(min_raise)
                if raise_move:
                    return raise_move
                if "call" in legal_actions:
                    return {"action": "call"}

            if to_call == 0:
                if "check" in legal_actions:
                    return {"action": "check"}

            if your_num >= 6 or to_call <= 2:
                if "call" in legal_actions:
                    return {"action": "call"}

            return {"action": "fold"} if "fold" in legal_actions else {"action": "check"}

bot = RobustShowdownBot()

@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok"}), 200

@app.route('/move', methods=['POST'])
def move():
    try:
        data = request.get_json(force=True)
        decision = bot.evaluate_move(data)
        return jsonify(decision), 200
    except Exception as e:
        logging.error(f"Error in /move: {str(e)}")
        return jsonify({"action": "check"}), 200

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
