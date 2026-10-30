---
title: Gear-deck perception
type: component
updated: 2026-10-30
sources: [seed, rdf03-t9]
---
# Gear-deck perception

`perception/gear.py` is the perception used by the current production loop: it reads the gear-deck
field with trained models, finds deck UI buttons by template match, and OCRs field-effect banners.

## How it works
- Frames are normalised to `NORM_H` 1280 px tall so live grabs match the 2026-10-07 training recording.
- Types: `GearTeal/Grey/Red/Blue` (gear look changes after 초월), Bubble, Adjust, Growth, Doom, Joker,
  plus empty/junk/Crystal/Bomb/Decay. Type and pip come from models in `data/` (`gear_type_cnn.pt`,
  pip ensemble `gear_pip_pat_e1..e3.pt`, `gear_doom_centre_e*.pt`, joblib fallbacks); torch is imported lazily.
- `reload_if_changed()` hot-swaps model files between games (training may run alongside).
- Deck is detected from the deck bar each game (`detect_deck`) and selects a preset in `config/deck.toml`.
- `UI` holds tap targets (transcend, hunt, power panel, summon 0.520/0.850, support 0.220/0.870, hpsp).
- `banner_text`/`tactic_sp1000_card` use Tesseract (`C:\Program Files\Tesseract-OCR`, repo `tessdata/`).
  Room code and HP use the template digit reader `perception/digits.py` (exact-or-None) because
  Tesseract misread them.
- `dice_info_panel` / `dice_info_scores` detect the dice info panel (dark-pixel share in three bands); how the support bot uses them is in [support-players](support-players.md).
- `perception/collect.py` saves live crops + the bot's own labels to `data/crops_gear/` (review before training).

## Evidence
- `src/rdom/perception/gear.py` — docstring, `NORM_H`, `TYPES`, `TYPE_CLASSES`, `UI`, `reload_if_changed`, `PIP_ENSEMBLE`, `banner_text`, `dice_info_panel`, `dice_info_scores`, `_INFO_BANDS`
- `src/rdom/perception/digits.py` — docstring (Tesseract misreads 14324→14352, 150→15)
- `src/rdom/perception/collect.py` — live crop collection
- `config/deck.toml` — doom/decay presets
- `tools/train_gear_type_cnn.py`, `tools/train_gear_pip_cnn.py` — model training scripts
