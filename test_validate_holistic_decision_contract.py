import unittest

from validate_holistic_decision_contract import validate_row


def valid_row(status="BET"):
    judgment = {
        "research_decision": status,
        "selected_side": "HOME",
        "supporting_facts": ["Player-specific fact"],
        "counterevidence": ["Opponent-specific counterpoint"],
        "uncertainties": ["Health status not independently verified"],
        "reasons_for_pass": ["Conflicting current-form evidence"],
        "source_refs": ["https://example.com/player"],
        "evidence_weighing": "The player-specific evidence was weighed before any price was collected.",
    }
    return {
        "status": status,
        "decision_frozen_at_utc": "2026-10-09T11:35:00Z",
        "decision_method_contract": "2026-10-09-holistic-deep-research-v1",
        "decision_frozen_before_price": True,
        "deep_research_judgment": judgment,
        "reason_code": "HOLISTIC_RESEARCH_SUPPORTS_SELECTION" if status == "BET" else "HOLISTIC_RESEARCH_INSUFFICIENT_CONVICTION",
        "price_reveal": {"captured_at_utc": "2026-10-09T11:36:00Z"},
        "expected_value": None,
    }


class HolisticDecisionContractTests(unittest.TestCase):
    def test_valid_bet(self):
        validate_row(valid_row())

    def test_valid_pass_preserves_target(self):
        validate_row(valid_row("PASS"))

    def test_rejects_ev_reason(self):
        row = valid_row("PASS")
        row["reason_code"] = "NEGATIVE_EV"
        with self.assertRaisesRegex(ValueError, "price/EV-dependent"):
            validate_row(row)

    def test_rejects_price_before_decision(self):
        row = valid_row()
        row["price_reveal"]["captured_at_utc"] = "2026-10-09T11:33:00Z"
        with self.assertRaisesRegex(ValueError, "price was captured before"):
            validate_row(row)

    def test_rejects_missing_pass_reason(self):
        row = valid_row("PASS")
        row["deep_research_judgment"]["reasons_for_pass"] = []
        with self.assertRaisesRegex(ValueError, "reasons_for_pass"):
            validate_row(row)


if __name__ == "__main__":
    unittest.main()
