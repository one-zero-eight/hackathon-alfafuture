"""What the user typed: a job, an industry, or a free sphere. Typos and synonyms stay on the same page.

The job is used only when a decision is written. It does not decide whether a page exists.
"""
from dataclasses import dataclass

# Short names a person actually types. The official OKVED title is longer than this match needs.
_SECTIONS = {
    "A": ["сельское хозяйство", "агро", "урожай", "зерно", "рыболовство"],
    "B": ["добыча", "нефть", "газ", "уголь", "руда", "полезные ископаемые"],
    "C": ["производство", "завод", "промышленность", "машиностроение"],
    "D": ["электроэнергия", "энергетика", "электроснабжение"],
    "E": ["водоснабжение", "водоотведение", "отходы"],
    "F": ["строительство", "стройка", "жилье", "девелопмент", "подряд"],
    "G": ["торговля", "ритейл", "розница", "опт", "магазин"],
    "H": ["логистика", "транспорт", "перевозки", "хранение"],
    "I": ["гостиницы", "общепит", "ресторан"],
    "J": ["информационные технологии", "софт", "программирование", "айти", "связь"],
    "K": ["банк", "финансы", "страхование"],
    "L": ["недвижимость", "аренда"],
    "M": ["консалтинг", "юридические услуги", "наука"],
    "P": ["образование", "университет"],
    "Q": ["медицина", "здравоохранение"],
    "R": ["культура", "спорт"],
}
_TOPICS = {
    "procurement": ["закупки", "закупка", "снабжение", "поставщик", "поставки", "тендер"],
    "rates": ["ключевая ставка", "ставка"],
}
_ROLES = {
    "CFO": ["финансовый директор", "финдиректор", "cfo"],
    "CEO": ["генеральный директор", "гендиректор", "собственник", "ceo"],
    "chief_accountant": ["главный бухгалтер", "главбух"],
    "treasury_head": ["казначей", "руководитель казначейства"],
}


@dataclass(frozen=True)
class Focus:
    role: str | None
    section: str | None
    topic: str | None
    words: tuple[str, ...]
    label: str

    @property
    def free(self) -> bool:
        return bool(self.label) and not self.role and not self.section and not self.topic


def _norm(text: str) -> str:
    out = []
    for ch in (text or "").lower().replace("ё", "е"):
        out.append(ch if ("а" <= ch <= "я" or "a" <= ch <= "z" or ch.isdigit()) else " ")
    return " ".join("".join(out).split())


def _words(text: str) -> list[str]:
    return [w for w in _norm(text).split() if len(w) > 2]


def _dist(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[-1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _close(a: str, b: str) -> bool:
    """One or two wrong letters. Words shorter than four letters match only exactly, so «газ» is not «гасс»."""
    if a == b:
        return True
    if abs(len(a) - len(b)) > 2 or min(len(a), len(b)) < 4:
        return False
    return _dist(a, b) <= 2


def _hit(query: list[str], phrase: str) -> bool:
    need = _words(phrase) or ([_norm(phrase)] if _norm(phrase) else [])
    return bool(need) and all(any(_close(w, n) for w in query) for n in need)


def _best(query: list[str], table: dict[str, list[str]]) -> str | None:
    found, score = None, 0
    for key, phrases in table.items():
        best = max((len(_norm(p)) for p in phrases if _hit(query, p)), default=0)
        if best > score:
            found, score = key, best
    return found


def interpret(text: str) -> Focus:
    """Job, OKVED section and topic from one line. A miss still keeps the words for the news prompt."""
    label = " ".join((text or "").split())
    query = _words(label)
    if not query:
        return Focus(None, None, None, (), "")
    return Focus(_best(query, _ROLES), _best(query, _SECTIONS), _best(query, _TOPICS), tuple(query), label)


def cache_key(session: str, focus: Focus, company_section: str) -> str:
    """Same sphere, including a typo of it, reuses one page. The company's own section stays on the company page."""
    bits = []
    if focus.topic:
        bits.append(focus.topic)
    elif focus.section and focus.section != company_section:
        bits.append(focus.section)
    elif focus.free:
        bits.append("".join(focus.words[:3])[:24] or "sphere")
    if focus.role and focus.role != "CFO":
        bits.append(focus.role)
    return session if not bits else session + "__" + "__".join(bits)
