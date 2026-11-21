#!/usr/bin/env python3
"""
Deterministic ETL compiler for PatAmigo0/nutri-data-hub.

Produces license-isolated release bundles in dist/:
  1. core_foods.db.gz      - USDA FDC (CC0) + German BLS 4.0 (CC BY 4.0) + CIS staples (~20,800+ foods)
  2. starter_foods.db      - Compact SQLite FTS5 starter DB (~500 everyday RU+EN foods) for APK bundling
  3. medical_additives_registry.json.gz - Complete dual-jurisdiction EU (EC 1333/2008) + EAEU (TR TS 029/2012)
                                          additive registry compiled from OFF taxonomy (ODbL 1.0) + curated overrides
  4. allergens_registry.json.gz         - 15 statutory EU+EAEU allergens (incl. EAEU aspartame/PKU)
  5. manifest.json         - Versioned catalog with SHA-256 checksums and release download URLs
"""
import gzip
import hashlib
import io
import json
import os
import re
import shutil
import sqlite3
import sys
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "_raw_cache"
DIST_DIR = ROOT / "dist"

RELEASE_TAG = os.environ.get("RELEASE_TAG", "v1.0.0")
REPO_SLUG = os.environ.get("REPO_SLUG", "PatAmigo0/nutri-data-hub")
BASE_RELEASE_URL = f"https://github.com/{REPO_SLUG}/releases/download/{RELEASE_TAG}"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def gzip_file(src: Path, dst: Path) -> None:
    with src.open("rb") as fin, dst.open("wb") as raw_out:
        with gzip.GzipFile(filename=src.name, mode="wb", fileobj=raw_out, compresslevel=9, mtime=0) as fout:
            shutil.copyfileobj(fin, fout)


def normalize_search_text(text: str) -> str:
    s = text.lower().replace("ё", "е")
    s = re.sub(r"[^a-zа-я0-9\s]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


# Lightweight Russian suffix stemmer (keeps base roots for FTS matching)
RU_SUFFIXES = (
    "иями", "ями", "ами", "ого", "его", "ому", "ему", "ыми", "ими", "оей", "еей",
    "ая", "яя", "ое", "ее", "ые", "ие", "ый", "ий", "ой", "ом", "ем", "ую", "юю",
    "ов", "ев", "ей", "ам", "ям", "ах", "ях", "ом", "ем", "ой", "ей", "ия", "ья",
    "ка", "ки", "ку", "ке", "а", "я", "о", "е", "ы", "и", "у", "ю", "ь",
)


def stem_tokens(text: str) -> str:
    norm = normalize_search_text(text)
    out = []
    seen = set()
    for tok in norm.split():
        if tok not in seen:
            out.append(tok)
            seen.add(tok)
        if len(tok) >= 5 and any("а" <= ch <= "я" for ch in tok):
            for suf in RU_SUFFIXES:
                if tok.endswith(suf) and len(tok) - len(suf) >= 3:
                    stem = tok[: -len(suf)]
                    if stem not in seen:
                        out.append(stem)
                        seen.add(stem)
                    break
        elif len(tok) >= 5 and tok.endswith("s") and not tok.endswith("ss"):
            stem = tok[:-1]
            if stem not in seen:
                out.append(stem)
                seen.add(stem)
    return " ".join(out)


def safe_float(val, default=0.0) -> float:
    if val is None or val == "" or val == "-":
        return default
    try:
        v = float(str(val).replace(",", "."))
        return v if v >= 0.0 else default
    except ValueError:
        return default


def extract_usda_foods() -> list[dict]:
    records = []
    sources = [
        ("usda_foundation.zip", "FoundationFoods", "usda_fdc_foundation", 3),
        ("usda_sr_legacy.zip", "SRLegacyFoods", "usda_sr_legacy", 2),
        ("usda_survey.zip", "SurveyFoods", "usda_fndds", 1),
    ]
    for zname, root_key, src_tag, priority in sources:
        zpath = RAW_DIR / zname
        if not zpath.exists():
            print(f"WARN: missing {zpath}, skipping")
            continue
        with zipfile.ZipFile(zpath) as zf:
            data = json.loads(zf.read(zf.namelist()[0]))
            foods = data.get(root_key, [])
            count = 0
            for item in foods:
                desc = (item.get("description") or "").strip()
                if not desc:
                    continue
                nutrients = {}
                for fn in item.get("foodNutrients", []):
                    nu = fn.get("nutrient") or {}
                    num = str(nu.get("number") or "")
                    amt = fn.get("amount")
                    if num and amt is not None:
                        nutrients[num] = safe_float(amt)
                kcal = nutrients.get("208")
                if kcal is None:
                    kcal = nutrients.get("957") or nutrients.get("958")
                if kcal is None and "268" in nutrients:
                    kcal = round(nutrients["268"] / 4.184, 1)
                protein = nutrients.get("203", 0.0)
                fat = nutrients.get("204", 0.0)
                carbs = nutrients.get("205", 0.0)
                if kcal is None:
                    if protein == 0.0 and fat == 0.0 and carbs == 0.0:
                        continue
                    kcal = round(4.0 * protein + 9.0 * fat + 4.0 * carbs, 1)
                fiber = nutrients.get("291", 0.0)
                sugars = nutrients.get("269", 0.0)
                sat_fat = nutrients.get("606", 0.0)
                sodium_mg = nutrients.get("307", 0.0)
                fdc_id = item.get("fdcId") or item.get("foodCode") or f"{count}"
                cat = ""
                if isinstance(item.get("foodCategory"), dict):
                    cat = item["foodCategory"].get("description", "")
                elif isinstance(item.get("wweiaFoodCategory"), dict):
                    cat = item["wweiaFoodCategory"].get("wweiaFoodCategoryDescription", "")
                records.append({
                    "id": f"{src_tag}_{fdc_id}",
                    "name_ru": "",
                    "name_en": desc,
                    "aliases": "",
                    "kcal": round(kcal, 1),
                    "protein": round(protein, 2),
                    "fat": round(fat, 2),
                    "carbs": round(carbs, 2),
                    "fiber": round(fiber, 2),
                    "sugars": round(sugars, 2),
                    "sat_fat": round(sat_fat, 2),
                    "sodium_mg": int(round(sodium_mg)),
                    "default_grams": 100.0,
                    "category": cat[:48],
                    "source": src_tag,
                    "priority": priority,
                })
                count += 1
            print(f"USDA {src_tag}: {count} foods")
    return records


def extract_bls_foods() -> list[dict]:
    zpath = RAW_DIR / "bls_4_0.zip"
    if not zpath.exists():
        print("WARN: missing bls_4_0.zip, skipping")
        return []
    records = []
    with zipfile.ZipFile(zpath) as outer:
        xlsx_bytes = outer.read("BLS_4_0_2025_DE/BLS_4_0_Daten_2025_DE.xlsx")
    with zipfile.ZipFile(io.BytesIO(xlsx_bytes)) as xz:
        ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
        shared = []
        if "xl/sharedStrings.xml" in xz.namelist():
            for _, elem in ET.iterparse(xz.open("xl/sharedStrings.xml"), events=("end",)):
                if elem.tag == ns + "si":
                    shared.append("".join(t.text or "" for t in elem.iter(ns + "t")))
                    elem.clear()
        want_cols = {"A", "B", "C", "G", "M", "P", "S", "V", "HL", "IM", "DT"}
        row_idx = 0
        for _, elem in ET.iterparse(xz.open("xl/worksheets/sheet1.xml"), events=("end",)):
            if elem.tag == ns + "row":
                row_idx += 1
                if row_idx == 1:
                    elem.clear()
                    continue
                vals = {}
                for c in elem:
                    ref = c.attrib.get("r", "")
                    col = "".join(ch for ch in ref if ch.isalpha())
                    if col not in want_cols:
                        continue
                    t = c.attrib.get("t", "")
                    v = c.find(ns + "v")
                    if v is not None and v.text is not None:
                        vals[col] = shared[int(v.text)] if t == "s" else v.text
                    else:
                        is_el = c.find(ns + "is")
                        if is_el is not None:
                            vals[col] = "".join(x.text or "" for x in is_el.iter(ns + "t"))
                elem.clear()
                code = (vals.get("A") or "").strip()
                name_de = (vals.get("B") or "").strip()
                name_en = (vals.get("C") or "").strip()
                if not code or not (name_en or name_de):
                    continue
                kcal = safe_float(vals.get("G"))
                protein = safe_float(vals.get("M"))
                fat = safe_float(vals.get("P"))
                carbs = safe_float(vals.get("S"))
                if kcal == 0.0 and protein == 0.0 and fat == 0.0 and carbs == 0.0:
                    continue
                records.append({
                    "id": f"bls4_{code}",
                    "name_ru": "",
                    "name_en": name_en or name_de,
                    "aliases": name_de if name_de and name_de != name_en else "",
                    "kcal": round(kcal, 1),
                    "protein": round(protein, 2),
                    "fat": round(fat, 2),
                    "carbs": round(carbs, 2),
                    "fiber": round(safe_float(vals.get("V")), 2),
                    "sugars": round(safe_float(vals.get("HL")), 2),
                    "sat_fat": round(safe_float(vals.get("IM")), 2),
                    "sodium_mg": int(round(safe_float(vals.get("DT")))),
                    "default_grams": 100.0,
                    "category": f"BLS-{code[:1]}",
                    "source": "bls_4_0",
                    "priority": 2,
                })
    print(f"German BLS 4.0: {len(records)} foods")
    return records


def load_cis_foods() -> list[dict]:
    items = json.loads((ROOT / "foods" / "cis_staples_ru_en.json").read_text(encoding="utf-8"))
    records = []
    for item in items:
        aliases = ", ".join(item.get("aliases", []))
        records.append({
            "id": item["id"],
            "name_ru": item["nameRu"],
            "name_en": item["nameEn"],
            "aliases": aliases,
            "kcal": round(float(item["kcal"]), 1),
            "protein": round(float(item["protein"]), 2),
            "fat": round(float(item["fat"]), 2),
            "carbs": round(float(item["carbs"]), 2),
            "fiber": round(float(item.get("fiber", 0.0)), 2),
            "sugars": round(float(item.get("sugars", 0.0)), 2),
            "sat_fat": round(float(item.get("satFat", 0.0)), 2),
            "sodium_mg": int(item.get("sodiumMg", 0)),
            "default_grams": float(item.get("defaultGrams", 100.0)),
            "category": item.get("category", "cis"),
            "source": "cis_curated",
            "priority": 10,
        })
    print(f"CIS curated staples: {len(records)} foods")
    return records


def write_food_sqlite(db_path: Path, records: list[dict]) -> None:
    if db_path.exists():
        db_path.unlink()
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.executescript("""
        PRAGMA journal_mode = DELETE;
        PRAGMA page_size = 4096;
        CREATE TABLE metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE foods (
            rowid INTEGER PRIMARY KEY AUTOINCREMENT,
            id TEXT UNIQUE NOT NULL,
            name_ru TEXT NOT NULL,
            name_en TEXT NOT NULL,
            aliases TEXT NOT NULL,
            search_stems TEXT NOT NULL,
            kcal REAL NOT NULL,
            protein REAL NOT NULL,
            fat REAL NOT NULL,
            carbs REAL NOT NULL,
            fiber REAL NOT NULL,
            sugars REAL NOT NULL,
            sat_fat REAL NOT NULL,
            sodium_mg INTEGER NOT NULL,
            default_grams REAL NOT NULL,
            category TEXT NOT NULL,
            source TEXT NOT NULL,
            priority INTEGER NOT NULL
        );
        CREATE VIRTUAL TABLE foods_fts USING fts4(
            content="foods",
            name_ru,
            name_en,
            aliases,
            search_stems,
            tokenize=unicode61
        );
    """)
    rows = []
    for r in records:
        combined = f"{r['name_ru']} {r['name_en']} {r['aliases']}"
        stems = stem_tokens(combined)
        rows.append((
            r["id"], r["name_ru"], r["name_en"], r["aliases"], stems,
            r["kcal"], r["protein"], r["fat"], r["carbs"],
            r["fiber"], r["sugars"], r["sat_fat"], r["sodium_mg"],
            r["default_grams"], r["category"], r["source"], r["priority"],
        ))
    cur.executemany(
        """INSERT OR REPLACE INTO foods (
            id, name_ru, name_en, aliases, search_stems,
            kcal, protein, fat, carbs, fiber, sugars, sat_fat, sodium_mg,
            default_grams, category, source, priority
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        rows,
    )
    cur.execute("INSERT INTO foods_fts(foods_fts) VALUES('rebuild')")
    cur.execute("INSERT INTO foods_fts(foods_fts) VALUES('optimize')")
    cur.executemany(
        "INSERT INTO metadata(key, value) VALUES (?, ?)",
        [
            ("schema_version", "1"),
            ("release_tag", RELEASE_TAG),
            ("food_count", str(len(records))),
            ("license", "USDA FDC CC0 1.0 + German BLS 4.0 CC BY 4.0 + CIS Curated CC0"),
            ("built_at", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")),
        ],
    )
    conn.commit()
    cur.execute("VACUUM")
    conn.close()


# Dual-jurisdiction regulatory status maps
EU_BANNED = {
    "E121", "E123", "E128", "E154", "E171", "E180", "E216", "E217", "E240",
    "E924", "E924A", "E924B", "E925", "E926", "E928",
}
EAEU_BANNED = {
    "E121", "E123", "E128", "E216", "E217", "E240", "E924A", "E924B", "E926",
}
SOUTHAMPTON_SIX = {"E102", "E104", "E110", "E122", "E124", "E129"}

CLASS_RU_MAP = {
    "colour": ("Краситель", "Colorant"),
    "preservative": ("Консервант", "Preservative"),
    "antioxidant": ("Антиоксидант", "Antioxidant"),
    "sweetener": ("Подсластитель", "Sweetener"),
    "emulsifier": ("Эмульгатор", "Emulsifier"),
    "stabiliser": ("Стабилизатор", "Stabilizer"),
    "thickener": ("Загуститель", "Thickener"),
    "gelling-agent": ("Желирующий агент", "Gelling agent"),
    "acidity-regulator": ("Регулятор кислотности", "Acidity regulator"),
    "flavour-enhancer": ("Усилитель вкуса", "Flavor enhancer"),
    "raising-agent": ("Разрыхлитель", "Raising agent"),
    "anti-caking-agent": ("Антислёживающий агент", "Anti-caking agent"),
    "glazing-agent": ("Глазирователь", "Glazing agent"),
    "humectant": ("Влагоудерживающий агент", "Humectant"),
    "sequestrant": ("Комплексообразователь", "Sequestrant"),
    "flour-treatment-agent": ("Улучшитель муки", "Flour treatment agent"),
    "modified-starch": ("Модифицированный крахмал", "Modified starch"),
    "propellant": ("Пропеллент / газ", "Propellant"),
    "packaging-gas": ("Упаковочный газ", "Packaging gas"),
    "foaming-agent": ("Пенообразователь", "Foaming agent"),
    "anti-foaming-agent": ("Пеногаситель", "Anti-foaming agent"),
    "bulking-agent": ("Наполнитель", "Bulking agent"),
    "carrier": ("Носитель", "Carrier"),
    "firming-agent": ("Уплотнитель", "Firming agent"),
    "melting-salt": ("Соль-плавитель", "Melting salt"),
}


def default_category_by_code(num: int) -> tuple[str, str]:
    if 100 <= num < 200:
        return ("Краситель", "Colorant")
    if 200 <= num < 300:
        return ("Консервант", "Preservative")
    if 300 <= num < 400:
        return ("Антиоксидант", "Antioxidant")
    if 400 <= num < 500:
        return ("Стабилизатор / эмульгатор", "Stabilizer / Emulsifier")
    if 500 <= num < 600:
        return ("Регулятор кислотности", "Acidity regulator")
    if 600 <= num < 700:
        return ("Усилитель вкуса", "Flavor enhancer")
    if 900 <= num < 1000:
        return ("Подсластитель / глазирователь", "Sweetener / Glazing agent")
    return ("Пищевая добавка", "Food additive")


def build_medical_registry() -> list[dict]:
    overrides_path = ROOT / "registry" / "custom_additives_overrides.json"
    overrides_list = json.loads(overrides_path.read_text(encoding="utf-8"))
    overrides_by_marker = {item["commonMarker"].upper(): item for item in overrides_list}

    by_marker: dict[str, dict] = {}
    off_path = RAW_DIR / "off_additives.txt"
    if off_path.exists():
        txt = off_path.read_text(encoding="utf-8", errors="replace")
        for block in txt.split("\n\n"):
            lines = [ln.strip() for ln in block.splitlines() if ln.strip() and not ln.strip().startswith("#")]
            if not lines:
                continue
            code = None
            en_names = []
            ru_names = []
            classes = []
            efsa_risk = ""
            anses = False
            for ln in lines:
                if ln.startswith("xx:"):
                    cand = ln[3:].strip().split(",")[0].strip().upper()
                    if re.match(r"^E\d{3,4}[A-Z]?$", cand):
                        code = cand
                elif ln.startswith("en:"):
                    parts = [p.strip() for p in ln[3:].split(",") if p.strip()]
                    if not code and parts and re.match(r"^E\d{3,4}[A-Z]?$", parts[0].upper()):
                        code = parts[0].upper()
                    en_names = [p for p in parts if p.upper() != code]
                elif ln.startswith("ru:"):
                    parts = [p.strip() for p in ln[3:].split(",") if p.strip()]
                    ru_names = [p for p in parts if not re.match(r"^[EЕ]\s*\d{3,4}[A-Za-z]?$", p)]
                elif ln.startswith("additives_classes:en:"):
                    classes = [c.strip().replace("en:", "") for c in ln.split(":", 2)[2].split(",") if c.strip()]
                elif ln.startswith("efsa_evaluation_overexposure_risk:en:"):
                    efsa_risk = ln.split(":", 2)[2].strip().replace("en:", "").lower()
                elif ln.startswith("anses_additives_of_interest:en:"):
                    anses = "yes" in ln.lower()
            if not code:
                continue
            num_match = re.match(r"^E(\d{3,4})", code)
            num = int(num_match.group(1)) if num_match else 0
            name_en = en_names[0] if en_names else code
            # Pick best Cyrillic Russian name when available
            cyr_ru = [r for r in ru_names if re.search(r"[А-Яа-яЁё]", r)]
            name_ru = cyr_ru[0] if cyr_ru else name_en

            cat_ru, cat_en = default_category_by_code(num)
            for cls in classes:
                if cls in CLASS_RU_MAP:
                    cat_ru, cat_en = CLASS_RU_MAP[cls]
                    break

            eu_status = "BANNED" if code in EU_BANNED else ("WARNING" if code in SOUTHAMPTON_SIX else "PERMITTED")
            eaeu_status = "BANNED" if code in EAEU_BANNED else ("WARNING" if code in SOUTHAMPTON_SIX else "PERMITTED")

            if code in EU_BANNED or code in EAEU_BANNED or code in SOUTHAMPTON_SIX or efsa_risk == "high":
                risk = "HIGH"
            elif efsa_risk == "moderate" or anses:
                risk = "MEDIUM"
            else:
                risk = "LOW"

            if code in EU_BANNED and code not in EAEU_BANNED:
                desc_ru = f"{cat_ru}. Запрещена как пищевая добавка в ЕС; в странах ЕАЭС статус отличается."
                desc_en = f"{cat_en}. Banned as a food additive in the EU; regulatory status differs in EAEU."
            elif code in EU_BANNED and code in EAEU_BANNED:
                desc_ru = f"{cat_ru}. Запрещена к применению в пищевых продуктах в ЕС и ЕАЭС."
                desc_en = f"{cat_en}. Banned in food products across both EU and EAEU."
            elif code in SOUTHAMPTON_SIX:
                desc_ru = f"{cat_ru}. Может оказывать отрицательное влияние на активность и внимание детей; требует предупреждения на этикетке."
                desc_en = f"{cat_en}. May have an adverse effect on activity and attention in children; requires label warning."
            elif risk == "HIGH":
                desc_ru = f"{cat_ru}. По оценке EFSA относится к добавкам с высоким риском превышения допустимого суточного потребления."
                desc_en = f"{cat_en}. Flagged by EFSA for elevated risk of exceeding acceptable daily intake."
            elif risk == "MEDIUM":
                desc_ru = f"{cat_ru}. Рекомендуется умеренное потребление; отмечена в мониторинге EFSA/ANSES."
                desc_en = f"{cat_en}. Moderate intake advised; monitored under EFSA/ANSES additive reviews."
            else:
                desc_ru = f"{cat_ru}. Разрешена к применению в установленных технологических дозах (EC 1333/2008, ТР ТС 029/2012)."
                desc_en = f"{cat_en}. Permitted within regulated limits under EC 1333/2008 and EAEU TR TS 029/2012."

            by_marker[code] = {
                "id": code.lower(),
                "commonMarker": code,
                "nameRu": name_ru,
                "nameEn": name_en,
                "impactDescription": desc_ru,
                "impactDescriptionEn": desc_en,
                "riskLevel": risk,
                "category": cat_ru,
                "categoryEn": cat_en,
                "euStatus": eu_status,
                "eaeuStatus": eaeu_status,
            }

    # Apply curated clinical overrides (including non-E allergens & bespoke clinical notes)
    for marker, ov in overrides_by_marker.items():
        merged = dict(by_marker.get(marker, {}))
        merged.update(ov)
        merged.setdefault("euStatus", "BANNED" if marker in EU_BANNED else ("WARNING" if marker in SOUTHAMPTON_SIX else "PERMITTED"))
        merged.setdefault("eaeuStatus", "BANNED" if marker in EAEU_BANNED else ("WARNING" if marker in SOUTHAMPTON_SIX else "PERMITTED"))
        by_marker[marker] = merged

    result = sorted(by_marker.values(), key=lambda x: (not x["commonMarker"].startswith("E"), x["commonMarker"]))
    print(f"Medical registry compiled: {len(result)} entries (EU+EAEU)")
    return result


def main() -> None:
    DIST_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Compile full core_foods.db + compact starter_foods.db
    cis = load_cis_foods()
    usda = extract_usda_foods()
    bls = extract_bls_foods()
    all_foods = cis + usda + bls
    print(f"Total core_foods records: {len(all_foods)}")

    core_db = DIST_DIR / "core_foods.db"
    write_food_sqlite(core_db, all_foods)
    core_db_gz = DIST_DIR / "core_foods.db.gz"
    gzip_file(core_db, core_db_gz)
    print(f"core_foods.db: {core_db.stat().st_size:,} bytes | gz: {core_db_gz.stat().st_size:,} bytes")

    # Compact starter DB for APK assets: all CIS staples + USDA Foundation Foods (~470 everyday items)
    starter_foods = cis + [f for f in usda if f["source"] == "usda_fdc_foundation"]
    starter_db = DIST_DIR / "starter_foods.db"
    write_food_sqlite(starter_db, starter_foods)
    print(f"starter_foods.db: {starter_db.stat().st_size:,} bytes ({len(starter_foods)} foods)")

    # 2. Compile dual-jurisdiction medical additive registry (ODbL 1.0 isolated)
    registry = build_medical_registry()
    reg_json = DIST_DIR / "medical_additives_registry.json"
    reg_json.write_text(json.dumps(registry, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    reg_gz = DIST_DIR / "medical_additives_registry.json.gz"
    gzip_file(reg_json, reg_gz)
    print(f"medical_additives_registry.json: {reg_json.stat().st_size:,} bytes | gz: {reg_gz.stat().st_size:,} bytes")

    # 3. Compile 15 statutory EU+EAEU allergens
    allergens = json.loads((ROOT / "registry" / "allergens_15.json").read_text(encoding="utf-8"))
    all_json = DIST_DIR / "allergens_registry.json"
    all_json.write_text(json.dumps(allergens, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    all_gz = DIST_DIR / "allergens_registry.json.gz"
    gzip_file(all_json, all_gz)

    # 4. Build unified release manifest.json
    def asset_entry(filename: str, extra: dict | None = None) -> dict:
        p = DIST_DIR / filename
        entry = {
            "fileName": filename,
            "url": f"{BASE_RELEASE_URL}/{filename}",
            "sizeBytes": p.stat().st_size,
            "sha256": sha256_file(p),
        }
        if extra:
            entry.update(extra)
        return entry

    manifest = {
        "schemaVersion": 1,
        "releaseTag": RELEASE_TAG,
        "publishedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "repository": REPO_SLUG,
        "datasets": {
            "medicalRegistry": asset_entry(
                "medical_additives_registry.json.gz",
                {"entryCount": len(registry), "license": "ODbL 1.0 (Open Food Facts) + EU/EAEU public regulations"},
            ),
            "allergens": asset_entry(
                "allergens_registry.json.gz",
                {"entryCount": len(allergens), "license": "CC0 / Public Regulatory Texts (EU 1169/2011 + EAEU TR TS 022/2011)"},
            ),
            "coreFoods": asset_entry(
                "core_foods.db.gz",
                {"entryCount": len(all_foods), "license": "USDA FDC CC0 1.0 + German BLS 4.0 CC BY 4.0 + CIS Curated CC0"},
            ),
        },
    }
    voice_catalog_path = DIST_DIR / "voice_catalog.json"
    voice_zip_path = DIST_DIR / "voice-previews-v1.zip"
    if voice_catalog_path.exists():
        vc = json.loads(voice_catalog_path.read_text(encoding="utf-8"))
        manifest["datasets"]["voiceCatalog"] = asset_entry(
            "voice_catalog.json",
            {"entryCount": len(vc.get("voices", []))},
        )
    if voice_zip_path.exists():
        manifest["datasets"]["voicePreviews"] = asset_entry("voice-previews-v1.zip")

    manifest_path = DIST_DIR / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {manifest_path}")


if __name__ == "__main__":
    main()
