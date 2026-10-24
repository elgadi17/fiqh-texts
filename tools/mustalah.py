#!/usr/bin/env python3
"""كشف المصطلح: قياس الألفاظ المرشّحة على الكتب قبل البحث (مقتبس من «هدية وتد الوقفية»، ومكيَّف لفهرس المسائل).

  python3 tools/mustalah.py measure "لفظ" "لفظ" …    لكل لفظ: كم مسألة، وكم كتابًا، وكم موضعًا
  python3 tools/mustalah.py jiwar "لفظ" [--top 15]    أكثر ما يسبق اللفظ ويليه، فيظهر المصطلح المركّب
  python3 tools/mustalah.py siyaq "لفظ" [--limit 12]  سياقات موزّعة على الكتب (واحد من كل كتاب أولًا) لتمييز المعاني
  python3 tools/mustalah.py kutub "لفظ" ["لفظ" …]     قائمة الكتب للألفاظ: الكتاب · المسائل · المواضع (تُعرض قبل القراءة)

اللفظ كلمة أو عبارة، ويُطابَق مع السوابق (و ف ب ل ك ال)؛ و«كلمة*» تقبل اللواحق.
خيار عام: --book جزء من اسم الكتاب. الأرقام تثبت وجود اللفظ لا مضمون المسألة.
"""
import argparse
import collections
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from arabic import norm  # noqa: E402
import search  # noqa: E402

PREFIX = r"(?:[وف]?[بلك]?(?:ال)?)"


def pattern(term: str) -> re.Pattern:
    parts = []
    for w in term.split():
        star = w.endswith("*")
        w = norm(w.rstrip("*"))
        if not w:
            continue
        for x in w.split():
            parts.append(PREFIX + re.escape(x) + (r"\S*" if star else ""))
    return re.compile(r"(?<!\S)" + r"\s+".join(parts) + r"(?!\S)")


def query_for(term: str) -> str:
    ws = term.split()
    return ws[0] if len(ws) == 1 else f'"{term.replace("*", "")}"'


def units(con, term, book=None):
    """المسائل التي فيها اللفظ (من الفهرس)، ومعها نص كل مسألة."""
    fq = "body : (" + search.to_fts(query_for(term)) + ")"
    sql = ("SELECT u.book, u.vol, u.uid, u.l0, u.l1, u.p0, u.p1, u.mufti, u.text FROM fts JOIN units u "
           "ON u.rowid = fts.rowid WHERE fts MATCH ?")
    args = [fq]
    if book:
        sql += " AND u.book LIKE ?"
        args.append(f"%{book}%")
    return con.execute(sql + " ORDER BY u.book, u.l0", args).fetchall()


def occurrences(term, rows):
    """المواضع الفعلية للّفظ في نص المسائل (بعد التوحيد)."""
    pat = pattern(term)
    out = []
    for r in rows:
        t = norm(r[8])
        for m in pat.finditer(t):
            out.append((r, t, m.start(), m.end()))
    return out


def connect():
    if not search.DB.exists():
        search.build()
    return sqlite3.connect(search.DB)


def cmd_measure(con, a):
    print(f"{'اللفظ':<24} مسائل  كتب  مواضع")
    for term in a.terms:
        rows = units(con, term, a.book)
        occ = occurrences(term, rows)
        books = {r[0] for r in rows}
        print(f"{term:<24} {len(rows):>5} {len(books):>5} {len(occ):>6}")
    print("\n(المسائل من الفهرس؛ المواضع تطابق اللفظ متتاليًا بسوابقه، فقد تقلّ عن المسائل في العبارات.)")


def cmd_jiwar(con, a):
    occ = occurrences(a.term, units(con, a.term, a.book))
    before, after = collections.Counter(), collections.Counter()
    for _, t, s, e in occ:
        b = t[:s].split()
        f = t[e:].split()
        if b:
            before[b[-1]] += 1
        if f:
            after[f[0]] += 1
    print(f"«{a.term}»: {len(occ)} موضعًا\n\nما يسبقه:")
    for w, n in before.most_common(a.top):
        print(f"  {n:>5}  {w} {a.term}")
    print("\nما يليه:")
    for w, n in after.most_common(a.top):
        print(f"  {n:>5}  {a.term} {w}")


def cmd_siyaq(con, a):
    occ = occurrences(a.term, units(con, a.term, a.book))
    by_book = collections.defaultdict(list)
    for o in occ:
        by_book[o[0][0]].append(o)
    picked, rnd = [], 0
    while len(picked) < a.limit and any(len(v) > rnd for v in by_book.values()):
        for b in sorted(by_book):
            if len(by_book[b]) > rnd and len(picked) < a.limit:
                picked.append(by_book[b][rnd])
        rnd += 1
    print(f"«{a.term}»: {len(occ)} موضعًا في {len(by_book)} كتابًا — المعروض {len(picked)}\n")
    for r, t, s, e in picked:
        book, vol, uid, l0, l1, p0, p1, mf = r[:8]
        pg = "؟" if p0 is None else (f"{p0}" if p0 == p1 else f"{p0}-{p1}")
        ctx = t[max(0, s - a.ctx):s] + "【" + t[s:e] + "】" + t[e:e + a.ctx]
        print(f"■ {book} | ص {pg} (تقريبي) | أسطر {l0}-{l1} | المسؤول: {mf or '—'}\n   …{ctx}…\n")


def cmd_kutub(con, a):
    stats = collections.defaultdict(lambda: [set(), 0])
    for term in a.terms:
        rows = units(con, term, a.book)
        for r in rows:
            stats[r[0]][0].add(r[2])
        for o in occurrences(term, rows):
            stats[o[0][0]][1] += 1
    print(f"الألفاظ: {' · '.join(a.terms)}\n")
    print(f"{'الكتاب':<48} مسائل  مواضع")
    for b, (us, n) in sorted(stats.items(), key=lambda kv: -len(kv[1][0])):
        print(f"{b:<48} {len(us):>5} {n:>6}")
    print(f"\n{len(stats)} كتابًا. تُعرض على المستخدم ويُتّفق على الكتب قبل القراءة الكاملة.")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--book")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("measure"); p.add_argument("terms", nargs="+")
    p = sub.add_parser("jiwar"); p.add_argument("term"); p.add_argument("--top", type=int, default=15)
    p = sub.add_parser("siyaq"); p.add_argument("term"); p.add_argument("--limit", type=int, default=12)
    p.add_argument("--ctx", type=int, default=120)
    p = sub.add_parser("kutub"); p.add_argument("terms", nargs="+")
    a = ap.parse_args()
    con = connect()
    {"measure": cmd_measure, "jiwar": cmd_jiwar, "siyaq": cmd_siyaq, "kutub": cmd_kutub}[a.cmd](con, a)


if __name__ == "__main__":
    main()
