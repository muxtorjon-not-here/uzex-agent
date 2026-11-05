"""Builds uzex.duckdb from the raw CSVs. Usage: python build_db.py [data_dir] [out_db]"""
import sys, os, duckdb
data = sys.argv[1] if len(sys.argv) > 1 else "../uzex_spot_data"
out = sys.argv[2] if len(sys.argv) > 2 else "uzex.duckdb"
if os.path.exists(out): os.remove(out)
c = duckdb.connect(out)
def num(col): return f"""TRY_CAST(replace(replace("{col}",' ',''),chr(160),'') AS DOUBLE)"""
def dt(col): return f"""try_strptime("{col}",'%d.%m.%Y')::DATE"""
opts = "header=true, all_varchar=true, delim=',', quote='\"', escape='\"'"
c.execute(f"""CREATE TABLE raw_deals AS SELECT * FROM read_csv('{data}/deals_*.csv', {opts}, union_by_name=true)""")
c.execute(f"""CREATE TABLE raw_contracts AS SELECT * FROM read_csv('{data}/contracts.csv', {opts})""")
c.execute(f"""CREATE TABLE participants AS SELECT "ИНН" inn, "Наименование" name, "Регион" region, "Вид деятельности" activity, "Роль" role, "Плательщик НДС" vat_payer FROM read_csv('{data}/participants.csv', {opts})""")
c.execute(f"""CREATE TABLE brokers AS SELECT "Код брокера" broker_code, "Наименование" name, "ИНН" inn, "Регион" region FROM read_csv('{data}/brokers.csv', {opts})""")
c.execute(f"""CREATE TABLE usd_rates AS SELECT {dt('Дата')} rate_date, {num('Курс')} rate FROM read_csv('{data}/usd_rates.csv', {opts})""")
c.execute(f"""CREATE TABLE contracts AS SELECT
 "Номер контракта" contract_no, "Наименование продукта" product_name, "Марка товара" brand, "Размер товара" size, "Сорт товара" grade, "Тип товара" type, "Класс товара" class,
 "Код ТН ВЭД" hs_code, "Группа товара" product_group, "Категория товара" category, "Отрасль промышленности" industry,
 "Единица измерения" unit, {num('Лот')} lot, "Валюта" currency, {num('Базисная цена')} base_price, "Сумма залога" deposit, "Базис поставки" delivery_basis,
 "Регион" region, "Адрес склада" warehouse, "Тип торгов" auction_type, "Тип контракта" contract_type, "Форма контракта" contract_form,
 {num('Срок оплаты')} pay_days, {num('Срок поставки')} delivery_days, "Упаковка" packaging, "ИНН продавца" seller_inn,
 {dt('Дата регистрации')} registered, {dt('Действует до')} valid_until FROM raw_contracts""")
c.execute(f"""CREATE TABLE deals AS SELECT
 "Номер сделки" deal_no, {dt('Дата сделки')} deal_date, "Время сделки" deal_time, "Тип торгов" auction_type, {num('Количество')} qty, {num('Сумма сделки')} amount,
 {num('Стартовая цена')} start_price, "Номер контракта" contract_no, "Наименование товара" product, {num('Лот')} lot, "Единица измерения" unit, "Регион" region,
 "Тип контракта" contract_type, "Форма контракта" contract_form, "Состояние сделки" status, "ИНН продавца" seller_inn, "ИНН покупателя" buyer_inn,
 "Брокер продавца" seller_broker, "Брокер покупателя" buyer_broker, {dt('Дата оплаты')} paid_date, {dt('Дата поставки')} delivered_date, {num('Поставлено')} delivered_lots FROM raw_deals""")
print(c.execute("select count(*), count(distinct deal_no), min(deal_date), max(deal_date) from deals").fetchall())
