from __future__ import annotations

import argparse
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from pathlib import Path
from urllib.parse import unquote, urlparse

import requests

from . import thumbnail_matcher as tm

DEFAULT_THUMB_TYPE = "Named_Boxarts"
DEFAULT_EXTENSIONS = {
    ".7z",
    ".bin",
    ".chd",
    ".cue",
    ".gb",
    ".gba",
    ".gbc",
    ".gen",
    ".iso",
    ".md",
    ".nes",
    ".n64",
    ".sfc",
    ".smc",
    ".zip",
}

# User-friendly type aliases → Libretro Named_XXX
TYPE_ALIASES: dict[str, str] = {
    "boxarts": "Named_Boxarts",
    "covers": "Named_Boxarts",
    "logos": "Named_Logos",
    "titles": "Named_Titles",
    "snaps": "Named_Snaps",
    "screenshots": "Named_Snaps",
}

# Libretro Named_XXX → short directory name (for template variable {type_dir})
TYPE_DIR_NAMES: dict[str, str] = {
    "Named_Boxarts": "Boxarts",
    "Named_Logos": "Logos",
    "Named_Titles": "Titles",
    "Named_Snaps": "Snaps",
}

# Libretro Named_XXX → short file stem (for template variable {type_alias})
TYPE_ALIAS_NAMES: dict[str, str] = {
    "Named_Boxarts": "boxfront",
    "Named_Logos": "logo",
    "Named_Titles": "title",
    "Named_Snaps": "snap",
}

# Rule JSON file paths
PRESETS_JSON = Path(__file__).parent / "presets.json"
USER_RULES_JSON = Path(__file__).parent / "user_rules.json"


def load_rules_json(path: Path) -> dict[str, dict]:
    """Load rules from a JSON file, returning empty dict if not found."""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def all_preset_names() -> list[str]:
    """Return merged list of built-in + user preset names."""
    builtin = load_rules_json(PRESETS_JSON)
    user = load_rules_json(USER_RULES_JSON)
    return list(dict.fromkeys([*builtin, *user]))


def find_preset(name: str) -> dict | None:
    """Look up a preset by name: user rules take priority over built-in."""
    user = load_rules_json(USER_RULES_JSON)
    if name in user:
        return user[name]
    builtin = load_rules_json(PRESETS_JSON)
    return builtin.get(name)


def save_user_rule(name: str, rule: dict[str, dict[str, str]], *, filename: str = "game", desc: str = "") -> None:
    """Save a rule to user_rules.json."""
    user_rules = load_rules_json(USER_RULES_JSON)
    user_rules[name] = {
        "rule": rule,
        "filename": filename,
        "desc": desc or f"User rule: {name}",
    }
    USER_RULES_JSON.write_text(json.dumps(user_rules, ensure_ascii=False, indent=2), encoding="utf-8")


def safe_filename(name: str) -> str:
    name = re.sub(tm.forbidden, "_", name).strip(" .")
    return name or "unknown"


def json_default(value):
    if isinstance(value, Path):
        return str(value)
    return value


def print_json(payload: dict, exit_code: int = 0) -> int:
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=json_default))
    return exit_code


def write_report(payload: dict, report_path: str | None) -> None:
    if not report_path:
        return
    path = Path(report_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=json_default), encoding="utf-8")


def print_event(event: str, **payload) -> None:
    print(json.dumps({"event": event, **payload}, ensure_ascii=False, default=json_default), flush=True)


def parse_extensions(value: str | None) -> set[str] | None:
    if not value:
        return None
    extensions = set()
    for item in value.split(","):
        item = item.strip().lower()
        if not item:
            continue
        extensions.add(item if item.startswith(".") else f".{item}")
    return extensions or None


def resolve_type_alias(raw: str) -> str:
    """Resolve a user-friendly alias or pass through a Named_XXX string."""
    key = raw.strip().lower()
    if key in TYPE_ALIASES:
        return TYPE_ALIASES[key]
    if raw.startswith("Named_"):
        return raw
    return raw


def parse_types(value: str | None) -> list[str]:
    """Parse --type value into a list of Named_XXX strings."""
    if not value:
        return [DEFAULT_THUMB_TYPE]
    value = value.strip().lower()
    if value == "all":
        return list(tm.THUMB_DIRS)
    result = []
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        result.append(resolve_type_alias(part))
    return result or [DEFAULT_THUMB_TYPE]


def default_save_rule(thumb_types: list[str], output: Path) -> dict[str, dict[str, str]]:
    """Generate a default save rule based on the number of thumb types.

    Single type: files go directly into output dir, named by game.
    Multiple types: each type gets a subdirectory named after the type.
    """
    rule: dict[str, dict[str, str]] = {}
    if len(thumb_types) == 1:
        t = thumb_types[0]
        rule[t] = {"dir": str(output), "name": "{game}"}
    else:
        for t in thumb_types:
            rule[t] = {"dir": f"{{output}}/{TYPE_DIR_NAMES.get(t, t)}", "name": "{game}"}
    return rule


def parse_save_rule(
    value: str | None,
    thumb_types: list[str],
    output: Path,
    preset: str | None = None,
) -> dict[str, dict[str, str]]:
    """Parse --save-rule value.

    Accepts:
    - None + no preset: use default_save_rule()
    - Preset name via --preset: use PRESET_RULES[preset]
    - JSON string: {"Named_Boxarts": {"dir": "...", "name": "..."}}
    - @path: read JSON from file

    --save-rule takes priority over --preset.
    """
    if not value and not preset:
        return default_save_rule(thumb_types, output)

    # --save-rule takes priority over --preset
    if value:
        raw = value.strip()
        if raw.startswith("@"):
            path = Path(raw[1:])
            raw = path.read_text(encoding="utf-8")

        rule = json.loads(raw)

        # Validate: each key should map to {"dir": ..., "name": ...}
        for key, val in rule.items():
            if not isinstance(val, dict) or "dir" not in val or "name" not in val:
                raise ValueError(f"Invalid save rule entry: {key} -> {val}. Expected {{'dir': '...', 'name': '...'}}")

        return rule

    # --preset
    p = find_preset(preset)
    if not p:
        available = ", ".join(all_preset_names())
        raise ValueError(f"Unknown preset '{preset}'. Available: {available}")
    rule = dict(p["rule"])
    # Only include types the user actually requested
    if thumb_types:
        filtered = {t: rule[t] for t in thumb_types if t in rule}
        if filtered:
            rule = filtered
    return rule


def render_save_path(
    rule_entry: dict[str, str],
    *,
    output: str,
    game: str,
    rom: str,
    thumb_type: str,
    suffix: str,
) -> Path:
    """Render a save rule entry into a concrete file path.

    Template variables:
    - {output}: --output value
    - {game}: safe game name (from match or ROM filename)
    - {rom}: safe ROM filename stem
    - {type_dir}: short directory name (Boxarts, Logos, etc.)
    - {type_alias}: short file stem (boxfront, logo, etc.)
    """
    dir_template = rule_entry["dir"]
    name_template = rule_entry["name"]

    type_dir = TYPE_DIR_NAMES.get(thumb_type, thumb_type)
    type_alias = TYPE_ALIAS_NAMES.get(thumb_type, thumb_type)

    variables = {
        "output": output,
        "game": safe_filename(game),
        "rom": safe_filename(rom),
        "type_dir": type_dir,
        "type_alias": type_alias,
    }

    dir_str = dir_template.format(**variables)
    name_str = name_template.format(**variables)

    return Path(dir_str) / f"{name_str}{suffix}"


def image_suffix(url: str) -> str:
    suffix = Path(unquote(urlparse(url).path)).suffix.lower()
    return suffix if suffix else ".png"


def ensure_thumbnail_json(system: str, json_dir: str | Path, address: str) -> None:
    if not tm.system_json_path(system, json_dir).exists():
        tm.matcher.build_system_thumbnails_json(system, json_dir, address=address)


def pick_match_url(match: tm.Match, thumb_type: str, *, fallback: bool = True) -> tuple[str | None, str | None]:
    if thumb_type in match.urls:
        return thumb_type, match.urls[thumb_type]
    if fallback and match.urls:
        first_type = next(iter(match.urls))
        return first_type, match.urls[first_type]
    return None, None


def find_type_url(
    game_name: str,
    thumb_type: str,
    thumbnail_index: dict[str, dict[str, str]],
    *,
    min_score: int = 50,
    no_meta: bool = False,
    hack: bool = False,
    before: str | None = None,
) -> tuple[str | None, str | None]:
    """Find best URL for a specific thumb_type, building a type-specific match index."""
    type_images = thumbnail_index.get(thumb_type)
    if not type_images:
        return None, None
    # Build match index only for this type
    type_index = {thumb_type: type_images}
    match_index = tm.build_thumbnail_match_index(type_index, no_meta=no_meta, hack=hack)
    matches = tm.find_best_thumbnails_from_index(
        game_name, type_index, match_index,
        min_score=min_score, limit=1, no_meta=no_meta, hack=hack, before=before,
    )
    if matches:
        return thumb_type, matches[0].urls.get(thumb_type)
    return None, None


def download_url(url: str, output_path: Path, *, retries: int = 2, retry_delay: float = 1.0) -> int:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    last_error = None
    for attempt in range(retries + 1):
        try:
            response = requests.get(
                url,
                headers={"User-Agent": "tiny-scraper-cover-cli/1.0"},
                timeout=tm.REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            output_path.write_bytes(response.content)
            return attempt + 1
        except Exception as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(retry_delay)
    raise last_error


def match_to_dict(match: tm.Match | None) -> dict | None:
    if not match:
        return None
    return asdict(match)


def output_base_name(item: tm.GameMedia, match: tm.Match, filename_mode: str) -> str:
    if filename_mode == "rom":
        return item.path.stem
    if filename_mode == "match":
        return match.name
    return item.name or match.name or item.path.stem


def confirm_overwrite(existing_paths: list[str]) -> bool | None:
    if not existing_paths:
        return True
    if not sys.stdin.isatty():
        return None
    answer = input(f"发现 {len(existing_paths)} 个目标文件已存在，是否覆盖？[y/N] ").strip().lower()
    return answer in {"y", "yes"}


def overwrite_required_payload(mode: str, existing_results: list[dict]) -> dict:
    return {
        "ok": False,
        "mode": mode,
        "needs_overwrite_confirmation": True,
        "existing_count": len(existing_results),
        "existing_files": [item["saved_to"] for item in existing_results],
    }


def resolve_save_to(
    thumb_type: str,
    game_name: str,
    rom_stem: str,
    url: str,
    save_rule: dict[str, dict[str, str]],
    output: Path,
) -> Path | None:
    """Resolve the save path for a given thumb type using the save rule."""
    rule_entry = save_rule.get(thumb_type)
    if not rule_entry:
        return None
    return render_save_path(
        rule_entry,
        output=str(output),
        game=game_name,
        rom=rom_stem,
        thumb_type=thumb_type,
        suffix=image_suffix(url),
    )


def download_result(result: dict, *, retries: int, retry_delay: float, existing: str) -> dict:
    if not result["matched"] or not result["cover_url"] or not result["saved_to"]:
        return result
    output_path = Path(result["saved_to"])
    if output_path.exists() and existing == "skip":
        result["skipped"] = True
        result["skip_reason"] = "exists"
        return result
    try:
        result["attempts"] = download_url(
            result["cover_url"],
            output_path,
            retries=retries,
            retry_delay=retry_delay,
        )
        result["downloaded"] = True
    except Exception as exc:
        result["error"] = str(exc)
    return result


def _collect_existing_paths(results_per_type: dict[str, list[dict]]) -> list[str]:
    """Collect all saved_to paths that already exist on disk."""
    paths = []
    for type_results in results_per_type.values():
        for r in type_results:
            if r.get("saved_to") and Path(r["saved_to"]).exists():
                paths.append(r["saved_to"])
    return paths


def download_game(args: argparse.Namespace) -> int:
    tm.SHOW_PROGRESS = False
    output_dir = Path(args.output)
    thumb_types: list[str] = args.types
    save_rule: dict[str, dict[str, str]] = args.save_rule
    ensure_thumbnail_json(args.system, args.json_dir, args.address)
    thumbnail_index = tm.load_system_thumbnails_json(args.system, args.json_dir)
    matches = tm.matcher.find_or_build_json(
        args.name,
        args.system,
        args.json_dir,
        address=args.address,
        min_score=args.min_score,
        limit=args.limit,
        no_meta=args.no_meta,
        hack=args.hack,
        before=args.before,
    )

    match = matches[0] if matches else None
    type_results: list[dict] = []

    if match:
        base_name = args.save_as or match.name
        for thumb_type in thumb_types:
            selected_type, url = pick_match_url(match, thumb_type, fallback=False)
            # If best match doesn't have this type, try other candidates
            if not url and matches:
                for alt_match in matches[1:]:
                    alt_type, alt_url = pick_match_url(alt_match, thumb_type, fallback=False)
                    if alt_url:
                        selected_type, url = alt_type, alt_url
                        break
            # Fallback: search per-type index using game name
            if not url:
                selected_type, url = find_type_url(
                    args.name, thumb_type, thumbnail_index,
                    min_score=args.min_score, no_meta=args.no_meta,
                    hack=args.hack, before=args.before,
                )
            saved_to = None
            downloaded = False
            skipped = False
            skip_reason = None
            attempts = 0
            error = None

            if url:
                saved_to = resolve_save_to(
                    thumb_type, base_name, base_name, url, save_rule, output_dir,
                )

                if not args.dry_run and saved_to:
                    existing = args.existing
                    if existing == "ask" and saved_to.exists():
                        if not sys.stdin.isatty():
                            type_results.append({
                                "matched": True, "downloaded": False, "skipped": False,
                                "selected_type": selected_type, "cover_url": url,
                                "saved_to": str(saved_to), "attempts": 0, "error": None,
                                "needs_overwrite": True,
                            })
                            continue
                        confirm = input(f"目标文件已存在：{saved_to}，是否覆盖？[y/N] ").strip().lower()
                        existing = "overwrite" if confirm in {"y", "yes"} else "skip"
                    if existing == "skip" and saved_to.exists():
                        skipped = True
                        skip_reason = "exists"
                    else:
                        try:
                            attempts = download_url(url, saved_to, retries=args.retries, retry_delay=args.retry_delay)
                            downloaded = True
                        except Exception as exc:
                            error = str(exc)

            type_results.append({
                "matched": bool(url),
                "downloaded": downloaded if match else False,
                "skipped": skipped,
                "skip_reason": skip_reason,
                "attempts": attempts,
                "error": error,
                "selected_type": selected_type,
                "cover_url": url,
                "saved_to": str(saved_to) if saved_to else None,
            })
    else:
        for thumb_type in thumb_types:
            type_results.append({
                "matched": False, "downloaded": False, "skipped": False,
                "skip_reason": None, "attempts": 0, "error": None,
                "selected_type": None, "cover_url": None, "saved_to": None,
            })

    matched_any = any(r["matched"] for r in type_results)
    failed_any = any(r["error"] for r in type_results)
    payload = {
        "ok": matched_any and not failed_any,
        "mode": "download-game",
        "dry_run": args.dry_run,
        "system": args.system,
        "name": args.name,
        "save_as": args.save_as,
        "types": thumb_types,
        "save_rule": save_rule,
        "matched": matched_any,
        "downloaded": any(r["downloaded"] for r in type_results),
        "downloaded_count": sum(1 for r in type_results if r["downloaded"]),
        "skipped_count": sum(1 for r in type_results if r.get("skipped")),
        "failed_count": sum(1 for r in type_results if r["error"]),
        "unmatched_count": sum(1 for r in type_results if not r["matched"]),
        "type_results": type_results,
        "match": match_to_dict(match),
        "matches": [match_to_dict(item) for item in matches],
    }
    write_report(payload, args.report)
    exit_code = 0 if matched_any and not failed_any else 2 if not matched_any else 1
    return print_json(payload, exit_code)


def download_file(args: argparse.Namespace) -> int:
    tm.SHOW_PROGRESS = False
    path = Path(args.path)
    system = args.system or tm.infer_system_from_game_path(path)
    output_dir = Path(args.output)
    thumb_types: list[str] = args.types
    save_rule: dict[str, dict[str, str]] = args.save_rule
    ensure_thumbnail_json(system, args.json_dir, args.address)
    thumbnail_index = tm.load_system_thumbnails_json(system, args.json_dir)
    item = tm.matcher.find_game_media(
        path,
        system=system,
        metadata_dir=args.metadata_dir,
        json_dir=args.json_dir,
        min_score=args.min_score,
        limit=args.limit,
        no_meta=args.no_meta,
        hack=args.hack,
        before=args.before,
    )

    match = item.media[0] if item.media else None
    type_results: list[dict] = []

    for thumb_type in thumb_types:
        if match:
            selected_type, url = pick_match_url(match, thumb_type, fallback=False)
            # If best match doesn't have this type, try other candidates
            if not url and item.media:
                for alt_match in item.media[1:]:
                    alt_type, alt_url = pick_match_url(alt_match, thumb_type, fallback=False)
                    if alt_url:
                        selected_type, url = alt_type, alt_url
                        break
            # Fallback: search per-type index using matched game name
            if not url and item.name:
                selected_type, url = find_type_url(
                    item.name, thumb_type, thumbnail_index,
                    min_score=args.min_score, no_meta=args.no_meta,
                    hack=args.hack, before=args.before,
                )
            base_name = output_base_name(item, match, args.filename)
            if url:
                saved_to = resolve_save_to(
                    thumb_type, base_name, item.path.stem, url, save_rule, output_dir,
                )
            else:
                saved_to = None
                selected_type = None
        else:
            url = None
            selected_type = None
            saved_to = None

        result = {
            "file": str(item.path),
            "crc": item.crc,
            "game": item.name,
            "match_source": item.match_source,
            "matched": bool(url),
            "downloaded": False,
            "skipped": False,
            "skip_reason": None,
            "attempts": 0,
            "error": None,
            "selected_type": selected_type,
            "cover_url": url,
            "saved_to": str(saved_to) if saved_to else None,
        }

        if not args.dry_run and result["matched"] and result["saved_to"]:
            output_path = Path(result["saved_to"])
            existing = args.existing
            if existing == "ask" and output_path.exists():
                if not sys.stdin.isatty():
                    result["needs_overwrite"] = True
                    type_results.append(result)
                    continue
                confirm = input(f"目标文件已存在：{output_path}，是否覆盖？[y/N] ").strip().lower()
                existing = "overwrite" if confirm in {"y", "yes"} else "skip"
            result = download_result(result, retries=args.retries, retry_delay=args.retry_delay, existing=existing)

        type_results.append(result)

    matched_any = any(r["matched"] for r in type_results)
    payload = {
        "ok": matched_any,
        "mode": "download-file",
        "dry_run": args.dry_run,
        "system": system,
        "output": str(output_dir),
        "types": thumb_types,
        "save_rule": save_rule,
        "type_results": type_results,
    }
    write_report(payload, args.report)
    return print_json(payload, 0 if matched_any else 2)


def download_folder(args: argparse.Namespace) -> int:
    tm.SHOW_PROGRESS = False
    directory = Path(args.path)
    system = args.system or tm.infer_system_from_game_path(directory)
    output_dir = Path(args.output)
    extensions = parse_extensions(args.extensions) or DEFAULT_EXTENSIONS
    thumb_types: list[str] = args.types
    save_rule: dict[str, dict[str, str]] = args.save_rule
    ensure_thumbnail_json(system, args.json_dir, args.address)
    # Pre-load thumbnail index for per-type fallback matching
    thumbnail_index = tm.load_system_thumbnails_json(system, args.json_dir)
    items = tm.matcher.scan_game_media(
        directory,
        system=system,
        metadata_dir=args.metadata_dir,
        json_dir=args.json_dir,
        recursive=not args.no_recursive,
        extensions=extensions,
        min_score=args.min_score,
        limit=args.limit,
        no_meta=args.no_meta,
        hack=args.hack,
        before=args.before,
        workers=args.workers,
    )

    # Build results per type
    all_results: list[dict] = []
    for item in items:
        match = item.media[0] if item.media else None
        if match:
            base_name = output_base_name(item, match, args.filename)
        else:
            base_name = item.path.stem

        for thumb_type in thumb_types:
            if match:
                selected_type, url = pick_match_url(match, thumb_type, fallback=False)
                # If best match doesn't have this type, try other candidates
                if not url and item.media:
                    for alt_match in item.media[1:]:
                        alt_type, alt_url = pick_match_url(alt_match, thumb_type, fallback=False)
                        if alt_url:
                            selected_type, url = alt_type, alt_url
                            break
                # Fallback: search per-type index using matched game name
                if not url and item.name:
                    selected_type, url = find_type_url(
                        item.name, thumb_type, thumbnail_index,
                        min_score=args.min_score, no_meta=args.no_meta,
                        hack=args.hack, before=args.before,
                    )
            else:
                selected_type, url = None, None

            saved_to = None
            if url:
                saved_to = resolve_save_to(
                    thumb_type, base_name, item.path.stem, url, save_rule, output_dir,
                )

            all_results.append({
                "file": str(item.path),
                "crc": item.crc,
                "game": item.name,
                "match_source": item.match_source,
                "matched": bool(url),
                "downloaded": False,
                "skipped": False,
                "skip_reason": None,
                "attempts": 0,
                "error": None,
                "selected_type": selected_type,
                "cover_url": url,
                "saved_to": str(saved_to) if saved_to else None,
                "thumb_type": thumb_type,
            })

    matched_indexes = [i for i, r in enumerate(all_results) if r["matched"]]
    unmatched = [r for r in all_results if not r["matched"]]

    if args.progress:
        print_event(
            "scan_done",
            scanned_count=len(items),
            matched_count=len(matched_indexes),
            unmatched_count=len(unmatched),
            types=thumb_types,
        )

    existing = args.existing
    if not args.dry_run and matched_indexes:
        existing_results = [
            all_results[i]
            for i in matched_indexes
            if all_results[i].get("saved_to") and Path(all_results[i]["saved_to"]).exists()
        ]
        if existing == "ask" and existing_results:
            confirm = confirm_overwrite([item["saved_to"] for item in existing_results])
            if confirm is None:
                payload = overwrite_required_payload("download-folder", existing_results)
                payload.update({
                    "system": system,
                    "path": str(directory),
                    "output": str(output_dir),
                    "filename": args.filename,
                    "types": thumb_types,
                })
                write_report(payload, args.report)
                if args.progress:
                    print_event("overwrite_required", **payload)
                    return 3
                return print_json(payload, 3)
            existing = "overwrite" if confirm else "skip"

        total = len(matched_indexes)
        workers = max(1, args.download_workers)
        if workers == 1:
            for current, result_index in enumerate(matched_indexes, start=1):
                if args.progress:
                    print_event("download_start", index=current, total=total, file=all_results[result_index]["file"], thumb_type=all_results[result_index].get("thumb_type"))
                all_results[result_index] = download_result(
                    all_results[result_index],
                    retries=args.retries,
                    retry_delay=args.retry_delay,
                    existing=existing,
                )
                if args.progress:
                    event = "download_done" if all_results[result_index]["downloaded"] else "download_failed"
                    print_event(event, index=current, total=total, **all_results[result_index])
        else:
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = {}
                for current, result_index in enumerate(matched_indexes, start=1):
                    if args.progress:
                        print_event("download_start", index=current, total=total, file=all_results[result_index]["file"], thumb_type=all_results[result_index].get("thumb_type"))
                    futures[executor.submit(
                        download_result,
                        all_results[result_index],
                        retries=args.retries,
                        retry_delay=args.retry_delay,
                        existing=existing,
                    )] = (current, result_index)
                for future in as_completed(futures):
                    current, result_index = futures[future]
                    all_results[result_index] = future.result()
                    if args.progress:
                        event = "download_done" if all_results[result_index]["downloaded"] else "download_failed"
                        print_event(event, index=current, total=total, **all_results[result_index])

    matched = [r for r in all_results if r["matched"]]
    downloaded = [r for r in all_results if r["downloaded"]]
    skipped = [r for r in all_results if r["skipped"]]
    failed = [r for r in all_results if r["error"]]
    unmatched_items = [r for r in all_results if not r["matched"]]

    # Per-type summary
    per_type_summary = {}
    for thumb_type in thumb_types:
        type_items = [r for r in all_results if r.get("thumb_type") == thumb_type]
        per_type_summary[thumb_type] = {
            "matched_count": sum(1 for r in type_items if r["matched"]),
            "downloaded_count": sum(1 for r in type_items if r["downloaded"]),
            "skipped_count": sum(1 for r in type_items if r["skipped"]),
            "failed_count": sum(1 for r in type_items if r["error"]),
            "unmatched_count": sum(1 for r in type_items if not r["matched"]),
        }

    summary = {
        "ok": bool(matched) and not unmatched_items and not failed,
        "mode": "download-folder",
        "dry_run": args.dry_run,
        "system": system,
        "path": str(directory),
        "output": str(output_dir),
        "filename": args.filename,
        "types": thumb_types,
        "save_rule": save_rule,
        "scanned_count": len(items),
        "downloaded_count": 0 if args.dry_run else len(downloaded),
        "skipped_count": len(skipped),
        "matched_count": len(matched),
        "failed_count": len(failed),
        "unmatched_count": len(unmatched_items),
        "per_type": per_type_summary,
        "matched": matched,
        "downloaded": downloaded,
        "skipped": skipped,
        "failed": failed,
        "unmatched": unmatched_items,
        "items": all_results,
    }
    report = {key: value for key, value in summary.items() if key not in {"items", "matched", "downloaded", "skipped"}}
    write_report(report, args.report)
    if args.progress:
        print_event("summary", **{key: value for key, value in summary.items() if key not in {"items", "matched", "downloaded", "skipped", "failed", "unmatched"}})
        return 0 if matched else 2
    return print_json(summary, 0 if matched else 2)


def add_common_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--output", required=True, help="封面保存目录")
    parser.add_argument(
        "--type",
        dest="type_raw",
        default=None,
        help="媒体类型，支持：boxarts/covers, logos, titles, snaps/screenshots。可逗号分隔指定多个（如 boxarts,titles）或 all 下载全部。默认 boxarts",
    )
    parser.add_argument(
        "--save-rule",
        dest="save_rule_raw",
        default=None,
        help=(
            "保存路径规则，JSON 格式或 @文件路径。"
            r'格式：{"Named_Boxarts":{"dir":"{output}/{game}","name":"boxfront"}}。'
            "变量：{output},{game},{rom},{type_dir},{type_alias}"
        ),
    )
    parser.add_argument(
        "--preset",
        default=None,
        help="预置规则名称，内置: pegasus, es-de, retroarch, simple；也支持用户自定义规则",
    )
    parser.add_argument("--min-score", type=int, default=tm.DEF_SCORE, help="最低匹配分")
    parser.add_argument("--limit", type=int, default=1, help="候选数量")
    parser.add_argument(
        "--filename",
        choices=("game", "rom", "match"),
        default="game",
        help="保存文件名来源：game=匹配到的游戏名，rom=ROM 文件名，match=封面库匹配名",
    )
    parser.add_argument("--no-meta", action="store_true", default=True, help="匹配名称时忽略括号元数据")
    parser.add_argument("--keep-meta", action="store_false", dest="no_meta", help="匹配名称时保留括号元数据")
    parser.add_argument("--hack", action="store_true", help="保留方括号 hack 标记参与匹配")
    parser.add_argument("--before", default=None, help="只使用指定分隔符前面的名称")
    parser.add_argument("--address", default=tm.ADDRESS, help="Libretro thumbnails 地址")
    parser.add_argument("--json-dir", default=str(tm.THUMBNAIL_JSON_DIR), help="封面索引 JSON 目录")
    parser.add_argument("--metadata-dir", default=str(tm.METADATA_JSON_DIR), help="metadata JSON 目录")
    parser.add_argument(
        "--existing",
        choices=("ask", "skip", "overwrite"),
        default="ask",
        help="目标文件已存在时的处理方式：ask=询问，skip=跳过，overwrite=覆盖",
    )
    parser.add_argument("--retries", type=int, default=2, help="下载失败后的重试次数")
    parser.add_argument("--retry-delay", type=float, default=1.0, help="每次重试前等待秒数")
    parser.add_argument("--progress", action="store_true", help="输出 JSON Lines 进度事件")
    parser.add_argument("--report", default=None, help="把完整 JSON 结果写入指定报告文件")
    parser.add_argument("--dry-run", action="store_true", help="只输出匹配结果，不下载")


def _post_parse_args(args: argparse.Namespace) -> None:
    """Process parsed args to resolve types and save rule."""
    # Skip for commands that don't use common options
    if args.command in ("save-preset", "list-presets"):
        return
    args.types = parse_types(args.type_raw)
    args.save_rule = parse_save_rule(args.save_rule_raw, args.types, Path(args.output), preset=args.preset)
    # Apply preset's recommended filename if user didn't explicitly change it
    if args.preset and args.filename == "game":
        p = find_preset(args.preset)
        if p:
            preset_filename = p.get("filename")
            if preset_filename:
                args.filename = preset_filename


def cmd_save_preset(args: argparse.Namespace) -> int:
    """Save a custom rule to user_rules.json."""
    raw = args.rule.strip()
    if raw.startswith("@"):
        path = Path(raw[1:])
        raw = path.read_text(encoding="utf-8")
    rule = json.loads(raw)
    # Validate
    for key, val in rule.items():
        if not isinstance(val, dict) or "dir" not in val or "name" not in val:
            raise ValueError(f"Invalid rule entry: {key} -> {val}. Expected {{'dir': '...', 'name': '...'}}")
    save_user_rule(args.name, rule, filename=args.filename, desc=args.desc)
    return print_json({
        "ok": True,
        "action": "save-preset",
        "name": args.name,
        "rule": rule,
        "filename": args.filename,
        "desc": args.desc,
        "path": str(USER_RULES_JSON),
    }, 0)


def cmd_list_presets(args: argparse.Namespace) -> int:
    """List all available presets (built-in + user)."""
    builtin = load_rules_json(PRESETS_JSON)
    user = load_rules_json(USER_RULES_JSON)
    result = []
    for name, info in builtin.items():
        result.append({"name": name, "source": "builtin", "desc": info.get("desc", ""), "filename": info.get("filename", "game"), "rule": info.get("rule", {})})
    for name, info in user.items():
        result.append({"name": name, "source": "user", "desc": info.get("desc", ""), "filename": info.get("filename", "game"), "rule": info.get("rule", {})})
    return print_json({"ok": True, "presets": result}, 0)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="下载游戏封面并输出 JSON 结果")
    subparsers = parser.add_subparsers(dest="command", required=True)

    game_parser = subparsers.add_parser("download-game", help="按游戏名下载封面")
    game_parser.add_argument("--name", required=True, help="游戏名")
    game_parser.add_argument("--system", required=True, help="Libretro 平台名")
    game_parser.add_argument("--save-as", default=None, help="指定保存文件名，不含扩展名")
    add_common_options(game_parser)
    game_parser.set_defaults(func=download_game)

    file_parser = subparsers.add_parser("download-file", help="按单个 ROM 文件下载封面")
    file_parser.add_argument("--path", required=True, help="ROM 文件路径")
    file_parser.add_argument("--system", default=None, help="Libretro 平台名，不填则从路径推断")
    add_common_options(file_parser)
    file_parser.set_defaults(func=download_file)

    folder_parser = subparsers.add_parser("download-folder", help="扫描文件夹并下载封面")
    folder_parser.add_argument("--path", required=True, help="ROM 文件夹路径")
    folder_parser.add_argument("--system", default=None, help="Libretro 平台名，不填则从路径推断")
    folder_parser.add_argument("--extensions", default=None, help="ROM 后缀，逗号分隔，例如 .gbc,.zip")
    folder_parser.add_argument("--no-recursive", action="store_true", help="不递归扫描子目录")
    folder_parser.add_argument("--workers", type=int, default=1, help="扫描进程数")
    folder_parser.add_argument("--download-workers", type=int, default=4, help="封面下载线程数")
    add_common_options(folder_parser)
    folder_parser.set_defaults(func=download_folder)

    save_preset_parser = subparsers.add_parser("save-preset", help="保存自定义规则到用户规则文件")
    save_preset_parser.add_argument("--name", required=True, help="规则名称")
    save_preset_parser.add_argument("--rule", required=True, help="规则 JSON 或 @文件路径")
    save_preset_parser.add_argument("--filename", default="game", choices=("game", "rom", "match"), help="推荐的 --filename 值")
    save_preset_parser.add_argument("--desc", default="", help="规则描述")
    save_preset_parser.set_defaults(func=cmd_save_preset)

    list_presets_parser = subparsers.add_parser("list-presets", help="列出所有可用预置规则")
    list_presets_parser.set_defaults(func=cmd_list_presets)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _post_parse_args(args)
    try:
        return args.func(args)
    except Exception as exc:
        return print_json({"ok": False, "error": str(exc)}, 1)


if __name__ == "__main__":
    sys.exit(main())
