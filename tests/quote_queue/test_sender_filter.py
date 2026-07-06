"""Unit de la regla de aceptación de submissions de ventas."""
from modules.quote_queue.sender_filter import is_processable_submission

RT = {"simon@h2oins.com", "esteban@h2oins.com"}
NV = {"duvan@h2oins.com", "veronica@h2oins.com"}


def test_rt_sender_existing_subject_ok():
    assert is_processable_submission(
        "simon@h2oins.com", "Submission // ACME LLC", RT, NV) is True


def test_rt_sender_new_venture_subject_rejected():
    assert is_processable_submission(
        "simon@h2oins.com", "Submission New Venture // ACME", RT, NV) is False


def test_new_venture_sender_new_venture_subject_ok():
    assert is_processable_submission(
        "duvan@h2oins.com", "Submission New Venture // ACME", RT, NV) is True


def test_new_venture_sender_existing_subject_rejected():
    assert is_processable_submission(
        "duvan@h2oins.com", "Submission // ACME", RT, NV) is False


def test_reply_subject_rejected():
    assert is_processable_submission(
        "simon@h2oins.com", "Re: Submission // ACME", RT, NV) is False


def test_forward_subject_rejected():
    assert is_processable_submission(
        "simon@h2oins.com", "Fwd: Submission // ACME", RT, NV) is False


def test_analysis_subject_rejected():
    assert is_processable_submission(
        "simon@h2oins.com", "[ANALISIS] Submission // ACME", RT, NV) is False


def test_unknown_sender_rejected():
    assert is_processable_submission(
        "ajeno@gmail.com", "Submission // ACME", RT, NV) is False


def test_case_insensitive_sender_and_subject():
    assert is_processable_submission(
        "Duvan@H2OINS.com", "SUBMISSION NEW VENTURE // X", RT, NV) is True


def test_empty_sets_reject_all():
    assert is_processable_submission(
        "simon@h2oins.com", "Submission // ACME", set(), set()) is False
