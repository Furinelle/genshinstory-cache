# 先抓取/更新链接
uv run python -m gi_wiki_scraper.link_parsers.generate_links

# 再执行增量抓取与解析
uv run python -m gi_wiki_scraper.run_all_parsers_incremental

# 一键更新 GI 本地缓存（推荐）
python scripts/update_genshinstory_cache.py

# 常用恢复方式
python scripts/update_genshinstory_cache.py --status
python scripts/update_genshinstory_cache.py --skip-links
python scripts/update_genshinstory_cache.py --from-step scrape
python scripts/update_genshinstory_cache.py --from-step cache --skip-deps

默认会清空 HTTP_PROXY/HTTPS_PROXY/ALL_PROXY 等代理环境变量，并设置 NO_PROXY 直连
baike.mihoyo.com、本机、GitHub 与 PyPI 相关域名。所有步骤日志会写入
logs/update_genshinstory_cache/<时间戳>/。
