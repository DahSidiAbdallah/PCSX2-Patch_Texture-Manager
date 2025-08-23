import pytest
from main import fmt_speed, fmt_eta


def test_fmt_speed_zero():
    assert fmt_speed(0) == '0 B/s'


def test_fmt_speed_bytes():
    assert fmt_speed(512) == '512 B/s'


def test_fmt_speed_kib():
    assert fmt_speed(2048) == '2.00 KiB/s'


def test_fmt_speed_none():
    assert fmt_speed(None) == '--'


def test_fmt_eta_none():
    assert fmt_eta(None) == '--:--'


def test_fmt_eta_seconds():
    assert fmt_eta(5) == '00:05'


def test_fmt_eta_minutes_seconds():
    assert fmt_eta(65) == '01:05'


def test_fmt_eta_hours():
    assert fmt_eta(3665) == '01:01:05'
