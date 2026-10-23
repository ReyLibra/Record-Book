# Changelog

## 1.2.0

### New pages
- **Home** is now a dashboard:
  - a showcase of your top DPS per element that rotates on its own, with the character's art, build and talents
  - **Support Character Usage**: the teammates you use most in your logged teams
  - the current **banners**, rotating
  - your top **To-Do** goals
  - **Content Timers** for Spiral Abyss, Stygian Onslaught and Imaginarium Theater, with a server choice (America, Europe, Asia, TW/HK/MO)
- **DPS Log**, the former Home page:
  - your logged characters in one column per element, with a moving, starry backdrop in the theme's colour
  - click anywhere in a character's cell to open their character log
- **Tier List Maker**:
  - drag characters, weapons and artifacts into tiers
  - the page scrolls while you drag
  - a picture dropped off the chart goes back to the front of the grid
- **To Do List**, a planner for leveling characters and weapons:
  - every goal lists the materials it still needs, in the game's groups: Mora, EXP and specialty, then boss drops and gems beside mob drops and talent books
  - click any material to enter how many you have. Boss drops open with everything that boss drops, every gem element included (Childe: Hydro, Electro and Cryo).
  - what you have goes to your goals one at a time, in priority order, and leftovers are crafted up a tier (3 → 1) where that covers what a goal still needs (shown with ⚒)
  - drag-and-drop **Reorder** sets the priority
  - an **All Materials** summary and the domains open today
  - **Notes**: a title, text, and pictures of characters, weapons, artifacts or materials
- **End Game**:
  - **Spiral Abyss** floors 9–12
  - **Stygian Onslaught** at Hard, Menacing, Fearless and Dire, with each boss's TLDR from stygian.moe
  - **Imaginarium Theater** seasons, Lunar stages first, with each season's elements
  - LIVE / TESTING tags and corrected schedules
- **Loading screen** while the app starts: everything is loaded before the window appears, so no page pops in or stutters the first time it's opened.

### Navigation
- DPS Log sits above the Buff/Shred List, and the To Do List follows the Tier List Maker.
- A collapsible **LINKS** section above Settings (collapsed by default).

### Themes and look
- Four character themes: **Furina**, **Mavuika**, **Mona** and **Keqing**, listed after the element themes.
- "Default (blue)" is now **Default**.
- Every container has the same rounded top-right and bottom-left corners, and the colours are consistent across pages.
- Small tags and buttons follow the chosen theme everywhere (some stayed light blue).
- Light mode: To Do cards are easier to read.
- Text can be selected and copied anywhere in the app.

### Pages that changed
- **Buff/Shred List**: corrected totals, and totals no longer cut off in fullscreen.
- **Element filters** follow the game's order: Pyro, Hydro, Dendro, Electro, Anemo, Cryo, Geo.
- **Weapons**: each weapon in the grid shows its type's symbol.
- **Character log**:
  - opens much faster (about 70 ms, was about 460 ms)
  - its runs' teammates are evenly spaced and line up from run to run
  - no more sideways scrolling in a small window

### Fixes
- Fixed a crash that could happen at random while a page was loading pictures.
- The Home banner keeps its size after the window is maximized on another page.
- Popups size themselves to what's in them (long boss names and material names were cut off).

### Under the hood
- Unused code removed and the code tidied up.
