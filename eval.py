"""End-to-end evaluation. Expected values come from SQL on the RAW CSVs (README formulas), not from the app's normalised
tables, so a normalisation bug shows up as a failure. Usage: python eval.py [base_url] [--limit N]"""
import json
import re
import sys
import time

import duckdb
import httpx

from textnorm import name_key

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
LOT = """cast(replace(rd."Лот",' ','') as double)"""
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
    # harder: traps from the README and the data profile
    ("Сколько бензина продано в 2025 году без аннулированных сделок? Дай отдельно по тоннам и литрам.",
     [one(f"""select sum({QTY}*{LOT}) from rd join rc using("Номер контракта") where {OK} and {YR(2025)} and upper("Наименование продукта") like '%БЕНЗИН%' and rd."Единица измерения"='тонна'"""),
      one(f"""select sum({QTY}*{LOT}) from rd join rc using("Номер контракта") where {OK} and {YR(2025)} and upper("Наименование продукта") like '%БЕНЗИН%' and rd."Единица измерения"='литр'""")], "num"),
    ("Какова общая сумма экспортных сделок в долларах за 2025 год без аннулированных?",
     [one(f"""select round(sum({AMT}),2) from rd where {OK} and {YR(2025)} and "Тип контракта"='Экспортный'""")], "num"),
    ("2024-yilda jami savdo aylanmasi so'mda qancha (eksportni kurs bo'yicha so'mga o'tkazib, bekor qilinganlarsiz)?",
     [one(f"""select round(sum(case when "Тип контракта"='Экспортный' then {AMT}*cast(u."Курс" as double) else {AMT} end),2) from rd join ru u on rd."Дата сделки"=u."Дата" where {OK} and {YR(2024)}""")], "num"),
    ("2025-yilda nechta bitim qisman yetkazilgan?", [one(f"""select count(*) from rd where {YR(2025)} and "Состояние сделки"='Исполнен(Частично)'""")], "num"),
    ("Сколько сделок в 2024 году оплачено позже срока?",
     [one(f"""select count(*) from rd join rc using("Номер контракта") where {YR(2024)} and "Дата оплаты"<>'' and strptime("Дата оплаты",'%d.%m.%Y')::date-strptime("Дата сделки",'%d.%m.%Y')::date>cast("Срок оплаты" as int)""")], "num"),
    ("Shuzel Savdo kompaniyasi xaridor sifatida nechta bitim tuzgan?", [one("""select count(*) from rd where "ИНН покупателя"='947124787'""")], "num"),
    ("Сколько сделок у компании FOMET BIZNES?", ["962497462", "945375950"], "str"),
    ("Қайси брокер 2023 йилда сотувчи томонида энг кўп битим тузган?",
     [one(f"""select b."Наименование" from rd join rb b on rd."Брокер продавца"=b."Код брокера" where {YR(2023)} and {OK} group by 1 order by count(*) desc limit 1""")], "str"),
    ("Хлопок-сырец форвард: сколько тонн продано в 2024 году без аннулированных?",
     [one(f"""select sum({QTY}*{LOT})/1000 from rd where {OK} and {YR(2024)} and "Форма контракта"='Форвард' and upper("Наименование товара") like '%ХЛОПОК%'""")], "num"),
    ("Цемент средневзвешенная цена за тонну в 2025 году без аннулированных?",
     [one(f"""select sum({AMT})/sum({QTY}*{LOT}) from rd join rc using("Номер контракта") where {OK} and {YR(2025)} and upper("Наименование продукта") like '%ЦЕМЕНТ%'""")], "num"),
    # must refuse: not in the data
    ("Сколько золота продано на бирже в 2024 году?", [], "refuse"),
    ("2027-yilda sement narxi qancha bo'ladi?", [], "refuse"),
    ("Кто директор компании \"Zapo Servis\" MChJ и какой у неё телефон?", [], "refuse"),
    ("\"Toshkent Oltin Savdo\" MChJ qancha bitim tuzgan?", [], "refuse"),
    ("Какой был объём торгов в 2019 году?", [], "refuse"),
    ("Почему в 2023 году подорожал цемент?", [], "refuse"),
]


def agent_lang_wrong(a, q):
    import agent
    return agent.wrong_language(a, agent.lang_of(q))


def digits(s):
    return re.sub(r"[\s  ]", "", s)


def has_num(text, v):
    v = float(v)
    found = re.findall(r"\d[\d\s  ]*(?:[.,]\d+)?", text)
    vals = [float(digits(x).replace(",", ".")) for x in found if digits(x).replace(",", ".").count(".") <= 1]
    return any(abs(x - v) <= max(abs(v) * 1e-6, 0.51) for x in vals)


def main():
    base = next((a for a in sys.argv[1:] if a.startswith("http")), "http://127.0.0.1:8000")
    passed, res = 0, []
    only = next((a[5:] for a in sys.argv if a.startswith("only=")), None)
    cases = [x for x in CASES if not only or re.search(only, x[0])]
    for q, exp, kind in cases:
        t = time.time()
        r = httpx.post(base + "/api/ask", json={"question": q}, timeout=95).json()
        a, st = r["answer"], r["status"]
        if kind == "refuse":
            ok = st == "no_data"
        elif kind == "num":
            ok = all(has_num(a, v) for v in exp)
        else:
            ok = all(digits(str(v)).lower() in digits(a).lower() or name_key(str(v)) in name_key(a) for v in exp)
        ok = ok and not (kind != "refuse" and agent_lang_wrong(a, q))
        passed += ok
        wrong_lang = kind != "refuse" and __import__("agent").wrong_language(a, __import__("agent").lang_of(q))
        print(("PASS" if ok else "FAIL"), "WRONGLANG" if wrong_lang else "", f"[{time.time()-t:.1f}s {st} {r.get('model')} calls={len(r['steps'])}]", q, "\n   ->", a.replace("\n", " ")[:300], "\n   expected:", exp, flush=True)
        res.append({"q": q, "expected": [str(x) for x in exp], "answer": a, "status": st, "ok": bool(ok), "steps": r["steps"]})
        time.sleep(float(next((a[6:] for a in sys.argv if a.startswith("sleep=")), 7)))
    print(f"\n{passed}/{len(cases)} passed")
    json.dump(res, open("eval_results.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)


if __name__ == "__main__":
    main()
