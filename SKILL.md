---
name: "game-cover-downloader"
description: "Downloads game cover thumbnails with tiny-scraper. Invoke when user asks to find or download covers for games, ROM files, or ROM folders."
---

# Game Cover Downloader

Use this skill when the user asks to download, fetch, find, match, or preview game media images for:

- a game name
- a single ROM file
- a ROM folder
- a console/platform game library

The backend is the tiny-scraper CLI in this repository. Always run commands from the project root.

## Project Structure

```
game-cover-downloader/
  SKILL.md                       # This file
  fetch_data.py                  # Data download script (downloads libretro_data from GitHub Release)
  scripts/
    __init__.py
    cover_cli.py                 # CLI entry point
    thumbnail_matcher.py         # Core matching engine
    presets.json                 # Built-in preset rules (pegasus, es-de, etc.)
    user_rules.json              # User custom rules (saved via save-preset)
  libretro_data/                 # (not in repo — downloaded via fetch_data.py)
    mediadata/                   # Per-system thumbnail index JSON
    metadata/                    # Per-system ROM metadata JSON
    merged_games.json            # Merged game name database
    platform-aliases.json        # Platform name alias mapping
```

If `libretro_data/` is missing, the CLI will print a helpful error telling the user to run `python fetch_data.py` first.

## Media Types

The CLI supports 4 media types from the Libretro thumbnail library:

| Alias | Libretro Name | 中文 | {type_dir} | {type_alias} |
|-------|---------------|------|------------|-------------|
| `boxarts` / `covers` | Named_Boxarts | 封面 | Boxarts | boxfront |
| `titles` | Named_Titles | 标题画面 | Titles | title |
| `snaps` / `screenshots` | Named_Snaps | 截图 | Snaps | snap |
| `logos` | Named_Logos | Logo | Logos | logo |

- Default: `boxarts` (封面)
- Multiple types: `--type boxarts,titles` or `--type all`

## Save Rule (`--save-rule`)

The `--save-rule` parameter controls how downloaded files are named and where they are saved. It accepts a JSON object mapping each media type to a `{"dir": "...", "name": "..."}` rule.

### Template Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `{output}` | The `--output` directory | `F:\roms\n64\covers` |
| `{game}` | Safe game name (from match or ROM filename, depends on `--filename`) | `马里奥64` |
| `{rom}` | Safe ROM filename stem | `马里奥64` |
| `{type_dir}` | Short type directory name | `Boxarts`, `Logos` |
| `{type_alias}` | Short type file stem | `boxfront`, `logo` |

### Default Rules

- **Single type** (no `--save-rule`): `{"Named_Boxarts": {"dir": "{output}", "name": "{game}"}}`
  → `F:\covers\Super Mario Bros. 3.png`

- **Multiple types** (no `--save-rule`): each type gets a subdirectory
  → `{"Named_Boxarts": {"dir": "{output}/Boxarts", "name": "{game}"}, ...}`
  → `F:\covers\Boxarts\Super Mario Bros. 3.png`

## Preset Rules (`--preset`)

Use `--preset` to apply a predefined save rule for a common frontend layout. This is easier than writing `--save-rule` JSON manually. Presets also auto-set `--filename` to the recommended value.

Built-in presets are stored in `scripts/presets.json`. User custom presets are stored in `scripts/user_rules.json` and take priority over built-in ones with the same name.

### Built-in Presets

| Preset | Frontend | Layout | Auto `--filename` |
|--------|----------|--------|--------------------|
| `pegasus` | Pegasus Frontend | 每个游戏一个文件夹，封面 `boxFront.png`，logo `logo.png` | `game` |
| `es-de` | EmulationStation-DE | 按类型分子目录 `covers/` `marquees/` `titlescreens/` `screenshots/`，文件名用 ROM 名 | `rom` |
| `retroarch` | RetroArch | Libretro 标准结构 `Named_Boxarts/` `Named_Logos/` 等 | `game` |
| `simple` | 通用 | 所有封面直接存到 output 目录 | `game` |

### Preset Examples

**Pegasus — 每个游戏一个文件夹：**

```powershell
python -m scripts.cover_cli download-folder --path "F:\Roms\fc" --system "Nintendo - Nintendo Entertainment System" --output "F:\Roms\fc\media" --type boxarts,logos --preset pegasus
```

Result:
```
F:\Roms\fc\media\
  Super Mario Bros. 3\
    boxFront.png
    logo.png
```

**ES-DE — 按类型分子目录，ROM 名作文件名：**

```powershell
python -m scripts.cover_cli download-folder --path "F:\Roms\gbc" --system "Nintendo - Game Boy Color" --output "F:\Roms\gbc\media" --type boxarts,logos --preset es-de
```

Result:
```
F:\Roms\gbc\media\
  covers\
    Super Mario Land.zip.png
  marquees\
    Super Mario Land.zip.png
```

**RetroArch — Libretro 标准目录：**

```powershell
python -m scripts.cover_cli download-folder --path "F:\Roms\n64" --system "Nintendo - Nintendo 64" --output "F:\Roms\n64\thumbnails" --type all --preset retroarch
```

Result:
```
F:\Roms\n64\thumbnails\
  Named_Boxarts\Super Mario 64.png
  Named_Logos\Super Mario 64.png
  Named_Titles\Super Mario 64.png
  Named_Snaps\Super Mario 64.png
```

`--preset` and `--save-rule` are mutually exclusive — if both are provided, `--save-rule` takes priority.

### Save Custom Preset (`save-preset`)

When the user asks to save a rule for reuse, use the `save-preset` command. This writes the rule to `scripts/user_rules.json` so it can be referenced by name later with `--preset`.

```powershell
python -m scripts.cover_cli save-preset --name "my-n64" --rule '{"Named_Boxarts":{"dir":"{output}/{rom}","name":"boxfront"},"Named_Logos":{"dir":"{output}/{rom}","name":"logo"}}' --filename rom --desc "N64: ROM名文件夹+类型别名文件名"
```

After saving, use it:

```powershell
python -m scripts.cover_cli download-folder --path "F:\Roms\n64" --output "F:\Roms\n64\media" --preset my-n64
```

### List All Presets (`list-presets`)

```powershell
python -m scripts.cover_cli list-presets
```

Returns all built-in and user presets with name, source, description, and filename mode.

### Custom Rule Examples

**Per-game folder with type-alias filenames** (each game gets a folder, cover named `boxfront`, logo named `logo`):

```json
{
  "Named_Boxarts": {"dir": "{output}/{game}", "name": "boxfront"},
  "Named_Logos": {"dir": "{output}/{game}", "name": "logo"}
}
```

Result:
```
F:\covers\
  马里奥64\
    boxfront.png
    logo.png
```

**Per-game folder with type subdirectories** (each game gets a folder containing Boxarts/, Logos/ etc.):

```json
{
  "Named_Boxarts": {"dir": "{output}/{game}/Boxarts", "name": "{game}"},
  "Named_Logos": {"dir": "{output}/{game}/Logos", "name": "{game}"}
}
```

Result:
```
F:\covers\
  马里奥64\
    Boxarts\马里奥64.png
    Logos\马里奥64.png
```

**Different drives for different types**:

```json
{
  "Named_Boxarts": {"dir": "D:\\covers\\n64", "name": "{rom}"},
  "Named_Logos": {"dir": "E:\\logos\\n64", "name": "{rom}"}
}
```

**ROM filename as folder, cover named by game**:

```json
{
  "Named_Boxarts": {"dir": "{output}/{rom}", "name": "{game}"}
}
```

### How to Pass `--save-rule`

1. **JSON string** (note: in PowerShell, use single quotes to avoid variable expansion):

```powershell
python -m scripts.cover_cli download-folder --path "F:\roms\n64" --system "Nintendo - Nintendo 64" --output "F:\roms\n64\covers" --type boxarts,logos --save-rule '{"Named_Boxarts":{"dir":"{output}/{game}","name":"boxfront"},"Named_Logos":{"dir":"{output}/{game}","name":"logo"}}' --filename rom
```

2. **@file reference** (recommended for complex rules):

```powershell
# Write rule to a file first
python -m scripts.cover_cli download-folder --path "F:\roms\n64" --system "Nintendo - Nintendo 64" --output "F:\roms\n64\covers" --type boxarts,logos --save-rule "@rule.json" --filename rom
```

## Commands

### Download by game name

```powershell
python -m scripts.cover_cli download-game --name "<game name>" --system "<Libretro system>" --output "<output folder>"
```

Use `--save-as` when retrying a ROM with a web-found No-Intro name but the saved cover should keep the original ROM name:

```powershell
python -m scripts.cover_cli download-game --name "<No-Intro name>" --system "<Libretro system>" --output "<output folder>" --save-as "<rom stem>"
```

### Download for one ROM file

```powershell
python -m scripts.cover_cli download-file --path "<rom file>" --output "<output folder>"
```

If platform inference may fail, include `--system`:

```powershell
python -m scripts.cover_cli download-file --path "F:\Roms\gbc\Zelda.zip" --system "Nintendo - Game Boy Color" --output "D:\covers\gbc"
```

### Download for a ROM folder

```powershell
python -m scripts.cover_cli download-folder --path "<rom folder>" --output "<output folder>"
```

Full example with progress, retries, concurrent downloads, and report:

```powershell
python -m scripts.cover_cli download-folder --path "F:\Roms\gbc" --system "Nintendo - Game Boy Color" --output "D:\covers\gbc" --extensions ".gbc,.zip" --filename rom --existing skip --retries 3 --retry-delay 1 --progress --report ".\cover-report.json"
# 默认4线程下载，可加 --download-workers 8 开启更高线程
```

### Batch download by game names (Stage 2 recovery)

```powershell
python -m scripts.cover_cli download-batch --system "<Libretro system>" --output "<output folder>" --names '{"<rom stem>": "<No-Intro name>", ...}'
```

The `--names` parameter is a JSON mapping from ROM filename stems to No-Intro game names. Supports `@file.json` to read from a file. The command matches all names first, then downloads covers with multi-threading (`--download-workers`, default 4).

```powershell
python -m scripts.cover_cli download-batch \
  --system "Nintendo - Game Boy Color" \
  --output "D:\covers\gbc" \
  --names '{"超级马里奥": "Super Mario Bros.", "塞尔达": "The Legend of Zelda - Link'\''s Awakening"}' \
  --preset es-de \
  --existing skip \
  --download-workers 8 \
  --progress \
  --report ".\cover-retry-report.json"
```

### Dry run

Use `--dry-run` before downloading if the user wants to preview matches or verify accuracy.

```powershell
python -m scripts.cover_cli download-folder --path "F:\Roms\gbc" --output "D:\covers\gbc" --dry-run
```

## Options

- `--system`: Libretro platform name. Ask the user if it cannot be inferred from the path.
- `--output`: target cover folder. Required.
- `--type`: media type(s). Accepts: `boxarts`/`covers`, `titles`, `snaps`/`screenshots`, `logos`. Comma-separated for multiple, or `all` for all 4 types. Defaults to `boxarts`.
- `--save-rule`: save path rule as JSON or `@file.json`. Format: `{"Named_Boxarts": {"dir": "...", "name": "..."}}`. Template variables: `{output}`, `{game}`, `{rom}`, `{type_dir}`, `{type_alias}`. Defaults: single type → direct to output; multiple types → subdirectory per type.
- `--preset`: predefined save rule for common frontends. Built-in: `pegasus`, `es-de`, `retroarch`, `simple`. Also supports user custom rules saved via `save-preset`. See [Preset Rules](#preset-rules---preset) section. Mutually exclusive with `--save-rule` (if both given, `--save-rule` wins).
- `--min-score`: minimum fuzzy match score, defaults to `80`.
- `--limit`: number of candidates, defaults to `1`.
- `--filename`: output filename source, use `rom` to save covers with ROM names, `game` for matched game names, or `match` for thumbnail library names. This determines what `{game}` resolves to when using `--save-rule`.
- `--save-as`: for `download-game`, save the downloaded cover using this filename stem instead of the matched game name.
- `--report`: write a lightweight JSON report file for AI recovery. In folder mode it includes summary fields plus only `failed` and `unmatched` arrays, not all matched/downloaded items.
- `--extensions`: comma-separated ROM extensions for folder scanning.
- `--workers`: number of scan workers for folder mode.
- `--download-workers`: number of cover download threads for folder mode, defaults to `4`. Users can specify a higher value (e.g. `8` or `16`) for faster downloads on high-bandwidth connections.
- `--names`: (download-batch only) JSON mapping from ROM filename stems to No-Intro game names, or `@file.json` to read from a file.
- `--existing`: what to do when target files already exist: `ask`, `skip`, or `overwrite`. Defaults to `ask`.
- `--retries`: retry count for failed image downloads, defaults to `2`.
- `--retry-delay`: seconds to wait before each retry, defaults to `1.0`.
- `--progress`: output JSON Lines progress events so AI can track current download progress.
- `--dry-run`: output matches without downloading.

## Clarification rules

Ask the user for missing information when needed:

1. Game name, ROM file, or ROM folder.
2. Platform/system if it is not obvious.
3. Output folder.
4. If the user specifies how files should be organized (e.g. "each game in its own folder", "cover named boxfront"), translate that into a `--save-rule` JSON. You do NOT need to ask the user about `--save-rule` directly — just generate the correct rule from their description.

Common patterns the user might describe:

| User says | Rule to generate |
|-----------|-----------------|
| "just download covers" | No `--save-rule` needed (default) |
| "Pegasus layout" / "天马格式" | `--preset pegasus` |
| "ES-DE layout" / "EmulationStation格式" | `--preset es-de` |
| "RetroArch layout" / "Libretro标准结构" | `--preset retroarch` |
| "each game in its own folder, cover named boxfront, logo named logo" | `--preset pegasus` |
| "each game in its own folder with Boxarts/Logos subfolders" | `{"Named_Boxarts":{"dir":"{output}/{game}/Boxarts","name":"{game}"},"Named_Logos":{"dir":"{output}/{game}/Logos","name":"{game}"}}` |
| "covers to A drive, logos to B drive" | `{"Named_Boxarts":{"dir":"A:/covers","name":"{rom}"},"Named_Logos":{"dir":"B:/logos","name":"{rom}"}}` |
| "use ROM filename as folder name" | `{"Named_Boxarts":{"dir":"{output}/{rom}","name":"boxfront"}}` |
| "save this rule as xxx" / "记住这个规则" | Use `save-preset` command to write to user_rules.json |
| "有哪些规则" / "有什么预置规则" / "列出规则" | Run `list-presets` and show each preset's name, description, and rule JSON to the user |

## Output handling

The CLI prints JSON. Summarize these fields to the user:

- `ok`
- `system`
- `output`
- `types` — list of media types downloaded
- `save_rule` — the rule used for saving
- `downloaded_count`
- `matched_count`
- `failed_count`
- `unmatched_count`
- `per_type` — per-type breakdown of counts
- failed or unmatched files, if any

When using `--report` in folder mode, read the lightweight report file to inspect:

- summary counts such as `scanned_count`, `matched_count`, `downloaded_count`, `failed_count`, and `unmatched_count`.
- `per_type` breakdown.
- `unmatched`: ROMs that did not match any cover.
- `failed`: ROMs that matched but failed to download.

Do not expect the folder report to contain every matched/downloaded/skipped item; it is intentionally small to reduce token usage.

## Recovery for unmatched games

After every folder download, if `unmatched_count > 0`, ask the user whether to run the second-stage recovery flow. Do not start web search automatically unless the user confirms.

Example prompt:

```text
还有 35 个 ROM 未匹配到封面，是否需要我联网查询对应的 No-Intro 名称并尝试二阶段下载？
```

Use this flow when the user confirms, or when the user explicitly asks to retry unmatched games, recover failed cover matches, or search No-Intro names online.

### Stage 2: Batch Recovery Flow

The second stage first collects ALL unmatched ROM names, then downloads them in one batch with multi-threading.

1. Run or reuse a folder command with `--report` so unmatched ROMs are available in a JSON file.
2. Read the report and collect `unmatched` items. Use each item's `file` and ROM filename stem.
3. **For each unmatched ROM**, search the web with queries like:
   - `"<rom stem>" "<system>" "No-Intro"`
   - `"<rom stem>" "Game Boy Color" English title`
   - `"<rom stem>" "GBC" rom name`
4. Prefer exact No-Intro-style names matching the requested system and region. If confidence is low, ask the user before downloading.
5. **Collect all name mappings** into a JSON object: `{"<rom stem>": "<No-Intro name>", ...}`
6. Run `download-batch` with the complete mapping — this matches all names first, then downloads with multi-threading:

```powershell
python -m scripts.cover_cli download-batch \
  --system "<Libretro system>" \
  --output "<output folder>" \
  --names '{"<rom stem 1>": "<No-Intro name 1>", "<rom stem 2>": "<No-Intro name 2>"}' \
  --existing skip \
  --download-workers 4 \
  --preset es-de
```

Or write the mapping to a file for cleaner command lines:

```powershell
# Write names mapping to file
# Content: {"超级马里奥": "Super Mario Bros.", "塞尔达": "The Legend of Zelda"}
python -m scripts.cover_cli download-batch \
  --system "<Libretro system>" \
  --output "<output folder>" \
  --names "@retry_names.json" \
  --existing skip \
  --download-workers 4 \
  --preset es-de \
  --report ".\cover-retry-report.json"
```

7. Summarize recovered, still-unmatched, and low-confidence items. Include source URLs when web search was used.

### Stage 2 Retry Loop (handling remaining failures)

If `download-batch` still has `failed` or `unmatched` items, the names used were likely incorrect. **Do not blindly retry with the same names** — the AI must re-analyze and find better names:

1. Read the `download-batch` report (from `--report`) and identify `failed` + `unmatched` items.
2. For each failed/unmatched item, **re-search the web** with alternative queries:
   - Try different search terms: `"<rom stem>" "<system>" rom dat`, `"<rom stem>" redump`, or search in the ROM's original language
   - Try partial name matching: search only the core part of the ROM name, drop region/version tags
   - Check No-Intro DAT files or ROM databases for the exact title
3. If a better name is found, update the names mapping and run `download-batch` again with only the corrected items.
4. If no better name can be found after reasonable effort, report these as "permanently unmatched" to the user.

**Important**: The retry logic lives in the AI (this SKILL.md), not in the CLI tool. `download-batch` simply takes a mapping and downloads — it does not guess or auto-correct game names.

## Sandbox permission handling

If command output or terminal logs contain any of these sandbox permission errors:

- `TRAE Sandbox Error: hit restricted`
- `Not allow operate files`
- permission errors mentioning the requested output path

Do not tell the user to run the command manually as the primary solution. Instead:

1. Explain that matching succeeded or partially succeeded, but AI was blocked from writing to the requested directory by Trae sandbox rules.
2. Tell the user exactly which directory should be allowed, usually the `--output` directory. If the user is downloading into a ROM library, suggest allowing the output directory only, not the whole drive.
3. Ask the user to add that path in `Settings -> Conversation -> Custom Sandbox Configuration`.
4. After the user confirms the permission is added, rerun the same command automatically.
5. If the user does not want to change sandbox settings, offer an alternative output path inside the current workspace.

Example response when blocked:

```text
匹配已完成，但 Trae 沙箱阻止 AI 写入：F:\roms\gbc\covers。
请在 Settings -> Conversation -> Custom Sandbox Configuration 里允许这个目录：
F:\roms\gbc\covers
允许后告诉我，我会自动重试同一条下载命令。
```

If `ok` is false for normal matching reasons, explain the error or unmatched result and suggest using `--system`, lowering `--min-score`, or running `--dry-run`.
