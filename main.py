from fastapi import FastAPI, Request
from typing import List, Optional, Dict, Any

app = FastAPI(title="Showdown Phase 2 Bot - Reading the Table")

class ShowdownBot:
    def __init__(self):
        self.current_match_id: Optional[str] = None
        self.current_leg: Optional[int] = None
        self.table_rule: Optional[str] = None
        self.inferred_rules: Dict[str, Dict[str, Any]] = {}

    def reset_for_new_leg(self, match_id: str, leg_number: Optional[int], table_rule: str):
        self.current_match_id = match_id
        self.current_leg = leg_number
        self.table_rule = table_rule

    def analyze_showdowns(self, recent_hands: List[Dict[str, Any]]):
        if not self.table_rule or not recent_hands:
            return

        rule_data = self.inferred_rules.setdefault(self.table_rule, {
            "pair_beats_nonpair": True,
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

    def evaluate_hand_strength(self, your_num: int, comm_num: Optional[int], table_rule: str) -> float:
        if comm_num is None:
            return (your_num - 1) / 12.0

        is_pair = (your_num == comm_num)
        if is_pair:
            base_strength = 0.80 + (your_num / 13.0) * 0.20
        else:
            base_strength = (your_num / 13.0) * 0.75

        return base_strength

    def decide_action(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        match_id = payload.get("match_id")
        leg = payload.get("leg_number")
        rule = payload.get("table_rule", "standard")
        recent_hands = payload.get("recent_hands", [])

        if match_id != self.current_match_id or leg != self.current_leg:
            self.reset_for_new_leg(match_id, leg, rule)

        self.analyze_showdowns(recent_hands)

        legal_actions = payload.get("legal_actions", [])
        your_number = payload.get("your_number")
        community_number = payload.get("community_number")
        to_call = payload.get("to_call", 0)
        pot = payload.get("pot", 0)
        min_raise = payload.get("min_raise_to")
        max_raise = payload.get("max_raise_to")

        strength = self.evaluate_hand_strength(your_number, community_number, rule)
        pot_odds = to_call / (pot + to_call) if (pot + to_call) > 0 else 0.0

        if strength >= 0.80:
            if "raise" in legal_actions and min_raise is not None:
                target_raise = int(min_raise + (pot * 0.5))
                raise_amount = min(max(target_raise, min_raise), max_raise)
                return {"action": "raise", "amount": raise_amount}
            elif "bet" in legal_actions and min_raise is not None:
                return {"action": "bet", "amount": min_raise}
            elif "call" in legal_actions:
                return {"action": "call"}

        elif strength >= 0.45:
            if to_call == 0 and "check" in legal_actions:
                return {"action": "check"}
            elif "call" in legal_actions and (pot_odds <= 0.35 or to_call <= 10):
                return {"action": "call"}

        if to_call == 0 and "check" in legal_actions:
            return {"action": "check"}

        if "fold" in legal_actions:
            return {"action": "fold"}

        return {"action": "call"} if "call" in legal_actions else {"action": "check"}

bot = ShowdownBot()

@app.get("/health")
def health_check():
    return {"status": "ok"}

@app.post("/move")
async def move(request: Request):
    payload = await request.json()
    action = bot.decide_action(payload)
    return action
