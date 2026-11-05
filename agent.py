"""Grounded exchange-data agent: Gemini writes SQL, DuckDB computes, code verifies every number in the answer."""
import datetime as dt
import decimal
import difflib
import json
import os
import re
import threading
import time

import duckdb
import httpx

from textnorm import name_key

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uzex.duckdb")
API = "https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent"
MODELS = [m.strip() for m in os.getenv("GEMINI_MODELS", "gemini-2.5-flash,gemini-2.5-flash-lite").split(",") if m.strip()]
DEADLINE_S = 75  # the committee allows 90 s per answer
MAX_ROWS = 50

_db = duckdb.connect(DB_PATH, read_only=True, config={"memory_limit": os.getenv("DUCKDB_MEM", "320MB"), "threads": 2})
_db.execute("SET enable_external_access=false")
_db.execute("SET lock_configuration=true")

_entities = []
for inn, name, region, activity, role, key in _db.execute(
        "select inn,name,region,activity,role,name_key from participants").fetchall():
    _entities.append({"kind": "company", "inn": inn, "name": name, "region": region, "activity": activity, "role": role, "key": key})
for code, name, inn, region, key in _db.execute("select broker_code,name,inn,region,name_key from brokers").fetchall():
    _entities.append({"kind": "broker", "broker_code": code, "inn": inn, "name": name, "region": region, "key": key})

SYSTEM = """Sen UZEX birja bitimlari reyestri bo'yicha javob beruvchi agentsan. Ты агент по реестру сделок биржи.
Ma'lumotlar o'ylab topilgan, 03.01.2022 - 30.10.2026 oralig'ida, holatlar 30.10.2026 kuni oxiriga.

HARD RULES
1. Every fact must come from a tool result in THIS conversation. Never answer from memory. Never invent a number, company, product, date.
2. If the data cannot answer (not in the schema, outside the period, forecast/future, opinion, reasons "why", owners, phones, real-world facts, or the query returned nothing) reply exactly with:
   Uzbek: "Ma'lumotda javob yo'q." / Russian: "В данных ответа нет." and one short sentence on what is missing. Do not guess or give a near substitute. Do not mention a product/company that was asked about but not found.
3. Answer in the language AND script of the question (Uzbek Latin, Uzbek Cyrillic, or Russian).
4. Compute everything in SQL, including percentages, differences, shares, roundings. Never do arithmetic yourself. Copy numbers from the results exactly; you may round money to "mlrd/млрд", "mln/млн" only with 2+ decimals, and then also keep the exact figure.
5. Start with the direct answer. Then one short line "Hisoblash:"/"Расчёт:" stating filters used (period, statuses, units, currency). No filler.

DATA RULES (from the organisers' README)
- Table deals is one wide table. Use it. volume = qty*lot in unit of measure, unit_price = amount/(qty*lot), both precomputed.
- Cancelled deals (is_cancelled, status 'Аннулирован(Не оплачен)') DID NOT HAPPEN. Exclude them with NOT is_cancelled from turnover, volume, prices, rankings and averages, and say so. When asked "how many deals" count NOT is_cancelled and also state the total including cancelled. Only include them when the question is about cancellations or statuses.
- Money: amount is in contract currency (UZS, or USD for export). NEVER sum amount across currencies. For totals use amount_uzs (USD converted at the deal-date rate; already computed). For export-only questions report USD (amount) and, if useful, amount_uzs.
- Average price: volume-weighted = SUM(amount)/SUM(volume), per unit and currency, unless the question asks for a simple average or median. State which.
- Units: NEVER sum different units. Бензин is sold in тонна and литр, Дизельное топливо in тонна and килограмм. volume_t converts kg and t to tonnes (NULL for other units). Group by unit for price and for litres. Check the units before answering a volume or price question on a product.
- Products: filter by commodity (canonical, exact values listed below), never by the raw product text. grade_n: '1','2','3','высший'. class_n: '1','2','3','4'. mark e.g. 'АИ-92', 'ЦЕМI42,5Н', 'ЦЕМII/А-Ш32,5Н', 'БНД90/130', 'NE24/1', 'PP-2310', 'ДТ-Е-К5', spaces removed and upper-case. size_n e.g. 'Ø12ММ'. Use contract_form for spot/forward/futures of cotton.
- Regions: deals.region, participants.region, brokers.region use Uzbek names; deals.region_ru and contracts.region use Russian. region is the seller's warehouse region. seller_region and buyer_region are company registration regions. If asked "buyers from X" use buyer_region; "sold in/from X" or "region of the deal" use region.
- Companies/brokers: ALWAYS call find_entity first when the question names one, then filter by inn or broker code, never by name. Several different companies can have near-identical names: if find_entity returns more than one plausible match with a different INN, report each one separately or say which you used. If none matches, the company is not in the data: use rule 2.
- An INN in the question: filter seller_inn or buyer_inn directly; a company is either a seller or a buyer.
- Late payment: paid_date - deal_date > pay_days (days_to_pay > pay_days). Late delivery: days_to_deliver > delivery_days. pay_days runs from deal date, delivery_days from payment date, calendar days.
- Partially delivered: status 'Исполнен(Частично)', delivered_lots of qty, delivered_volume in units.
- USD rate of a day: usd_rates(rate_date, rate). Sum/start price per unit: start_price is per unit of measure in contract currency.
- Dates are DATE type. Months: yr and mon columns. Quarter: quarter(deal_date). When the period is not stated, use the whole data and say so.
- Use LIMIT for rankings and include ties awareness. Return the name and INN together in ranking queries.
- Contract details (deposit, delivery_basis, packaging, warehouse, registered, valid_until) are in contracts.

SCHEMA
deals(deal_no BIGINT, deal_date DATE, deal_time VARCHAR, yr, mon, auction_type ['Английский аукцион','Обратный аукцион','Двусторонний аукцион'], qty, amount, start_price, contract_no BIGINT, product, commodity, grade_n, class_n, mark, size_n, product_group ['Высоколиквидные товары','Прочие товары'], category, industry, hs_code, lot, unit ['тонна','килограмм','литр','штука','куб.метр','кв.метр','метр'], volume, volume_t, unit_price, currency ['UZS','USD'], usd_rate, amount_uzs, amount_usd, region, region_ru, contract_type ['Внутренний','Экспортный'], contract_form ['Спот','Форвард','Фьючерс'], status ['Новый','Не подписан','Заключен','Ждёт оплату','Оплачен','Исполнен','Исполнен(Частично)','Аннулирован(Не оплачен)'], is_cancelled BOOL, seller_inn, seller_name, seller_region, buyer_inn, buyer_name, buyer_region, seller_broker, seller_broker_name, buyer_broker, buyer_broker_name, paid_date, delivered_date, delivered_lots, delivered_volume, days_to_pay, days_to_deliver, pay_days, delivery_days, delivery_basis ['EXW','FCA','DAP','CPT'], packaging, deposit_pct, base_price)
contracts(contract_no BIGINT, commodity, grade_n, class_n, mark, size_n, product_name, brand, size, grade, type, class, hs_code, product_group, category, industry, unit, lot, currency ['Узбекский сум','Доллар США'], base_price, deposit, delivery_basis, region, warehouse, auction_type, contract_type, contract_form, pay_days, delivery_days, packaging, seller_inn, registered DATE, valid_until DATE, seller_name)
participants(inn, name, region, activity, role ['Продавец','Покупатель'], vat_payer ['Да','Нет'])
brokers(broker_code, name, inn, region)
usd_rates(rate_date DATE, rate)
All inn columns are VARCHAR.

REGIONS (deals.region): Toshkent shahri, Toshkent viloyati, Namangan viloyati, Buxoro viloyati, Samarqand viloyati, Sirdaryo viloyati, Qashqadaryo viloyati, Xorazm viloyati, Andijon viloyati, Farg‘ona viloyati, Surxondaryo viloyati, Navoiy viloyati, Qoraqalpog‘iston Respublikasi, Jizzax viloyati. Note the character ‘ in Farg‘ona and Qoraqalpog‘iston.

COMMODITIES (commodity value = Uzbek word): Хлопок-сырец=paxta xomashyosi, Пряжа хлопчатобумажная=ip-kalava, Шрот хлопковый=paxta shroti/kunjara, Масло хлопковое=paxta yog'i, Масло подсолнечное=kungaboqar yog'i, Пшеница=bug'doy, Мука=un, Рис=guruch, Сахар=shakar, Вода питьевая=ichimlik suvi, Комбикорм=omuxta yem, Соль пищевая=osh tuzi, Гипс=gips, Известь=ohak, Цемент=sement, Бензин=benzin, Дизельное топливо=dizel yoqilg'isi, Мазут=mazut, Сжиженный газ=suyultirilgan gaz, Битум=bitum, Аргон=argon, Азот=azot, Серная кислота=sulfat kislota, Сода каустическая=kaustik soda, Карбамид=karbamid/mochevina, Аммиачная селитра=ammiakli selitra, Эмаль=emal, Трубы полиэтиленовые=polietilen quvur, Полиэтилен=polietilen, Полипропилен=polipropilen, Поливинилхлорид=PVX, Пиломатериалы=yog'och taxta, Кирпич=g'isht, Стекло=oyna/shisha, Лист стальной=po'lat list, Проволока арматурная=armatura simi, Арматура=armatura, Катод медный=mis katod, Профиль алюминиевый=alyuminiy profil, Подшипник=podshipnik, Кабель силовой=kuch kabeli.
Anything else (gold, oil, coal, meat, etc.) is NOT in the data: rule 2.
"""

TOOLS = [{"functionDeclarations": [
    {"name": "run_sql",
     "description": "Run one read-only DuckDB SELECT over deals, contracts, participants, brokers, usd_rates. Returns up to 50 rows.",
     "parameters": {"type": "OBJECT", "properties": {"sql": {"type": "STRING"}}, "required": ["sql"]}},
    {"name": "find_entity",
     "description": "Find companies and brokers by name in any script (Latin/Cyrillic), tolerant of spelling. Returns candidates with INN.",
     "parameters": {"type": "OBJECT", "properties": {"name": {"type": "STRING"}}, "required": ["name"]}},
]}]

FORBIDDEN = re.compile(r"\b(insert|update|delete|drop|alter|create|attach|detach|copy|export|import|install|load|pragma|set|call|checkpoint|read_csv\w*|read_parquet|read_text|read_blob|glob)\b", re.I)


def _plain(v):
    if isinstance(v, decimal.Decimal):
        return float(v)
    if isinstance(v, (dt.date, dt.datetime)):
        return v.strftime("%d.%m.%Y")
    if isinstance(v, dt.timedelta):
        return v.days
    if isinstance(v, float):
        return round(v, 6)
    return v


def run_sql(sql: str) -> dict:
    s = sql.strip().rstrip(";")
    if ";" in s or not re.match(r"^(select|with)\b", s, re.I) or FORBIDDEN.search(re.sub(r"'[^']*'", "''", s)):
        return {"error": "Only a single read-only SELECT is allowed."}
    cur = _db.cursor()
    timer = threading.Timer(25, cur.interrupt)
    timer.start()
    try:
        cur.execute(s)
        cols = [d[0] for d in cur.description]
        rows = cur.fetchmany(MAX_ROWS + 1)
    except Exception as e:  # the model reads the error and corrects its SQL
        return {"error": str(e)[:500]}
    finally:
        timer.cancel()
        cur.close()
    return {"columns": cols, "rows": [[_plain(v) for v in r] for r in rows[:MAX_ROWS]], "truncated": len(rows) > MAX_ROWS}


def find_entity(name: str) -> dict:
    q = name_key(name)
    if not q:
        return {"matches": []}
    scored = []
    words = q.split()
    for e in _entities:
        k = e["key"]
        if k == q:
            s = 1.0
        elif all(w in k.split() for w in words):
            s = 0.95
        elif q in k:
            s = 0.9
        else:
            if abs(len(k) - len(q)) > 6 or k[:1] != q[:1]:
                continue
            s = difflib.SequenceMatcher(None, q, k).ratio()
            if s < 0.8:
                continue
        scored.append((s, e))
    scored.sort(key=lambda x: -x[0])
    return {"matches": [{**{a: b for a, b in e.items() if a != "key"}, "score": round(s, 2)} for s, e in scored[:8]]}


# ---------- verification ----------
NUM_RE = re.compile(r"(?<![\w.,])\d[\d\s  ]*(?:[.,]\d+)?(?![\d])")
DATE_RE = re.compile(r"\b\d{2}\.\d{2}\.\d{4}\b")
SCALES = [(r"трлн|trln", 1e12), (r"млрд|mlrd|milliard", 1e9), (r"млн|mln|million|миллион", 1e6), (r"тыс|ming", 1e3)]
NAME_RE = re.compile(r"\"[^\"\n]{2,60}\"\s*(?:MChJ|МЧЖ|AJ|АЖ|XK|ХК)|[A-ZА-ЯЎҚҒҲ‘’]{2,}(?:\s[A-ZА-ЯЎҚҒҲ‘’]{2,})+\s(?:MCHJ|МЧЖ|AJ|XK)\b")
REFUSALS = ("ma'lumotda javob yo", "ma’lumotda javob yo", "ma‘lumotda javob yo", "в данных ответа нет", "маълумотда жавоб йўқ")


def is_refusal(text: str) -> bool:
    t = text.lower()
    return any(r in t for r in REFUSALS)


def _to_float(tok: str):
    t = re.sub(r"[\s  ]", "", tok).replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return None


def _evidence(steps):
    nums, blob = [], []
    for st in steps:
        res = st["result"]
        if "rows" in res:
            for r in res["rows"]:
                for v in r:
                    if isinstance(v, bool):
                        continue
                    if isinstance(v, (int, float)):
                        nums.append(float(v))
                    elif v is not None:
                        blob.append(str(v))
                        for m in re.findall(r"\d+(?:[.,]\d+)?", str(v)):
                            nums.append(float(m.replace(",", ".")))
        for e in res.get("matches", []):
            blob.append(e["name"])
            if e.get("inn"):
                nums.append(float(e["inn"]))
    return nums, " ".join(blob)


def verify(answer: str, question: str, steps):
    """Returns the claims in the answer that no tool result supports."""
    nums, blob = _evidence(steps)
    bad = []
    text = DATE_RE.sub(lambda m: m.group(0) if m.group(0) in blob or m.group(0) in question or m.group(0) in ("03.01.2022", "30.10.2026") else "\0" + m.group(0), answer)
    bad += [d for d in re.findall(r"\0(\d{2}\.\d{2}\.\d{4})", text)]
    text = DATE_RE.sub(" ", text.replace("\0", ""))
    qnums = {_to_float(x) for x in NUM_RE.findall(question)}
    for m in NUM_RE.finditer(text):
        tok = m.group(0).strip()
        v = _to_float(tok)
        if v is None:
            continue
        tail = text[m.end():m.end() + 10].lower()
        scale = next((s for rx, s in SCALES if re.match(r"\s*(" + rx + ")", tail)), 1.0)
        val = v * scale
        if v in qnums or (scale == 1 and v <= 12 and float(v).is_integer()) or (scale == 1 and 2022 <= v <= 2026):
            continue
        decimals = len(tok.replace(",", ".").split(".")[1]) if "." in tok.replace(",", ".") else 0
        tol = max(0.5 * 10 ** (-decimals) * scale, abs(val) * 1e-9)
        if not any(abs(abs(n) - val) <= tol for n in nums):
            bad.append(tok)
    keyblob = name_key(blob)
    for nm in NAME_RE.findall(answer):
        if name_key(nm) not in keyblob:
            bad.append(nm)
    return bad


# ---------- Gemini loop ----------
def _call(key, contents, deadline):
    body = {"systemInstruction": {"parts": [{"text": SYSTEM}]}, "contents": contents, "tools": TOOLS,
            "generationConfig": {"temperature": 0}}
    last = None
    for attempt in range(6):
        model = MODELS[min(attempt // 2, len(MODELS) - 1)]
        left = deadline - time.time()
        if left < 3:
            break
        try:
            r = httpx.post(API.format(m=model), headers={"x-goog-api-key": key}, json=body, timeout=min(left, 40))
            if r.status_code == 200:
                d = r.json()
                cand = (d.get("candidates") or [{}])[0]
                if cand.get("content", {}).get("parts"):
                    return cand["content"], model
                last = "empty response: " + str(cand.get("finishReason"))
            else:
                last = f"HTTP {r.status_code}: {r.text[:200]}"
                if r.status_code not in (429, 500, 503):
                    break
        except httpx.HTTPError as e:
            last = repr(e)
        time.sleep(min(2 * (attempt + 1), 6))
    raise RuntimeError(last or "model unavailable")


def lang_of(q: str) -> str:
    if re.search(r"[ўқғҳЎҚҒҲ]", q):
        return "uzc"
    if re.search(r"[а-яА-Я]", q):
        return "ru"
    return "uz"


MSG = {
    "unverified": {"ru": "Не удалось надёжно подтвердить ответ данными, поэтому я его не даю. Переформулируйте вопрос.",
                   "uz": "Javobni ma'lumotlar bilan ishonchli tasdiqlab bo'lmadi, shuning uchun bermayapman. Savolni boshqacha yozing.",
                   "uzc": "Жавобни маълумотлар билан ишончли тасдиқлаб бўлмади, шунинг учун бермаяпман. Саволни бошқача ёзинг."},
    "busy": {"ru": "Сервис модели сейчас недоступен, попробуйте ещё раз через минуту.",
             "uz": "Model xizmati hozir ishlamayapti, bir daqiqadan keyin qayta urinib ko'ring.",
             "uzc": "Модель хизмати ҳозир ишламаяпти, бир дақиқадан кейин қайта уриниб кўринг."},
}


def answer(question: str) -> dict:
    key = os.environ.get("GEMINI_API_KEY", "")
    t0 = time.time()
    deadline = t0 + DEADLINE_S
    lang = lang_of(question)
    contents = [{"role": "user", "parts": [{"text": question}]}]
    steps, retries, model = [], 0, None
    out = lambda text, status: {"answer": text, "status": status, "steps": steps, "seconds": round(time.time() - t0, 1), "model": model}
    try:
        for _ in range(10):
            content, model = _call(key, contents, deadline)
            contents.append(content)
            calls = [p["functionCall"] for p in content["parts"] if "functionCall" in p]
            if calls:
                replies = []
                for fc in calls:
                    args = fc.get("args", {})
                    if fc["name"] == "run_sql":
                        res = run_sql(args.get("sql", ""))
                    elif fc["name"] == "find_entity":
                        res = find_entity(args.get("name", ""))
                    else:
                        res = {"error": "unknown tool"}
                    steps.append({"tool": fc["name"], "args": args, "result": res})
                    replies.append({"functionResponse": {"name": fc["name"], "response": {"result": res}}})
                contents.append({"role": "user", "parts": replies})
                continue
            text = "".join(p.get("text", "") for p in content["parts"] if not p.get("thought")).strip()
            if is_refusal(text):
                return out(text, "no_data")
            if not any("rows" in s["result"] and s["result"]["rows"] for s in steps):
                bad = ["no data was queried"]
            else:
                bad = verify(text, question, steps)
            if not bad:
                return out(text, "verified")
            retries += 1
            if retries > 2:
                return out(MSG["unverified"][lang], "unverified")
            contents.append({"role": "user", "parts": [{"text":
                "VERIFIER: these claims are not found in any tool result: " + json.dumps(bad, ensure_ascii=False) +
                ". Compute them with run_sql and copy exact values, or remove them. If the data cannot answer, use the no-answer reply."}]})
        return out(MSG["unverified"][lang], "unverified")
    except RuntimeError as e:
        print("MODEL ERROR:", e, flush=True)
        return out(MSG["busy"][lang], "error")
