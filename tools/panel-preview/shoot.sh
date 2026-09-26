#!/usr/bin/env bash
# Render every panel state to PNG with headless Chrome.
#
#   tools/panel-preview/shoot.sh [output-directory]
#
# Chrome does not exit on its own after --screenshot, so every run is wrapped
# in timeout. The page is served over HTTP because an ES module will not load
# from a file:// URL.
set -uo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
out="${1:-$here/out}"
port="${PORT:-8899}"
chrome="${CHROME:-google-chrome}"

mkdir -p "$out"

python3 -m http.server "$port" --directory "$here/../.." >/dev/null 2>&1 &
server=$!
trap 'kill "$server" 2>/dev/null' EXIT
sleep 1

base="http://127.0.0.1:${port}/tools/panel-preview/index.html"

shoot() { # name query [window-size]
  local name="$1" query="$2" size="${3:-1280,940}"
  timeout 40 "$chrome" --headless=new --no-sandbox --disable-gpu \
    --disable-dev-shm-usage --no-first-run --hide-scrollbars \
    --user-data-dir="$(mktemp -d)" --force-device-scale-factor=2 \
    --virtual-time-budget=2000 --window-size="$size" \
    --screenshot="${out}/${name}.png" "${base}?${query}" >/dev/null 2>&1
  printf '  %-26s %s bytes\n' "$name" "$(stat -c%s "${out}/${name}.png" 2>/dev/null || echo MISSING)"
}

shoot contacts-light       "s=healthy&theme=light"
shoot contacts-dark        "s=healthy&theme=dark"
shoot welcome              "s=empty&theme=light"
shoot sign-in-needed       "s=reauth&theme=light"
shoot offline-dark         "s=offline&theme=dark"
shoot connection           "s=healthy&theme=light&tab=status"
shoot connection-multi     "s=multi&theme=dark&tab=status"
shoot help                 "s=healthy&theme=light&tab=help"
shoot dialog-send          "s=healthy&theme=light&dialog=send&noanim=1"
shoot dialog-delete-dark   "s=healthy&theme=dark&dialog=delete&noanim=1"
shoot add-contact          "s=nocontacts&theme=light&add=1"
shoot toast-dark           "s=healthy&theme=dark&toast=1&noanim=1"
shoot mobile-contacts      "s=healthy&theme=light" "390,844"
shoot mobile-sign-in-dark  "s=reauth&theme=dark" "390,844"
shoot mobile-connection    "s=healthy&theme=light&tab=status" "390,844"

echo "written to ${out}"
