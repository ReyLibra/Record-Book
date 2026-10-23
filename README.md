# Record Book

Claude Code Project

A desktop companion for **Genshin Impact**: a character, weapon and artifact database in Prydwen's style, a log of your teams' DPS, and planners for leveling, tier lists and endgame content.

Built with Python and PySide6 (Qt) on game data from [Project Amber](https://gi.yatta.moe). Windows, current version **1.2.0** ([changelog](CHANGELOG.md)).

## Features

### Database
- **Characters**, **Weapons** and **Artifacts**: browse, filter and search everything in the game, with full kits, stats by level, refinements and set bonuses.
- Search understands shorthand (`HT`, `Kazu`, `PJWS`, `Childe`).
- Optional unreleased content, and a choice of Traveler.

### DPS log
- **DPS Log**: your logged characters in one column per element, ranked by their best DPS. Click one to open their log.
- **Character log**: every run with its date, mode, team (weapons, artifact sets, talents, constellations), total damage and the DPS it works out to. Each mode's highest run is marked. Three modes are tracked:
  - **Spiral Abyss**: 90 seconds, with energy at the start
  - **Stygian Fearless**: 120 seconds, no energy at the start
  - **Stygian Dire**: 120 seconds, no energy at the start

### Tools
- **Home**: your top DPS per element, the supports you use most, the current banners, your top To-Do goals and the endgame timers.
- **Buff/Shred List**: every buff and resistance shred in the game, with totals, filters and the conditions behind each one.
- **Tier List Maker**: drag characters, weapons and artifacts into tiers.
- **To Do List**: plan character and weapon levels and talents.
  - Every goal lists the materials it still needs.
  - Enter what you own; it goes to your goals in priority order, and leftovers are crafted up a tier.
  - Shows the domains open today and lets you keep notes with pictures.
- **End Game**: Spiral Abyss floors 9–12, Stygian Onslaught bosses with a TLDR for each, and Imaginarium Theater seasons, with live timers for your server.

### Look
- Dark and light modes.
- Element themes, and character themes (Furina, Mavuika, Mona, Keqing).
- A loading screen that prepares every page, so nothing stutters the first time it opens.

## Getting started

### The app
Download **Record Book.exe** from the [Releases](../../releases) page and run it. It keeps its data next to itself (see [Your data](#your-data)), so put it in a folder of its own.

### From source
Needs **Python 3.13** or newer.

```bash
pip install -r requirements.txt
```

```bash
python record_book.py
```

### Building the exe

```bash
python build.py
```

This writes `Record Book.exe` (a single file) next to the source, with the app's icon and version. Build files go in `build/`, which is safe to delete.

## Your data

Everything stays on your computer, in the app's folder:

| File | What it holds |
|---|---|
| `record_book.db` | your characters, builds, runs, To Do goals, notes, tier lists and settings |
| `.cache/` | downloaded game data and pictures (downloaded again if deleted) |
| `crash.log` | a trace of what happened before a crash, for bug reports |

Back up `record_book.db` to keep your logs. It's ignored by git.

## Data sources

- [Project Amber (gi.yatta.moe)](https://gi.yatta.moe): characters, weapons, artifacts, materials, domains and bosses.
- [Lunaris](https://lunaris.moe): Spiral Abyss, Stygian Onslaught and Imaginarium Theater line-ups.
- [stygian.moe](https://stygian.moe): the Stygian Onslaught boss TLDRs.
- [Genshin Impact Wiki](https://genshin-impact.fandom.com): banner art.

Record Book is a fan project and isn't affiliated with HoYoverse. Genshin Impact and its art belong to HoYoverse.

## Project layout

| File | What it is |
|---|---|
| `record_book.py` | the main window, navigation and startup |
| `home_page.py`, `dps_log_page.py`, `log_page.py`, `character_page.py`, `database_pages.py` | Home, DPS Log, character log, Characters, Weapons and Artifacts |
| `buffs_page.py`, `buff_scan.py`, `buff_totals.py`, `buffs_data.py` | the Buff/Shred List and how buffs are read from kit text |
| `tier_list_page.py`, `todo_page.py`, `endgame_page.py` | Tier List Maker, To Do List, End Game |
| `gamedata.py`, `materials.py`, `endgame.py`, `unreleased.py`, `weapon_sources.py` | fetching and reading game data |
| `store.py` | the database |
| `widgets.py`, `dialogs.py`, `theme.py`, `loading_screen.py`, `settings_dialog.py` | shared widgets, popups, themes, the loading screen and Settings |
| `build.py` | builds the exe |
