"""Second, wider evaluation: question types not in eval.py. Expected values come from the raw CSVs.
Usage: python eval2.py base_url [sleep=12] [only=regex]"""
import json
import re
import sys
import time

import httpx

import eval as b
from textnorm import name_key

AMT, QTY, LOT, OK, YR, one, c = b.AMT, b.QTY, b.LOT, b.OK, b.YR, b.one, b.c
UZS = f"""(case when rd."Тип контракта"='Экспортный' then {AMT}*cast(u."Курс" as double) else {AMT} end)"""
JU = """join ru u on rd."Дата сделки"=u."Дата" """
JC = """join rc using("Номер контракта")"""
d = lambda col: f"""strptime({col},'%d.%m.%Y')::date"""

t24 = one(f"select sum({UZS}) from rd {JU} where {OK} and {YR(2024)}")
t25 = one(f"select sum({UZS}) from rd {JU} where {OK} and {YR(2025)}")
c25 = one(f"select count(*) from rd where {YR(2025)}")
x25 = one(f"""select count(*) from rd where {YR(2025)} and "Состояние сделки" like 'Аннулирован%'""")
big = c.execute(f"""select "Номер сделки" from rd {JU} where {OK} and {YR(2025)} order by {UZS} desc limit 1""").fetchone()[0]
inn_row = c.execute("""select "Наименование","Вид деятельности" from rp where "ИНН"='953758401'""").fetchone()
brk = c.execute("""select "Наименование","Регион" from rb where "Код брокера"='BK027'""").fetchone()
cat24 = one(f"""select rc."Категория товара" from rd {JU} {JC} where {OK} and {YR(2024)} group by 1 order by sum({UZS}) desc limit 1""")
mon = c.execute(f"""select count(*) n from rd where {YR(2025)} and {OK} group by substr("Дата сделки",4,2) order by n desc limit 1""").fetchone()[0]

N, P, S, R = "num", "pct", "str", "refuse"
CASES = [
    ("Какой был самый высокий курс доллара за весь период?", [one("""select max(cast("Курс" as double)) from ru""")], P),
    ("Сколько контрактов зарегистрировано в 2024 году?", [one("""select count(*) from rc where "Дата регистрации" like '%.2024'""")], N),
    ("Какая сумма залога и какая упаковка у контракта 100002?", ["10", "мешках по 50"], S),
    ("100001 raqamli shartnomaning ombor manzili qayerda?", ["Tinchlik"], S),
    ("Что за компания с ИНН 953758401 и какой у неё вид деятельности?", [inn_row[0], inn_row[1]], S),
    ("Сколько сделок в Ферганской области за 2025 год без аннулированных?", [one(f"""select count(*) from rd where {OK} and {YR(2025)} and "Регион"='Farg‘ona viloyati'""")], N),
    ("Farg'ona viloyatida 2023-yilda nechta bitim bo'lgan, bekor qilinganlarsiz?", [one(f"""select count(*) from rd where {OK} and {YR(2023)} and "Регион"='Farg‘ona viloyati'""")], N),
    ("Какой номер у самой крупной сделки 2025 года по сумме в сумах, без аннулированных?", [big], S),
    ("Какая средневзвешенная цена за литр бензина АИ-92 в 2026 году без аннулированных?",
     [one(f"""select sum({AMT})/sum({QTY}*{LOT}) from rd where {OK} and {YR(2026)} and upper("Наименование товара") like '%АИ-92%' and rd."Единица измерения"='литр'""")], P),
    ("Сколько килограммов муки первого сорта продано в 2024 году без аннулированных?",
     [one(f"""select sum({QTY}*{LOT}) from rd where {OK} and {YR(2024)} and upper("Наименование товара") like '%МУКА%' and regexp_matches(upper("Наименование товара"),'(^|[^А-ЯA-Z0-9])(1|I|ПЕРВЫЙ)[- ]*СОРТ')""")], N),
    ("2025-yilda 3-sinf bug'doydan necha tonna sotilgan, bekor qilinganlarsiz?",
     [one(f"""select sum({QTY}*{LOT}) from rd where {OK} and {YR(2025)} and upper("Наименование товара") like '%ПШЕНИЦА%' and regexp_matches(upper("Наименование товара"),'(^|[^А-ЯA-Z0-9])(3|III)[- ]*КЛАСС')""")], N),
    ("Сколько сделок прошло через обратный аукцион в 2023 году, включая аннулированные?", [one(f"""select count(*) from rd where {YR(2023)} and "Тип торгов"='Обратный аукцион'""")], N),
    ("2025-yilda eng ko'p bitim tuzilgan oyda nechta bitim bo'lgan, bekor qilinganlarsiz?", [mon], N),
    ("Какая категория товаров заняла первое место по обороту в сумах в 2024 году?", [cat24], S),
    ("Какая доля аннулированных сделок в 2025 году в процентах?", [round(100 * x25 / c25, 2)], P),
    ("На сколько процентов вырос оборот в сумах в 2025 году по сравнению с 2024 годом, без аннулированных?", [round(100 * (t25 / t24 - 1), 2)], P),
    ("Сколько уникальных покупателей совершили сделки в 2026 году, без аннулированных?", [one(f"""select count(distinct "ИНН покупателя") from rd where {OK} and {YR(2026)}""")], N),
    ("Toshkent viloyatida ro'yxatdan o'tgan nechta xaridor bor?", [one("""select count(*) from rp where "Роль"='Покупатель' and "Регион"='Toshkent viloyati'""")], N),
    ("Сколько строительных компаний среди участников?", [one("""select count(*) from rp where "Вид деятельности"='Строительная компания'""")], N),
    ("Сколько сделок сейчас в статусе «Не подписан»?", [one("""select count(*) from rd where "Состояние сделки"='Не подписан'""")], N),
    ("Сколько дней в среднем проходило от оплаты до поставки цемента в 2024 году?",
     [one(f"""select avg({d('"Дата поставки"')}-{d('"Дата оплаты"')}) from rd {JC} where {YR(2024)} and "Дата поставки"<>'' and "Дата оплаты"<>'' and upper("Наименование продукта") like '%ЦЕМЕНТ%'""")], P),
    ("30.10.2026 kuni nechta bitim tuzilgan?", [one("""select count(*) from rd where "Дата сделки"='30.10.2026'""")], N),
    ("BK027 kodli broker nomi nima va qaysi viloyatda?", [brk[0], brk[1]], S),
    ("Сколько брокеров зарегистрировано в Ташкенте (город)?", [one("""select count(*) from rb where "Регион"='Toshkent shahri'""")], N),
    ("Какая максимальная цена за тонну медного катода в экспортных сделках 2025 года в долларах?",
     [one(f"""select max({AMT}/({QTY}*{LOT})) from rd where {OK} and {YR(2025)} and "Тип контракта"='Экспортный' and upper("Наименование товара") like '%КАТОД%'""")], P),
    ("2025 йилда нечта экспорт битими бўлган, бекор қилинганларсиз?", [one(f"""select count(*) from rd where {OK} and {YR(2025)} and "Тип контракта"='Экспортный'""")], N),
    ("Сколько тонн цемента фактически поставлено по сделкам 2024 года?",
     [one(f"""select sum(cast("Поставлено" as double)*{LOT}) from rd {JC} where {YR(2024)} and "Поставлено"<>'' and upper("Наименование продукта") like '%ЦЕМЕНТ%'""")], N),
    ("Сколько сделок заключено в субботу за весь период?", [0], N),
    ("Какой курс евро был 15.03.2025?", [], R),
    ("Какая цена на нефть Brent в 2025 году?", [], R),
    ("Сколько сделок было 15.02.2021?", [], R),
    ("2026-yil dekabrda nechta bitim tuzilgan?", [], R),
    ("Какая прибыль была у компании \"Zapo Servis\" MChJ в 2025 году?", [], R),
    ("Qaysi broker eng ishonchli va yaxshi?", [], R),
]


def nums(text):
    found = re.findall(r"\d[\d\s  ]*(?:[.,]\d+)?", text)
    out = []
    for x in found:
        y = re.sub(r"[\s  ]", "", x).replace(",", ".")
        try:
            out.append(float(y))
        except ValueError:
            pass
    return out


def main():
    base = next((a for a in sys.argv[1:] if a.startswith("http")), "http://127.0.0.1:8001")
    pause = float(next((a[6:] for a in sys.argv if a.startswith("sleep=")), 12))
    only = next((a[5:] for a in sys.argv if a.startswith("only=")), None)
    cases = [x for x in CASES if not only or re.search(only, x[0])]
    passed, res = 0, []
    for q, exp, kind in cases:
        t = time.time()
        r = httpx.post(base + "/api/ask", json={"question": q}, timeout=95).json()
        a, st = r["answer"], r["status"]
        vals = nums(a)
        if kind == R:
            ok = st == "no_data"
        elif kind == N:
            ok = all(any(abs(x - float(v)) <= max(abs(float(v)) * 1e-6, 0.51) for x in vals) for v in exp)
        elif kind == P:
            ok = all(any(abs(x - float(v)) <= max(abs(float(v)) * 1e-6, 0.011) for x in vals) for v in exp)
        else:
            flat = re.sub(r"\s", "", a).lower()
            ok = all(re.sub(r"\s", "", str(v)).lower() in flat or name_key(str(v)) in name_key(a) for v in exp)
        if kind != R and st == "no_data":
            ok = False
        passed += ok
        print("PASS" if ok else "FAIL", f"[{time.time()-t:.1f}s {st} {r.get('model')} calls={len(r['steps'])}]", q, "\n   ->", a.replace("\n", " ")[:300], "\n   expected:", exp, flush=True)
        res.append({"q": q, "expected": [str(x) for x in exp], "answer": a, "status": st, "ok": bool(ok), "steps": r["steps"]})
        time.sleep(pause)
    print(f"\n{passed}/{len(cases)} passed")
    json.dump(res, open("eval_results2.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)


if __name__ == "__main__":
    main()
