# Game Cover Downloader

[中文文档](README_zh.md)

A CLI tool for batch downloading game covers, logos, title screens, and screenshots from the [Libretro Thumbnail Library](https://thumbnails.libretro.com/). Features fuzzy ROM filename matching, multi-threaded downloads, frontend layout presets (Pegasus / ES-DE / RetroArch), and custom save rules.

When used as an AI coding assistant Skill, you can drive downloads with natural language — no need to memorize CLI arguments.

## Features

- 🎮 Download covers by game name, single ROM file, or ROM folder
- 🔍 Fuzzy match ROM filenames against the Libretro game database
- 🖼️ Four media types: Boxarts, Logos, Titles, Snaps
- 📁 Built-in presets for Pegasus / ES-DE / RetroArch / Simple layouts
- ✏️ Custom save rules (JSON format), with save-as-preset for reuse
- 🚀 Default 4-thread downloads, configurable to higher thread counts
- 🔄 Two-stage recovery for unmatched ROMs (web search for No-Intro names)
- 📊 JSON output with progress events and download reports

## Requirements

- Python 3.10+
- [requests](https://pypi.org/project/requests/)

## Installation

### 1. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 2. Download game database

The `libretro_data/` directory (~400 MB) contains the game name database and is **not included** in the Git repository. Download it with the included script:

```bash
python fetch_data.py
```

This will automatically download and extract the data from the latest [GitHub Release](https://github.com/wang1025475397/game-cover-downloader/releases).

<details>
<summary>Manual download</summary>

If `fetch_data.py` doesn't work, you can manually download `libretro_data.zip` from the [Releases page](https://github.com/wang1025475397/game-cover-downloader/releases) and extract it to the project root.

Make sure the final structure looks like this (avoid nested `libretro_data/libretro_data/`):

```
game-cover-downloader/
  libretro_data/         ← this folder must be directly under the project root
    mediadata/
    metadata/
    merged_games.json
    platform-aliases.json
```

**Wrong** ❌:
```
game-cover-downloader/
  libretro_data/
    libretro_data/       ← nested! drag the inner folder up one level
      mediadata/
```

</details>

## Quick Start

### CLI Usage

```bash
# Download a single game's cover
python -m scripts.cover_cli download-game --name "Super Mario Bros." --system "Nintendo - Nintendo Entertainment System" --output "./covers"

# Download a single ROM file's cover
python -m scripts.cover_cli download-file --path "F:\Roms\gbc\Zelda.zip" --output "./covers"

# Batch download covers for a ROM folder
python -m scripts.cover_cli download-folder --path "F:\Roms\gbc" --system "Nintendo - Game Boy Color" --output "./covers" --download-workers 4
```

### Using Preset Layouts

```bash
# Pegasus frontend layout (per-game folder)
python -m scripts.cover_cli download-folder --path "F:\Roms\fc" --system "Nintendo - Nintendo Entertainment System" --output "./media" --type boxarts,logos --preset pegasus

# ES-DE frontend layout (per-type subdirectories)
python -m scripts.cover_cli download-folder --path "F:\Roms\gbc" --system "Nintendo - Game Boy Color" --output "./media" --type boxarts,logos --preset es-de

# RetroArch standard structure
python -m scripts.cover_cli download-folder --path "F:\Roms\n64" --system "Nintendo - Nintendo 64" --output "./thumbnails" --type all --preset retroarch
```

### List Available Presets

```bash
python -m scripts.cover_cli list-presets
```

### Save a Custom Preset

```bash
python -m scripts.cover_cli save-preset --name "my-n64" --rule '{"Named_Boxarts":{"dir":"{output}/{rom}","name":"boxfront"},"Named_Logos":{"dir":"{output}/{rom}","name":"logo"}}' --filename rom --desc "N64: ROM-name folders with type-alias filenames"
```

## Installing as an AI Coding Assistant Skill

This tool follows the [Agent Skills standard](https://docs.anthropic.com/en/docs/claude-code/skills). The `SKILL.md` is compatible with all AI coding clients that support this standard. Simply place the project folder into the corresponding client's skills directory — no extra configuration needed.

### Client Installation Paths

| Client | User-level Path (Recommended) | Project-level Path |
|--------|-------------------------------|-------------------|
| **Claude Code** | `~/.claude/skills/game-cover-downloader/` | `.claude/skills/game-cover-downloader/` |
| **Codex CLI** | `~/.codex/skills/game-cover-downloader/` | `.codex/skills/game-cover-downloader/` |
| **OpenClaw** | `~/.openclaw/skills/game-cover-downloader/` | `<workspace>/skills/game-cover-downloader/` |
| **CodeBuddy** | `~/.codebuddy/skills/game-cover-downloader/` | `.codebuddy/skills/game-cover-downloader/` |

> **Windows users**: `~` corresponds to `%USERPROFILE%`, e.g. `C:\Users\YourName\.claude\skills\game-cover-downloader\`

### Installation Steps

**Option 1: Git Clone (Recommended)**

```bash
# Example for Claude Code — replace the path for other clients
git clone https://github.com/wang1025475397/game-cover-downloader.git ~/.claude/skills/game-cover-downloader
```

**Option 2: Manual Copy**

1. Download and extract the project ZIP
2. Copy the entire `game-cover-downloader` folder to the client's skills directory from the table above
3. Ensure the directory structure is `<skills-path>/game-cover-downloader/SKILL.md`

**Option 3: Project-level Install (Team Sharing)**

Place the `game-cover-downloader` folder in the project root's corresponding location (e.g. `.claude/skills/`) and share it via Git.

### Verify Installation

Restart your AI coding assistant after installation. Mention downloading game covers in a conversation to trigger the Skill. For example:

- "Download covers for N64 games"
- "Download NES covers and logos in Pegasus format"
- "What download presets are available?"

## Project Structure

```
game-cover-downloader/
  SKILL.md                       # AI Skill definition
  requirements.txt               # Python dependencies
  fetch_data.py                  # Data download script
  README.md                      # This file
  scripts/
    __init__.py
    cover_cli.py                 # CLI entry point
    thumbnail_matcher.py         # Core matching engine
    presets.json                 # Built-in preset rules
    user_rules.json              # User custom rules (generated by save-preset)
  libretro_data/                 # (not in repo — downloaded via fetch_data.py)
    mediadata/                   # Per-system thumbnail index JSON
    metadata/                    # Per-system ROM metadata JSON
    merged_games.json            # Merged game name database
    platform-aliases.json        # Platform name alias mapping
```

## Common Options

| Option | Description | Default |
|--------|-------------|---------|
| `--system` | Libretro platform name | Auto-inferred |
| `--output` | Output directory | Required |
| `--type` | Media types: `boxarts`/`titles`/`snaps`/`logos`, comma-separated or `all` | `boxarts` |
| `--preset` | Preset rule: `pegasus`/`es-de`/`retroarch`/`simple` or user custom | None |
| `--save-rule` | Custom save rule JSON | Default rules |
| `--filename` | Filename source: `game`/`rom`/`match` | `game` |
| `--download-workers` | Download thread count | `4` |
| `--min-score` | Minimum fuzzy match score | `80` |
| `--existing` | Existing file handling: `ask`/`skip`/`overwrite` | `ask` |
| `--dry-run` | Preview matches without downloading | `false` |

## License

MIT
