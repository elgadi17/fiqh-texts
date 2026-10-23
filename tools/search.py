#!/usr/bin/env python3
"""البحث في الكتب: فهرس ألفاظ (SQLite FTS5) مبني على المسائل.

  python3 tools/search.py build                 # بناء الفهرس (مرة في بداية الجلسة، ثوانٍ)
  python3 tools/search.py "بيع الثمار" [خيارات]   # بحث

صيغة الاستعلام (بعد توحيد الحروف وتجريد السوابق تلقائيًا):
  كلمتان أو أكثر           ← تجتمع في المسألة نفسها
  "بيع الثمار"             ← عبارة متتالية
  بيع*                     ← الكلمة ومشتقاتها اللاحقة (بيعه، بيعها، بيعت)
  بيع OR شراء              ← إحداهما
  NEAR(بيع ثمار, 5)        ← متقاربتان في حدود خمس كلمات
  بيع NOT ربا              ← استبعاد

خيارات: --book جزء من اسم الكتاب، --mufti جزء من اسم المسؤول، --limit عدد النتائج،
        --full لعرض نص المسألة كاملًا، --json لإخراج آلي.
النتائج: الكتاب، الجزء، الصفحة (تقريبية)، المسؤول، أسطر المسألة في ملف «منقحة» والأصل.
"""
import sys, json, re, sqlite3, argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from arabic import index_form, norm, stem

ROOT = Path(__file__).resolve().parent.parent
SRC, IDX = ROOT / "منقحة", ROOT / "فهرس"
DB = Path("/tmp/fiqh_index.sqlite")


def build():
    if DB.exists(): DB.unlink()
    con = sqlite3.connect(DB)
    con.executescript("""
        CREATE TABLE units(rowid INTEGER PRIMARY KEY, book, vol, uid, l0, l1, p0, p1, mufti, title, text);
        CREATE VIRTUAL TABLE fts USING fts5(body, mufti, content='', tokenize='unicode61 remove_diacritics 2');
    """)
    n = 0
    for f in sorted(IDX.glob("*.jsonl")):
        src = SRC / (f.stem + ".txt")
        if not src.exists(): continue
        lines = src.read_text(encoding="utf-8").split("\n")
        rows = []
        for x in open(f, encoding="utf-8"):
            u = json.loads(x)
            text = "\n".join(lines[u["l0"] - 1:u["l1"]])
            n += 1
            rows.append((n, u["book"], u["vol"], u["id"], u["l0"], u["l1"], u["p0"], u["p1"], u["mufti"], u["title"], text,
                         index_form(text), index_form(u["mufti"])))
        con.executemany("INSERT INTO units VALUES (?,?,?,?,?,?,?,?,?,?,?)", [r[:11] for r in rows])
        con.executemany("INSERT INTO fts(rowid, body, mufti) VALUES (?,?,?)", [(r[0], r[11], r[12]) for r in rows])
    con.commit()
    con.execute("INSERT INTO fts(fts) VALUES('optimize')"); con.commit()
    print(f"فُهرست {n} مسألة من {len(list(IDX.glob('*.jsonl')))} ملفًا ← {DB}")


def to_fts(q):
    """تحويل استعلام المستخدم إلى صيغة FTS5 مع توحيد الكلمات وتجريد سوابقها."""
    out = []
    for tok in re.findall(r'"[^"]+"|NEAR\([^)]*\)|\S+', q):
        if tok in ("OR", "AND", "NOT"):
            out.append(tok); continue
        if tok.startswith('"'):
            ws = [stem(w) for w in norm(tok.strip('"')).split()]
            # المفهرس يضع المجرّدة بعد الكلمة، فالعبارة تُطلب متقاربة بقدر طولها
            out.append(ws[0] if len(ws) == 1 else f"NEAR({' '.join(ws)}, {len(ws)})"); continue
        if tok.startswith("NEAR("):
            inner, _, dist = tok[5:-1].rpartition(",")
            if not dist.strip().isdigit(): inner, dist = tok[5:-1], "10"
            ws = []
            for w in inner.split():
                star = w.endswith("*")
                ws += [stem(x) + ("*" if star else "") for x in norm(w.rstrip("*")).split()]
            # المجرّدات المضافة في الفهرس تضاعف المسافة بين الكلمات تقريبًا
            out.append(f"NEAR({' '.join(ws)}, {2 * int(dist.strip())})"); continue
        star = tok.endswith("*")
        w = norm(tok.rstrip("*"))
        if not w: continue
        for part in w.split():
            s = stem(part)
            out.append(s + ("*" if star else ""))
    return " ".join(out)


def search(q, book=None, mufti=None, limit=30, full=False, as_json=False):
    if not DB.exists(): build()
    con = sqlite3.connect(DB)
    fq = "body : (" + to_fts(q) + ")"
    if mufti: fq = f"({fq}) AND mufti:({to_fts(mufti)})"
    sql = """SELECT u.book, u.vol, u.uid, u.l0, u.l1, u.p0, u.p1, u.mufti, u.title, u.text, bm25(fts)
             FROM fts JOIN units u ON u.rowid = fts.rowid WHERE fts MATCH ?"""
    args = [fq]
    if book: sql += " AND u.book LIKE ?"; args.append(f"%{book}%")
    sql += " ORDER BY bm25(fts) LIMIT ?"; args.append(limit)
    rows = con.execute(sql, args).fetchall()
    total = con.execute("SELECT count(*) FROM fts JOIN units u ON u.rowid = fts.rowid WHERE fts MATCH ?"
                        + (" AND u.book LIKE ?" if book else ""), args[:-1]).fetchone()[0]
    if as_json:
        print(json.dumps([dict(zip(["book", "vol", "uid", "l0", "l1", "p0", "p1", "mufti", "title", "text"], r[:10]))
                          for r in rows], ensure_ascii=False)); return
    print(f"الاستعلام: {fq}\nالنتائج: {total} مسألة (المعروض {len(rows)})\n")
    keys = [w.strip('"*') for w in re.findall(r'[^\s()"]+', fq) if w not in ("OR", "AND", "NOT", "NEAR") and not w.isdigit()]
    for r in rows:
        book, vol, uid, l0, l1, p0, p1, mf, title, text, _ = r
        pg = "؟" if p0 is None else (f"{p0}" if p0 == p1 else f"{p0}-{p1}")
        print(f"■ {book} | ج{vol or '-'} | ص {pg} (تقريبي) | المسؤول: {mf or '—'} | أسطر {l0}-{l1} | مسألة {uid}")
        if full:
            print(text.strip())
        else:
            lines = text.split("\n")
            hits, last = [], -9
            for i, x in enumerate(lines):
                if i - last > 2 and any(k and k in norm(x) for k in keys):
                    hits.append(i); last = i
            for i in hits[:3]:
                print("   …", " ".join(y.strip() for y in lines[max(0, i - 1):i + 2] if y.strip())[:300])
        print()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "build":
        build(); sys.exit()
    ap = argparse.ArgumentParser()
    ap.add_argument("query")
    ap.add_argument("--book"); ap.add_argument("--mufti")
    ap.add_argument("--limit", type=int, default=30)
    ap.add_argument("--full", action="store_true"); ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    search(a.query, a.book, a.mufti, a.limit, a.full, a.json)
