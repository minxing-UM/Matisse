import json
import re
import xml.etree.ElementTree as ET

from datetime import datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen


ROOT_DIR = Path(__file__).resolve().parents[2]
CONFIG_FILE = ROOT_DIR / "config" / "web_sources.json"
WORLD_FILE = ROOT_DIR / "repository" / "knowledge" / "world_memories.json"


class _TextParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.title = ""
        self.parts = []
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        self._in_title = tag == "title"
        if tag in {"p", "br", "li", "h1", "h2", "h3"}:
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        self.parts.append(data)


class WebManager:
    """Fetches only user-configured HTTPS pages/RSS feeds; the model never fetches URLs."""

    def __init__(self, context_limit=4):
        self.context_limit = context_limit
        WORLD_FILE.parent.mkdir(parents=True, exist_ok=True)
        if not WORLD_FILE.exists():
            self._save({"version": 1, "items": []})
        self.data = self._load(WORLD_FILE)

    @staticmethod
    def _load(path):
        with open(path, "r", encoding="utf-8") as file:
            return json.load(file)

    def _save(self, data=None):
        if data is not None:
            self.data = data
        with open(WORLD_FILE, "w", encoding="utf-8") as file:
            json.dump(self.data, file, ensure_ascii=False, indent=2)

    @staticmethod
    def _safe_url(url):
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("Only configured HTTPS URLs may be fetched.")
        if parsed.hostname in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("Local URLs are not allowed.")

    def _fetch(self, url):
        self._safe_url(url)
        request = Request(url, headers={"User-Agent": "Matisse/0.0.3 (personal companion)"})
        with urlopen(request, timeout=12) as response:
            final_url = response.geturl()
            self._safe_url(final_url)
            content = response.read(800_000).decode(response.headers.get_content_charset() or "utf-8", "replace")
        return final_url, content

    @staticmethod
    def _clean(value):
        return re.sub(r"\s+", " ", value or "").strip()

    def _rss_items(self, source, xml):
        root = ET.fromstring(xml)
        entries = root.findall(".//item") or root.findall(".//{*}entry")
        items = []
        for entry in entries[:int(source.get("max_items", 3))]:
            link = entry.findtext("link") or ""
            link_node = entry.find("{*}link")
            if link_node is not None:
                link = link_node.attrib.get("href", link)
            items.append({
                "source": source["name"], "url": link,
                "title": self._clean(entry.findtext("title") or entry.findtext("{*}title")),
                "text": self._clean(entry.findtext("description") or entry.findtext("{*}summary") or entry.findtext("{*}content")),
                "published_at": self._clean(entry.findtext("pubDate") or entry.findtext("{*}published"))
            })
        return [item for item in items if item["url"] and item["text"]]

    def refresh(self):
        """Return new raw items. Callers decide whether to ask the model to summarize them."""
        if not CONFIG_FILE.exists():
            return []
        config = self._load(CONFIG_FILE)
        if not config.get("enabled", False):
            return []
        known = {item.get("url") for item in self.data.get("items", [])}
        found = []
        for source in config.get("sources", []):
            try:
                url, body = self._fetch(source["url"])
                if source.get("kind", "rss") == "rss":
                    candidates = self._rss_items(source, body)
                else:
                    parser = _TextParser(); parser.feed(body)
                    candidates = [{"source": source["name"], "url": url, "title": self._clean(parser.title), "text": self._clean(" ".join(parser.parts))[:8000], "published_at": ""}]
                found.extend(item for item in candidates if item["url"] not in known)
            except Exception:
                continue
        return found

    def store(self, item, summary):
        now = datetime.now()
        self.data.setdefault("items", []).append({
            **item, "summary": summary[:1200], "captured_at": now.isoformat(),
            "expires_at": (now + timedelta(days=14)).isoformat(), "status": "active"
        })
        self._save()

    def build_runtime_context(self, user_input):
        now = datetime.now()
        words = set(re.findall(r"[\u4e00-\u9fff]|[a-z0-9_]{2,}", user_input.casefold()))
        active = [item for item in self.data.get("items", []) if item.get("status") == "active" and datetime.fromisoformat(item["expires_at"]) > now]
        ranked = sorted(active, key=lambda item: len(words & set(re.findall(r"[\u4e00-\u9fff]|[a-z0-9_]{2,}", (item["title"] + item["summary"]).casefold()))), reverse=True)[:self.context_limit]
        if not ranked:
            return ""
        notes = "\n".join(f"- {item['summary']} (来源：{item['source']}，{item['url']})" for item in ranked)
        return "[PRIVATE RECENT WEB NOTES]\nUse only when relevant; cite source/date if discussing current events.\n" + notes
