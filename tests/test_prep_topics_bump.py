"""Пороги бампа готовности тем: weak→medium за 1, medium→confident за 2."""

from core.domains.preparation.prep_topics import apply_review_bump


def test_weak_to_medium_after_one_review():
    level, packs = apply_review_bump("weak", 0)
    assert level == "medium"
    assert packs == 0


def test_medium_stays_after_first_review():
    level, packs = apply_review_bump("medium", 0)
    assert level == "medium"
    assert packs == 1


def test_medium_to_confident_after_two_reviews():
    level, packs = apply_review_bump("medium", 1)
    assert level == "confident"
    assert packs == 0


def test_confident_only_increments_counter():
    level, packs = apply_review_bump("confident", 5)
    assert level == "confident"
    assert packs == 6
