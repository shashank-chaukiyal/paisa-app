"""
app/services/sms_parser.py

Production-grade SMS parser for Indian bank & UPI messages.
Design:
  • Each bank has a named BankParser with ranked regex patterns.
  • Parser returns a ParseResult with confidence score.
  • Unknown messages return confidence=0 — never silently fail.
  • All amounts normalized to INTEGER PAISE to avoid float drift.

Supported senders (extendable):
  HDFC, SBI, ICICI, AXIS, KOTAK, PAYTM, PHONEPE, GOOGLEPAY, YESBANK, PNB
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import structlog

log = structlog.get_logger(__name__)

# ─── Data classes ─────────────────────────────────────────────────────

@dataclass
class ParseResult:
    success: bool
    bank_name: Optional[str] = None
    txn_type: Optional[str] = None                # "debit" | "credit"
    amount_paise: Optional[int] = None
    merchant: Optional[str] = None
    account_masked: Optional[str] = None
    reference_id: Optional[str] = None
    upi_vpa: Optional[str] = None
    balance_paise: Optional[int] = None
    txn_date: Optional[datetime] = None
    confidence: float = 0.0                       # 0.0–1.0
    error: Optional[str] = None
    raw_body: str = ""

    @property
    def amount_rupees(self) -> Optional[float]:
        if self.amount_paise is None:
            return None
        return self.amount_paise / 100


@dataclass
class BankPattern:
    name: str
    sender_patterns: list[str]                    # regex on sender
    debit_patterns: list[str]
    credit_patterns: list[str]
    amount_pattern: str = r"(?:Rs\.?|INR|₹)\s*([0-9,]+(?:\.[0-9]{1,2})?)"
    account_pattern: str = r"[Aa]/[Cc]\s*[Xx]{2,}\s*(\d{4})"
    ref_pattern: str = r"(?:Ref\s*(?:No|ID)?\.?\s*|UPI\s*Ref\s*No\s*:?\s*)([A-Z0-9]{6,25})"
    vpa_pattern: str = r"([\w.\-]+@[\w]+)"


# ─── Bank patterns ────────────────────────────────────────────────────

BANK_PATTERNS: list[BankPattern] = [
    BankPattern(
        name="HDFC",
        sender_patterns=[r"HDFCBK", r"HDFC", r"HDFCBNK"],
        debit_patterns=[
            r"(?:debited|deducted|spent|withdrawn)",
            r"is debited with",
            r"payment of",
        ],
        credit_patterns=[
            r"(?:credited|received|deposit)",
            r"is credited with",
        ],
    ),
    BankPattern(
        name="SBI",
        sender_patterns=[r"SBIINB", r"SBIPSG", r"SBI"],
        debit_patterns=[r"debited", r"payment made", r"withdrawn"],
        credit_patterns=[r"credited", r"received"],
        account_pattern=r"(?:A/c|Acc)\s*[Xx*]{2,}\s*(\d{4})",
    ),
    BankPattern(
        name="ICICI",
        sender_patterns=[r"ICICIB", r"ICICI"],
        debit_patterns=[r"debited", r"spent", r"payment"],
        credit_patterns=[r"credited", r"received", r"refund"],
    ),
    BankPattern(
        name="AXIS",
        sender_patterns=[r"AXISBK", r"AXIS"],
        debit_patterns=[r"debited", r"spent"],
        credit_patterns=[r"credited", r"deposit"],
    ),
    BankPattern(
        name="KOTAK",
        sender_patterns=[r"KOTAKB", r"KMB"],
        debit_patterns=[r"debited", r"withdrawn"],
        credit_patterns=[r"credited", r"received"],
    ),
    BankPattern(
        name="PAYTM",
        sender_patterns=[r"PAYTM", r"PYTMUPI"],
        debit_patterns=[r"paid", r"debited", r"sent"],
        credit_patterns=[r"received", r"added", r"cashback"],
        vpa_pattern=r"([\w.\-]+@paytm)",
    ),
    BankPattern(
        name="PHONEPE",
        sender_patterns=[r"PHONEP", r"PhonePe"],
        debit_patterns=[r"paid", r"sent", r"debited"],
        credit_patterns=[r"received", r"credited"],
        vpa_pattern=r"([\w.\-]+@ybl|[\w.\-]+@ibl)",
    ),
    BankPattern(
        name="GOOGLEPAY",
        sender_patterns=[r"GPAY", r"GooglePay", r"TEZAPP"],
        debit_patterns=[r"paid", r"sent"],
        credit_patterns=[r"received"],
        vpa_pattern=r"([\w.\-]+@okaxis|[\w.\-]+@okhdfcbank|[\w.\-]+@oksbi)",
    ),
    BankPattern(
        name="YESBANK",
        sender_patterns=[r"YESBK", r"YESBNK"],
        debit_patterns=[r"debited"],
        credit_patterns=[r"credited"],
    ),
    BankPattern(
        name="PNB",
        sender_patterns=[r"PNBSMS", r"PNB"],
        debit_patterns=[r"debited", r"withdrawn"],
        credit_patterns=[r"credited"],
    ),
]


# ─── Helpers ──────────────────────────────────────────────────────────

def _parse_amount(raw: str) -> int:
    """Convert '1,23,456.78' → 12345678 (paise)."""
    cleaned = raw.replace(",", "").strip()
    if "." in cleaned:
        rupees, paise_str = cleaned.split(".", 1)
        paise = int(paise_str.ljust(2, "0")[:2])
    else:
        rupees = cleaned
        paise = 0
    return int(rupees) * 100 + paise


def _detect_bank(sender: str, body: str, patterns: list[BankPattern]) -> Optional[BankPattern]:
    for bp in patterns:
        for sp in bp.sender_patterns:
            if re.search(sp, sender, re.IGNORECASE):
                return bp
    # Fallback: scan body for bank name clues
    for bp in patterns:
        if re.search(bp.name, body, re.IGNORECASE):
            return bp
    return None


def message_hash(user_id: str, device_id: str, body: str) -> str:
    """SHA-256 based dedup key for idempotency."""
    raw = f"{user_id}:{device_id}:{body.strip()}"
    return hashlib.sha256(raw.encode()).hexdigest()


# ─── Core parser ──────────────────────────────────────────────────────

class SmsParser:
    """
    Thread-safe, stateless SMS parser.
    All public methods are pure functions — safe to call from async workers.
    """

    def __init__(self):
        # Pre-compile patterns for performance
        self._compiled: dict[str, list[re.Pattern]] = {}

    def parse(self, sender: str, body: str, received_at: datetime | None = None) -> ParseResult:
        """
        Primary entry point.
        Returns ParseResult with confidence ∈ [0.0, 1.0].
        Never raises — errors are returned in ParseResult.error.
        """
        body_norm = body.strip()
        result = ParseResult(success=False, raw_body=body_norm)

        try:
            bank = _detect_bank(sender, body_norm, BANK_PATTERNS)
            if not bank:
                result.error = f"Unknown sender: {sender!r}"
                result.confidence = 0.0
                log.debug("sms_parser.unknown_sender", sender=sender)
                return result

            result.bank_name = bank.name
            result.confidence = 0.3  # bank identified

            # ── Determine transaction direction ────────────────────────
            is_debit = any(
                re.search(p, body_norm, re.IGNORECASE) for p in bank.debit_patterns
            )
            is_credit = any(
                re.search(p, body_norm, re.IGNORECASE) for p in bank.credit_patterns
            )

            if not (is_debit or is_credit):
                result.error = "No transaction direction detected"
                return result

            # Prefer explicit debit over ambiguous credit (e.g. "payment received")
            result.txn_type = "debit" if is_debit else "credit"
            result.confidence = 0.5

            # ── Amount ────────────────────────────────────────────────
            amt_match = re.search(bank.amount_pattern, body_norm, re.IGNORECASE)
            if not amt_match:
                result.error = "No amount found"
                return result

            result.amount_paise = _parse_amount(amt_match.group(1))
            result.confidence = 0.75

            # ── Account number ────────────────────────────────────────
            acc_match = re.search(bank.account_pattern, body_norm, re.IGNORECASE)
            if acc_match:
                result.account_masked = f"XX{acc_match.group(1)}"

            # ── Reference / UTR ───────────────────────────────────────
            ref_match = re.search(bank.ref_pattern, body_norm, re.IGNORECASE)
            if ref_match:
                result.reference_id = ref_match.group(1)

            # ── UPI VPA ───────────────────────────────────────────────
            vpa_match = re.search(bank.vpa_pattern, body_norm, re.IGNORECASE)
            if vpa_match:
                result.upi_vpa = vpa_match.group(1)

            # ── Merchant extraction (best-effort) ─────────────────────
            result.merchant = self._extract_merchant(body_norm, bank.name)

            # ── Available balance ──────────────────────────────────────
            bal_match = re.search(
                r"(?:Avl\s*Bal|Available\s*Balance|Bal)[:\s]*Rs\.?\s*([0-9,]+(?:\.[0-9]{1,2})?)",
                body_norm,
                re.IGNORECASE,
            )
            if bal_match:
                result.balance_paise = _parse_amount(bal_match.group(1))

            result.txn_date = received_at or datetime.utcnow()
            result.success = True
            result.confidence = 0.9 if result.reference_id else 0.82

            log.info(
                "sms_parser.parsed",
                bank=bank.name,
                type=result.txn_type,
                amount_paise=result.amount_paise,
                confidence=result.confidence,
                has_vpa=bool(result.upi_vpa),
                has_ref=bool(result.reference_id),
            )

        except Exception as exc:
            result.error = f"Parser exception: {exc}"
            result.confidence = 0.0
            log.exception("sms_parser.exception", sender=sender, exc=str(exc))

        return result

    def _extract_merchant(self, body: str, bank: str) -> Optional[str]:
        """
        Heuristic merchant extraction.
        Patterns ordered by specificity — first match wins.
        """
        patterns = [
            # UPI: "paid to Swiggy"
            r"(?:paid|sent|payment)\s+to\s+([A-Z][A-Za-z0-9\s&.,'-]{2,40}?)(?:\s+via|\s+on|\s+Ref|\.|\n|$)",
            # "at MERCHANT_NAME"
            r"at\s+([A-Z][A-Za-z0-9\s&.,'-]{2,40}?)(?:\s+on|\s+Ref|\.|\n|$)",
            # "towards MERCHANT"
            r"towards\s+([A-Z][A-Za-z0-9\s&.,'-]{2,40}?)(?:\s+Ref|\.|\n|$)",
        ]
        for pat in patterns:
            m = re.search(pat, body, re.IGNORECASE)
            if m:
                merchant = m.group(1).strip().rstrip(".,")
                if 2 < len(merchant) < 60:
                    return merchant
        return None


# ─── Singleton ────────────────────────────────────────────────────────

sms_parser = SmsParser()


# ─── Tests / examples ─────────────────────────────────────────────────

if __name__ == "__main__":
    samples = [
        ("HDFCBK", "Rs.1,500.00 debited from A/c XX1234 on 12-Mar-25. Info: UPI/SWIGGY. Avl Bal: Rs.45,231.00 Ref 412345678901 -HDFC Bank"),
        ("PYTMUPI", "You have paid Rs.250 to Swiggy via Paytm UPI. UPI Ref No: 502131234567"),
        ("SBIINB", "Your A/c No. XX6789 is debited with Rs.3,000.00 on 12/03/2025. Info: UPI/PhonePe. Avl Bal: INR 12,345.67"),
        ("ICICIB", "ICICI Bank: Rs 500.00 debited from A/c XX4567. Info: UPI/amazon. Ref No 312345678. Avl Bal Rs 8,765.00"),
        ("AXISBK", "INR 2000.00 debited from A/c No XX9876 on 12-03-2025. UPI Ref No 603212345678."),
        ("HDFCBK", "Rs.5,000.00 credited to your A/c XX1234 on 12-Mar-25 by UPI transfer. Ref 712345678. Avl Bal Rs.50,231.00"),
    ]

    parser = SmsParser()
    for sender, body in samples:
        r = parser.parse(sender, body, datetime.utcnow())
        print(
            f"[{sender}] {r.bank_name} | {r.txn_type} | "
            f"₹{(r.amount_paise or 0)/100:.2f} | "
            f"merchant={r.merchant} | "
            f"vpa={r.upi_vpa} | "
            f"conf={r.confidence:.2f} | "
            f"ok={r.success}"
        )
