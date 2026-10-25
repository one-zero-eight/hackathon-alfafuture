"""Company profile from the organisers' anonymised bank data (semicolon CSV, not in git):
df_Uid_data_hack.csv (one row per company) and df_Uid_payment_hack.csv (payments between companies).

profile(uid) -> what the search needs (a description instead of a name) and what the analytics needs (OKVED, region, products, facts).
"""
import csv
import os
from collections import defaultdict
from pathlib import Path

PRODUCTS = {"CL_PRODUCT_RKO_MARK": ("расчётный счёт", None), "CL_PRODUCT_GAR_MARK": ("банковские гарантии", None),
            "CL_PRODUCT_LOA_MARK": ("кредиты", "credit"), "CL_PRODUCT_LEA_MARK": ("лизинг", "leasing"),
            "CL_PRODUCT_DEP_MARK": ("депозиты", "deposits"), "CL_PRODUCT_ZPP_MARK": ("зарплатный проект", None),
            "FACTORING_MARK": ("факторинг", None)}
SECTIONS = ((3, "A"), (9, "B"), (33, "C"), (35, "D"), (39, "E"), (43, "F"), (47, "G"), (53, "H"), (56, "I"), (63, "J"), (66, "K"),
            (68, "L"), (75, "M"), (82, "N"), (84, "O"), (85, "P"), (88, "Q"), (93, "R"), (96, "S"), (98, "T"), (99, "U"))


class CompanyUnavailable(LookupError):
    pass


def okved_section(code: str) -> str:
    """OKVED2 class (the number before the dot) to its section letter."""
    try:
        n = int(str(code).split(".")[0])
    except ValueError:
        return ""
    return next((section for high, section in SECTIONS if n <= high), "")


def _flag(value) -> bool:
    try:
        return float(value or 0) > 0
    except ValueError:
        return False


def _money(value: float) -> str:
    if value >= 1e9:
        return f"{value / 1e9:.1f} млрд руб."
    if value >= 1e6:
        return f"{value / 1e6:.0f} млн руб."
    return f"{value:.0f} руб."


class CompanyBook:
    def __init__(self, directory=None):
        self.dir = Path(directory or os.environ.get("COMPANY_DIR", "/company"))
        self._rows: dict[str, dict] | None = None
        self._groups: dict[str, int] = {}
        self._profiles: dict[str, dict] = {}

    def _load(self):
        if self._rows is None:
            path = self.dir / "df_Uid_data_hack.csv"
            if not path.is_file():
                raise CompanyUnavailable(f"company data not found: {path}")
            with path.open(encoding="utf-8", newline="") as f:
                self._rows = {r["SYNTHETIC_U"]: r for r in csv.DictReader(f, delimiter=";")}
            for r in self._rows.values():
                if r.get("GROUP_ID"):
                    self._groups[r["GROUP_ID"]] = self._groups.get(r["GROUP_ID"], 0) + 1
        return self._rows

    def listing(self, q: str, offset: int, limit: int) -> dict:
        """Companies for the picker, in file order; q is a case-insensitive substring of the id or the OKVED name."""
        q = q.strip().lower()
        hits = [{"id": uid, "okved_name": r["MAINOKVED_NAME"]} for uid, r in self._load().items()
                if not q or q in uid.lower() or q in r["MAINOKVED_NAME"].lower()]
        return {"total": len(hits), "items": hits[offset:offset + limit]}

    def _payments(self, uid):
        """One pass over the payments: top OKVED names of suppliers (uid pays) and customers (pay uid), and uid's incoming payers."""
        rows, suppliers, customers, incoming = self._load(), defaultdict(float), defaultdict(float), defaultdict(float)
        path = self.dir / "df_Uid_payment_hack.csv"
        if path.is_file():
            with path.open(encoding="utf-8", newline="") as f:
                for r in csv.DictReader(f, delimiter=";"):
                    payer, beneficiary = r["PAYER"], r["BENEFICIARY"]
                    if payer == beneficiary or uid not in (payer, beneficiary):
                        continue
                    try:
                        amount = float(r["PAY_AMT"] or 0)
                    except ValueError:
                        continue
                    other, side = (beneficiary, suppliers) if payer == uid else (payer, customers)
                    if rows.get(other, {}).get("MAINOKVED_NAME"):
                        side[rows[other]["MAINOKVED_NAME"]] += amount
                    if beneficiary == uid:
                        incoming[payer] += amount
        top = lambda d: [name for name, _ in sorted(d.items(), key=lambda x: -x[1])[:3]]
        return top(suppliers), top(customers), incoming

    def profile(self, uid: str) -> dict:
        if uid in self._profiles:
            return self._profiles[uid]
        r = self._load().get(uid)
        if r is None:
            raise CompanyUnavailable(f"company {uid} not found")
        suppliers, customers, incoming = self._payments(uid)
        marks = [(ru, key) for col, (ru, key) in PRODUCTS.items() if _flag(r.get(col))]
        try:
            revenue = float(r["REVENUE_COMPANY"])
        except (KeyError, ValueError):
            revenue = 0
        size = r.get("AMOUNT_WORKERS_FNS_GRADATION") or r.get("AMOUNT_WORKERS_SPARK_GRADATION")
        abroad = (r.get("FTS_COUNTRY_NAME") or "").strip()
        parts = [f"компания, ОКВЭД {r['MAINOKVED_CODE']} «{r['MAINOKVED_NAME']}»", f"{r['CITY']}, {r['REGION']}".strip(", ")]
        if size:
            parts.append(f"сотрудников: {size}")
        if r.get("COMPANY_AGE_YEARS_GRADATION"):
            parts.append(f"возраст {r['COMPANY_AGE_YEARS_GRADATION']} лет")
        if _flag(r.get("FTS_FLAG")):
            parts.append("ведёт внешнеэкономическую деятельность" + (f" ({abroad})" if abroad else ""))
        if suppliers:
            parts.append("основные поставщики: " + "; ".join(suppliers))
        if customers:
            parts.append("основные покупатели: " + "; ".join(customers))
        group = r.get("GROUP_ID") or ""
        facts = (f"{uid}: ОКВЭД {r['MAINOKVED_CODE']} {r['MAINOKVED_NAME']}, {r['CITY']}, {r['REGION']}, выручка {_money(revenue)}, "
                 f"группа {group or 'нет'} ({self._groups.get(group, 1) if group else 1} комп.), продукты: {', '.join(ru for ru, _ in marks) or 'нет'}.")
        if incoming:
            top = max(incoming, key=incoming.get)
            facts += (f" Крупнейший внешний плательщик {top} ({self._load().get(top, {}).get('MAINOKVED_NAME') or 'отрасль неизвестна'}) —"
                      f" {100 * incoming[top] / sum(incoming.values()):.0f}% внешних входящих платежей.")
        if _flag(r.get("FTS_FLAG")) and abroad:
            facts += f" Внешняя торговля: {abroad}."
        self._profiles[uid] = {
            "uid": uid, "label": r["CITY"] or "Компания",  # the synthetic id never reaches the screen
            "description": ", ".join(parts), "facts": facts,
            "region": r["REGION"], "city": r["CITY"], "okved": okved_section(r["MAINOKVED_CODE"]),
            "okved_code": r["MAINOKVED_CODE"], "okved_name": r["MAINOKVED_NAME"],
            "products": [key for _, key in marks if key], "products_ru": [ru for ru, _ in marks],
            "date_label": f"выручка {_money(revenue)}, {r['CITY']}".strip(" ,"),
        }
        return self._profiles[uid]
