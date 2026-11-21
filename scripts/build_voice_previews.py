#!/usr/bin/env python3
"""
Downloads official voice audio samples and transcodes them to Android API 26+
compatible 24 kbps mono Opus inside Ogg (.ogg) clips, trimmed to <= 4.5s and
loudness-normalized so every preview plays at uniform volume.
"""
import hashlib
import json
import os
import subprocess
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CATALOG_SRC = ROOT / "voices" / "voice_catalog_source.json"
DIST_PREVIEWS = ROOT / "dist" / "voice_previews"
DIST_DIR = ROOT / "dist"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def transcode_to_ogg(src: Path, dst: Path) -> None:
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(src),
        "-t", "4.5",
        "-af", "silenceremove=start_periods=1:start_silence=0.15:start_threshold=-45dB,loudnorm=I=-16:TP=-1.5:LRA=11",
        "-ac", "1",
        "-ar", "24000",
        "-c:a", "libopus",
        "-b:a", "24k",
        "-vbr", "constrained",
        "-compression_level", "10",
        "-application", "voip",
        "-frame_duration", "60",
        "-f", "ogg",
        str(dst),
    ]
    subprocess.run(cmd, check=True)


def main() -> None:
    DIST_PREVIEWS.mkdir(parents=True, exist_ok=True)
    catalog = json.loads(CATALOG_SRC.read_text(encoding="utf-8"))
    manifest_voices = []

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        for v in catalog["voices"]:
            vid = v["id"]
            src_url = v.get("sampleSourceUrl", "")
            out_ogg = DIST_PREVIEWS / f"{vid}.ogg"
            if src_url and not out_ogg.exists():
                ext = ".wav" if src_url.endswith(".wav") else ".mp3"
                raw_file = tmp_dir / f"{vid}{ext}"
                print(f"Fetching sample for {vid} ...")
                req = urllib.request.Request(src_url, headers={"User-Agent": "nutri-data-hub-builder/1.0"})
                with urllib.request.urlopen(req, timeout=30) as resp, raw_file.open("wb") as out:
                    out.write(resp.read())
                transcode_to_ogg(raw_file, out_ogg)
            entry = {k: val for k, val in v.items() if k != "sampleSourceUrl"}
            if out_ogg.exists():
                entry["previewFileName"] = out_ogg.name
                entry["previewSizeBytes"] = out_ogg.stat().st_size
                entry["previewSha256"] = sha256_file(out_ogg)
                print(f"  -> {out_ogg.name}: {out_ogg.stat().st_size} bytes")
            manifest_voices.append(entry)

    # Package all .ogg previews into one zip for bulk release download
    zip_path = DIST_DIR / "voice-previews-v1.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_STORED) as zf:
        for ogg in sorted(DIST_PREVIEWS.glob("*.ogg")):
            zf.write(ogg, arcname=ogg.name)
    print(f"Wrote {zip_path} ({zip_path.stat().st_size} bytes)")

    out_catalog = {
        "schemaVersion": catalog["schemaVersion"],
        "voices": manifest_voices,
    }
    catalog_out = DIST_DIR / "voice_catalog.json"
    catalog_out.write_text(json.dumps(out_catalog, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {catalog_out}")


if __name__ == "__main__":
    main()
