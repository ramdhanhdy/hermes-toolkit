# Portable AI Food Scale Blueprint

Captured from a user idea: build a portable digital food scale connected to AI calorie/macro logging.

## Core Principle

The scale should only measure grams. Food identification and nutrition lookup should happen in the phone/PC/AI layer. Avoid designing a scale that tries to infer food identity by itself.

Canonical UX:

```text
weigh food → say/type/scan food name → AI calculates macros → auto-log → phone/PC dashboard
```

## Recommended Architecture

```text
ESP32 smart scale
  ↓ BLE/WiFi
Phone PWA / Telegram bot / local web app
  ↓
AI food parser
  ↓
Nutrition lookup: personal DB → barcode/Open Food Facts → USDA → FatSecret/local Indonesian foods
  ↓
Hermes fitness tracker daily_nutrition.json + SQLite pipeline
```

## Hardware Estimate, Indonesia/Tokopedia May 2026

- Barebones prototype: ~Rp70k–155k
- Portable usable prototype: ~Rp215k–395k
- Polished v1: ~Rp350k–650k
- Add 15–30% contingency for shipping, bad modules, spare parts, and enclosure revisions.

Typical parts:
- ESP32 dev board: Rp21k–60k
- 5kg load cell: Rp23.5k–49k
- HX711 amplifier: Rp9k–15k
- 0.96 inch OLED I2C: Rp26.5k–35k
- TP4056 USB-C charging/protection: Rp4.5k–15k
- 18650 battery: ~Rp70k
- 18650 holder: Rp5k–15.5k
- Buttons/wires/misc: ~Rp15k–30k
- 3D printed enclosure: ~Rp25k–75k at ~Rp500–750/g for ~50–100g print

## Build Phases

1. Manual UI MVP: phone/web/Telegram form `[grams] [food] [meal] [log]` using current kitchen scale.
2. Dumb ESP32 scale: ESP32 + HX711 + load cell with tare, stable weight detection, serial/BLE/WiFi output.
3. Connected logger: phone/PWA receives current grams, asks food name, logs macros.
4. Smart assist: favorites, repeat previous food, barcode scan, voice input, photo suggestion, confidence labels.
5. Portable polish: OLED, battery, USB-C charging, enclosure, rubber feet, calibration mode, sleep.

## Integration Notes

When confirmed, append the meal/item to `data/daily_nutrition.json`, then run:

```bash
cd ~/.hermes/skills/fitness-tracker
python3 scripts/run_pipeline.py
```

The item payload should preserve source and confidence because recipes/oil/sauce create large uncertainty.

Example item:

```json
{
  "food_raw": "ayam cabe ijo",
  "weight_g": 65,
  "kcal": 160,
  "protein_g": 18.5,
  "fat_g": 7.0,
  "carbs_g": 2.0,
  "source": "FatSecret/personal DB",
  "confidence": "medium",
  "notes": "Oil level unknown"
}
```

## Accuracy Caveats

Weight can be accurate; calories/macros depend on food identity and recipe. Biggest uncertainty: oil, coconut milk, sauces, fried vs steamed/grilled, bone-in vs edible portion, restaurant portions, mixed dishes.

Use confidence labels:
- High: cooked white rice, boiled egg, packaged label food.
- Medium: home nasi goreng, ayam cabe ijo.
- Low: buffet/restaurant mixed dishes.
