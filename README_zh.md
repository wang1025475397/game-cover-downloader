# Game Cover Downloader

[English](README.md)

从 [Libretro 缩略图库](https://thumbnails.libretro.com/) 批量下载游戏封面、Logo、标题画面和截图的 CLI 工具。支持模糊匹配 ROM 文件名、多线程下载、多种前端布局预设（Pegasus / ES-DE / RetroArch）和自定义保存规则。

作为 AI 编程助手的 Skill 使用时，可用自然语言驱动下载，无需记忆命令行参数。

## 功能特性

- 🎮 按游戏名、单个 ROM 文件或 ROM 文件夹批量下载封面
- 🔍 模糊匹配 ROM 文件名与 Libretro 数据库中的游戏名
- 🖼️ 支持封面 (Boxarts)、Logo、标题画面 (Titles)、截图 (Snaps) 四种媒体类型
- 📁 内置 Pegasus / ES-DE / RetroArch / Simple 四种前端布局预设
- ✏️ 自定义保存规则（JSON 格式），支持保存为用户预设复用
- 🚀 默认 4 线程下载，可指定更高线程数
- 🔄 未匹配 ROM 的二阶段恢复流程（联网搜索 No-Intro 名称重试）
- 📊 JSON 格式输出，支持进度报告和下载报告

## 依赖

- Python 3.10+
- [requests](https://pypi.org/project/requests/)

## 安装

### 1. 安装 Python 依赖

```bash
pip install -r requirements.txt
```

### 2. 下载游戏数据库

`libretro_data/` 目录（约 400 MB）包含游戏名称数据库，**未包含**在 Git 仓库中。使用内置脚本下载：

```bash
python fetch_data.py
```

脚本会自动从最新 [GitHub Release](https://github.com/YOUR_USERNAME/game-cover-downloader/releases) 下载并解压数据。

<details>
<summary>手动下载</summary>

如果 `fetch_data.py` 无法运行，可以从 [Releases 页面](https://github.com/YOUR_USERNAME/game-cover-downloader/releases) 手动下载 `libretro_data.zip` 并解压到项目根目录：

```
game-cover-downloader/
  libretro_data/    ← 解压到这里
    mediadata/
    metadata/
    merged_games.json
    platform-aliases.json
```

</details>

## 快速开始

### 命令行直接使用

```bash
# 下载单个游戏的封面
python -m scripts.cover_cli download-game --name "Super Mario Bros." --system "Nintendo - Nintendo Entertainment System" --output "./covers"

# 下载单个 ROM 文件的封面
python -m scripts.cover_cli download-file --path "F:\Roms\gbc\Zelda.zip" --output "./covers"

# 批量下载整个 ROM 文件夹的封面
python -m scripts.cover_cli download-folder --path "F:\Roms\gbc" --system "Nintendo - Game Boy Color" --output "./covers" --download-workers 4
```

### 使用预设布局

```bash
# Pegasus 前端格式（每个游戏一个文件夹）
python -m scripts.cover_cli download-folder --path "F:\Roms\fc" --system "Nintendo - Nintendo Entertainment System" --output "./media" --type boxarts,logos --preset pegasus

# ES-DE 前端格式（按类型分子目录）
python -m scripts.cover_cli download-folder --path "F:\Roms\gbc" --system "Nintendo - Game Boy Color" --output "./media" --type boxarts,logos --preset es-de

# RetroArch 标准结构
python -m scripts.cover_cli download-folder --path "F:\Roms\n64" --system "Nintendo - Nintendo 64" --output "./thumbnails" --type all --preset retroarch
```

### 查看可用预设

```bash
python -m scripts.cover_cli list-presets
```

### 保存自定义预设

```bash
python -m scripts.cover_cli save-preset --name "my-n64" --rule '{"Named_Boxarts":{"dir":"{output}/{rom}","name":"boxfront"},"Named_Logos":{"dir":"{output}/{rom}","name":"logo"}}' --filename rom --desc "N64: ROM名文件夹+类型别名文件名"
```

## 作为 AI 编程助手 Skill 安装

本工具遵循 [Agent Skills 标准](https://docs.anthropic.com/en/docs/claude-code/skills)，`SKILL.md` 兼容所有支持该标准的 AI 编程客户端。将本项目文件夹放入对应客户端的 skills 目录即可，无需额外配置。

### 各客户端安装路径

| 客户端 | 用户级路径（推荐） | 项目级路径 |
|--------|-------------------|-----------|
| **Claude Code** | `~/.claude/skills/game-cover-downloader/` | `.claude/skills/game-cover-downloader/` |
| **Codex CLI** | `~/.codex/skills/game-cover-downloader/` | `.codex/skills/game-cover-downloader/` |
| **OpenClaw** | `~/.openclaw/skills/game-cover-downloader/` | `<workspace>/skills/game-cover-downloader/` |
| **CodeBuddy** | `~/.codebuddy/skills/game-cover-downloader/` | `.codebuddy/skills/game-cover-downloader/` |

> **Windows 用户**：`~` 对应 `%USERPROFILE%`，例如 `C:\Users\你的用户名\.claude\skills\game-cover-downloader\`

### 安装步骤

**方式一：Git 克隆（推荐）**

```bash
# Claude Code 示例，其他客户端替换路径即可
git clone https://github.com/<你的用户名>/game-cover-downloader.git ~/.claude/skills/game-cover-downloader
```

**方式二：手动复制**

1. 下载本项目 ZIP 并解压
2. 将整个 `game-cover-downloader` 文件夹复制到上表中对应客户端的 skills 目录
3. 确保目录结构为 `<skills路径>/game-cover-downloader/SKILL.md`

**方式三：项目级安装（团队共享）**

将 `game-cover-downloader` 文件夹放在项目根目录的对应位置（如 `.claude/skills/`），通过 Git 与团队共享。

### 验证安装

安装后重启 AI 编程助手，在对话中提及下载游戏封面即可触发 Skill。例如：

- "帮我下载 N64 的封面"
- "用天马格式下载 FC 的封面和 logo"
- "有哪些下载规则？"

## 项目结构

```
game-cover-downloader/
  SKILL.md                       # AI Skill 定义文件
  requirements.txt               # Python 依赖
  fetch_data.py                  # 数据下载脚本
  README.md                      # 英文文档
  README_zh.md                   # 中文文档
  scripts/
    __init__.py
    cover_cli.py                 # CLI 入口
    thumbnail_matcher.py         # 核心匹配引擎
    presets.json                 # 内置预置规则
    user_rules.json              # 用户自定义规则（save-preset 生成）
  libretro_data/                 # （不在仓库中，通过 fetch_data.py 下载）
    mediadata/                   # 各平台缩略图索引 JSON
    metadata/                    # 各平台 ROM 元数据 JSON
    merged_games.json            # 合并后的游戏名数据库
    platform-aliases.json        # 平台名称别名映射
```

## 常用参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--system` | Libretro 平台名 | 自动推断 |
| `--output` | 输出目录 | 必填 |
| `--type` | 媒体类型：`boxarts`/`titles`/`snaps`/`logos`，逗号分隔或 `all` | `boxarts` |
| `--preset` | 预置规则：`pegasus`/`es-de`/`retroarch`/`simple` 或用户自定义 | 无 |
| `--save-rule` | 自定义保存规则 JSON | 默认规则 |
| `--filename` | 文件名来源：`game`/`rom`/`match` | `game` |
| `--download-workers` | 下载线程数 | `4` |
| `--min-score` | 模糊匹配最低分数 | `80` |
| `--existing` | 已有文件处理：`ask`/`skip`/`overwrite` | `ask` |
| `--dry-run` | 仅预览匹配结果，不下载 | `false` |

## License

MIT
