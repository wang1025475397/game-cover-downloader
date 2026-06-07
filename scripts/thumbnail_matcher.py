from __future__ import annotations

import json
import os
from pickle import FALSE
import re
import unicodedata
import zipfile
import zlib
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from difflib import SequenceMatcher
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote
from urllib.request import Request, urlopen

ADDRESS = "https://thumbnails.libretro.com"
DEF_SCORE = 80
MAX_SCORE = 100
THUMB_DIRS = ["Named_Boxarts", "Named_Titles", "Named_Snaps", "Named_Logos"]

# 直接修改这些变量即可运行脚本示例
MIN_SCORE = DEF_SCORE
LIMIT = 5
NO_META = True
HACK = False
BEFORE = None
REQUEST_TIMEOUT = 15
READ_CHUNK_SIZE = 64 * 1024
MAX_DIRECTORY_BYTES = 20 * 1024 * 1024
SHOW_PROGRESS = True

_PROJECT_ROOT = Path(__file__).parent.parent
THUMBNAIL_JSON_DIR = _PROJECT_ROOT / "libretro_data/mediadata"
METADATA_JSON_DIR = _PROJECT_ROOT / "libretro_data/metadata"
MERGED_GAMES_JSON_PATH = _PROJECT_ROOT / "libretro_data/merged_games.json"
PLATFORM_ALIASES_JSON_PATH = _PROJECT_ROOT / "libretro_data/platform-aliases.json"


def _check_libretro_data() -> None:
    """Raise with a helpful message if libretro_data is missing."""
    data_dir = _PROJECT_ROOT / "libretro_data"
    if data_dir.is_dir():
        return
    raise FileNotFoundError(
        "libretro_data 目录不存在。请先运行以下命令下载数据：\n"
        "  python fetch_data.py\n"
        "或从 GitHub Release 手动下载: https://github.com/YOUR_USERNAME/game-cover-downloader/releases"
    )


_check_libretro_data()

BUILD_ALL_PLATFORM_JSON = False
BUILD_JSON_IF_SYSTEM_MISSING = True
SKIP_EXISTING_PLATFORM_JSON = True
SCAN_WORKERS = 16

forbidden = re.compile(
    r"[\u0022\u003c\u003e\u007c\u0000\u0001\u0002\u0003\u0004\u0005\u0006\u0007\u0008"
    + r"\u0009\u000a\u000b\u000c\u000d\u000e\u000f\u0010\u0011\u0012\u0013\u0014\u0015"
    + r"\u0016\u0017\u0018\u0019\u001a\u001b\u001c\u001d\u001e\u001f\u003a\u002a\u003f\u005c\u002f\u0026]"
)
camelcase_pattern = re.compile(
    r"((?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])|(?<=[0-9])(?=[A-Z][a-z])|(?<=[a-zA-Z])(?=[0-9]))"
)
zero_lead_pattern = re.compile(r"([^\d])0+([1-9])")
almost_symbols_pattern = re.compile(r"[^\w\s,']")
roman_bounded_numeral = re.compile(r"\b[IVXLCDM]+\b")
roman_numerals = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}


@dataclass(frozen=True)
class Match:
    name: str
    score: float
    urls: dict[str, str]


@dataclass(frozen=True)
class GameMedia:
    path: Path
    crc: str
    name: str | None
    metadata: dict | None
    media: list[Match]
    match_source: str = "crc"


class LinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs = []

    def handle_starttag(self, tag, attrs):
        if tag != "a":
            return
        for key, value in attrs:
            if key == "href" and value:
                self.hrefs.append(value)


def text_ratio(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio() * 100


def extdigits(input_str: str) -> str:
    result = ""
    for ch in input_str:
        if ch.isdigit():
            result += ch
    return result


def removeparenthesis(input_str: str, open_p: str = "(", close_p: str = ")") -> str:
    result = ""
    remainder = ""
    paren_level = 0
    for ch in input_str:
        if ch == open_p:
            if paren_level < 0:
                paren_level = 1
            else:
                paren_level += 1
        elif ch == close_p:
            paren_level -= 1
            remainder = ""
        elif paren_level <= 0:
            result += ch
        else:
            remainder += ch
    return result + remainder


def extractbefore(before: str | None, name: str) -> str:
    if before:
        name_without_meta = re.search(r"(^[^\[({]*)", name)
        if name_without_meta:
            before_index = name_without_meta.group(1).find(before)
            if before_index != -1:
                return name[0:before_index]
    return name


def replacemany(our_str: str, to_be_replaced: str, replace_with: str) -> str:
    for nextchar in to_be_replaced:
        our_str = our_str.replace(nextchar, replace_with)
    return our_str


def removefirst(name: str, suf: str) -> str:
    return name.replace(suf, "", 1)


def removeprefix(name: str, pre: str) -> str:
    if name.startswith(pre):
        return name[len(pre) :]
    return name


def from_roman(num: str) -> int:
    result = 0
    for i, c in enumerate(num):
        if (i + 1) == len(num) or roman_numerals[c] >= roman_numerals[num[i + 1]]:
            result += roman_numerals[c]
        else:
            result -= roman_numerals[c]
    return result


def replace_roman(source: str) -> str:
    return roman_bounded_numeral.sub(lambda m: str(from_roman(m.group())), source)


def normalize_game_name(name: str, *, no_meta: bool = False, hack: bool = False) -> tuple[str, str, list[str], str]:
    if no_meta:
        name = removeparenthesis(name, "(", ")")
    if not hack:
        name = removeparenthesis(name, "[", "]")

    name = name.replace("_", " ")
    name = re.sub(zero_lead_pattern, r"\g<1>\g<2>", name)
    name = "".join(c for c in unicodedata.normalize("NFKD", name) if not unicodedata.combining(c))

    subtitles = name.split(" - ")
    if len(subtitles) == 1:
        subtitles = name.split(": ")

    subtitles_no_space = [""] * len(subtitles)
    for i, subtitle in enumerate(subtitles):
        stripped_symbols = re.sub(almost_symbols_pattern, "", subtitle)
        if stripped_symbols:
            subtitle = stripped_symbols

        subtitle = " ".join(part for token in re.split(camelcase_pattern, subtitle) if token and (part := token.strip()))
        subtitle = replace_roman(subtitle)
        subtitle = subtitle.replace("Center", "Centre")
        subtitle = subtitle.lower()
        subtitle = subtitle.replace("1rst", "1st")
        subtitle = subtitle.replace("first", "1st")
        subtitle = subtitle.replace("second", "2nd")
        subtitle = subtitle.replace("third", "3rd")
        subtitle = subtitle.replace("fourth", "4th")
        subtitle = subtitle.replace("fifth", "5th")
        subtitle = subtitle.replace("sixth", "6th")
        subtitle = subtitle.replace("seventh", "7th")
        subtitle = subtitle.replace("eighth", "8th")
        subtitle = subtitle.replace("ninth", "9th")
        subtitle = subtitle.replace("tenth", "10th")

        for suffix, prefix in [
            (", the", "the "),
            (", los", "los "),
            (", las", "las "),
            (", les", "les "),
            (", le", "le "),
            (", la", "la "),
            (", l'", "l'"),
            (", der", "der "),
            (", die", "die "),
            (", das", "das "),
            (", el", "el "),
            (", os", "os "),
            (", as", "as "),
            (", o", "o "),
            (", a", "a "),
        ]:
            subtitle = removefirst(subtitle, suffix)
            subtitle = removeprefix(subtitle, prefix)

        subtitle = replacemany(subtitle, ",'", "")
        subtitle = subtitle.replace(" and ", " ")
        subtitle = subtitle.replace(" the ", " ")
        words = subtitle.strip().split()
        subtitles[i] = " ".join(words)
        subtitles_no_space[i] = "".join(words)

    no_space_name = "".join(subtitles_no_space)
    return " ".join(subtitles), no_space_name, subtitles_no_space, extdigits(no_space_name)


def normalize_local_name(name: str, *, no_meta: bool = False, hack: bool = False, before: str | None = None):
    safe_name = re.sub(forbidden, "_", extractbefore(before, name))
    return name, normalize_game_name(safe_name, no_meta=no_meta, hack=hack)


def clean_lookup_name(name: str) -> str:
    cleaned = game_name_from_filename(name)
    cleaned = removeparenthesis(cleaned, "(", ")")
    cleaned = removeparenthesis(cleaned, "（", "）")
    cleaned = removeparenthesis(cleaned, "[", "]")
    cleaned = removeparenthesis(cleaned, "【", "】")
    return " ".join(cleaned.replace("_", " ").strip().split())


def normalize_lookup_key(name: str) -> str:
    normalized, no_space_name, _, _ = normalize_game_name(clean_lookup_name(name), no_meta=True)
    return no_space_name or normalized.replace(" ", "")


def normalize_remote_name(name: str, *, no_meta: bool = False, hack: bool = False):
    return name, normalize_game_name(name, no_meta=no_meta, hack=hack)


class TitleScorer:
    def __init__(self, local_norms: dict, remote_norms: dict, hack: bool = False):
        self.local_norms = local_norms
        self.remote_norms = remote_norms
        self.hack = hack

    def __call__(self, name, other):
        name, name_ns, name_ns_subs, digits = self.local_norms[name]
        other, other_ns, other_ns_subs, other_digits = self.remote_norms[other]
        if name == other or name_ns == other_ns:
            return MAX_SCORE
        if not name_ns:
            return 0

        remaining = MAX_SCORE - DEF_SCORE
        if not self.hack and other in self.local_norms:
            remaining -= remaining * 0.65

        rest_of_score = text_ratio(digits, other_digits) * 0.01 * 0.03 * remaining
        heuristic = remaining * 0.97
        ratio = text_ratio(name, other) * 0.01

        if not name_ns.isdigit():
            sum_ns = ""
            for sub_ns in other_ns_subs:
                if name_ns == sub_ns or name_ns == (sum_ns := sum_ns + sub_ns):
                    rest_of_score += heuristic * ratio
                    return DEF_SCORE + rest_of_score
        if not other_ns.isdigit():
            sum_ns = ""
            for sub_ns in name_ns_subs:
                if other_ns == sub_ns or other_ns == (sum_ns := sum_ns + sub_ns):
                    rest_of_score += heuristic * ratio
                    return DEF_SCORE + rest_of_score

        common = len(os.path.commonprefix([name_ns, other_ns])) / len(name_ns)
        parity = min(len(name_ns), len(other_ns)) / max(len(name_ns), len(other_ns))
        rest_of_score += (heuristic * common * 0.80) + (heuristic * parity * 0.20)
        return rest_of_score + DEF_SCORE * ratio


def read_url_text(url: str) -> str:
    request = Request(url, headers={"User-Agent": "thumbnail-matcher/1.0"})
    chunks = []
    total = 0
    with urlopen(request, timeout=REQUEST_TIMEOUT) as response:
        while True:
            chunk = response.read(READ_CHUNK_SIZE)
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if SHOW_PROGRESS:
                print(f"  read {total // 1024} KB", end="\r")
            if total > MAX_DIRECTORY_BYTES:
                raise RuntimeError(f"Directory response is too large: {url}")
    if SHOW_PROGRESS and total:
        print(f"  read {total // 1024} KB")
    return b"".join(chunks).decode("utf-8", errors="replace")


def scan_thumbnail_directory(
    system: str,
    *,
    address: str = ADDRESS,
    thumb_dirs: list[str] | None = None,
) -> dict[str, dict[str, str]]:
    thumb_dirs = thumb_dirs or THUMB_DIRS
    base_url = address.rstrip("/") + "/" + quote(system)
    result = {}

    for thumb_dir in thumb_dirs:
        directory_url = f"{base_url}/{thumb_dir}/"
        if SHOW_PROGRESS:
            print(f"Scanning {directory_url}")
        try:
            html = read_url_text(directory_url)
        except HTTPError as exc:
            if exc.code in (400, 404):
                result[thumb_dir] = {}
                continue
            raise RuntimeError(f"Could not scan thumbnail directory {directory_url}: {exc}") from exc
        except URLError as exc:
            raise RuntimeError(f"Could not scan thumbnail directory {directory_url}: {exc}") from exc

        parser = LinkParser()
        parser.feed(html)
        result[thumb_dir] = {
            unquote(Path(href).name[:-4]): directory_url + href
            for href in parser.hrefs
            if href.endswith(".png")
        }
        if SHOW_PROGRESS:
            print(f"  found {len(result[thumb_dir])} png files")

    return result


def list_thumbnail_systems(address: str = ADDRESS) -> list[str]:
    root_url = address.rstrip("/") + "/"
    if SHOW_PROGRESS:
        print(f"Scanning systems from {root_url}")
    html = read_url_text(root_url)
    parser = LinkParser()
    parser.feed(html)

    systems = []
    for href in parser.hrefs:
        if not href.endswith("/"):
            continue
        name = unquote(href.strip("/"))
        if name and not name.startswith(("?", "/")):
            systems.append(name)
    return sorted(set(systems))


def safe_json_filename(system: str) -> str:
    safe_name = re.sub(forbidden, "_", system).strip(" .")
    return f"{safe_name or 'unknown'}.json"


def system_json_path(system: str, json_dir: str | Path = THUMBNAIL_JSON_DIR) -> Path:
    return Path(json_dir, safe_json_filename(system))


def build_system_thumbnails_json(
    system: str,
    json_dir: str | Path = THUMBNAIL_JSON_DIR,
    *,
    address: str = ADDRESS,
    thumb_dirs: list[str] | None = None,
) -> dict[str, dict[str, str]]:
    thumbnail_index = scan_thumbnail_directory(system, address=address, thumb_dirs=thumb_dirs)
    json_dir = Path(json_dir)
    json_dir.mkdir(parents=True, exist_ok=True)
    output_path = system_json_path(system, json_dir)
    with output_path.open("w", encoding="utf-8") as file:
        json.dump(thumbnail_index, file, ensure_ascii=False, indent=2)
    return thumbnail_index


def build_all_json(
    json_dir: str | Path = THUMBNAIL_JSON_DIR,
    *,
    address: str = ADDRESS,
    thumb_dirs: list[str] | None = None,
    skip_existing: bool = True,
) -> list[str]:
    json_dir = Path(json_dir)
    json_dir.mkdir(parents=True, exist_ok=True)
    systems = list_thumbnail_systems(address)
    for index, system in enumerate(systems, 1):
        output_path = system_json_path(system, json_dir)
        if skip_existing and output_path.exists():
            if SHOW_PROGRESS:
                print(f"[{index}/{len(systems)}] exists: {output_path.name}")
            continue
        if SHOW_PROGRESS:
            print(f"[{index}/{len(systems)}] {system}")
        try:
            build_system_thumbnails_json(system, json_dir, address=address, thumb_dirs=thumb_dirs)
        except RuntimeError as exc:
            print(f"  skipped: {exc}")
    return systems


def load_system_thumbnails_json(
    system: str,
    json_dir: str | Path = THUMBNAIL_JSON_DIR,
) -> dict[str, dict[str, str]]:
    with system_json_path(system, json_dir).open("r", encoding="utf-8") as file:
        return json.load(file)


def load_system_metadata_json(
    system: str,
    metadata_dir: str | Path = METADATA_JSON_DIR,
) -> list[dict]:
    with system_json_path(system, metadata_dir).open("r", encoding="utf-8") as file:
        return json.load(file)


def load_merged_games_json(path: str | Path = MERGED_GAMES_JSON_PATH) -> dict:
    with Path(path).open("r", encoding="utf-8") as file:
        return json.load(file)


def normalize_platform_alias(name: str) -> str:
    name = name.strip().lower().replace("_", " ").replace("-", " ")
    return re.sub(r"\s+", " ", name)


def load_platform_aliases(path: str | Path = PLATFORM_ALIASES_JSON_PATH) -> dict[str, str]:
    with Path(path).open("r", encoding="utf-8") as file:
        platforms = json.load(file)

    aliases = {}
    for platform in platforms:
        canonical = platform["canonical"]
        aliases[normalize_platform_alias(canonical)] = canonical
        for alias in platform.get("aliases", []):
            aliases[normalize_platform_alias(str(alias))] = canonical
    return aliases


def infer_system_from_game_path(path: str | Path, aliases_path: str | Path = PLATFORM_ALIASES_JSON_PATH) -> str:
    path = Path(path)
    platform_name = path.parent.name if path.suffix else path.name
    system = load_platform_aliases(aliases_path).get(normalize_platform_alias(platform_name))
    if not system:
        raise ValueError(f"无法根据游戏文件夹名称识别系统: {platform_name}")
    return system


def iter_merged_games(merged_games: dict):
    for item in merged_games.values():
        if isinstance(item, list):
            yield from item
        else:
            yield item


def build_merged_game_name_index(merged_games: dict, system: str) -> tuple[list[str], dict[str, dict], dict[str, tuple[str, str, list[str], str]]]:
    candidates = []
    candidate_items = {}
    for item in iter_merged_games(merged_games):
        if item.get("platform") != system:
            continue
        for key in ("cn_cleaned_name", "cn_name"):
            candidate = item.get(key)
            if not candidate:
                continue
            candidate = str(candidate)
            if candidate not in candidate_items:
                candidates.append(candidate)
                candidate_items[candidate] = item
    return candidates, candidate_items, dict(normalize_remote_name(candidate, no_meta=True) for candidate in candidates)


def score_merged_game_name(
    filename: str,
    system: str,
    merged_games_path: str | Path = MERGED_GAMES_JSON_PATH,
    merged_games: dict | None = None,
    merged_game_index: tuple[list[str], dict[str, dict], dict[str, tuple[str, str, list[str], str]]] | None = None,
) -> tuple[dict | None, float]:
    lookup_name = clean_lookup_name(filename)
    if merged_game_index:
        candidates, candidate_items, remote_norms = merged_game_index
    else:
        merged_games = merged_games or load_merged_games_json(merged_games_path)
        candidates, candidate_items, remote_norms = build_merged_game_name_index(merged_games, system)

    if not candidates:
        return None, 0.0

    local_norms = dict([normalize_local_name(lookup_name, no_meta=True)])
    scorer = TitleScorer(local_norms, remote_norms)
    best_name, best_score = max(
        ((candidate, scorer(lookup_name, candidate)) for candidate in candidates),
        key=lambda item: item[1],
    )
    return candidate_items[best_name], best_score


def find_merged_game_by_name(
    filename: str,
    system: str,
    merged_games_path: str | Path = MERGED_GAMES_JSON_PATH,
    merged_games: dict | None = None,
    merged_game_index: tuple[list[str], dict[str, dict], dict[str, tuple[str, str, list[str], str]]] | None = None,
) -> dict | None:
    item, score = score_merged_game_name(filename, system, merged_games_path, merged_games, merged_game_index)
    return item if score >= DEF_SCORE else None


def merged_game_media_names(item: dict) -> list[str]:
    names = []
    for key in ("en_cleaned_name", "en_name"):
        name = item.get(key)
        if name and name not in names:
            names.append(name)
    return names


def metadata_names(item: dict) -> list[str]:
    names = []
    for key in ("name", "rom_name"):
        name = item.get(key)
        if name:
            name = game_name_from_filename(str(name))
            if name not in names:
                names.append(name)
    return names


def build_metadata_name_index(metadata: list[dict]) -> tuple[list[str], dict[str, dict], dict[str, tuple[str, str, list[str], str]]]:
    candidates = []
    candidate_items = {}
    for item in metadata:
        for candidate in metadata_names(item):
            if candidate not in candidate_items:
                candidates.append(candidate)
                candidate_items[candidate] = item
    return candidates, candidate_items, dict(normalize_remote_name(candidate, no_meta=True) for candidate in candidates)


def find_metadata_by_name(
    metadata: list[dict],
    names: list[str],
    metadata_name_index: tuple[list[str], dict[str, dict], dict[str, tuple[str, str, list[str], str]]] | None = None,
) -> dict | None:
    if metadata_name_index:
        candidates, candidate_items, remote_norms = metadata_name_index
    else:
        candidates, candidate_items, remote_norms = build_metadata_name_index(metadata)

    if not candidates:
        return None

    exact_matches = []
    for name in names:
        for candidate in candidates:
            if normalize_lookup_key(name) == normalize_lookup_key(candidate):
                exact_matches.append(candidate)
    if exact_matches:
        return candidate_items[min(exact_matches, key=len)]

    best_item = None
    best_score = 0.0
    for name in names:
        local_norms = dict([normalize_local_name(name, no_meta=True)])
        scorer = TitleScorer(local_norms, remote_norms)
        candidate_name, score = max(
            ((candidate, scorer(name, candidate)) for candidate in candidates),
            key=lambda item: item[1],
        )
        if score > best_score:
            best_score = score
            best_item = candidate_items[candidate_name]

    return best_item if best_score >= DEF_SCORE else None


def build_crc_metadata_map(metadata: list[dict]) -> dict[str, dict]:
    result = {}
    for item in metadata:
        crc = item.get("crc")
        if crc:
            result[str(crc).upper()] = item
    return result


def file_crc32(path: str | Path) -> str:
    crc = 0
    with Path(path).open("rb") as file:
        while chunk := file.read(READ_CHUNK_SIZE):
            crc = zlib.crc32(chunk, crc)
    return f"{crc & 0xFFFFFFFF:08X}"


def zip_crc32(path: str | Path) -> str:
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            if not info.is_dir():
                return f"{info.CRC & 0xFFFFFFFF:08X}"
    raise ValueError(f"Zip has no file: {path}")


def game_crc32(path: str | Path) -> str:
    path = Path(path)
    if path.suffix.lower() == ".zip":
        return zip_crc32(path)
    return file_crc32(path)


def find_game_by_crc(
    crc: str,
    system: str,
    metadata_dir: str | Path = METADATA_JSON_DIR,
) -> dict | None:
    metadata = load_system_metadata_json(system, metadata_dir)
    return build_crc_metadata_map(metadata).get(crc.upper())


def find_media_by_crc(
    crc: str,
    system: str,
    metadata_dir: str | Path = METADATA_JSON_DIR,
    json_dir: str | Path = THUMBNAIL_JSON_DIR,
    *,
    min_score: int = DEF_SCORE,
    limit: int = 5,
    no_meta: bool = False,
    hack: bool = False,
    before: str | None = None,
) -> GameMedia | None:
    metadata = find_game_by_crc(crc, system, metadata_dir)
    if not metadata:
        return None

    name = metadata.get("name") or game_name_from_filename(metadata.get("rom_name") or "")
    media = find_in_json(
        name,
        system,
        json_dir,
        min_score=min_score,
        limit=limit,
        no_meta=no_meta,
        hack=hack,
        before=before,
    )
    return GameMedia(path=Path(), crc=crc.upper(), name=name, metadata=metadata, media=media, match_source="crc")


def find_game_media_from_indexes(
    path: str | Path,
    system: str,
    system_metadata: list[dict],
    metadata_map: dict[str, dict],
    thumbnail_index: dict[str, dict[str, str]],
    merged_games: dict,
    thumbnail_match_index: tuple[list[str], dict[str, tuple[str, str, list[str], str]]] | None = None,
    metadata_name_index: tuple[list[str], dict[str, dict], dict[str, tuple[str, str, list[str], str]]] | None = None,
    merged_game_index: tuple[list[str], dict[str, dict], dict[str, tuple[str, str, list[str], str]]] | None = None,
    *,
    min_score: int = DEF_SCORE,
    limit: int = 5,
    no_meta: bool = False,
    hack: bool = False,
    before: str | None = None,
) -> GameMedia:
    path = Path(path)
    crc = game_crc32(path)
    metadata = metadata_map.get(crc)
    name = None
    media = []
    match_source = "crc" if metadata else "none"

    thumbnail_match_index = thumbnail_match_index or build_thumbnail_match_index(thumbnail_index, no_meta=no_meta, hack=hack)

    if metadata:
        name = metadata.get("name") or game_name_from_filename(metadata.get("rom_name") or "")
        media = find_best_thumbnails_from_index(
            name,
            thumbnail_index,
            thumbnail_match_index,
            min_score=min_score,
            limit=limit,
            no_meta=no_meta,
            hack=hack,
            before=before,
        )
    else:
        merged_game = find_merged_game_by_name(path.name, system, merged_games=merged_games, merged_game_index=merged_game_index)
        if merged_game:
            candidate_names = merged_game_media_names(merged_game)
            metadata = find_metadata_by_name(system_metadata, candidate_names, metadata_name_index)
            if metadata:
                name = metadata.get("name") or game_name_from_filename(metadata.get("rom_name") or "")
                match_source = "name"
            elif candidate_names:
                name = candidate_names[0]
                match_source = "name"

            for candidate_name in candidate_names:
                candidate_media = find_best_thumbnails_from_index(
                    candidate_name,
                    thumbnail_index,
                    thumbnail_match_index,
                    min_score=min_score,
                    limit=limit,
                    no_meta=no_meta,
                    hack=hack,
                    before=before,
                )
                if candidate_media:
                    media = candidate_media
                    break

    return GameMedia(path=path, crc=crc, name=name, metadata=metadata, media=media, match_source=match_source)


def find_game_media(
    path: str | Path,
    system: str | None = None,
    metadata_dir: str | Path = METADATA_JSON_DIR,
    json_dir: str | Path = THUMBNAIL_JSON_DIR,
    *,
    min_score: int = DEF_SCORE,
    limit: int = 5,
    no_meta: bool = False,
    hack: bool = False,
    before: str | None = None,
) -> GameMedia:
    system = system or infer_system_from_game_path(path)
    system_metadata = load_system_metadata_json(system, metadata_dir)
    return find_game_media_from_indexes(
        path,
        system,
        system_metadata,
        build_crc_metadata_map(system_metadata),
        load_system_thumbnails_json(system, json_dir),
        load_merged_games_json(),
        None,
        None,
        None,
        min_score=min_score,
        limit=limit,
        no_meta=no_meta,
        hack=hack,
        before=before,
    )


def scan_game_media_chunk(args) -> list[GameMedia]:
    (
        paths,
        system,
        system_metadata,
        metadata_map,
        thumbnail_index,
        merged_games,
        min_score,
        limit,
        no_meta,
        hack,
        before,
    ) = args
    metadata_name_index = build_metadata_name_index(system_metadata)
    merged_game_index = build_merged_game_name_index(merged_games, system)
    thumbnail_match_index = build_thumbnail_match_index(thumbnail_index, no_meta=no_meta, hack=hack)
    return [
        find_game_media_from_indexes(
            path,
            system,
            system_metadata,
            metadata_map,
            thumbnail_index,
            merged_games,
            thumbnail_match_index,
            metadata_name_index,
            merged_game_index,
            min_score=min_score,
            limit=limit,
            no_meta=no_meta,
            hack=hack,
            before=before,
        )
        for path in paths
    ]


def scan_game_media(
    directory: str | Path,
    system: str | None = None,
    metadata_dir: str | Path = METADATA_JSON_DIR,
    json_dir: str | Path = THUMBNAIL_JSON_DIR,
    *,
    recursive: bool = True,
    extensions: set[str] | None = None,
    min_score: int = DEF_SCORE,
    limit: int = 5,
    no_meta: bool = False,
    hack: bool = False,
    before: str | None = None,
    workers: int = 1,
) -> list[GameMedia]:
    directory = Path(directory)
    system = system or infer_system_from_game_path(directory)
    files = directory.rglob("*") if recursive else directory.glob("*")
    allowed_extensions = {ext.lower() for ext in extensions} if extensions else None
    paths = [
        path
        for path in files
        if path.is_file() and (not allowed_extensions or path.suffix.lower() in allowed_extensions)
    ]

    system_metadata = load_system_metadata_json(system, metadata_dir)
    metadata_map = build_crc_metadata_map(system_metadata)
    thumbnail_index = load_system_thumbnails_json(system, json_dir)
    merged_games = load_merged_games_json()

    workers = max(1, min(workers, len(paths) or 1))
    if workers <= 1:
        return scan_game_media_chunk((
            paths,
            system,
            system_metadata,
            metadata_map,
            thumbnail_index,
            merged_games,
            min_score,
            limit,
            no_meta,
            hack,
            before,
        ))

    chunk_size = (len(paths) + workers - 1) // workers
    chunks = [paths[index : index + chunk_size] for index in range(0, len(paths), chunk_size)]
    args = [
        (
            chunk,
            system,
            system_metadata,
            metadata_map,
            thumbnail_index,
            merged_games,
            min_score,
            limit,
            no_meta,
            hack,
            before,
        )
        for chunk in chunks
    ]

    results = []
    with ProcessPoolExecutor(max_workers=workers) as executor:
        for chunk_results in executor.map(scan_game_media_chunk, args):
            results.extend(chunk_results)
    return results


def find_in_json(
    filename: str,
    system: str,
    json_dir: str | Path = THUMBNAIL_JSON_DIR,
    *,
    min_score: int = DEF_SCORE,
    limit: int = 5,
    no_meta: bool = False,
    hack: bool = False,
    before: str | None = None,
) -> list[Match]:
    thumbnail_index = load_system_thumbnails_json(system, json_dir)
    return find_best_thumbnails(
        filename,
        thumbnail_index,
        min_score=min_score,
        limit=limit,
        no_meta=no_meta,
        hack=hack,
        before=before,
    )


def find_or_build_json(
    filename: str,
    system: str,
    json_dir: str | Path = THUMBNAIL_JSON_DIR,
    *,
    address: str = ADDRESS,
    min_score: int = DEF_SCORE,
    limit: int = 5,
    no_meta: bool = False,
    hack: bool = False,
    before: str | None = None,
) -> list[Match]:
    path = system_json_path(system, json_dir)
    if not path.exists():
        build_system_thumbnails_json(system, json_dir, address=address)

    thumbnail_index = load_system_thumbnails_json(system, json_dir)
    if not thumbnail_index:
        build_system_thumbnails_json(system, json_dir, address=address)
        thumbnail_index = load_system_thumbnails_json(system, json_dir)

    return find_best_thumbnails(
        filename,
        thumbnail_index,
        min_score=min_score,
        limit=limit,
        no_meta=no_meta,
        hack=hack,
        before=before,
    )


def build_remote_names(thumbnail_index: dict[str, dict[str, str]]) -> set[str]:
    remote_names = set()
    for images in thumbnail_index.values():
        remote_names.update(images.keys())
    return remote_names


def build_thumbnail_match_index(
    thumbnail_index: dict[str, dict[str, str]],
    *,
    no_meta: bool = False,
    hack: bool = False,
) -> tuple[list[str], dict[str, tuple[str, str, list[str], str]]]:
    remote_names = list(build_remote_names(thumbnail_index))
    remote_norms = dict(normalize_remote_name(name, no_meta=no_meta, hack=hack) for name in remote_names)
    return remote_names, remote_norms


def game_name_from_filename(filename: str) -> str:
    path = Path(filename)
    if path.suffix and re.fullmatch(r"\.[A-Za-z0-9]{1,7}", path.suffix):
        return path.stem
    return filename


def find_best_thumbnails_from_index(
    filename: str,
    thumbnail_index: dict[str, dict[str, str]],
    thumbnail_match_index: tuple[list[str], dict[str, tuple[str, str, list[str], str]]],
    *,
    min_score: int = DEF_SCORE,
    limit: int = 5,
    no_meta: bool = False,
    hack: bool = False,
    before: str | None = None,
) -> list[Match]:
    game_name = game_name_from_filename(filename)
    remote_names, remote_norms = thumbnail_match_index
    if not remote_names:
        return []

    local_norms = dict([normalize_local_name(game_name, no_meta=no_meta, hack=hack, before=before)])
    scorer = TitleScorer(local_norms, remote_norms, hack=hack)

    scored = sorted(
        ((remote_name, scorer(game_name, remote_name)) for remote_name in remote_names),
        key=lambda item: item[1],
        reverse=True,
    )[:limit]

    matches = []
    for remote_name, score in scored:
        if score < min_score:
            continue
        urls = {
            thumb_type: images[remote_name]
            for thumb_type, images in thumbnail_index.items()
            if remote_name in images
        }
        matches.append(Match(name=remote_name, score=score, urls=urls))
    return matches


def find_best_thumbnails(
    filename: str,
    thumbnail_index: dict[str, dict[str, str]],
    *,
    min_score: int = DEF_SCORE,
    limit: int = 5,
    no_meta: bool = False,
    hack: bool = False,
    before: str | None = None,
) -> list[Match]:
    return find_best_thumbnails_from_index(
        filename,
        thumbnail_index,
        build_thumbnail_match_index(thumbnail_index, no_meta=no_meta, hack=hack),
        min_score=min_score,
        limit=limit,
        no_meta=no_meta,
        hack=hack,
        before=before,
    )


def find_image_for_filename(
    filename: str,
    system: str,
    *,
    address: str = ADDRESS,
    min_score: int = DEF_SCORE,
    limit: int = 5,
    no_meta: bool = False,
    hack: bool = False,
    before: str | None = None,
) -> list[Match]:
    thumbnail_index = scan_thumbnail_directory(system, address=address)
    return find_best_thumbnails(
        filename,
        thumbnail_index,
        min_score=min_score,
        limit=limit,
        no_meta=no_meta,
        hack=hack,
        before=before,
    )


class ThumbnailMatcher:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._thumbnail_cache = {}
        self._metadata_cache = {}
        self._merged_games = None
        self._thumbnail_match_index_cache = {}
        self._metadata_name_index_cache = {}
        self._merged_game_index_cache = {}
        self._initialized = True

    @classmethod
    def instance(cls) -> "ThumbnailMatcher":
        return cls()

    def load_thumbnails(self, system: str, json_dir: str | Path = THUMBNAIL_JSON_DIR) -> dict[str, dict[str, str]]:
        key = (system, Path(json_dir))
        if key not in self._thumbnail_cache:
            self._thumbnail_cache[key] = load_system_thumbnails_json(system, json_dir)
        return self._thumbnail_cache[key]

    def load_metadata(self, system: str, metadata_dir: str | Path = METADATA_JSON_DIR) -> list[dict]:
        key = (system, Path(metadata_dir))
        if key not in self._metadata_cache:
            self._metadata_cache[key] = load_system_metadata_json(system, metadata_dir)
        return self._metadata_cache[key]

    def load_merged_games(self) -> dict:
        if self._merged_games is None:
            self._merged_games = load_merged_games_json()
        return self._merged_games

    def thumbnail_match_index(self, system: str, json_dir: str | Path = THUMBNAIL_JSON_DIR, *, no_meta: bool = False, hack: bool = False):
        key = (system, Path(json_dir), no_meta, hack)
        if key not in self._thumbnail_match_index_cache:
            self._thumbnail_match_index_cache[key] = build_thumbnail_match_index(
                self.load_thumbnails(system, json_dir),
                no_meta=no_meta,
                hack=hack,
            )
        return self._thumbnail_match_index_cache[key]

    def metadata_name_index(self, system: str, metadata_dir: str | Path = METADATA_JSON_DIR):
        key = (system, Path(metadata_dir))
        if key not in self._metadata_name_index_cache:
            self._metadata_name_index_cache[key] = build_metadata_name_index(self.load_metadata(system, metadata_dir))
        return self._metadata_name_index_cache[key]

    def merged_game_index(self, system: str):
        if system not in self._merged_game_index_cache:
            self._merged_game_index_cache[system] = build_merged_game_name_index(self.load_merged_games(), system)
        return self._merged_game_index_cache[system]

    def build_system_thumbnails_json(self, system: str, json_dir: str | Path = THUMBNAIL_JSON_DIR, *, address: str = ADDRESS, thumb_dirs: list[str] | None = None):
        result = build_system_thumbnails_json(system, json_dir, address=address, thumb_dirs=thumb_dirs)
        self._thumbnail_cache[(system, Path(json_dir))] = result
        self._thumbnail_match_index_cache = {
            key: value for key, value in self._thumbnail_match_index_cache.items() if key[0] != system or key[1] != Path(json_dir)
        }
        return result

    def build_all_json(self, json_dir: str | Path = THUMBNAIL_JSON_DIR, *, address: str = ADDRESS, thumb_dirs: list[str] | None = None, skip_existing: bool = True):
        return build_all_json(json_dir, address=address, thumb_dirs=thumb_dirs, skip_existing=skip_existing)

    def find_in_json(self, filename: str, system: str, json_dir: str | Path = THUMBNAIL_JSON_DIR, *, min_score: int = DEF_SCORE, limit: int = 5, no_meta: bool = False, hack: bool = False, before: str | None = None) -> list[Match]:
        return find_best_thumbnails_from_index(
            filename,
            self.load_thumbnails(system, json_dir),
            self.thumbnail_match_index(system, json_dir, no_meta=no_meta, hack=hack),
            min_score=min_score,
            limit=limit,
            no_meta=no_meta,
            hack=hack,
            before=before,
        )

    def find_or_build_json(self, filename: str, system: str, json_dir: str | Path = THUMBNAIL_JSON_DIR, *, address: str = ADDRESS, min_score: int = DEF_SCORE, limit: int = 5, no_meta: bool = False, hack: bool = False, before: str | None = None) -> list[Match]:
        path = system_json_path(system, json_dir)
        if not path.exists():
            self.build_system_thumbnails_json(system, json_dir, address=address)
        thumbnail_index = self.load_thumbnails(system, json_dir)
        if not thumbnail_index:
            thumbnail_index = self.build_system_thumbnails_json(system, json_dir, address=address)
        return find_best_thumbnails_from_index(
            filename,
            thumbnail_index,
            self.thumbnail_match_index(system, json_dir, no_meta=no_meta, hack=hack),
            min_score=min_score,
            limit=limit,
            no_meta=no_meta,
            hack=hack,
            before=before,
        )

    def find_game_media(self, path: str | Path, system: str | None = None, metadata_dir: str | Path = METADATA_JSON_DIR, json_dir: str | Path = THUMBNAIL_JSON_DIR, *, min_score: int = DEF_SCORE, limit: int = 5, no_meta: bool = False, hack: bool = False, before: str | None = None) -> GameMedia:
        system = system or infer_system_from_game_path(path)
        metadata = self.load_metadata(system, metadata_dir)
        return find_game_media_from_indexes(
            path,
            system,
            metadata,
            build_crc_metadata_map(metadata),
            self.load_thumbnails(system, json_dir),
            self.load_merged_games(),
            self.thumbnail_match_index(system, json_dir, no_meta=no_meta, hack=hack),
            self.metadata_name_index(system, metadata_dir),
            self.merged_game_index(system),
            min_score=min_score,
            limit=limit,
            no_meta=no_meta,
            hack=hack,
            before=before,
        )

    def scan_game_media(self, directory: str | Path, system: str | None = None, metadata_dir: str | Path = METADATA_JSON_DIR, json_dir: str | Path = THUMBNAIL_JSON_DIR, *, recursive: bool = True, extensions: set[str] | None = None, min_score: int = DEF_SCORE, limit: int = 5, no_meta: bool = False, hack: bool = False, before: str | None = None, workers: int = 1) -> list[GameMedia]:
        return scan_game_media(
            directory,
            system,
            metadata_dir,
            json_dir,
            recursive=recursive,
            extensions=extensions,
            min_score=min_score,
            limit=limit,
            no_meta=no_meta,
            hack=hack,
            before=before,
            workers=workers,
        )


matcher = ThumbnailMatcher.instance()


def run_example1():
    FILENAME = "Super Mario Bros. 3"
    SYSTEM = "Nintendo - Nintendo Entertainment System"
    if BUILD_ALL_PLATFORM_JSON:
        systems = matcher.build_all_json(
            THUMBNAIL_JSON_DIR,
            address=ADDRESS,
            skip_existing=SKIP_EXISTING_PLATFORM_JSON,
        )
        print(f"Checked {len(systems)} platform JSON files in {THUMBNAIL_JSON_DIR}")

    if BUILD_JSON_IF_SYSTEM_MISSING:
        matches = matcher.find_or_build_json(
            FILENAME,
            SYSTEM,
            THUMBNAIL_JSON_DIR,
            address=ADDRESS,
            min_score=MIN_SCORE,
            limit=LIMIT,
            no_meta=NO_META,
            hack=HACK,
            before=BEFORE,
        )
    else:
        matches = matcher.find_in_json(
            FILENAME,
            SYSTEM,
            THUMBNAIL_JSON_DIR,
            min_score=MIN_SCORE,
            limit=LIMIT,
            no_meta=NO_META,
            hack=HACK,
            before=BEFORE,
        )

    if not matches:
        print("No match found")
        return

    for match in matches:
        print(f"{match.score:.1f} {match.name}")
        for thumb_type, url in match.urls.items():
            print(f"  {thumb_type}: {url}")


def run_example2():
    rom_path = Path(r"F:\Roms\gbc")

    if rom_path.is_file():
        results = [
            matcher.find_game_media(
                rom_path,
                limit=1,
                no_meta=True,
            )
        ]
    else:
        results = matcher.scan_game_media(
            rom_path,
            extensions={".gbc", ".zip"},
            limit=1,
            no_meta=True,
            workers=SCAN_WORKERS,
        )

    def print_matched_item(item: GameMedia):
        print(f"file: {item.path}")
        print(f"crc: {item.crc}")
        print(f"match_source: {item.match_source}")
        print(f"game: {item.name or '未匹配到 metadata'}")
        if item.metadata:
            print("metadata:")
            print(json.dumps(item.metadata, ensure_ascii=False, indent=2))
        for match in item.media:
            print(f"media: {match.name} ({match.score:.1f})")
            for thumb_type, url in match.urls.items():
                print(f"  {thumb_type}: {url}")
        print()

    crc_matched = []
    name_matched = []
    unmatched = []
    for item in results:
        if not item.media:
            unmatched.append(item)
        elif item.match_source == "crc":
            crc_matched.append(item)
        else:
            name_matched.append(item)

    for item in crc_matched:
        print_matched_item(item)

    if name_matched:
        print("非 CRC 匹配到的文件:")
        for item in name_matched:
            print_matched_item(item)

    if unmatched:
        print("未匹配到的文件:")
        for item in unmatched:
            print(f"file: {item.path}")
            print(f"crc: {item.crc}")
            print(f"match_source: {item.match_source}")
            print(f"game: {item.name or '未匹配到 metadata'}")
            print()


def main():
    run_example2()


if __name__ == "__main__":
    main()
