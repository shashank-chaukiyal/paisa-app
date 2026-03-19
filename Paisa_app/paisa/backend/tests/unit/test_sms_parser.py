"""
tests/unit/test_sms_parser.py
Unit tests for the SMS parser — regression coverage for known bank formats.
"""
import pytest
from datetime import datetime
from app.services.sms_parser import SmsParser, _parse_amount, message_hash

parser = SmsParser()
NOW = datetime(2025, 3, 12, 10, 0, 0)


# ─── Amount parsing ───────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected_paise", [
    ("1,500.00", 150_000),
    ("500", 50_000),
    ("1,23,456.78", 12_345_678),
    ("10.50", 1_050),
    ("1000000", 100_000_000),
])
def test_parse_amount(raw, expected_paise):
    assert _parse_amount(raw) == expected_paise


# ─── HDFC ─────────────────────────────────────────────────────────────

def test_hdfc_debit():
    r = parser.parse(
        "HDFCBK",
        "Rs.1,500.00 debited from A/c XX1234 on 12-Mar-25. Info: UPI/SWIGGY. Avl Bal: Rs.45,231.00 Ref 412345678901",
        NOW,
    )
    assert r.success is True
    assert r.txn_type == "debit"
    assert r.amount_paise == 150_000
    assert r.account_masked == "XX1234"
    assert r.reference_id == "412345678901"
    assert r.bank_name == "HDFC"
    assert r.balance_paise == 4_523_100
    assert r.confidence >= 0.8


def test_hdfc_credit():
    r = parser.parse(
        "HDFCBK",
        "Rs.5,000.00 credited to your A/c XX1234 on 12-Mar-25 by UPI transfer. Ref 712345678. Avl Bal Rs.50,231.00",
        NOW,
    )
    assert r.success is True
    assert r.txn_type == "credit"
    assert r.amount_paise == 500_000


# ─── SBI ──────────────────────────────────────────────────────────────

def test_sbi_debit():
    r = parser.parse(
        "SBIINB",
        "Your A/c No. XX6789 is debited with Rs.3,000.00 on 12/03/2025. Info: UPI/PhonePe. Avl Bal: INR 12,345.67",
        NOW,
    )
    assert r.success is True
    assert r.txn_type == "debit"
    assert r.amount_paise == 300_000
    assert r.bank_name == "SBI"


# ─── Paytm UPI ────────────────────────────────────────────────────────

def test_paytm_upi():
    r = parser.parse(
        "PYTMUPI",
        "You have paid Rs.250 to Swiggy via Paytm UPI. UPI Ref No: 502131234567",
        NOW,
    )
    assert r.success is True
    assert r.txn_type == "debit"
    assert r.amount_paise == 25_000
    assert r.reference_id == "502131234567"
    assert r.merchant is not None
    assert "Swiggy" in (r.merchant or "")


# ─── Unknown sender ───────────────────────────────────────────────────

def test_unknown_sender():
    r = parser.parse("MYNTRA", "Your order has been shipped", NOW)
    assert r.success is False
    assert r.confidence == 0.0


# ─── Low confidence — no amount ───────────────────────────────────────

def test_no_amount():
    r = parser.parse(
        "HDFCBK",
        "Your account has been debited. Please check your bank app for details.",
        NOW,
    )
    assert r.success is False
    assert r.confidence < 0.7


# ─── Message hash idempotency ──────────────────────────────────────────

def test_message_hash_deterministic():
    h1 = message_hash("user-1", "device-A", "Rs.500 debited")
    h2 = message_hash("user-1", "device-A", "Rs.500 debited")
    h3 = message_hash("user-1", "device-B", "Rs.500 debited")
    assert h1 == h2
    assert h1 != h3
    assert len(h1) == 64  # SHA-256 hex


# ─── Merchant extraction ──────────────────────────────────────────────

def test_merchant_extraction():
    r = parser.parse(
        "ICICIB",
        "ICICI Bank: Rs 500.00 debited from A/c XX4567. Info: UPI/amazon@icici. paid to Amazon India Ref No 312345678.",
        NOW,
    )
    assert r.success is True
    assert r.merchant is not None
