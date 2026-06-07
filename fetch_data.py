#!/usr/bin/env python3
"""Download libretro_data from GitHub Release if not present."""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path

try:
    import requests
except ImportError:
    print("请先安装 requests: pip install requests", file=sys.stderr)
    sys.exit(1)

PROJECT_ROOT = Path(__file__).parent
DATA_DIR = PROJECT_ROOT / "libretro_data"

# 替换为你的实际 GitHub 仓库地址
RELEASE_URL = "https://github.com/wang1025475397/game-cover-downloader/releases/latest/download/libretro_data.zip"


def is_data_present() -> bool:
    """Check if libretro_data directory exists and has required files."""
    if not DATA_DIR.is_dir():
        return False
    required = [
        DATA_DIR / "merged_games.json",
        DATA_DIR / "platform-aliases.json",
        DATA_DIR / "mediadata",
        DATA_DIR / "metadata",
    ]
    return all(p.exists() for p in required)


def download_and_extract(url: str, dest: Path) -> None:
    """Download a zip file and extract it so that dest/ contains the data."""
    print(f"正在下载数据包...")
    resp = requests.get(url, stream=True, timeout=120)
    resp.raise_for_status()

    total = int(resp.headers.get("content-length", 0))
    downloaded = 0
    zip_path = dest.parent / "_libretro_data_tmp.zip"

    try:
        with zip_path.open("wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
                downloaded += len(chunk)
                if total:
                    pct = downloaded * 100 // total
                    print(f"\r  进度: {pct}% ({downloaded // 1024 // 1024} MB / {total // 1024 // 1024} MB)", end="", flush=True)
        print()  # newline after progress

        print("正在解压...")
        with zipfile.ZipFile(zip_path, "r") as zf:
            names = zf.namelist()
            # Detect if zip has a top-level libretro_data/ directory
            has_toplevel = any(n.startswith("libretro_data/") or n == "libretro_data" for n in names)
            if has_toplevel:
                # Zip contains libretro_data/ at top level → extract to project root
                zf.extractall(dest.parent)
            else:
                # Zip contents are flat (mediadata/, metadata/, ...) → extract into libretro_data/
                zf.extractall(dest)

        if not is_data_present():
            print("警告：解压后未检测到完整数据，请检查 zip 文件结构。", file=sys.stderr)
            print(f"期望结构：libretro_data/mediadata/ 或 libretro_data/libretro_data/mediadata/", file=sys.stderr)
        else:
            print("数据包安装完成！")
    finally:
        if zip_path.exists():
            zip_path.unlink()


def main() -> int:
    if is_data_present():
        print("libretro_data 已存在，无需下载。")
        return 0

    print("未检测到 libretro_data 数据目录。")
    print(f"将从 GitHub Release 下载: {RELEASE_URL}")
    download_and_extract(RELEASE_URL, DATA_DIR)
    return 0


if __name__ == "__main__":
    sys.exit(main())
