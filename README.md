# nutri-data-hub

Versioned open nutrition, additive, allergen, and neural TTS preview bundles published through GitHub Releases.

## Release Assets

Every release publishes a signed-by-checksum `manifest.json` alongside separate license-isolated archives:

- `core_foods.db.gz`: ~20,820 foods compiled from USDA FoodData Central (CC0 1.0), German BLS 4.0 (CC BY 4.0), and curated CIS staples with an Android-compatible SQLite FTS4 index (`unicode61` + Russian/English stem tokens).
- `medical_additives_registry.json.gz`: 560 dual-jurisdiction EU (EC 1333/2008) and EAEU (TR TS 029/2012) additive entries compiled from Open Food Facts taxonomy (ODbL 1.0) plus curated clinical notes.
- `allergens_registry.json.gz`: 15 statutory EU and EAEU allergens (including EAEU aspartame / phenylalanine PKU labeling).
- `voice_catalog.json` + `voice-previews-v1.zip` + individual `<voice_id>.ogg` clips (24 kbps mono Opus in `.ogg` containers for Android API 26+ `MediaPlayer`).

## How to Update App Data

1. Edit `registry/custom_additives_overrides.json`, `registry/allergens_15.json`, `foods/cis_staples_ru_en.json`, or `voices/voice_catalog_source.json`.
2. Push a new tag (for example `v1.0.1`) or trigger the **Publish Data Release** GitHub Actions workflow manually.
3. Clients poll `https://github.com/PatAmigo0/nutri-data-hub/releases/latest/download/manifest.json`, verify SHA-256 digests, and hot-swap updated bundles atomically.

## License Isolation

See [ATTRIBUTION.md](ATTRIBUTION.md) for dataset licenses. Scripts in this repository are MIT-licensed. `core_foods.db.gz` (CC0 + CC BY 4.0) and `medical_additives_registry.json.gz` (ODbL 1.0) are built and shipped as separate release files.
