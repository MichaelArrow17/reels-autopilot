from reels_autopilot.topic_scout import safety_reason, heuristic_scores, total_score, THRESHOLD


def test_safety_rejects_sara():
    assert safety_reason("ujaran rasis terhadap suatu etnis") is not None


def test_safety_rejects_finance_promise():
    assert safety_reason("Investasi dijamin cuan pasti dalam seminggu") is not None


def test_safety_rejects_health_promise():
    assert safety_reason("Obat kanker ini menyembuhkan total") is not None


def test_safety_allows_ai_topic():
    assert safety_reason("Kenapa AI kadang ngarang fakta") is None


def test_score_formula_and_niche():
    item = {"judul": "Kenapa ChatGPT kadang ngarang fakta", "sumber": "evergreen_bank"}
    skor = heuristic_scores(item, n_sources=2)
    assert skor["niche_fit"] >= 6
    assert skor["curiosity_gap"] >= 6
    total = total_score(skor)
    assert 0 <= total <= 100
    assert total >= THRESHOLD or skor["niche_fit"] >= 6
