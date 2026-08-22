import os
import json
import logging
from flask import Flask, request, jsonify

# Set up logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

app = Flask(__name__)

class ShowdownPhase2Engine:
    def __init__(self):
        self.current_match_id = None
        self.current_leg = None
        self.table_rule = None
        self.inferred_rules = {}

    def reset_for_new_leg(self, match_id, leg_number, table_rule):
        """Resets tracking state whenever a new leg or match begins."""
        self.current_match_id = match_id
        self.current_leg = leg_number
        self.table_rule = table_rule
        logging.info(f"Reset engine for new leg: match={match_id}, leg={leg_number}, rule={table_rule}")

    def analyze_showdowns(self, recent_hands):
        """Observes showdown results from recent_hands to infer rule behavior."""
        if not self.table_rule or not recent_hands:
            return

        rule_data = self.inferred_rules.setdefault(self.table_rule, {
            "observed_showdowns": []
        })

        for hand in recent_hands:
            shown = hand.get("shown_numbers", {})
            winners = hand.get("winners", [])
            comm = hand.get("community_number")

            if len(shown) == 2 and comm is not None and winners:
                obs = {
                    "seat_0_num": shown.get("0"),
                    "seat_1_num": shown.get("1"),
                    "comm": comm,
                    "winners": winners
                }
                if obs not in rule_data["observed_showdowns"]:
                    rule_data["observed_showdowns"].append(obs)

    def make_raise(self, legal_actions, amount, min_raise, max_raise):
        if "raise" in legal_actions or "bet" in legal_actions:
            target_action = "raise" if "raise" in legal_actions else "bet"
            if min_raise is not None and max_raise is not None:
                clamped_amount = max(min_raise, min(amount, max_raise))
                return {"action": target_action, "amount": int(clamped_amount)}
        return None

    def evaluate_showdown_move(self, data):
        match_id = data.get("match_id")
        leg_number = data.get("leg_number")
        table_rule = data.get("table_rule", "standard")
        recent_hands = data.get("recent_hands", [])

        # Detect new leg or new match and reset history state
        if match_id != self.current_match_id or leg_number != self.current_leg:
            self.reset_for_new_leg(match_id, leg_number, table_rule)

        # Learn from showdowns
        self.analyze_showdowns(recent_hands)

        legal_actions = data.get("legal_actions", [])
        your_num = data.get("your_number")
        comm_num = data.get("community_number")
        round_type = data.get("round")
        to_call = data.get("to_call", 0)
        min_raise = data.get("min_raise_to")
        max_raise = data.get("max_raise_to")

        if round_type == "post_reveal":
            has_pair = (your_num == comm_num)

            if has_pair:
                raise_act = self.make_raise(legal_actions, min_raise * 2 if min_raise else 10, min_raise, max_raise)
                if raise_act:
                    return raise_act
                if "call" in legal_actions:
                    return {"action": "call"}
                if "check" in legal_actions:
                    return {"action": "check"}

            if to_call == 0:
                if your_num >= 10:
                    raise_act = self.make_raise(legal_actions, min_raise, min_raise, max_raise)
                    if raise_act:
                        return raise_act
                return {"action": "check"}

            if your_num >= 11 and to_call <= 20:
                return {"action": "call"}
            elif your_num >= 8 and to_call <= 6:
                return {"action": "call"}

            return {"action": "fold"} if "fold" in legal_actions else {"action": "check"}

        else:  # pre_reveal
            if your_num >= 11:
                raise_act = self.make_raise(legal_actions, min_raise, min_raise, max_raise)
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


engine = ShowdownPhase2Engine()


@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok"}), 200


@app.route('/move', methods=['POST'])
def move():
    try:
        data = request.get_json(force=True)
        decision = engine.evaluate_showdown_move(data)
        return jsonify(decision), 200
    except Exception as e:
        logging.error(f"Error processing /move: {str(e)}")
        return jsonify({"action": "check"}), 200


if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
