"""End-to-end evaluation. Expected values come from SQL on the RAW CSVs (README formulas), not from the app's normalised
tables, so a normalisation bug shows up as a failure. Usage: python eval.py [base_url] [--limit N]"""
import json
import re
import sys
import time

import duckdb
import httpx

D = "../uzex_spot_data"
c = duckdb.connect()
o = "header=true, all_varchar=true, delim=',', quote='\"', escape='\"'"
c.execute(f"create view rd as select * from read_csv('{D}/deals_*.csv', {o}, union_by_name=true)")
c.execute(f"create view rc as select * from read_csv('{D}/contracts.csv', {o})")
c.execute(f"create view rp as select * from read_csv('{D}/participants.csv', {o})")
c.execute(f"create view rb as select * from read_csv('{D}/brokers.csv', {o})")
c.execute(f"create view ru as select * from read_csv('{D}/usd_rates.csv', {o})")
AMT = """cast(replace("Сумма сделки",' ','') as double)"""
QTY = """cast(replace("Количество",' ','') as double)"""
LOT = """cast(replace("Лот",' ','') as double)"""
OK = """"Состояние сделки" not like 'Аннулирован%'"""
YR = lambda y: f""""Дата сделки" like '%.{y}'"""


def one(sql):
    return c.execute(sql).fetchone()[0]


top_buyer = c.execute(f"""select p."Наименование", sum({AMT}) s from rd join rp p on rd."ИНН покупателя"=p."ИНН" where {OK} and {YR(2025)} and "Тип контракта"='Внутренний' group by 1 order by 2 desc limit 1""").fetchone()
top_region = one(f"""select "Регион" from rd where {OK} and {YR(2024)} group by 1 order by count(*) desc limit 1""")
sample = c.execute("""select "Номер сделки","Сумма сделки","Состояние сделки" from rd where "Номер сделки"='504708'""").fetchone()

CASES = [
    # (question, expected numbers/strings that must appear, kind)
    ("2023-yilda nechta bitim bekor qilingan (aннулирован)?", [one(f"""select count(*) from rd where {YR(2023)} and "Состояние сделки" like 'Аннулирован%'""")], "num"),
    ("Сколько всего сделок в 2024 году с учётом аннулированных?", [one(f"select count(*) from rd where {YR(2024)}")], "num"),
    ("Какой курс доллара был 15.03.2025?", [float(one("""select "Курс" from ru where "Дата"='15.03.2025'"""))], "num"),
    ("Сколько тонн карбамида продано в 2025 году без аннулированных сделок?",
     [one(f"""select sum({QTY}*rd."Лот"::double) from rd join rc using("Номер контракта") where {OK} and {YR(2025)} and upper("Наименование продукта") similar to '.*(КАРБАМИД|МОЧЕВИНА).*'""")], "num"),
    ("2024-yilda qaysi viloyatda eng ko'p bitim tuzilgan?", [top_region], "str"),
    ("2025 yilda ichki bozorda eng katta summaga xarid qilgan xaridor kim?", [top_buyer[0]], "str"),
    ("504708 raqamli bitimning summasi qancha va holati qanday?", ["1 018 102 922"], "str"),
    ("Сколько брокерских контор в данных?", [120], "num"),
    ("Сколько экспортных сделок было в 2022 году без аннулированных?", [one(f"""select count(*) from rd where {OK} and {YR(2022)} and "Тип контракта"='Экспортный'""")], "num"),
    ("Qancha ishtirokchi QQS to'lovchi hisoblanadi?", [one("""select count(*) from rp where "Плательщик НДС"='Да'""")], "num"),
    # must refuse: not in the data
    ("Сколько золота продано на бирже в 2024 году?", [], "refuse"),
    ("2027-yilda sement narxi qancha bo'ladi?", [], "refuse"),
    ("Кто директор компании \"Zapo Servis\" MChJ и какой у неё телефон?", [], "refuse"),
    ("\"Toshkent Oltin Savdo\" MChJ qancha bitim tuzgan?", [], "refuse"),
    ("Какой был объём торгов в 2019 году?", [], "refuse"),
    ("Почему в 2023 году подорожал цемент?", [], "refuse"),
]


def digits(s):
    return re.sub(r"[\s  ]", "", s)


def has_num(text, v):
    t = digits(text).replace(",", ".")
    v = float(v)
    forms = {f"{v:.0f}", f"{v:.1f}", f"{v:.2f}", str(v)}
    return any(f in t for f in forms)


def main():
    base = next((a for a in sys.argv[1:] if a.startswith("http")), "http://127.0.0.1:8000")
    passed, res = 0, []
    for q, exp, kind in CASES:
        t = time.time()
        r = httpx.post(base + "/api/ask", json={"question": q}, timeout=95).json()
        a, st = r["answer"], r["status"]
        if kind == "refuse":
            ok = st == "no_data"
        elif kind == "num":
            ok = all(has_num(a, v) for v in exp)
        else:
            ok = all(digits(str(v)).lower() in digits(a).lower() for v in exp)
        passed += ok
        print(("PASS" if ok else "FAIL"), f"[{time.time()-t:.1f}s {st}]", q, "\n   ->", a.replace("\n", " ")[:260], "\n   expected:", exp, flush=True)
        res.append({"q": q, "expected": [str(x) for x in exp], "answer": a, "status": st, "ok": bool(ok), "steps": r["steps"]})
        time.sleep(float(next((a[6:] for a in sys.argv if a.startswith("sleep=")), 7)))
    print(f"\n{passed}/{len(CASES)} passed")
    json.dump(res, open("eval_results.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)


if __name__ == "__main__":
    main()
