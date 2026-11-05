"""Stage 2 of the build: canonical commodities/grades/classes, company name keys, one wide deals table.
Run after build_db.py. Usage: python normalize.py [db]"""
import os
import re
import sys

import duckdb

from textnorm import name_key

out = sys.argv[1] if len(sys.argv) > 1 else "uzex.duckdb"
c = duckdb.connect(out)

COMMODITIES = [  # regex on upper-cased text -> canonical Russian name; order matters
    (r"ХЛОПОК", "Хлопок-сырец"), (r"ПРЯЖА", "Пряжа хлопчатобумажная"), (r"ШРОТ", "Шрот хлопковый"),
    (r"МАСЛО ХЛОПК|ХЛОПКОВОЕ МАСЛО", "Масло хлопковое"), (r"ПОДСОЛНЕЧ", "Масло подсолнечное"),
    (r"ПШЕНИЦА", "Пшеница"), (r"МУКА", "Мука"), (r"\bРИС\b", "Рис"), (r"САХАР", "Сахар"), (r"ВОДА", "Вода питьевая"),
    (r"КОМБИКОРМ|КОРМОСМЕСЬ", "Комбикорм"), (r"\bСОЛЬ\b", "Соль пищевая"), (r"ГИПС", "Гипс"), (r"ИЗВЕСТЬ", "Известь"),
    (r"ЦЕМЕНТ", "Цемент"), (r"БЕНЗИН", "Бензин"), (r"ДИЗЕЛЬ", "Дизельное топливо"), (r"МАЗУТ", "Мазут"),
    (r"СЖИЖЕНН", "Сжиженный газ"), (r"БИТУМ", "Битум"), (r"АРГОН", "Аргон"), (r"АЗОТ", "Азот"),
    (r"КИСЛОТА", "Серная кислота"), (r"\bСОДА\b", "Сода каустическая"), (r"КАРБАМИД|МОЧЕВИНА", "Карбамид"),
    (r"СЕЛИТРА", "Аммиачная селитра"), (r"ЭМАЛЬ", "Эмаль"), (r"ТРУБ", "Трубы полиэтиленовые"),
    (r"ПОЛИЭТИЛЕН", "Полиэтилен"), (r"ПОЛИПРОПИЛЕН", "Полипропилен"), (r"ПОЛИВИНИЛХЛОРИД", "Поливинилхлорид"),
    (r"ПИЛОМАТЕРИАЛ", "Пиломатериалы"), (r"КИРПИЧ", "Кирпич"), (r"СТЕКЛО", "Стекло"), (r"ЛИСТ СТАЛЬНОЙ", "Лист стальной"),
    (r"ПРОВОЛОКА", "Проволока арматурная"), (r"АРМАТУРА", "Арматура"), (r"КАТОД", "Катод медный"),
    (r"ПРОФИЛЬ", "Профиль алюминиевый"), (r"ПОДШИПНИК", "Подшипник"), (r"КАБЕЛЬ", "Кабель силовой"),
]
NUM = {"I": "1", "II": "2", "III": "3", "IV": "4", "1": "1", "2": "2", "3": "3", "4": "4",
       "ПЕРВЫЙ": "1", "ВТОРОЙ": "2", "ТРЕТИЙ": "3"}


def commodity(t):
    for rx, name in COMMODITIES:
        if re.search(rx, t):
            return name
    raise SystemExit("UNMAPPED PRODUCT: " + t)


def grade(t):
    if re.search(r"ВЫСШ|В/С", t):
        return "высший"
    m = re.search(r"(?<![А-ЯA-Z0-9])(ПЕРВЫЙ|ВТОРОЙ|ТРЕТИЙ|III|II|I|1|2|3)[- ]*СОРТ", t)
    return NUM[m.group(1)] if m else None


def klass(t):
    m = re.search(r"(?<![А-ЯA-Z0-9])(IV|III|II|I|1|2|3|4)[- ]*КЛАСС", t)
    return NUM[m.group(1)] if m else None


def squash(s):
    return re.sub(r"\s+", "", s).upper() if s else None


rows = c.execute("select contract_no, product_name, brand, size, grade, type, class from contracts").fetchall()
known = sorted({squash(r[2]) for r in rows if r[2] and len(squash(r[2])) >= 3 and not squash(r[2]).startswith("ВЫСШ")},
               key=len, reverse=True)
norm = []
for no, name, brand, size, gr, ty, cl in rows:
    t = " ".join(x for x in (name, brand, size, gr, ty, cl) if x).upper()
    sq = squash(t)
    mark = squash(brand)
    if mark and mark.startswith("ВЫСШ"):
        mark = None
    if not mark:
        mark = next((k for k in known if k in sq), None)
    sz = squash(size)
    if not sz:
        m = re.search(r"(Ø\s*\d+\s*ММ|\d+Х\d+(?:Х\d+)?\s*ММ|\d+\s*ММ)", t)
        sz = squash(m.group(1)) if m else None
    norm.append((no, commodity(t), grade(t), klass(t), mark, sz))
c.execute("create table cnorm(contract_no varchar, commodity varchar, grade_n varchar, class_n varchar, mark varchar, size_n varchar)")
c.executemany("insert into cnorm values (?,?,?,?,?,?)", norm)

for tbl, key in (("participants", "inn"), ("brokers", "broker_code")):
    c.execute(f"alter table {tbl} add column name_key varchar")
    vals = [(name_key(n), k) for k, n in c.execute(f"select {key}, name from {tbl}").fetchall()]
    c.execute("create temp table k(nk varchar, id varchar)")
    c.executemany("insert into k values (?,?)", vals)
    c.execute(f"update {tbl} set name_key=k.nk from k where {tbl}.{key}=k.id")
    c.execute("drop table k")

c.execute("""CREATE TABLE deals2 AS SELECT
 CAST(d.deal_no AS BIGINT) deal_no, d.deal_date, d.deal_time, year(d.deal_date) yr, month(d.deal_date) mon, d.auction_type,
 d.qty, d.amount, d.start_price, CAST(d.contract_no AS BIGINT) contract_no, d.product, n.commodity, n.grade_n, n.class_n, n.mark, n.size_n,
 k.product_group, k.category, k.industry, k.hs_code, d.lot, d.unit, d.qty*d.lot volume,
 CASE d.unit WHEN 'тонна' THEN d.qty*d.lot WHEN 'килограмм' THEN d.qty*d.lot/1000 END volume_t,
 d.amount/(d.qty*d.lot) unit_price,
 CASE k.currency WHEN 'Доллар США' THEN 'USD' ELSE 'UZS' END currency, u.rate usd_rate,
 CASE WHEN k.currency='Доллар США' THEN d.amount*u.rate ELSE d.amount END amount_uzs,
 CASE WHEN k.currency='Доллар США' THEN d.amount ELSE d.amount/u.rate END amount_usd,
 d.region, k.region region_ru, d.contract_type, d.contract_form, d.status, d.status LIKE 'Аннулирован%' is_cancelled,
 d.seller_inn, s.name seller_name, s.region seller_region, d.buyer_inn, b.name buyer_name, b.region buyer_region,
 d.seller_broker, sb.name seller_broker_name, d.buyer_broker, bb.name buyer_broker_name,
 d.paid_date, d.delivered_date, d.delivered_lots, d.delivered_lots*d.lot delivered_volume,
 d.paid_date-d.deal_date days_to_pay, d.delivered_date-d.paid_date days_to_deliver, k.pay_days, k.delivery_days,
 k.delivery_basis, k.packaging, CAST(replace(replace(k.deposit,'%',''),' ','') AS INT) deposit_pct, k.base_price
 FROM deals d JOIN contracts k ON d.contract_no=k.contract_no JOIN cnorm n ON d.contract_no=n.contract_no
 JOIN usd_rates u ON d.deal_date=u.rate_date JOIN participants s ON d.seller_inn=s.inn JOIN participants b ON d.buyer_inn=b.inn
 JOIN brokers sb ON d.seller_broker=sb.broker_code JOIN brokers bb ON d.buyer_broker=bb.broker_code ORDER BY d.deal_date""")
c.execute("""CREATE TABLE contracts2 AS SELECT CAST(k.contract_no AS BIGINT) contract_no, n.commodity, n.grade_n, n.class_n, n.mark, n.size_n,
 k.* EXCLUDE(contract_no), p.name seller_name FROM contracts k JOIN cnorm n USING(contract_no) JOIN participants p ON k.seller_inn=p.inn""")
c.execute("drop table deals; drop table contracts; drop table cnorm; drop table raw_deals; drop table raw_contracts")
c.execute("alter table deals2 rename to deals; alter table contracts2 rename to contracts")
print(c.execute("select count(*), count(distinct commodity), round(sum(amount_uzs)) from deals").fetchall())
c.execute("checkpoint")
c.close()

# compact copy without free blocks
c = duckdb.connect()
c.execute(f"attach '{out}' as a (read_only); attach '{out}.tmp' as b; copy from database a to b; detach a; detach b")
c.close()
os.replace(out + ".tmp", out)
