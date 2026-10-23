#!/usr/bin/env python3
"""يقسّم كل كتاب في «منقحة/» إلى مسائل، ويكتب فهرسها في «فهرس/<الكتاب>.jsonl».

كل سطر في الفهرس مسألة: رقمها، والجزء، وأسطرها في الملف، وصفحاتها (تقريبية من أرقام
الصفحات التي أخرجها التعرف الضوئي)، والمسؤول إن أمكن استخراجه، وأول سطر منها.
كل سطر من الكتاب داخل في مسألة ما، فلا يضيع شيء من النص عند البحث؛ والكتب التي لا
تنتظم في مسائل تُقسّم إلى مقاطع بحسب الصفحات.
"""
import re, json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from arabic import HARAKAT

ROOT = Path(__file__).resolve().parent.parent
SRC, OUT = ROOT / "منقحة", ROOT / "فهرس"
MAX_LINES, CHUNK = 160, 80

def bare(s): return HARAKAT.sub("", s).strip()

START = [
    re.compile(r"^[\W\d]{0,4}و?(سئل|سيل|وسيل|سثل)\b"),
    re.compile(r"^[\W\d]{0,4}(و?مسألة|المسألة|و?مسالة|المسالة|و?نازلة|النازلة)\b"),
    re.compile(r"^\s*\[\s*\d{1,4}\s*\]"),
    re.compile(r"^[\W\d]{0,4}(سؤال|السؤال)\b"),
]
TITLE = re.compile(r"^\s*\[[^\]\[]{3,150}\]\s*$")           # عنوان بين معقوفين
ASKED = re.compile(r"^[\W\d]{0,4}و?(سئل|سيل|سثل)\s+(.{2,90}?)\s+(عن|عمن|عما|عمن|في|فيمن|هل|لما)\s")
ANSWER = re.compile(r"(?:^|\s)(?:ف|و)?(?:أجاب|اجاب)\s+((?:الشيخ|الإمام|الامام|القاضي|الفقيه|سيدي|سيدى|شيخنا|الأستاذ|ابن|أبو|ابو|المفتي|العلامة)[^:،.]{0,70})")
PAGE = re.compile(r"^\s*[\-–—¬~=|<+]{0,3}\s*(\d{1,4})\s*[\-–—¬~=|+]{0,3}\s*(?:[\u0621-\u064A]{1,2})?\s*$")

def is_start(line):
    b = bare(line)
    return any(p.match(b) for p in START) or bool(TITLE.match(b))

def volume(name):
    m = re.search(r"[-–]\s*0*(\d{1,2})(?:\s|\.txt|$)", name)
    return int(m.group(1)) if m else None

def pages(lines):
    """رقم صفحة كل سطر، أو None. رقم الصفحة في هذه الكتب يأتي في آخرها.

    تؤخذ أطول سلسلة متصاعدة متسقة من الأسطر الرقمية (تُهمل أرقام الحواشي والتصحيف)،
    ثم تُقدَّر صفحات الأسطر بين أرقامها بالتوزيع المتناسب.
    """
    cand = []
    for i, x in enumerate(lines):
        m = PAGE.match(x)
        if not m: continue
        raw = m.group(1)
        opts = {int(raw)} | ({int(raw[1:]), int(raw[:-1])} if len(raw) >= 3 else set())   # خانة زائدة
        cand += [(i, v) for v in opts if v > 0]
    n = len(cand)
    steps = sorted(b[0] - a[0] for a, b in zip(cand, cand[1:]) if b[1] == a[1] + 1 and 5 <= b[0] - a[0] <= 120)
    minpp = max(5, 0.5 * steps[len(steps) // 2]) if steps else 12       # أقل عدد أسطر للصفحة
    best, prev = [1] * n, [-1] * n
    for j in range(n):
        lj, vj = cand[j]
        for i in range(max(0, j - 150), j):
            li, vi = cand[i]
            dv, dl = vj - vi, lj - li
            if 1 <= dv <= 60 and minpp * dv <= dl <= 110 * dv and best[i] + 1 > best[j]:
                best[j], prev[j] = best[i] + 1, i
    if not n:
        return [None] * len(lines), []
    j = max(range(n), key=lambda k: best[k])
    chain = []
    while j != -1:
        chain.append(cand[j]); j = prev[j]
    chain.reverse()
    span_pages = chain[-1][1] - chain[0][1] + 1
    covered = (chain[-1][0] - chain[0][0]) / max(1, len(lines))
    if len(chain) < 10 or len(chain) < 0.25 * span_pages or covered < 0.4:
        return [None] * len(lines), []
    res = [None] * len(lines)
    (l0, v0) = chain[0]
    per = (chain[-1][0] - l0) / max(1, chain[-1][1] - v0)        # أسطر الصفحة في المتوسط
    for i in range(0, l0 + 1):
        res[i] = max(1, v0 - int((l0 - i) / per))
    for (la, va), (lb, vb) in zip(chain, chain[1:]):
        for i in range(la + 1, lb + 1):
            res[i] = va + max(1, -(-(i - la) * (vb - va) // (lb - la)))
    ll, vl = chain[-1]
    for i in range(ll + 1, len(lines)):
        res[i] = vl + 1 + int((i - ll - 1) / per)
    breaks = [(i - 1, res[i - 1]) for i in range(1, len(lines)) if res[i] != res[i - 1]]
    return res, breaks

def segment(name, text):
    lines = text.split("\n")
    from_word = any((ROOT / (Path(name).stem + ext)).exists() for ext in (".doc", ".docx"))
    pg, breaks = ([None] * len(lines), []) if from_word else pages(lines)   # لا أرقام صفحات في ملفات Word
    starts = [i for i, x in enumerate(lines) if is_start(x)]
    # عنوان يليه «وسئل» بعد أسطر قليلة: المسألة تبدأ من العنوان
    starts = [s for k, s in enumerate(starts)
              if not (k and s - starts[k - 1] <= 3 and TITLE.match(bare(lines[starts[k - 1]])))]
    structured = len(starts) >= max(10, len(lines) / 400)
    if not structured:      # كتاب غير منتظم في مسائل: مقاطع بحسب الصفحات
        starts = [b + 1 for b, _ in breaks] if breaks else list(range(0, len(lines), 50))
        starts = [0] + [s for s in starts if 0 < s < len(lines)]
    elif not starts or starts[0] != 0:
        starts = [0] + starts
    units, mufti_prev = [], ""
    bounds = list(zip(starts, starts[1:] + [len(lines)]))
    for a, b in bounds:
        if a >= b: continue
        body = [bare(x) for x in lines[a:min(b, a + 12)]]
        mufti = ""
        for x in body:
            m = ASKED.match(x)
            if m:
                who = m.group(2).strip()
                who = re.sub(r"^(عنها|عنهما|عنهم|عنه)\s+", "", who)
                who = re.split(r"،|\s(?:فقيل|فذكر|فذ كر|وأطال|أعني|وفيه|ورويناها)\b", who)[0].strip()
                if re.match(r"(عن|عمن|عما|عمّن|في|هل|أيضا عن|أيضاً عن)\b", who): who = ""
                if re.fullmatch(r"(أيضا|أيضاً|ايضا|عنه|أيضا عن.*|(أيضا\s+)?(رحمه الله|رضي الله عنه|رحمه الله تعالى|رضي الله تعالى عنه)(\s+أيضا)?)", who):
                    who = mufti_prev
                mufti = who; break
        if not mufti:
            for x in [bare(y) for y in lines[a:min(b, a + 60)]]:
                m = ANSWER.search(x)
                if m: mufti = m.group(1).strip(); break
        if mufti: mufti_prev = mufti
        title = next((x.strip() for x in lines[a:b] if len(bare(x)) > 15), "")[:160]
        for c in range(a, b, CHUNK if b - a > MAX_LINES else b - a):
            e = min(b, c + (CHUNK if b - a > MAX_LINES else b - a))
            units.append({"l0": c + 1, "l1": e, "p0": pg[c], "p1": pg[e - 1],
                          "mufti": mufti if structured else "", "title": title,
                          "part": (c - a) // CHUNK + 1 if b - a > MAX_LINES else 0})
    return units, structured, len(breaks)

def main():
    OUT.mkdir(exist_ok=True)
    summary = {}
    names = set()
    for f in sorted(SRC.glob("*.txt")):
        units, structured, nb = segment(f.name, f.read_text(encoding="utf-8"))
        book = f.stem
        names.add(book + ".jsonl")
        with open(OUT / (book + ".jsonl"), "w", encoding="utf-8") as w:
            for k, u in enumerate(units, 1):
                w.write(json.dumps({"id": k, "book": book, "vol": volume(f.name), **u}, ensure_ascii=False) + "\n")
        summary[book] = {"مسائل": len(units), "منتظم": structured, "صفحات": nb,
                         "بمسؤول": sum(1 for u in units if u["mufti"])}
    for old in OUT.glob("*.jsonl"):
        if old.name not in names: old.unlink()
    (OUT / "ملخص.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    for k, v in summary.items(): print(k[:45].ljust(45), v)

if __name__ == "__main__":
    main()
