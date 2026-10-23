#!/usr/bin/env python3
"""ينشئ نسخة منقحة للبحث من ملفات المستودع في مجلد «منقحة/».

يصحح الأخطاء الآلية المطّردة الناتجة عن التعرف الضوئي فقط، ولا يمس الكلمات نفسها:
  1. «»» المستعملة مكان الفاصلة ← «،» (ما لم تكن غلقًا لـ«» مفتوحة في السطر نفسه)
  2. «ء» الملتصقة بآخر الكلمة مكان الفاصلة ← «،» (بشروط تحفظ الكلمات المهموزة الصحيحة)
  3. الفاصلة اللاتينية بعد حرف عربي ← «،»
  4. حذف علامات الاتجاه الخفية (RLM/LRM)
  5. توحيد الحروف الفارسية التي أخرجها التعرف الضوئي: ک←ك، ہ/ھ←ه، ی←ي (وفي آخر الكلمة ←ى)
ويحافظ على عدد الأسطر وترتيبها، فالسطر N في المنقحة هو السطر N في الأصل.
الأصول لا تُعدَّل أبدًا؛ وعند النقل يُرجع إلى الأصل.
"""
import re, sys, json, subprocess, collections
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "منقحة"
SKIP = {"جامع مسائل الأحكام - البرزلي - 07.txt"}  # فشل فيه التعرف الضوئي كليًا

HARAKAT = re.compile(r"[ً-ْٰ]")
# كلمات صحيحة تنتهي بهمزة بعد حرف ساكن أو حرف مد — لا تُمس
REAL = {"شيء", "جزء", "مرء", "المرء", "بدء", "عبء", "كفء", "سوء", "ضوء", "بطء",
        "ملء", "دفء", "نشء", "ردء", "فيء", "قيء", "خبء", "رزء", "كلء", "وطء", "بطء",
        "درء", "ملء", "نبء", "دفء", "جزء", "هزء", "وضوء", "الوضوء", "ضوء", "بريء", "دنيء",
        "رديء", "مليء", "جريء", "خطيء", "بطيء", "مجيء", "شيء", "الشيء", "الجزء",
        "السوء", "البدء", "النيء", "نيء", "البرء", "برء", "الوطء", "الدرء", "الفيء", "القيء", "الكفء", "النشء"}
# حروف إذا سبقت الهمزة الأخيرة فهي غالبًا همزة حقيقية (علماء، سماء، سوء، شيء)
KEEP_BEFORE = set("اوي") | {"ء", "آ", "أ", "إ"}

ALIF_ENDINGS = ("ها", "نا", "هما", "ذا", "وا")
ALIF_REAL = {"إناء", "الإناء", "فناء", "الفناء", "غناء", "ثناء", "الثناء", "بناء", "البناء",
             "هناء", "سناء", "اقتناء", "استثناء", "الاستثناء", "بهاء", "انتهاء", "الانتهاء",
             "إنهاء", "الإنهاء", "هاء", "دهاء", "شفاء", "الشفاء", "اعتناء", "أثناء", "ابتناء"}

def norm_letters(t):
    t = t.replace("ک", "ك").replace("ہ", "ه").replace("ھ", "ه").replace("ۀ", "ة")
    t = re.sub(r"ی(?=[\u0621-\u064A\u06CC])", "ي", t)
    return t.replace("ی", "ى")

def strip(w): return HARAKAT.sub("", w)

def build_vocab(texts):
    v = collections.Counter()
    for t in texts:
        v.update(strip(w) for w in re.findall(r"[ء-يً-ْٰ]+", t))
    return v

def fix_hamza(token, vocab, stats):
    m = re.match(r"^(.*?)(ء)([^؀-ۿ]*)$", token)
    if not m or not m.group(1): return token
    base, tail = m.group(1), m.group(3)
    sbase = strip(base)
    if not sbase: return token
    last = base[-1]
    if strip(base + "ء") in REAL or strip(base + "ء").lstrip("وفبل") in REAL: return token
    if last == "ً" or last == "ة" or last == "ى":     # اًء / ةء / ىء لا تكون صحيحة
        stats["ء←،"] += 1; return base + "،" + tail
    word = strip(base + "ء")
    if sbase[-1] == "ي" and len(sbase) >= 4:      # القاضيء ← القاضي، (مع حفظ شيء وبريء ونحوهما)
        if vocab[sbase] >= 10 * vocab[word]:
            stats["ء←،"] += 1; return base + "،" + tail
        return token
    if sbase[-1] == "ا" and len(sbase) >= 3:
        ratio = 2 if sbase.endswith(ALIF_ENDINGS) else (30 if len(sbase) >= 4 else 10**9)
        if word not in ALIF_REAL and word.lstrip("وفبل") not in ALIF_REAL and vocab[sbase] >= ratio * max(1, vocab[word]):
            stats["ء←،"] += 1; return base + "،" + tail
        return token
    if sbase[-1] in KEEP_BEFORE: return token
    if vocab[sbase] >= 3 and vocab[sbase] > 3 * vocab[strip(base + "ء")] / 4:
        stats["ء←،"] += 1; return base + "،" + tail
    return token

def fix_guillemets(line, stats):
    out, opened = [], 0
    for ch in line:
        if ch == "«": opened += 1; out.append(ch)
        elif ch == "»":
            if opened: opened -= 1; out.append(ch)
            else: stats["»←،"] += 1; out.append("،")
        else: out.append(ch)
    return "".join(out)

def clean(text, vocab, stats):
    text = text.replace("‏", "").replace("‎", "")
    lines = []
    for line in text.split("\n"):
        line = fix_guillemets(line, stats)
        line, n = re.subn(r"م\.سء", "م.س،", line); stats["ء←،"] += n
        line, n = re.subn(r"(?<=[ء-يً-ْ]),", "،", line); stats[",←،"] += n
        line = re.sub(r"\S+", lambda m: fix_hamza(m.group(0), vocab, stats), line)
        lines.append(line)
    return "\n".join(lines)

def doc_to_text(p):
    tmp = Path("/tmp/fiqh_conv"); tmp.mkdir(exist_ok=True)
    subprocess.run(["soffice", "--headless", "--convert-to", "txt:Text (encoded):UTF8",
                    "--outdir", str(tmp), str(p)], check=True, capture_output=True)
    return (tmp / (p.stem + ".txt")).read_text(encoding="utf-8", errors="replace")

def main():
    OUT.mkdir(exist_ok=True)
    srcs, typed = {}, set()   # ملفات Word منضدة باليد: لا تحتاج إلا توحيد الحروف
    for p in sorted(ROOT.glob("*")):
        if p.name in SKIP or not p.is_file(): continue
        if p.suffix == ".txt": srcs[p.name] = p.read_text(encoding="utf-8")
        elif p.suffix in (".doc", ".docx"): srcs[p.stem + ".txt"] = doc_to_text(p); typed.add(p.stem + ".txt")
    srcs = {k: norm_letters(v) for k, v in srcs.items()}
    vocab = build_vocab(srcs.values())
    report = {}
    for name, t in srcs.items():
        stats = collections.Counter()
        out = t.replace("\u200f", "").replace("\u200e", "") if name in typed else clean(t, vocab, stats)
        (OUT / name).write_text(out, encoding="utf-8")
        report[name] = dict(stats)
    (OUT / "تقرير_التنقيح.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    tot = collections.Counter()
    for s in report.values(): tot.update(s)
    print(len(srcs), "ملفًا", dict(tot))

if __name__ == "__main__":
    main()
