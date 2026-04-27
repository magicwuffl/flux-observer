#!/usr/bin/env python3
"""
Wettbewerber-/FLUX-News-Scraper fuer den Observer.

Strategie pro Quelle:
  1. RSS/Atom direkt (Config-Feld `rss`)
  2. Auto-Discovery: <link rel="alternate" type="application/rss+xml"> auf der URL
  3. HTML-Heuristik (article/section + h1/h2/h3 + a + time)

Ergebnis:
  incoming/<datestamp>/<slug>.json     – nur NEUE Items (nicht im State)
  state/<slug>.json                    – alle bisher gesehenen Item-IDs (Hash) + Mtimes

Aufruf:
  python3 scrapers/scrape_competitors.py [--source slug] [--no-state] [--quiet]

Setup:
  python3 -m pip install -r scrapers/requirements.txt
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import feedparser
import requests
import yaml
from bs4 import BeautifulSoup
from dateutil import parser as dateparser

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config" / "news-sources.yaml"
STATE_DIR = ROOT / "state"
INCOMING_DIR = ROOT / "incoming"

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Safari/605.1.15"
)
TIMEOUT = 20
MAX_ITEMS_DEFAULT = 10
HTML_HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.7",
}


def log(quiet: bool, *args):
    if not quiet:
        print(*args, flush=True)


def hash_id(*parts: str) -> str:
    h = hashlib.sha1()
    for p in parts:
        if p:
            h.update(p.encode("utf-8", "ignore"))
            h.update(b"|")
    return h.hexdigest()[:16]


def load_state(slug: str) -> dict:
    f = STATE_DIR / f"{slug}.json"
    if not f.exists():
        return {"seen": {}, "last_run": None}
    try:
        return json.loads(f.read_text("utf-8"))
    except Exception:
        return {"seen": {}, "last_run": None}


def save_state(slug: str, state: dict) -> None:
    STATE_DIR.mkdir(exist_ok=True)
    f = STATE_DIR / f"{slug}.json"
    f.write_text(json.dumps(state, ensure_ascii=False, indent=2), "utf-8")


def _make_soup(html: str) -> BeautifulSoup:
    """Bevorzugt lxml (toleranter bei Pimcore-Output), faellt zurueck auf html.parser."""
    for parser in ("lxml", "html5lib", "html.parser"):
        try:
            return BeautifulSoup(html, parser)
        except Exception:
            continue
    return BeautifulSoup(html, "html.parser")


def fetch(url: str) -> requests.Response | None:
    try:
        r = requests.get(url, headers=HTML_HEADERS, timeout=TIMEOUT, allow_redirects=True)
        if r.status_code >= 400:
            return None
        return r
    except requests.RequestException:
        return None


def discover_rss(url: str) -> str | None:
    """Auto-Discovery: holt die Seite, sucht <link rel=alternate type=application/rss+xml>."""
    r = fetch(url)
    if not r or "html" not in r.headers.get("content-type", "").lower():
        return None
    soup = _make_soup(r.text)
    for link in soup.find_all("link", rel=lambda v: v and "alternate" in v):
        t = (link.get("type") or "").lower()
        href = link.get("href")
        if not href:
            continue
        if "rss" in t or "atom" in t:
            return urljoin(url, href)
    # Heuristik: oft ist /feed oder /rss verfuegbar
    parsed = urlparse(url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    for guess in ("/feed", "/rss", "/feed.xml", "/rss.xml", "/news/feed", "/news/rss"):
        rr = fetch(base + guess)
        if rr and ("xml" in rr.headers.get("content-type", "").lower() or rr.text.strip().startswith("<?xml")):
            return base + guess
    return None


def parse_rss(feed_url: str, max_items: int) -> list[dict]:
    parsed = feedparser.parse(feed_url, request_headers={"User-Agent": UA})
    if parsed.bozo and not parsed.entries:
        return []
    out = []
    for e in parsed.entries[:max_items]:
        title = (e.get("title") or "").strip()
        link = (e.get("link") or "").strip()
        if not title or not link:
            continue
        published = (
            e.get("published")
            or e.get("updated")
            or e.get("pubDate")
            or e.get("dc_date")
            or ""
        )
        out.append(
            {
                "title": title,
                "link": link,
                "published_raw": published,
                "summary": (e.get("summary") or "")[:500],
            }
        )
    return out


def parse_html(url: str, html_cfg: dict | None, max_items: int, link_pattern: str | None = None) -> list[dict]:
    """Generische HTML-Listen-Extraktion. Wenn html_cfg gesetzt, dessen Selektoren nutzen, sonst Heuristik.

    link_pattern: Wenn gesetzt, werden alle <a href> matchend gegen das Regex aufgesammelt.
                  Title kommt aus dem Link-Text oder dem aria-label.
    """
    r = fetch(url)
    if not r:
        return []
    soup = _make_soup(r.text)

    # Schritt 1: link_pattern (kommt vor Heuristik – z.B. fuer Pimcore /aktuelles/artikel/*)
    if link_pattern:
        rx = re.compile(link_pattern, re.IGNORECASE)
        seen_links = set()
        out_lp = []
        parsed_base = urlparse(url)
        domain_root = f"{parsed_base.scheme}://{parsed_base.netloc}"
        for a in soup.find_all("a", href=True):
            href = a["href"]
            # Pimcore liefert relative URLs ohne fuehrendes / – domain-root behandeln,
            # damit urljoin nicht den aktuellen Pfad doppelt anhaengt.
            if not href.startswith(("http://", "https://", "/", "#", "mailto:", "javascript:")):
                full = f"{domain_root}/{href.lstrip('/')}"
            else:
                full = urljoin(url, href)
            if not rx.search(full):
                continue
            if full in seen_links:
                continue
            seen_links.add(full)
            title = a.get("aria-label") or a.get_text(" ", strip=True) or a.get("title") or ""
            title = re.sub(r"\s+", " ", title).strip()
            if not title or len(title) < 8:
                # Suche im umliegenden Block nach Headline
                parent = a.find_parent(["article", "li", "div"]) or a
                h = parent.find(["h1", "h2", "h3", "h4"])
                if h:
                    title = h.get_text(" ", strip=True)
            if not title:
                continue
            out_lp.append(
                {
                    "title": title[:300],
                    "link": full,
                    "published_raw": "",
                    "summary": "",
                }
            )
            if len(out_lp) >= max_items:
                break
        if out_lp:
            return out_lp

    candidates = []
    if html_cfg and html_cfg.get("item"):
        for el in soup.select(html_cfg["item"])[: max_items * 3]:
            title_el = el.select_one(html_cfg.get("title", "h1, h2, h3, a"))
            link_el = el.select_one(html_cfg.get("link", "a"))
            date_el = el.select_one(html_cfg.get("date", "time, .date"))
            if not title_el or not link_el:
                continue
            href = link_el.get("href")
            candidates.append(
                {
                    "title": title_el.get_text(" ", strip=True),
                    "link": urljoin(url, href) if href else None,
                    "published_raw": (date_el.get("datetime") or date_el.get_text(" ", strip=True))
                    if date_el
                    else "",
                    "summary": "",
                }
            )
    else:
        # Heuristik: jedes <article> oder div mit news-/item-Klasse, mit erstem h1-h3 und a
        roots = soup.select("article, .news-item, .news-list-item, .post, .listing__item, [class*='news'] li")
        if not roots:
            # fallback: alle h2/h3 mit a darin im main/section
            main = soup.select_one("main") or soup
            for h in main.find_all(["h2", "h3"])[: max_items * 3]:
                a = h.find("a")
                if not a:
                    continue
                roots.append(h.parent or h)
        for el in roots[: max_items * 3]:
            a = el.find("a")
            h = el.find(["h1", "h2", "h3", "h4"])
            if not a or not (h or a.get_text(strip=True)):
                continue
            title = (h.get_text(" ", strip=True) if h else a.get_text(" ", strip=True))[:300]
            href = a.get("href")
            time_el = el.find("time")
            candidates.append(
                {
                    "title": title,
                    "link": urljoin(url, href) if href else None,
                    "published_raw": (time_el.get("datetime") or time_el.get_text(" ", strip=True)) if time_el else "",
                    "summary": "",
                }
            )

    # dedup nach link
    seen_links = set()
    out = []
    for c in candidates:
        if not c["title"] or not c["link"]:
            continue
        if c["link"] in seen_links:
            continue
        seen_links.add(c["link"])
        out.append(c)
        if len(out) >= max_items:
            break
    return out


def normalize_date(raw: str) -> str | None:
    if not raw:
        return None
    try:
        d = dateparser.parse(raw, fuzzy=True)
        if d.tzinfo:
            d = d.astimezone(dt.timezone.utc).replace(tzinfo=None)
        return d.strftime("%Y-%m-%d")
    except Exception:
        return None


def keyword_pass(title: str, keywords: list[str]) -> bool:
    if not keywords:
        return True
    t = title.lower()
    return any(k.lower() in t for k in keywords)


def scrape_source(src: dict, only_slug: str | None, quiet: bool) -> tuple[str, list[dict]]:
    slug = src["slug"]
    if only_slug and slug != only_slug:
        return slug, []
    if src.get("enabled", True) is False:
        log(quiet, f"  - {slug}: deaktiviert (skipped)")
        return slug, []

    name = src.get("name", slug)
    url = src["url"]
    rss = src.get("rss")
    html_cfg = src.get("html") or {}
    link_pattern = src.get("link_pattern")
    keywords = src.get("keywords") or []
    max_items = int(src.get("max_items") or MAX_ITEMS_DEFAULT)

    log(quiet, f"\n→ {name} ({slug})")

    # Schritt 1: RSS
    feed_url = rss
    if not feed_url:
        feed_url = discover_rss(url)
        if feed_url:
            log(quiet, f"  RSS auto-discovered: {feed_url}")

    items: list[dict] = []
    if feed_url:
        items = parse_rss(feed_url, max_items)
        if items:
            log(quiet, f"  RSS: {len(items)} Items")

    # Schritt 2: HTML-Fallback (mit optionalem link_pattern)
    if not items:
        items = parse_html(url, html_cfg, max_items, link_pattern=link_pattern)
        if items:
            log(quiet, f"  HTML: {len(items)} Items")
        else:
            log(quiet, "  Keine Treffer")

    # Filter + Normalisierung
    enriched = []
    for it in items:
        if not keyword_pass(it["title"], keywords):
            continue
        published = normalize_date(it.get("published_raw") or "")
        item_id = hash_id(slug, it["link"], it["title"])
        enriched.append(
            {
                "id": item_id,
                "title": it["title"],
                "link": it["link"],
                "published": published,
                "summary": (it.get("summary") or "").strip(),
            }
        )

    return slug, enriched


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", help="Nur einen Slug scrapen (Test)")
    ap.add_argument("--no-state", action="store_true", help="State ignorieren – alle Items als neu")
    ap.add_argument("--no-write", action="store_true", help="Nichts auf Disk schreiben (Dry-Run)")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    if not CONFIG.exists():
        sys.exit(f"Config fehlt: {CONFIG}")

    sources = yaml.safe_load(CONFIG.read_text("utf-8")) or []
    today = dt.date.today().isoformat()
    daystamp = today
    out_dir = INCOMING_DIR / daystamp
    if not args.no_write:
        out_dir.mkdir(parents=True, exist_ok=True)

    summary = []
    total_new = 0
    for src in sources:
        slug, items = scrape_source(src, args.source, args.quiet)
        if not items:
            continue
        state = {} if args.no_state else load_state(slug)
        seen = state.get("seen", {})

        new_items = []
        for it in items:
            if it["id"] in seen:
                continue
            new_items.append(it)
            seen[it["id"]] = {"title": it["title"][:120], "first_seen": today}

        log(args.quiet, f"  Neu: {len(new_items)} / Bereits gesehen: {len(items) - len(new_items)}")

        if not args.no_write and new_items:
            payload = {
                "source": slug,
                "name": src.get("name", slug),
                "category": src.get("category", "unknown"),
                "scraped_at": dt.datetime.utcnow().isoformat() + "Z",
                "items": new_items,
            }
            (out_dir / f"{slug}.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), "utf-8"
            )

        if not args.no_write and not args.no_state:
            state["seen"] = seen
            state["last_run"] = today
            save_state(slug, state)

        summary.append((slug, len(new_items), len(items)))
        total_new += len(new_items)

    log(args.quiet, "\n=== Zusammenfassung ===")
    for slug, new_count, total in summary:
        log(args.quiet, f"  {slug:<20} {new_count:>3} neu / {total:>3} gesamt")
    log(args.quiet, f"\nTotal neu: {total_new}")
    if total_new == 0:
        log(args.quiet, "(Keine neuen Items – kein incoming/-File geschrieben.)")


if __name__ == "__main__":
    main()
