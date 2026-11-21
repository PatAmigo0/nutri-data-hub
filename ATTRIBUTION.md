# Dataset Attribution & License Boundaries

Each release bundle maintains strict license isolation:

1. **Food Nutrition Database (`core_foods.db.gz`, `starter_foods.db`)**
   - **USDA FoodData Central** (Foundation Foods 2025-12-18, SR Legacy 2018-04, FNDDS 2024-10-31): U.S. Department of Agriculture, Agricultural Research Service. Public Domain (CC0 1.0).
   - **German Nutrient Database BLS 4.0** (Max Rubner-Institut, Bundeslebensmittelschlüssel 4.0, 2025): Licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
   - **Curated CIS/Russian Staples** (`foods/cis_staples_ru_en.json`): Original compilation released under CC0 1.0.

2. **Medical Additive Registry (`medical_additives_registry.json.gz`)**
   - **Open Food Facts Additives Taxonomy** (`openfoodfacts/openfoodfacts-server`): Licensed under [Open Database License (ODbL) v1.0](https://opendatacommons.org/licenses/odbl/1-0/).
   - Regulatory status annotations reference public legal texts: Regulation (EC) No 1333/2008, Regulation (EU) No 1169/2011, EAEU TR TS 029/2012, and EAEU TR TS 022/2011.
   - Kept physically separate from `core_foods.db.gz`.

3. **Allergens Catalog (`allergens_registry.json.gz`)**
   - Derived from public EU 1169/2011 and EAEU TR TS 022/2011 statutory lists (CC0 1.0).

4. **Neural TTS Catalog & Voice Previews (`voice_catalog.json`, `*.ogg`)**
   - Piper VITS voice checkpoints and audio samples from `rhasspy/piper-voices` and `k2-fsa/sherpa-onnx` (`tts-models`). Each catalog entry lists its individual voice license (Public Domain, CC0, CC BY 4.0, or Non-Commercial notice).
   - Supertonic 3 int8 weights and audio samples from `Supertone/supertonic-3` (MIT code / OpenRAIL-M weights, subject to Attachment A use restrictions).
