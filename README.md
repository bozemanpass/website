# website
BPI Public Website

Static version of https://www.bozemanpass.com, converted from the former WordPress (Divi theme) site.

## Layout

- `site/` — the document root. Everything here is served as-is; edit these files to change the site.
- `tools/crawl.sh`, `tools/build.py` — the one-off scripts used to crawl the WordPress site and clean it up into `site/`. Kept for reference / re-running while WordPress is still live.
- `deploy/nginx.conf` — server config for hosting on a VM with nginx.
- `.github/workflows/pages.yml` — deploys `site/` to GitHub Pages on push to `main`.

URLs are root-relative (`/wp-content/...`), so the site must be served at the root of a domain (fine for both nginx and GitHub Pages with a custom domain).

## What changed from the WordPress site

- Contact form removed (contact page keeps email, phone and PGP key).
- Blog structure dropped: the "Latest News" page (`/articles/`) is a single static list of all posts; category, tag, author and date archive URLs are redirect stubs to `/articles/`.
- Every post keeps its original URL, including `/info/linux/malloc/Linux_Heap_Contention.html`.
- Sidebar search, archives, categories, recent comments and meta widgets removed; "Recent Posts" kept.
- RSS feed, WordPress REST/xmlrpc endpoints and the (defunct) Universal Analytics tag removed.
- Images in posts that pointed at old hostnames (`www-new.`, `server1010618.`) now load locally.
- Added `404.html`, `robots.txt` and `sitemap.xml`.

## Testing locally

    python3 -m http.server 8000 -d site

## Re-crawling (only while the WordPress site is still up)

    python3 -m venv .venv && .venv/bin/pip install -r tools/requirements.txt
    tools/crawl.sh mirror
    .venv/bin/python tools/build.py mirror site

## Deploying

**GitHub Pages:** in the repo settings, set Pages → Source to "GitHub Actions" and set the custom domain to `www.bozemanpass.com`; then point DNS (`www` CNAME → `<org>.github.io`) at it.

**nginx:** copy `site/` to the server's web root and install `deploy/nginx.conf` (see comments in it for TLS).
