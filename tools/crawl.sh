#!/usr/bin/env bash
# Mirror the public WordPress site into a local directory, for tools/build.py to clean up.
# Usage: tools/crawl.sh <mirror-dir>
set -euo pipefail

SITE=https://www.bozemanpass.com
OUT=${1:?usage: crawl.sh <mirror-dir>}
mkdir -p "$OUT"
cd "$OUT"

# Seed from the WordPress sitemaps so every post and page is found even if nothing links to it.
curl -fsS "$SITE/wp-sitemap.xml" | grep -o '<loc>[^<]*</loc>' | sed 's/<[^>]*>//g' |
  while read -r sm; do curl -fsS "$sm" | grep -o '<loc>[^<]*</loc>' | sed 's/<[^>]*>//g'; done > seed.txt
echo "$SITE/" >> seed.txt

# wget exits non-zero when any URL 404s, which a few dead links on the site do.
wget --mirror --page-requisites --no-parent \
  --span-hosts --domains=www.bozemanpass.com \
  --reject-regex '(/wp-json|/feed/|xmlrpc\.php|/wp-admin|/comments/|replytocom|\?p=|/wp-login)' \
  --wait=0.2 -i seed.txt -o wget.log || true

# The WordPress 404 page, used as the template for the static 404.html.
curl -sS -o 404.html "$SITE/this-page-does-not-exist-404/"
echo "Mirrored $(find www.bozemanpass.com -type f | wc -l) files into $OUT"
