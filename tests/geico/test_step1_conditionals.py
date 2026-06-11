"""Step 1 conditional questions revealed by the business class (G-NUNEZ).

Live 2026-06-11: choosing 'Package Delivery' (AI-resolved from 'AMAZON
GOODS 100%') revealed two REQUIRED radio groups ('food-based transportation
network services...', 'deliver packages for Amazon?') and Next refused to
advance. The page must answer every revealed conditional from a defaults
table (warning on judgment-call defaults) and HALT loudly only on questions
we have never seen.
"""

from __future__ import annotations

from modules.geico.pages.business_class_page import _match_conditional_default


def test_food_tnc_defaults_no():
    answer, soft = _match_conditional_default(
        "Does the customer use their vehicle(s) for food-based "
        "transportation network services, like UberEats, DoorDash, or "
        "similar mobile apps?Please make a selection."
    )
    assert answer == "No"
    assert soft is False


def test_amazon_delivery_defaults_no_with_warning():
    answer, soft = _match_conditional_default(
        "Do you (or does your business) deliver packages for Amazon?"
    )
    assert answer == "No"
    assert soft is True  # judgment call -> must surface as a warning


def test_oil_fields_defaults_no_with_warning():
    answer, soft = _match_conditional_default(
        "Are any vehicles used to haul to or from oil and gas fields?"
    )
    assert answer == "No"
    assert soft is True


def test_filings_defaults_neither():
    answer, soft = _match_conditional_default(
        "Are you required to provide a state or federal filing for any of "
        "the vehicles you are insuring?"
    )
    assert answer == "Neither"


def test_team_driving_defaults_no():
    answer, _ = _match_conditional_default(
        "Do any of your customer's vehicles require team driving or slip "
        "seating to keep the business running?"
    )
    assert answer == "No"


def test_unknown_question_returns_none():
    answer, _ = _match_conditional_default(
        "Does the customer transport exotic animals across state lines?"
    )
    assert answer is None
