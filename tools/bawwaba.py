#!/usr/bin/env python3
"""بوّابة النقل: لا يُسلَّم نقلٌ حتى يُقابَل بأسطره في الأصل (مقتبسة من «هدية وتد الوقفية»).

  python3 tools/bawwaba.py check "اسم الكتاب" 165-229 "النص المنقول"
  python3 tools/bawwaba.py audit ملف.xlsx|ملف.json     يقابل كل نقل في الملف، ويخرج برمز 1 إن فشل شيء

ملف المراجعة يحتاج لكل نقل: الكتاب، والأسطر (مثل 165-229)، والنص.
  - xlsx: أعمدة عناوينها «الكتاب» و«الأسطر» و«النص المفيد للحكم» (أو «النص»).
  - json: قائمة عناصر فيها book و lines و text.
النقل المقطّع بـ «…» أو «...» يُقابَل كل مقطع منه على حدة.

الأحكام:
  مطابق حرفيًّا        المقطع موجود في الأسطر كما هو (بعد توحيد المسافات)
  مطابق بعد التطبيع    موجود إذا وُحّدت الهمزات والياءات والتاء وحُذف التشكيل: يُصحَّح رسمه من الأصل
  غير مطابق            لا يوجد في الأسطر المعزوّة: يُرفض، ويُعرض أقرب ما فيها إليه
"""
import argparse
import difflib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from arabic import norm  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SPLIT = re.compile(r"\s*(?:…|\.\.\.+)\s*")


def source(book: str) -> Path:
    """الأصل في جذر المستودع، وإلا النسخة المنقحة (لملفات Word)."""
    cands = [p for p in ROOT.glob("*.txt") if book in p.stem] or \
            [p for p in (ROOT / "منقحة").glob("*.txt") if book in p.stem]
    exact = [p for p in cands if p.stem == book]
    if exact:
        return exact[0]
    if len(cands) != 1:
        raise SystemExit(f"اسم الكتاب «{book}» يطابق {len(cands)} ملفًا: {[p.stem for p in cands][:6]}")
    return cands[0]


def lines_of(book: str, rng: str, pad: int = 2) -> str:
    m = re.fullmatch(r"\s*(\d+)\s*(?:[-–]\s*(\d+))?\s*", str(rng))
    if not m:
        raise SystemExit(f"الأسطر «{rng}» غير مفهومة؛ اكتبها هكذا: 165-229")
    l0, l1 = int(m[1]), int(m[2] or m[1])
    lines = source(book).read_text(encoding="utf-8", errors="replace").split("\n")
    return "\n".join(lines[max(0, l0 - 1 - pad):l1 + pad])


def ws(t: str) -> str:
    return re.sub(r"\s+", " ", t).strip()


def verdict(seg: str, page: str):
    if ws(seg) in ws(page):
        return "مطابق حرفيًّا", None
    if norm(seg) in norm(page):
        return "مطابق بعد التطبيع", None
    n, p = norm(seg), norm(page)
    sm = difflib.SequenceMatcher(None, p, n, autojunk=False)
    m = sm.find_longest_match(0, len(p), 0, len(n))
    start = max(0, m.a - m.b)
    return "غير مطابق", p[start:start + len(n) + 20]


def check(book, rng, text):
    page = lines_of(book, rng)
    res = []
    for seg in SPLIT.split(text.strip().strip("«»\"")):
        seg = seg.strip(" «»\"")
        if len(norm(seg).split()) < 2:
            continue
        res.append((seg, *verdict(seg, page)))
    return res


def report(label, res) -> bool:
    ok = True
    for seg, v, near in res:
        mark = "✓" if v != "غير مطابق" else "✗"
        ok &= v != "غير مطابق"
        print(f"{mark} {label} — {v}: «{seg[:80]}{'…' if len(seg) > 80 else ''}»")
        if near:
            print(f"    أقرب ما في الأسطر: «{near[:120]}»")
    return ok


def load_rows(path: Path):
    if path.suffix == ".json":
        for i, x in enumerate(json.loads(path.read_text(encoding="utf-8")), 1):
            yield i, x.get("book") or x.get("الكتاب"), x.get("lines") or x.get("الأسطر"), x.get("text") or x.get("النص")
        return
    import openpyxl
    for ws_ in openpyxl.load_workbook(path, read_only=True, data_only=True).worksheets:
        rows = ws_.iter_rows(values_only=True)
        head = [str(h or "").strip() for h in next(rows)]
        def col(*names):
            for n in names:
                if n in head:
                    return head.index(n)
            raise SystemExit(f"لم أجد عمود {names[0]} في «{ws_.title}». الأعمدة: {head}")
        cb, cl, ct = col("الكتاب"), col("الأسطر"), col("النص المفيد للحكم", "النص")
        for i, r in enumerate(rows, 2):
            if r[ct]:
                yield i, r[cb], r[cl], str(r[ct])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("check"); p.add_argument("book"); p.add_argument("lines"); p.add_argument("text")
    p = sub.add_parser("audit"); p.add_argument("file")
    a = ap.parse_args()
    if a.cmd == "check":
        sys.exit(0 if report(f"{a.book} {a.lines}", check(a.book, a.lines, a.text)) else 1)
    ok, n = True, 0
    for i, book, rng, text in load_rows(Path(a.file)):
        n += 1
        if rng and "aljam3.com" in str(rng):
            print(f"↗ صف {i} · {book} — من كتب الجامع: لا يُقابَل هنا، وتجب مقابلته بـ get_page ({rng})"); continue
        if not book or not rng:
            print(f"✗ صف {i} — بلا كتاب أو أسطر: لا يُقابَل، فلا يُسلَّم"); ok = False; continue
        ok &= report(f"صف {i} · {book} {rng}", check(str(book), str(rng), text))
    print(f"\n{n} نقلًا — {'كلها مطابقة' if ok else 'فيها ما لا يطابق: يُصحَّح قبل التسليم'}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
