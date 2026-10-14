"""VO direction for ElevenLabs eleven_v4: pronunciation fixes + emotion audio tags per part.

Audio tags ([curious], [warm], [sighs]...) were verified on eleven_v4 with the HuyK clone: they shape delivery
and are NOT spoken (Scribe transcripts show them only as non-speech events). Tags/pronunciation apply to the
TTS text only — subtitles keep the original script wording.
"""
import re

from footage_filename_parser import slugify_vi

# How HuyK actually says things (from the voice sample transcript: "HuyK" -> "Huy Ka")
PRONUNCIATION = [
    (re.compile(r"\bHuyK\b", re.I), "Huy Ka"),
    (re.compile(r"\b18K\b", re.I), "mười tám ca"),
    (re.compile(r"\b24K\b", re.I), "hai mươi tư ca"),
    (re.compile(r"\bS925\b", re.I), "ét chín hai lăm"),
]
SAD = ("ban-di", "nuoc-mat", "lang-nguoi", "khoc", "tra-lai", "xa-cach", "cang-thang", "lang-le", "vat-va", "quay-di")
GRATEFUL = ("cam-on", "quy-lam", "tri-an", "dong-vien", "binh-luan", "ung-ho", "biet-on", "xung-dang")
HARD = ("kho", "loi", "lam-lai", "thao-ra", "bo-nghe", "phuc-tap", "chinh-xac", "sai-mot-ly", "moi-mat", "thuc-toi")
HEARTFELT = ("vo-nghia", "moi-mat", "dem-thuc", "thuc-toi", "cuoi-cung", "tam-long", "khoanh-khac")
REFLECT = ("thuc-ra", "nguoi-lam-nghe", "com-ao", "cuoc-song", "nhieu-khi", "phia-sau")
# Tags offered in the UI for a manual override ("" = natural delivery)
EMOTION_TAGS = ["", "[intrigued]", "[curious]", "[excited]", "[serious]", "[thoughtful]", "[softly, emotional]",
                "[heartfelt]", "[warm, grateful]", "[admiring]", "[playful]", "[warm, confident]"]
WONDER = ("lap-lanh", "dang-cap", "dac-biet", "an-tuong", "kinh-dien", "tuyet-dep")


def _has(slug: str, markers) -> bool:
    padded = f"-{slug}-"
    return any(f"-{m}-" in padded for m in markers)


def pronounce(text: str) -> str:
    for pattern, spoken in PRONUNCIATION:
        text = pattern.sub(spoken, text)
    return text


def emotion_tag(part: dict, index: int, total: int) -> str:
    """Pick one delivery tag from the part's role + wording (empty string = natural delivery)."""
    text = part.get("vo_text", "")
    slug = slugify_vi(text)
    if part["role"] == "outro" or (index == total - 1 and _has(slug, ("vien-chi-bao",))):
        return "[warm, confident]"
    if index == 0:
        return "[curious]" if "?" in text else "[intrigued]"
    if _has(slug, HEARTFELT):
        return "[heartfelt]"
    if _has(slug, SAD):
        return "[softly, emotional]"
    if _has(slug, GRATEFUL):
        return "[warm, grateful]"
    if "!" in text:
        return "[excited]"
    if _has(slug, HARD):
        return "[serious]"
    if _has(slug, WONDER):
        return "[admiring]"
    if "?" in text:
        return "[curious]"
    if _has(slug, REFLECT):
        return "[thoughtful]"
    return ""


def direct_parts(parts: list) -> list:
    """Return [(part_index, tts_text)] for parts that have VO, with pronunciation + emotion tags applied."""
    voiced = [(i, p) for i, p in enumerate(parts) if (p.get("vo_text") or "").strip()]
    out = []
    for n, (i, p) in enumerate(voiced):
        override = p.get("emotion_override")
        tag = override if override in EMOTION_TAGS else emotion_tag(p, n, len(voiced))
        out.append((i, f"{tag} {pronounce(p['vo_text'].strip())}".strip()))
    return out
