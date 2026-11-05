"""Checks the tools and the verifier without any LLM call."""
import agent

print(agent.run_sql("select count(*) n, sum(amount_uzs) s from deals where not is_cancelled"))
print(agent.run_sql("drop table deals"))
print(agent.run_sql("select * from read_csv('x.csv')"))
print(agent.run_sql("select 1; select 2"))
print(agent.run_sql("select 'drop' x"))
for n in ["ШУЗЕЛ САВДО", "Shuzel Savdo", "fomet biznes", "Kekuxo broker", "Google LLC"]:
    print(n, [(m["name"], m.get("inn"), m["score"]) for m in agent.find_entity(n)["matches"]][:3])

steps = [{"result": {"columns": ["n", "s", "d"], "rows": [[33719, 2345678901.25, "12.03.2024"]]}},
         {"result": {"matches": [{"name": "\"Zapo Servis\" MChJ", "inn": "123456789"}]}}]
cases = [("Bekor qilingan: 33 719 ta", []), ("Jami 2 345 678 901,25 so'm", []), ("Jami 2,35 mlrd so'm", []),
         ("Jami 2,9 mlrd so'm", ["2,9"]), ("99 999 ta bitim", ["99 999"]), ("Sana 12.03.2024", []), ("Sana 13.03.2024", ["13.03.2024"]),
         ("2025-yilda 33 719 ta", []), ("\"Zapo Servis\" MChJ sotdi", []), ("\"Fake Trade\" MChJ sotdi", ["\"Fake Trade\" MChJ"])]
cases += [("\"Fake Invest\" OK sotdi", ["x"]), ("FAKE BIZNES QK sotdi", ["x"]), ("«Fake Savdo» МЧЖ", ["x"])]
for text, want in cases:
    got = agent.verify(text, "savol", steps)
    print("OK " if bool(got) == bool(want) else "FAIL", text, got)

print("literal guard:")
for q, want_err in [("select count(*) from deals where commodity = 'sement'", True), ("select count(*) from deals where commodity = 'Цемент'", False),
                    ("select count(*) from deals where commodity in ('Цемент','oltin')", True), ("select count(*) from deals where commodity ilike '%цемент%'", False),
                    ("select count(*) from deals where region = 'Farg''ona viloyati'", True), ("select count(*) from deals where region = 'Farg‘ona viloyati'", False)]:
    print("OK " if ("error" in agent.run_sql(q)) == want_err else "FAIL", q)

print("language:")
for text, lang, want in [("2022 yilda jami 1 237 ta eksport bitimi amalga oshirilgan", "ru", True), ("В 2022 году было 1 237 экспортных сделок", "ru", False),
                         ("\"Zoket Invest\" OK — крупнейший покупатель за этот период", "ru", False), ("2024-yilda eng ko'p bitim Toshkent shahrida tuzilgan", "uz", False),
                         ("В 2024 году больше всего сделок заключено в Ташкенте", "uz", True)]:
    print("OK " if agent.wrong_language(text, lang) == want else "FAIL", lang, text)
