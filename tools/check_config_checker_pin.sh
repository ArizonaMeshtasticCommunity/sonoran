#!/usr/bin/env bash
# Say whether the vendored config checker is behind upstream (#61).
#
# The copy in web/static/vendor/config-checker is pinned to one commit,
# and nothing else tells us when upstream moves. This compares the pin in
# PROVENANCE.md with the head of upstream's default branch. It changes
# nothing. To update the copy, follow AGENTS.md section 8.
#
# Exit status: 0 when the pin is the upstream head, 1 when upstream has
# moved, 2 when the check could not run.
set -euo pipefail

here="$(cd "$(dirname "$0")/.." && pwd)"
provenance="$here/src/sonoran/web/static/vendor/config-checker/PROVENANCE.md"
upstream="${CONFIG_CHECKER_REPO:-https://github.com/ArizonaMeshtasticCommunity/config-checker.git}"

pin="$(grep -oE 'Commit: `[0-9a-f]{7,40}`' "$provenance" | grep -oE '[0-9a-f]{7,40}' || true)"
if [[ -z "$pin" ]]; then
  echo "cannot find the pinned commit in $provenance" >&2
  exit 2
fi

head="$(git ls-remote "$upstream" HEAD 2>/dev/null | cut -f1 || true)"
if [[ -z "$head" ]]; then
  echo "cannot read the upstream head from $upstream" >&2
  exit 2
fi

if [[ "$head" == "$pin"* ]]; then
  echo "up to date: the pin $pin is the upstream head"
  exit 0
fi
echo "upstream has moved: pinned $pin, upstream head ${head:0:7}"
echo "compare: https://github.com/ArizonaMeshtasticCommunity/config-checker/compare/$pin...${head:0:7}"
exit 1
