"""Vietnamese text helpers: sentence splitting, keyword tokens without diacritics, speech-time estimate."""
import re
import unicodedata

from footage_filename_parser import slugify_vi

STOPWORDS = set("""
la va cua nay thi ma mot nhung cac cho co khong duoc voi da roi cung nhu de den tu trong ra vao
o tai ve len xuong neu khi vi nen hay hoac rat qua lam the nao gi ai day do kia nhieu it moi chi
ban minh toi anh em chi chu ong ba nguoi ho chung thuc su that dang se van con lai luc nao
tren duoi boi rat sau truoc giua hon nhat cai chiec mau
kim vang bac nhan da
""".split())   # last line: jewellery-generic words that appear everywhere and carry no topic signal

SENTENCE_RE = re.compile(r"(?<=[.!?…])\s+|\n+")


def split_sentences(text: str) -> list:
    """Split a script into sentences; keep quotes attached; drop empty pieces."""
    parts = [p.strip() for p in SENTENCE_RE.split(text.strip()) if p and p.strip()]
    merged = []
    for p in parts:
        # merge tiny fragments (e.g. 'HuyK:' or a 2-word exclamation) into the previous sentence
        if merged and len(p.split()) <= 2:
            merged[-1] = f"{merged[-1]} {p}"
        else:
            merged.append(p)
    return merged


def keyword_tokens(text: str) -> set:
    """Keyword set for fuzzy matching, KEEPING Vietnamese diacritics ('bạc' silver != 'Bắc' north).

    Stopwords are checked on the ASCII form; 2-word phrases are added for extra precision.
    """
    raw = re.findall(r"\w+", unicodedata.normalize("NFC", text.lower()))
    words = [w for w in raw if not w.isdigit() and slugify_vi(w) not in STOPWORDS]
    bigrams = {f"{a}-{b}" for a, b in zip(words, words[1:])}
    return set(words) | bigrams


def estimate_speech_seconds(text: str, syllables_per_sec: float = 4.6) -> float:
    """Vietnamese is ~1 syllable per space-separated word."""
    return round(max(len(text.split()), 1) / syllables_per_sec, 2)
