"""توحيد النص العربي للبحث: حذف التشكيل والتطويل، وتوحيد الهمزات والتاء والياء، وتجريد السوابق."""
import re

HARAKAT = re.compile(r"[ؐ-ًؚ-ٰٟۖ-ۭـ]")
MAP = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ة": "ه", "ى": "ي",
                     "ؤ": "و", "ئ": "ي", "ک": "ك", "ی": "ي", "ہ": "ه", "ھ": "ه"})
NONWORD = re.compile(r"[^ء-ي0-9]+")


def norm(text: str) -> str:
    """نص موحّد: كلمات مفصولة بمسافة واحدة."""
    t = HARAKAT.sub("", text).translate(MAP)
    return NONWORD.sub(" ", t).strip()


def stem(tok: str) -> str:
    """تجريد السوابق الشائعة: و ف ثم ب ل ك ثم ال (مع بقاء ثلاثة أحرف على الأقل)."""
    t = tok
    if len(t) > 3 and t[0] in "وف":
        t = t[1:]
    if len(t) > 3 and t[0] in "بلك":
        t = t[1:]
    if len(t) > 4 and t.startswith("ال"):
        t = t[2:]
    elif len(t) > 3 and t.startswith("ل") and tok[0] in "وفل" and t.startswith("لل"):
        t = t[2:]
    return t


def index_form(text: str) -> str:
    """الصيغة المفهرسة: كل كلمة موحّدة، وتليها مجرّدتها إن اختلفت."""
    out = []
    for w in norm(text).split():
        out.append(w)
        s = stem(w)
        if s != w:
            out.append(s)
    return " ".join(out)
