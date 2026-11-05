"""Script-independent company name keys: Uzbek Cyrillic and Latin spellings map to the same key."""
import re

_MAP = {"а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo", "ж": "j", "з": "z", "и": "i",
        "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t",
        "у": "u", "ф": "f", "х": "x", "ц": "s", "ч": "ch", "ш": "sh", "щ": "sh", "ъ": "", "ы": "i", "ь": "",
        "э": "e", "ю": "yu", "я": "ya", "ў": "o", "қ": "q", "ғ": "g", "ҳ": "h"}


def translit(s: str) -> str:
    return "".join(_MAP.get(ch, ch) for ch in s.lower())


def name_key(s: str) -> str:
    t = translit(s)
    t = re.sub(r"[‘’'`ʻʼ\"«»“”]", "", t)
    t = re.sub(r"masuliyati cheklangan jamiyati|\bmchj\b|\baj\b|\booo\b", " ", t)
    return re.sub(r"[^a-z0-9]+", " ", t).strip()
