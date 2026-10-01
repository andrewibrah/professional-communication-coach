import json
import math
import subprocess
from pathlib import Path
from fastapi import HTTPException

MAX_BYTES = 12582912
# One codec frame plus recorder stop scheduling; never client-claimed duration.
DURATION_TOLERANCE = 0.15
FORMATS = {
    ".wav": ({"audio/wav", "audio/x-wav"}, {"wav"}),
    ".webm": ({"audio/webm"}, {"matroska", "webm"}),
    ".ogg": ({"audio/ogg"}, {"ogg"}),
    ".mp3": ({"audio/mpeg", "audio/mp3"}, {"mp3"}),
    ".mp4": ({"audio/mp4"}, {"mov", "mp4", "m4a", "3gp", "3g2", "mj2"}),
    ".m4a": ({"audio/mp4", "audio/x-m4a"}, {"mov", "mp4", "m4a", "3gp", "3g2", "mj2"}),
}


def extension(filename, mime):
    suffix = Path(filename or "").suffix.lower()
    if suffix not in FORMATS or mime.split(";")[0].lower() not in FORMATS[suffix][0]:
        raise HTTPException(415, "Unsupported audio type")
    return suffix


def probe(path, suffix, declared):
    if not math.isfinite(declared) or not 30 <= declared <= 180:
        raise HTTPException(422, "Recording must be 30 to 180 seconds")
    try:
        if not 0 < path.stat().st_size <= MAX_BYTES:
            raise ValueError("size")
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-protocol_whitelist",
                "file,pipe",
                "-show_entries",
                "format=duration,format_name:stream=codec_type,duration",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            timeout=15,
            check=True,
        )
        data = json.loads(result.stdout)
        fmt = data["format"]
        streams = data["streams"]
        valid = set(fmt["format_name"].split(",")) & FORMATS[suffix][1]
        if (
            not valid
            or not streams
            or any(s.get("codec_type") != "audio" for s in streams)
        ):
            raise ValueError("format")
        # MediaRecorder's streaming WebM commonly has no duration metadata.
        # Decode even when metadata exists: headers are not trusted authority.
        # Mono signed 16-bit PCM at 16 kHz bounds stdout to 5,792,000 bytes;
        # the 181-second cap still detects recordings beyond the allowed max.
        decoded = subprocess.run(
            [
                "ffmpeg",
                "-nostdin",
                "-v",
                "fatal",
                "-xerror",
                "-protocol_whitelist",
                "file,pipe",
                "-threads",
                "1",
                "-i",
                str(path),
                "-map",
                "0:a:0",
                "-vn",
                "-sn",
                "-dn",
                "-t",
                "181",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-f",
                "s16le",
                "pipe:1",
            ],
            capture_output=True,
            timeout=20,
            check=True,
        )
        duration = len(decoded.stdout) / (16000 * 2)
        if (
            not math.isfinite(duration)
            or not 30 - DURATION_TOLERANCE <= duration <= 180 + DURATION_TOLERANCE
            or abs(duration - declared) > 3
        ):
            raise ValueError("duration")
        return duration
    except FileNotFoundError:
        raise HTTPException(503, "Media validation unavailable") from None
    except Exception:
        raise HTTPException(422, "Invalid audio media or duration") from None
