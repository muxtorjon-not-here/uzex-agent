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
for text, want in cases:
    got = agent.verify(text, "savol", steps)
    print("OK " if bool(got) == bool(want) else "FAIL", text, got)
