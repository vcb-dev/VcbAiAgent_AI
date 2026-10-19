"""Job-level editor settings (CapCut-style option panels): defaults, allowed values, validation."""

DEFAULTS = {
    "voice": "huyk",            # huyk = ElevenLabs clone (if configured) | demo = offline system voice
    "music_track": "default",   # id from music_library.list_tracks()
    "music_volume": 0.38,       # 0.0 - 1.0; duck dưới giọng nhưng vẫn nghe được
    "sfx": True,
    "subtitles": True,
    "subtitle_style": "box",    # box | outline
    "hook_text": True,
    "logo": False,
    "transition": "cut",        # cut | dip (dip to black between parts)
    "color": "none",            # none | warm | cool
}
CHOICES = {"voice": {"huyk", "demo"}, "subtitle_style": {"box", "outline"}, "transition": {"cut", "dip"},
           "color": {"none", "warm", "cool"}}
BOOLS = {"sfx", "subtitles", "hook_text", "logo"}
VOICE_KEYS = {"voice"}          # changing these requires a new VO take
# Nhạc nền chỉnh trên trình phát ngay (CapCut); không encode lại video.
LIVE_KEYS = {"music_track", "music_volume"}


def validate(partial: dict, music_ids: set) -> dict:
    """Return the sanitised subset of `partial`; raise ValueError on unknown keys or bad values."""
    out = {}
    for key, value in partial.items():
        if key not in DEFAULTS:
            raise ValueError(f"unknown setting '{key}'")
        if key in BOOLS:
            if not isinstance(value, bool):
                raise ValueError(f"'{key}' must be true/false")
        elif key == "music_volume":
            if not isinstance(value, (int, float)) or not 0 <= value <= 1:
                raise ValueError("music_volume must be between 0 and 1")
            value = round(float(value), 2)
        elif key == "music_track":
            if value not in music_ids:
                raise ValueError("unknown music track")
        elif value not in CHOICES[key]:
            raise ValueError(f"'{key}' must be one of {sorted(CHOICES[key])}")
        out[key] = value
    return out
