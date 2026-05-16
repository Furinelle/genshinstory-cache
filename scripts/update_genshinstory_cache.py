#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
One-click GI cache refresh workflow for genshinstory-cache.

Default flow:
1. git pull --ff-only
2. ensure minimal Python runtime dependencies and Playwright Chromium
3. refresh GI wiki link files
4. incrementally scrape missing structured JSON
5. rebuild GI parser cache
6. export GI Markdown
7. rebuild GI catalog/search metadata
8. rebuild meme index

All subprocesses run with proxy variables cleared by default, suitable for
domestic direct access to baike.mihoyo.com.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOG_ROOT = PROJECT_ROOT / "logs" / "update_genshinstory_cache"

PROXY_VARS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
)

NO_PROXY_VALUE = ",".join(
    [
        "localhost",
        "127.0.0.1",
        "::1",
        "baike.mihoyo.com",
        "*.mihoyo.com",
        "*.miyoushe.com",
        "*.hoyoverse.com",
        "github.com",
        "*.github.com",
        "pypi.org",
        "files.pythonhosted.org",
        "*.pythonhosted.org",
    ]
)

MINIMAL_DEPS = (
    "beautifulsoup4>=4.12.3",
    "jieba>=0.42.1",
    "msgpack>=1.0.8",
    "playwright>=1.52.0",
    "pydantic>=2.0,<3.0",
)


@dataclass(frozen=True)
class Step:
    name: str
    description: str
    command: tuple[str, ...]


def python_cmd(*args: str) -> tuple[str, ...]:
    return (sys.executable, *args)


STEPS: tuple[Step, ...] = (
    Step("git-pull", "更新仓库代码", ("git", "-c", "http.proxy=", "-c", "https.proxy=", "pull", "--ff-only")),
    Step(
        "deps",
        "安装/更新最小运行依赖",
        python_cmd("-m", "pip", "install", "--disable-pip-version-check", "--no-input", *MINIMAL_DEPS),
    ),
    Step("playwright", "安装/检查 Playwright Chromium", python_cmd("-m", "playwright", "install", "chromium")),
    Step("links", "抓取/更新 GI 百科链接", python_cmd("-m", "gi_wiki_scraper.link_parsers.generate_links")),
    Step("scrape", "增量抓取并解析 GI 页面结构化 JSON", python_cmd("-m", "gi_wiki_scraper.run_all_parsers_incremental")),
    Step("cache", "重建 GI parser cache", python_cmd("scripts/giwiki_create_cache.py")),
    Step("markdown", "导出 GI Markdown", python_cmd("scripts/giwiki_generate_markdown.py")),
    Step("catalog", "重建 GI catalog/search metadata", python_cmd("scripts/generate_all_catalog_trees.py", "gi")),
    Step("meme", "重建表情索引", python_cmd("scripts/generate_meme_index.py")),
)


def make_env(keep_proxy: bool) -> dict[str, str]:
    env = os.environ.copy()
    if not keep_proxy:
        for key in PROXY_VARS:
            env.pop(key, None)
        env["NO_PROXY"] = NO_PROXY_VALUE
        env["no_proxy"] = NO_PROXY_VALUE

    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def format_cmd(command: Iterable[str]) -> str:
    return " ".join(command)


def run_step(step: Step, log_dir: Path, env: dict[str, str], dry_run: bool) -> None:
    log_path = log_dir / f"{step.name}.log"
    print(f"\n=== [{step.name}] {step.description} ===")
    print(f"$ {format_cmd(step.command)}")
    print(f"log: {log_path}")

    if dry_run:
        return

    log_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    with log_path.open("w", encoding="utf-8", newline="") as log_file:
        log_file.write(f"$ {format_cmd(step.command)}\n\n")
        log_file.flush()

        process = subprocess.Popen(
            step.command,
            cwd=PROJECT_ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        assert process.stdout is not None
        for line in process.stdout:
            print(line, end="")
            log_file.write(line)
        code = process.wait()

    elapsed = time.monotonic() - started
    if code != 0:
        raise SystemExit(f"[ERROR] step {step.name} failed with exit code {code}; see {log_path}")
    print(f"[OK] {step.name} completed in {elapsed:.1f}s")


def select_steps(args: argparse.Namespace) -> list[Step]:
    steps = list(STEPS)
    by_name = {step.name: step for step in steps}

    if args.only:
        unknown = [name for name in args.only if name not in by_name]
        if unknown:
            raise SystemExit(f"Unknown --only step(s): {', '.join(unknown)}")
        steps = [by_name[name] for name in args.only]

    if args.from_step:
        names = [step.name for step in steps]
        if args.from_step not in names:
            raise SystemExit(f"Unknown --from-step: {args.from_step}")
        steps = steps[names.index(args.from_step) :]

    skips = set(args.skip or [])
    if args.no_git_pull:
        skips.add("git-pull")
    if args.skip_deps:
        skips.update({"deps", "playwright"})
    if args.skip_links:
        skips.add("links")
    if args.skip_scrape:
        skips.add("scrape")
    if args.skip_cache:
        skips.add("cache")
    if args.skip_markdown:
        skips.add("markdown")
    if args.skip_catalog:
        skips.add("catalog")
    if args.skip_meme:
        skips.add("meme")

    unknown_skips = skips - set(by_name)
    if unknown_skips:
        raise SystemExit(f"Unknown --skip step(s): {', '.join(sorted(unknown_skips))}")

    return [step for step in steps if step.name not in skips]


def count_json_files(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for item in path.glob("*.json") if item.is_file())


def print_status() -> None:
    print("=== genshinstory-cache status ===")

    link_dir = PROJECT_ROOT / "gi_wiki_scraper" / "output" / "link"
    print(f"link files: {count_json_files(link_dir)} ({link_dir})")

    structured_dir = PROJECT_ROOT / "gi_wiki_scraper" / "output" / "structured_data"
    if structured_dir.exists():
        print("structured_data:")
        for folder in sorted((item for item in structured_dir.iterdir() if item.is_dir()), key=lambda p: p.name):
            print(f"  {folder.name}: {count_json_files(folder)}")
    else:
        print(f"structured_data: missing ({structured_dir})")

    cache_file = PROJECT_ROOT / "giwiki_data_parser" / "cache" / "giwiki_data.cache.gz"
    print(f"cache file: {'present' if cache_file.exists() else 'missing'} ({cache_file})")

    gi_docs = PROJECT_ROOT / "web" / "docs-site" / "public" / "domains" / "gi" / "docs"
    print(f"GI markdown files: {sum(1 for _ in gi_docs.rglob('*.md')) if gi_docs.exists() else 0}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="一键更新 genshinstory-cache 的 GI 本地缓存，默认清代理国内直连。"
    )
    parser.add_argument("--status", action="store_true", help="只打印当前缓存进度，不执行更新")
    parser.add_argument("--dry-run", action="store_true", help="只打印将执行的步骤，不实际运行")
    parser.add_argument("--keep-proxy", action="store_true", help="保留当前代理环境变量；默认会清空代理直连")
    parser.add_argument("--from-step", choices=[step.name for step in STEPS], help="从指定步骤开始执行")
    parser.add_argument("--only", nargs="+", choices=[step.name for step in STEPS], help="只执行指定步骤")
    parser.add_argument("--skip", nargs="+", choices=[step.name for step in STEPS], help="跳过指定步骤")
    parser.add_argument("--no-git-pull", action="store_true", help="跳过 git pull --ff-only")
    parser.add_argument("--skip-deps", action="store_true", help="跳过依赖安装与 Playwright Chromium 检查")
    parser.add_argument("--skip-links", action="store_true", help="跳过 GI 链接抓取")
    parser.add_argument("--skip-scrape", action="store_true", help="跳过结构化页面增量抓取")
    parser.add_argument("--skip-cache", action="store_true", help="跳过 parser cache 重建")
    parser.add_argument("--skip-markdown", action="store_true", help="跳过 Markdown 导出")
    parser.add_argument("--skip-catalog", action="store_true", help="跳过 GI catalog/search metadata 重建")
    parser.add_argument("--skip-meme", action="store_true", help="跳过表情索引重建")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.status:
        print_status()
        return 0

    selected_steps = select_steps(args)
    if not selected_steps:
        print("No steps selected.")
        return 0

    timestamp = time.strftime("%Y%m%d-%H%M%S")
    log_dir = LOG_ROOT / timestamp
    env = make_env(args.keep_proxy)

    print("=== genshinstory-cache one-click update ===")
    print(f"project: {PROJECT_ROOT}")
    print(f"logs: {log_dir}")
    print(f"proxy: {'kept from environment' if args.keep_proxy else 'cleared; domestic direct mode'}")
    print("steps: " + ", ".join(step.name for step in selected_steps))

    for step in selected_steps:
        run_step(step, log_dir, env, args.dry_run)

    print("\n[DONE] genshinstory-cache update workflow completed")
    print_status()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
