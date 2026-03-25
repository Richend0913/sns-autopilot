#!/usr/bin/env python3
"""
SNSオートパイロット - RSS Feed Generator
各コンテンツサイトからRSS 2.0フィードを生成し、Pinterest自動ピン用に配信。
"""

import os
import re
import json
import subprocess
from pathlib import Path
from datetime import datetime, timezone
from xml.etree.ElementTree import Element, SubElement, ElementTree, tostring
from xml.dom import minidom
from html.parser import HTMLParser


class HTMLMetaParser(HTMLParser):
    """HTMLからtitle, meta description, og:image等を抽出"""
    def __init__(self):
        super().__init__()
        self.title = ""
        self.description = ""
        self.og_image = ""
        self.canonical = ""
        self.date_published = ""
        self._in_title = False
        self._title_parts = []

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag == "title":
            self._in_title = True
        elif tag == "meta":
            name = attrs_dict.get("name", "").lower()
            prop = attrs_dict.get("property", "").lower()
            content = attrs_dict.get("content", "")
            if name == "description":
                self.description = content
            elif prop == "og:image":
                self.og_image = content
        elif tag == "link":
            rel = attrs_dict.get("rel", "")
            if rel == "canonical":
                self.canonical = attrs_dict.get("href", "")

    def handle_data(self, data):
        if self._in_title:
            self._title_parts.append(data)

    def handle_endtag(self, tag):
        if tag == "title" and self._in_title:
            self._in_title = False
            self.title = "".join(self._title_parts).strip()


def parse_html_file(filepath):
    """HTMLファイルからメタ情報を抽出"""
    parser = HTMLMetaParser()
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        parser.feed(content)
        # Try to extract datePublished from JSON-LD
        date_match = re.search(r'"datePublished"\s*:\s*"([^"]+)"', content)
        if date_match:
            parser.date_published = date_match.group(1)
        # Try to extract image from content if no og:image
        if not parser.og_image:
            img_match = re.search(r'<img[^>]+src="([^"]+)"', content)
            if img_match:
                parser.og_image = img_match.group(1)
    except Exception as e:
        print(f"  Warning: Could not parse {filepath}: {e}")
    return parser


def format_rfc822(date_str):
    """日付文字列をRFC822形式に変換"""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return dt.strftime("%a, %d %b %Y 00:00:00 +0900")
    except (ValueError, TypeError):
        return datetime.now().strftime("%a, %d %b %Y 00:00:00 +0900")


def generate_rss_xml(channel_info, items):
    """RSS 2.0 XMLを生成"""
    lines = []
    lines.append('<?xml version="1.0" encoding="UTF-8"?>')
    lines.append('<rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/" xmlns:atom="http://www.w3.org/2005/Atom">')
    lines.append('  <channel>')
    lines.append(f'    <title>{escape_xml(channel_info["title"])}</title>')
    lines.append(f'    <link>{escape_xml(channel_info["link"])}</link>')
    lines.append(f'    <description>{escape_xml(channel_info["description"])}</description>')
    lines.append(f'    <language>ja</language>')
    lines.append(f'    <lastBuildDate>{format_rfc822(datetime.now().strftime("%Y-%m-%d"))}</lastBuildDate>')
    lines.append(f'    <atom:link href="{escape_xml(channel_info["feed_url"])}" rel="self" type="application/rss+xml"/>')

    for item in items[:20]:
        lines.append('    <item>')
        lines.append(f'      <title>{escape_xml(item["title"])}</title>')
        lines.append(f'      <link>{escape_xml(item["link"])}</link>')
        lines.append(f'      <description>{escape_xml(item["description"])}</description>')
        lines.append(f'      <pubDate>{item["pubDate"]}</pubDate>')
        lines.append(f'      <guid isPermaLink="true">{escape_xml(item["link"])}</guid>')
        if item.get("image"):
            img = escape_xml(item["image"])
            lines.append(f'      <enclosure url="{img}" type="image/jpeg" length="0"/>')
            lines.append(f'      <media:content url="{img}" medium="image"/>')
        lines.append('    </item>')

    lines.append('  </channel>')
    lines.append('</rss>')
    return '\n'.join(lines)


def escape_xml(text):
    """XML特殊文字をエスケープ"""
    if not text:
        return ""
    return (text
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&apos;"))


def generate_okurite_feed(site_dir):
    """Okurite (ギフト情報サイト) のRSSフィード生成"""
    print("\n=== Okurite Feed ===")
    blog_dir = os.path.join(site_dir, "blog")
    base_url = "https://richend0913.github.io/okurite"

    items = []
    # Parse topics.json for scheduled articles
    topics_file = os.path.join(blog_dir, "topics.json")
    if os.path.exists(topics_file):
        with open(topics_file, "r", encoding="utf-8") as f:
            topics = json.load(f)

    # Parse existing blog HTML files
    for fname in sorted(os.listdir(blog_dir)):
        if not fname.endswith(".html") or fname == "index.html":
            continue
        filepath = os.path.join(blog_dir, fname)
        meta = parse_html_file(filepath)
        if meta.title:
            # Try to find image from topics.json
            slug = fname.replace(".html", "")
            hero_img = ""
            if os.path.exists(topics_file):
                for t in topics:
                    if t.get("slug") == slug:
                        hero_img = t.get("hero", "")
                        break
            if not hero_img:
                hero_img = meta.og_image

            items.append({
                "title": meta.title,
                "link": f"{base_url}/blog/{fname}",
                "description": meta.description or meta.title,
                "pubDate": format_rfc822(meta.date_published or "2026-03-24"),
                "image": hero_img
            })
            print(f"  Added: {meta.title[:50]}...")

    # Add items from topics.json that don't have HTML files yet
    if os.path.exists(topics_file):
        existing_slugs = {f.replace(".html", "") for f in os.listdir(blog_dir) if f.endswith(".html")}
        for t in topics:
            if t["slug"] not in existing_slugs:
                items.append({
                    "title": t["title"],
                    "link": f"{base_url}/blog/{t['slug']}.html",
                    "description": t.get("description", t["title"]),
                    "pubDate": format_rfc822("2026-03-24"),
                    "image": t.get("hero", "")
                })
                print(f"  Added (from topics): {t['title'][:50]}...")

    channel = {
        "title": "Okurite - ギフト・プレゼント情報",
        "link": base_url,
        "description": "大切な人へ贈るプレゼント・ギフトの選び方。母の日、誕生日、結婚祝いなどシーン別におすすめギフトを紹介。",
        "feed_url": f"{base_url}/feed.xml"
    }

    xml = generate_rss_xml(channel, items)
    feed_path = os.path.join(site_dir, "feed.xml")
    with open(feed_path, "w", encoding="utf-8") as f:
        f.write(xml)
    print(f"  Generated: {feed_path} ({len(items)} items)")
    return feed_path


def generate_calorie_feed(site_dir):
    """CalorieBook (カロリー情報サイト) のRSSフィード生成"""
    print("\n=== CalorieBook Feed ===")
    foods_dir = os.path.join(site_dir, "foods")
    base_url = "https://richend0913.github.io/calorie-book"

    items = []
    for fname in sorted(os.listdir(foods_dir)):
        if not fname.endswith(".html"):
            continue
        filepath = os.path.join(foods_dir, fname)
        meta = parse_html_file(filepath)
        if meta.title:
            items.append({
                "title": meta.title,
                "link": f"{base_url}/foods/{fname}",
                "description": meta.description or meta.title,
                "pubDate": format_rfc822(meta.date_published or "2026-03-24"),
                "image": meta.og_image or ""
            })
            print(f"  Added: {meta.title[:50]}...")

    channel = {
        "title": "カロリーブック - 食品カロリー・栄養成分データベース",
        "link": base_url,
        "description": "食品のカロリー・糖質・栄養成分を簡単検索。ダイエットや健康管理に役立つ栄養情報を掲載。",
        "feed_url": f"{base_url}/feed.xml"
    }

    xml = generate_rss_xml(channel, items)
    feed_path = os.path.join(site_dir, "feed.xml")
    with open(feed_path, "w", encoding="utf-8") as f:
        f.write(xml)
    print(f"  Generated: {feed_path} ({len(items)} items)")
    return feed_path


def generate_ryouri_feed(site_dir):
    """RyouriKihon (料理レシピサイト) のRSSフィード生成"""
    print("\n=== RyouriKihon Feed ===")
    recipes_dir = os.path.join(site_dir, "recipes")
    base_url = "https://richend0913.github.io/ryouri-kihon"

    items = []
    for fname in sorted(os.listdir(recipes_dir)):
        if not fname.endswith(".html"):
            continue
        filepath = os.path.join(recipes_dir, fname)
        meta = parse_html_file(filepath)
        if meta.title:
            items.append({
                "title": meta.title,
                "link": f"{base_url}/recipes/{fname}",
                "description": meta.description or meta.title,
                "pubDate": format_rfc822(meta.date_published or "2026-03-24"),
                "image": meta.og_image or ""
            })
            print(f"  Added: {meta.title[:50]}...")

    channel = {
        "title": "料理の基本 - 簡単レシピ集",
        "link": base_url,
        "description": "料理初心者でも作れる簡単レシピ。基本の作り方からアレンジまで、写真付きで丁寧に解説。",
        "feed_url": f"{base_url}/feed.xml"
    }

    xml = generate_rss_xml(channel, items)
    feed_path = os.path.join(site_dir, "feed.xml")
    with open(feed_path, "w", encoding="utf-8") as f:
        f.write(xml)
    print(f"  Generated: {feed_path} ({len(items)} items)")
    return feed_path


def generate_baby_feed(site_dir):
    """BabyCalendar (赤ちゃんカレンダー) のRSSフィード生成"""
    print("\n=== BabyCalendar Feed ===")
    months_dir = os.path.join(site_dir, "months")
    base_url = "https://richend0913.github.io/baby-calendar"

    items = []
    for fname in sorted(os.listdir(months_dir)):
        if not fname.endswith(".html"):
            continue
        filepath = os.path.join(months_dir, fname)
        meta = parse_html_file(filepath)
        if meta.title:
            items.append({
                "title": meta.title,
                "link": f"{base_url}/months/{fname}",
                "description": meta.description or meta.title,
                "pubDate": format_rfc822(meta.date_published or "2026-03-24"),
                "image": meta.og_image or ""
            })
            print(f"  Added: {meta.title[:50]}...")

    channel = {
        "title": "赤ちゃんカレンダー - 月齢別発達ガイド",
        "link": base_url,
        "description": "妊娠中から2歳まで、赤ちゃんの月齢別発達・成長ガイド。新米ママ・パパに役立つ情報を掲載。",
        "feed_url": f"{base_url}/feed.xml"
    }

    xml = generate_rss_xml(channel, items)
    feed_path = os.path.join(site_dir, "feed.xml")
    with open(feed_path, "w", encoding="utf-8") as f:
        f.write(xml)
    print(f"  Generated: {feed_path} ({len(items)} items)")
    return feed_path


def git_commit_and_push(site_dir, site_name):
    """feed.xmlをgit commit & push"""
    print(f"\n  Git push: {site_name}...")
    try:
        subprocess.run(["git", "add", "feed.xml"], cwd=site_dir, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", f"Add RSS feed for Pinterest auto-pinning ({site_name})"],
            cwd=site_dir, check=True, capture_output=True
        )
        subprocess.run(["git", "push"], cwd=site_dir, check=True, capture_output=True)
        print(f"  Pushed feed.xml to {site_name}")
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode() if e.stderr else ""
        if "nothing to commit" in stderr:
            print(f"  No changes to commit for {site_name}")
        else:
            print(f"  Git error for {site_name}: {stderr}")


def main():
    print("=" * 60)
    print("SNSオートパイロット - RSS Feed Generator")
    print("=" * 60)

    base = r"C:\Users\sushi"

    sites = [
        (os.path.join(base, "okurite"), "okurite", generate_okurite_feed),
        (os.path.join(base, "calorie-book"), "calorie-book", generate_calorie_feed),
        (os.path.join(base, "ryouri-kihon"), "ryouri-kihon", generate_ryouri_feed),
        (os.path.join(base, "baby-calendar"), "baby-calendar", generate_baby_feed),
    ]

    for site_dir, site_name, generator in sites:
        if not os.path.isdir(site_dir):
            print(f"\n  SKIP: {site_dir} not found")
            continue
        generator(site_dir)
        git_commit_and_push(site_dir, site_name)

    print("\n" + "=" * 60)
    print("All RSS feeds generated and deployed!")
    print("=" * 60)


if __name__ == "__main__":
    main()
