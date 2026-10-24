"""Company facts from the organizer CSVs: revenue, group, products, top counterparty.

Files are semicolon-separated: df_Uid_data_hack.csv and df_Uid_payment_hack.csv.
Set COMPANY_DIR to the folder that contains them. A name that is not a U_ id returns nothing.
"""
import csv
import os
from pathlib import Path

DEFAULT = Path(__file__).resolve().parents[1] / "external-docs" / "company"
MARKS = {
    "CL_PRODUCT_LOA_MARK": "кредит",
    "CL_PRODUCT_LEA_MARK": "лизинг",
    "CL_PRODUCT_DEP_MARK": "депозиты",
    "CL_PRODUCT_ZPP_MARK": "зарплатный проект",
    "CL_PRODUCT_RKO_MARK": "расчётный счёт",
    "CL_PRODUCT_GAR_MARK": "гарантии",
    "FACTORING_MARK": "факторинг",
}
_CACHE: dict[str, tuple[dict, dict]] = {}


def _dir() -> Path:
    return Path(os.environ.get("COMPANY_DIR", DEFAULT))


def _money(value: float) -> str:
    if value >= 1e9:
        return f"{value / 1e9:.1f} млрд руб."
    if value >= 1e6:
        return f"{value / 1e6:.0f} млн руб."
    return f"{value:.0f} руб."


def _tables() -> tuple[dict, dict]:
    folder = str(_dir())
    if folder in _CACHE:
        return _CACHE[folder]
    data = _dir() / "df_Uid_data_hack.csv"
    pays = _dir() / "df_Uid_payment_hack.csv"
    if not data.is_file():
        return {}, {}
    companies = {}
    groups: dict[str, int] = {}
    with data.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f, delimiter=";"):
            companies[row["SYNTHETIC_U"]] = row
            gid = row.get("GROUP_ID") or ""
            if gid:
                groups[gid] = groups.get(gid, 0) + 1
    incoming: dict[str, dict[str, float]] = {}
    if pays.is_file():
        with pays.open(encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f, delimiter=";"):
                ben, payer = row["BENEFICIARY"], row["PAYER"]
                if ben == payer:
                    continue
                try:
                    amt = float(row["PAY_AMT"])
                except ValueError:
                    continue
                incoming.setdefault(ben, {})
                incoming[ben][payer] = incoming[ben].get(payer, 0) + amt
    _CACHE[folder] = (companies, {"groups": groups, "incoming": incoming})
    return _CACHE[folder]


_KEYS = {
    "CL_PRODUCT_LOA_MARK": "credit",
    "CL_PRODUCT_LEA_MARK": "leasing",
    "CL_PRODUCT_DEP_MARK": "deposits",
}


def card(uid: str, role: str = "CFO") -> dict | None:
    """Profile dict for the chain. None when this id is not in the organizer file."""
    from reasoning.data import okved_section
    uid = (uid or "").strip()
    companies, _extra = _tables()
    row = companies.get(uid)
    if not row:
        return None
    try:
        revenue = float(row["REVENUE_COMPANY"])
    except ValueError:
        revenue = 0
    return {
        "id": uid, "synthetic_u": uid, "role": role,
        "okved": okved_section(row["MAINOKVED_CODE"]),
        "okved_code": row["MAINOKVED_CODE"],
        "okved_name": row["MAINOKVED_NAME"],
        "region": row.get("REGION") or "",
        "products": [key for col, key in _KEYS.items() if row.get(col) in ("1", "1.0")],
        "label": uid,
        "date_label": f"выручка {_money(revenue)}, {row.get('CITY') or ''}".strip(" ,"),
    }


def line(uid: str) -> str:
    """One sentence of bank facts. Empty when the id is unknown or the files are absent."""
    uid = (uid or "").strip()
    if not uid.startswith("U_"):
        return ""
    companies, extra = _tables()
    row = companies.get(uid)
    if not row:
        return ""
    try:
        revenue = float(row["REVENUE_COMPANY"])
    except ValueError:
        revenue = 0
    products = [name for col, name in MARKS.items() if row.get(col) in ("1", "1.0")]
    gid = row.get("GROUP_ID") or ""
    n = extra["groups"].get(gid, 1) if gid else 1
    text = (
        f"{uid}: ОКВЭД {row['MAINOKVED_CODE']} {row['MAINOKVED_NAME']}, "
        f"{row['CITY']}, {row['REGION']}, выручка {_money(revenue)}, "
        f"группа {gid or 'нет'} ({n} комп.), продукты: {', '.join(products) or 'нет'}."
    )
    payers = extra["incoming"].get(uid) or {}
    if payers:
        top = max(payers, key=payers.get)
        share = 100 * payers[top] / sum(payers.values())
        other = companies.get(top, {})
        name = other.get("MAINOKVED_NAME") or "отрасль неизвестна"
        text += f" Крупнейший внешний плательщик {top} ({name}) — {share:.0f}% внешних входящих платежей."
    country = (row.get("FTS_COUNTRY_NAME") or "").strip()
    if row.get("FTS_FLAG") in ("1", "1.0") and country:
        text += f" Внешняя торговля: {country}."
    return text
