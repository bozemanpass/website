#!/usr/bin/env python3
"""Convert a wget mirror of the WordPress site (see crawl.sh) into a clean static site.

Usage: python3 tools/build.py <mirror-dir> <output-dir>
Requires: beautifulsoup4, lxml
"""
import datetime
import re
import shutil
import sys
import urllib.parse
import urllib.request
from pathlib import Path

from bs4 import BeautifulSoup

SITE = "https://www.bozemanpass.com"
HOST = "www.bozemanpass.com"
# Old hostnames that still appear hard-coded in post content (and are broken on the live site).
LOCAL_HOSTS = r"(?:www|www-new|server1010618)\.bozemanpass\.com"

# WordPress archive pages that are dropped; each becomes a redirect stub to /articles/.
DROPPED_PREFIXES = ("category/", "tag/", "author/", "articles/page/")
DATE_ARCHIVE = re.compile(r"^\d{4}/(\d{2}/)?")

SIDEBAR_WIDGETS_KEPT = {"recent-posts-2"}

URL_ATTRS = ("href", "src", "content", "action", "data-src")


def localize_urls(text):
    """Make every reference to our own hosts root-relative, including JSON-escaped ones in inline scripts."""
    text = re.sub(r"(?:https?:)?//" + LOCAL_HOSTS + r"(?=[/\"'?#<\s])", "", text)
    text = re.sub(r"(?:https?:)?\\/\\/" + LOCAL_HOSTS + r"(?=\\/)", "", text)
    return text


def strip_ver(url):
    return re.sub(r"\?ver=[^&#\"']*$", "", url)


def page_path(rel):
    """Mirror-relative HTML file -> URL path, e.g. kim-1/index.html -> /kim-1/."""
    if rel == "index.html":
        return "/"
    if rel.endswith("/index.html"):
        return "/" + rel[: -len("index.html")]
    return "/" + rel


def is_dropped(rel):
    return rel.startswith(DROPPED_PREFIXES) or bool(DATE_ARCHIVE.match(rel))


def remove_wp_cruft(soup):
    head = soup.head
    for link in head.find_all("link"):
        rel = " ".join(link.get("rel", []))
        href = link.get("href", "")
        if rel in ("pingback", "EditURI", "shortlink", "https://api.w.org/", "wlwmanifest"):
            link.decompose()
        elif rel == "alternate" and (href.startswith("/wp-json") or "/feed/" in href):
            link.decompose()
        elif rel == "dns-prefetch" and not href.startswith("//fonts."):
            link.decompose()
    for meta in head.find_all("meta", attrs={"name": "generator"}):
        meta.decompose()

    for script in soup.find_all("script"):
        src = script.get("src", "")
        body = script.string or ""
        if (
            "googletagmanager.com" in src
            or "gtag(" in body
            or "recaptcha" in src
            or "recaptcha" in (script.get("id") or "")
            or script.get("type") == "speculationrules"
            or "wp-embed" in src
            or "es6-promise" in src
        ):
            script.decompose()

    # Sidebar: keep only the static "Recent Posts" list.
    sidebar = soup.find(id="sidebar")
    if sidebar:
        for widget in sidebar.find_all(class_="et_pb_widget", recursive=False):
            if widget.get("id") not in SIDEBAR_WIDGETS_KEPT:
                widget.decompose()

    # Search forms anywhere (header search, 404 page).
    for form in soup.find_all("form", class_="searchform"):
        form.decompose()
    for el in soup.select(".et_search_outer, #et_top_search"):
        el.decompose()

    # No feed any more.
    for el in soup.select("li.et-social-rss"):
        el.decompose()

    # Post meta links to dropped author/category/tag archives become plain text.
    for a in soup.select(".post-meta a, .et_post_meta_wrapper a"):
        href = a.get("href", "")
        if is_dropped(href.lstrip("/")):
            a.unwrap()

    footer = soup.find(id="footer-info")
    if footer:
        for text in footer.find_all(string=re.compile(r"©\d{4}")):
            text.replace_with(re.sub(r"©\d{4}", f"©{datetime.date.today().year}", text))


def fix_contact_page(soup):
    form_module = soup.find(class_="et_pb_contact_form_container")
    if not form_module:
        return
    column = form_module.find_parent(class_="et_pb_column")
    row = column.parent
    column.decompose()
    # Let the remaining (contact details) column span the full row.
    for col in row.find_all(class_="et_pb_column", recursive=False):
        col["class"] = ["et_pb_column_4_4" if c == "et_pb_column_1_2" else c for c in col["class"]]
        col["class"] = [c for c in col["class"] if c != "et-last-child"] + ["et-last-child"]
    for text in soup.find_all(string=re.compile(r"phone, email or by filling out the form on this page")):
        text.replace_with(text.replace("phone, email or by filling out the form on this page", "phone or email"))


def merge_article_list(soup, extra_pages):
    """Combine the paginated /articles/ listing into one page."""
    left = soup.find(id="left-area")
    pagination = left.find(class_="pagination")
    for extra in extra_pages:
        for article in extra.find(id="left-area").find_all("article", recursive=False):
            (pagination.insert_before if pagination else left.append)(article)
    if pagination:
        pagination.decompose()


def fix_404_page(soup):
    entry = soup.select_one("#left-area .entry")
    if entry:
        entry.append(BeautifulSoup('<p>Return to the <a href="/">home page</a> or browse our <a href="/articles/">articles</a>.</p>', "lxml").p)


def tidy_urls(soup):
    for tag in soup.find_all(True):
        for attr in URL_ATTRS:
            val = tag.get(attr)
            if isinstance(val, str) and val.startswith("/wp-"):
                tag[attr] = strip_ver(val)
        if tag.get("srcset"):
            tag["srcset"] = ", ".join(strip_ver(p.strip().split(" ")[0]) + (" " + p.strip().split(" ", 1)[1] if " " in p.strip() else "")
                                      for p in tag["srcset"].split(","))
        if tag.name == "a" and tag.get("href") == "":
            tag["href"] = "/"


def set_canonical(soup, path):
    link = soup.head.find("link", rel="canonical")
    if link:
        link["href"] = SITE + path


def local_refs(html):
    """All root-relative URLs referenced from a page (attributes, srcset and inline CSS)."""
    soup = BeautifulSoup(html, "lxml")
    refs = set()
    for tag in soup.find_all(True):
        for attr in URL_ATTRS:
            val = tag.get(attr)
            if isinstance(val, str):
                refs.add(val)
        if tag.get("srcset"):
            refs.update(p.strip().split(" ")[0] for p in tag["srcset"].split(","))
    for style in soup.find_all("style"):
        refs.update(css_refs(style.string or "", "/"))
    for tag in soup.find_all(style=True):
        refs.update(css_refs(tag["style"], "/"))
    # Assets loaded at runtime by inline scripts (e.g. the syntax highlighter's stylesheets).
    for script in soup.find_all("script"):
        for m in re.findall(r"(?:\\?/)wp-(?:content|includes)(?:\\?/)[^\"'\s]+", script.string or ""):
            m = m.replace("\\/", "/")
            if "." in m.split("?")[0].rsplit("/", 1)[-1]:  # files only, not base-path settings
                refs.add(m)
    return {r for r in refs if r.startswith("/") and not r.startswith("//")}


def css_refs(css, base):
    out = set()
    for m in re.finditer(r"url\(\s*['\"]?([^'\")]+)['\"]?\s*\)", css):
        u = m.group(1)
        if u.startswith("data:") or u.startswith("http") or u.startswith("//"):
            continue
        out.add(urllib.parse.urljoin(base, u))
    return out


def url_to_file(url):
    path = urllib.parse.unquote(urllib.parse.urlsplit(url).path)
    if path.endswith("/"):
        path += "index.html"
    return path.lstrip("/")


class Mirror:
    def __init__(self, root):
        self.root = root / HOST
        # wget keeps query strings in file names (style.css?ver=1.2); index by bare path.
        self.files = {}
        for f in self.root.rglob("*"):
            if f.is_file():
                self.files.setdefault(str(f.relative_to(self.root)).split("?")[0], f)

    def get(self, rel):
        if rel in self.files:
            return self.files[rel]
        # Not crawled (e.g. only referenced via an old hostname): fetch it from the live site.
        url = SITE + "/" + urllib.parse.quote(rel)
        dest = self.root / rel
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                data = r.read()
        except Exception as e:
            print(f"  missing: /{rel} ({e})")
            return None
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        self.files[rel] = dest
        print(f"  fetched: /{rel}")
        return dest


def redirect_stub(target):
    return f"""<!doctype html>
<html lang="en-US">
<head>
<meta charset="utf-8">
<title>Redirecting&hellip;</title>
<link rel="canonical" href="{SITE}{target}">
<meta name="robots" content="noindex">
<meta http-equiv="refresh" content="0; url={target}">
</head>
<body><p>This page has moved to <a href="{target}">{target}</a>.</p></body>
</html>
"""


def main():
    mirror_dir, out = Path(sys.argv[1]), Path(sys.argv[2])
    mirror = Mirror(mirror_dir)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    def parse(path):
        return BeautifulSoup(localize_urls(path.read_text(encoding="utf-8")), "lxml")

    pages = {}  # output rel path -> html
    stubs = []
    for rel, f in sorted(mirror.files.items()):
        if not rel.endswith(".html"):
            continue
        if is_dropped(rel):
            stubs.append(rel)
            continue
        soup = parse(f)
        if rel == "articles/index.html":
            extra = [parse(p) for r, p in sorted(mirror.files.items()) if r.startswith("articles/page/") and r.endswith(".html")]
            merge_article_list(soup, extra)
        if rel == "contact-us/index.html":
            fix_contact_page(soup)
        remove_wp_cruft(soup)
        tidy_urls(soup)
        set_canonical(soup, page_path(rel))
        pages[rel] = soup

    not_found = mirror_dir / "404.html"
    if not_found.exists():
        soup = parse(not_found)
        remove_wp_cruft(soup)
        fix_404_page(soup)
        tidy_urls(soup)
        link = soup.head.find("link", rel="canonical")
        if link:
            link.decompose()
        pages["404.html"] = soup

    for rel, soup in pages.items():
        dest = out / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(str(soup), encoding="utf-8")
    for rel in stubs:
        dest = out / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(redirect_stub("/articles/"), encoding="utf-8")

    # Copy every asset the pages reference, following url() references inside CSS.
    queue = set()
    for rel in pages:
        queue |= local_refs((out / rel).read_text(encoding="utf-8"))
    seen = set()
    broken = []
    while queue:
        url = queue.pop()
        rel = url_to_file(url)
        if rel in seen:
            continue
        seen.add(rel)
        if (out / rel).exists():
            continue
        if rel.endswith(".html") or rel.endswith("/index.html"):
            broken.append(url)
            continue
        src = mirror.get(rel)
        if src is None:
            broken.append(url)
            continue
        dest = out / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if rel.endswith(".css"):
            css = localize_urls(src.read_text(encoding="utf-8"))
            dest.write_text(css, encoding="utf-8")
            queue |= css_refs(css, "/" + rel)
        else:
            shutil.copyfile(src, dest)

    (out / "robots.txt").write_text(f"User-agent: *\nAllow: /\n\nSitemap: {SITE}/sitemap.xml\n")
    urls = sorted(page_path(r) for r in pages if r != "404.html")
    (out / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "".join(f"  <url><loc>{SITE}{u}</loc></url>\n" for u in urls)
        + "</urlset>\n"
    )

    print(f"{len(pages)} pages, {len(stubs)} redirect stubs, {len(seen)} referenced paths")
    if broken:
        print("Broken internal references:")
        for b in sorted(broken):
            print("  ", b)
        sys.exit(1)


if __name__ == "__main__":
    main()
