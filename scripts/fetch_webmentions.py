#!/usr/bin/env python3
import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


def fetch_json(url):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "webmentions-fetcher/1.0",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        charset = response.headers.get_content_charset("utf-8")
        payload = response.read().decode(charset)
        return json.loads(payload)


def fetch_mentions(domain, per_page=100):
    page = 1
    mentions = []
    while True:
        url = (
            f"https://webmention.io/api/mentions.jf2?domain={urllib.parse.quote(domain)}"
            f"&per-page={per_page}&page={page}"
        )
        print(f"Fetching {url}")
        data = fetch_json(url)
        children = data.get("children", [])
        if not children:
            break
        mentions.extend(children)
        if len(children) < per_page:
            break
        page += 1
        time.sleep(1)
    return mentions


def normalize_baseurl(baseurl):
    if not baseurl:
        return ""
    baseurl = "/" + baseurl.lstrip("/")
    return baseurl.rstrip("/")


def slug_from_target(target, domain, baseurl):
    parsed = urllib.parse.urlparse(target)
    host = parsed.hostname or ""
    if not host.endswith(domain):
        return None
    path = parsed.path or "/"
    if baseurl and path.startswith(baseurl):
        path = path[len(baseurl) :]
    parts = [segment for segment in path.strip("/").split("/") if segment]
    if not parts:
        return None
    slug = parts[-1]
    return slug


def build_mention(item):
    source = item.get("url") or item.get("wm-source") or ""
    author = item.get("author", {})
    if isinstance(author, str):
        author_data = {"name": author}
    else:
        author_data = {
            "name": author.get("name", ""),
            "url": author.get("url", ""),
            "photo": author.get("photo", ""),
        }
    content_obj = item.get("content", {}) or {}
    content = content_obj.get("text") or content_obj.get("html") or ""
    return {
        "source": source,
        "author": author_data,
        "published": item.get("published", ""),
        "content": content,
        "wm_property": item.get("wm-property", ""),
    }


def write_data_files(webmentions, target_dir):
    target_dir.mkdir(parents=True, exist_ok=True)
    for slug, entries in webmentions.items():
        path = target_dir / f"{slug}.json"
        with path.open("w", encoding="utf-8") as fp:
            json.dump(entries, fp, ensure_ascii=False, indent=2)
        print(f"Wrote {path}")


def collect_outbound_links(source_dir, site_domain, baseurl, site_url):
    post_url_map = {}
    baseurl = normalize_baseurl(baseurl)
    pattern = re.compile(r"^(\d{4})-(\d{2})-(\d{2})-(.+)\.md$")
    for filepath in Path(source_dir).glob("*.md"):
        match = pattern.match(filepath.name)
        if not match:
            continue
        year, month, day, slug = match.groups()
        relative_path = f"{baseurl}/{year}/{month}/{day}/{slug}/" if baseurl else f"/{year}/{month}/{day}/{slug}/"
        source_url = site_url.rstrip("/") + relative_path
        content = filepath.read_text(encoding="utf-8")
        urls = re.findall(r"https?://[^\s\"')>]+", content)
        for target in sorted(set(urls)):
            parsed = urllib.parse.urlparse(target)
            if not parsed.scheme or not parsed.netloc:
                continue
            if parsed.hostname and parsed.hostname.endswith(site_domain):
                continue
            post_url_map.setdefault(source_url, []).append(target)
    return post_url_map


def send_webmention(source, target, endpoint, token=None):
    data = urllib.parse.urlencode({"source": source, "target": target}).encode("utf-8")
    req = urllib.request.Request(endpoint, data=data)
    req.add_header("User-Agent", "webmentions-sender/1.0")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            print(f"Sent webmention: {source} -> {target} [{response.status}]")
            return True
    except urllib.error.HTTPError as exc:
        print(f"Failed to send {target} from {source}: {exc.code} {exc.reason}")
    except urllib.error.URLError as exc:
        print(f"Network error sending {target} from {source}: {exc}")
    return False


def main():
    parser = argparse.ArgumentParser(description="Fetch and store Webmention data for a Jekyll site.")
    parser.add_argument("--domain", required=True, help="Domain registered on webmention.io")
    parser.add_argument("--baseurl", default="", help="Jekyll baseurl")
    parser.add_argument("--data-dir", default="_data/webmentions", help="Output data directory")
    parser.add_argument("--posts-dir", default="_posts", help="Source posts directory")
    parser.add_argument("--site-url", default="", help="Canonical site URL, e.g. https://webi-sabi.com")
    parser.add_argument("--send", action="store_true", help="Send outbound webmentions for external links")
    parser.add_argument("--endpoint", default=os.environ.get("WEBMENTION_IO_ENDPOINT", "https://webmention.io/webmention"), help="Webmention sending endpoint")
    parser.add_argument("--token", default=os.environ.get("WEBMENTION_IO_TOKEN"), help="Optional token for webmention.io send endpoint")
    args = parser.parse_args()

    baseurl = normalize_baseurl(args.baseurl)
    webmentions = {}
    items = fetch_mentions(args.domain)
    for item in items:
        target = item.get("target") or item.get("wm-target")
        if not target:
            continue
        slug = slug_from_target(target, args.domain, baseurl)
        if not slug:
            continue
        mention = build_mention(item)
        webmentions.setdefault(slug, []).append(mention)

    if webmentions:
        write_data_files(webmentions, Path(args.data_dir))
    else:
        print("No Webmentions found.")

    if args.send:
        if not args.site_url:
            print("Skipping outbound Webmention send because --site-url is required.")
            return
        outbound = collect_outbound_links(args.posts_dir, args.domain, baseurl, args.site_url)
        if not outbound:
            print("No outbound links found to notify.")
            return
        for source, targets in outbound.items():
            for target in targets:
                send_webmention(source, target, args.endpoint, args.token)


if __name__ == "__main__":
    main()
