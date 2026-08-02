#!/usr/bin/env bash
# Compile the Meshtastic protobuf schema ahead of time.
#
# The config check page reads Android `.cfg` exports, which are protobuf.
# protobuf.js normally builds its decoders by compiling strings with
# `new Function`, and the dashboard forbids that: `script-src` carries no
# `unsafe-eval`, which is what stops a config someone hands us from
# becoming running code.
#
# This produces the same decoders ahead of time instead. The result calls
# `Function` nowhere, so `.cfg` files work with the policy left alone.
#
# Run this again when the vendored config checker is updated and its
# protobuf descriptor changes. Nothing runs it automatically, and the
# result is committed.
set -euo pipefail

here="$(cd "$(dirname "$0")/.." && pwd)"
static="$here/src/sonoran/web/static"
descriptor="$static/vendor/config-checker/js/protobuf/meshtastic-proto.js"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

# The descriptor is a JavaScript object on a global, not a JSON file.
node -e "
  global.window = {};
  require('$descriptor');
  require('fs').writeFileSync('$work/meshtastic.json',
    JSON.stringify(global.window.MeshtasticProto, null, 1));
"

# The generator must match the runtime we ship. protobuf.js 8 emits
# `reader.tag()`, which the vendored 7.6.3 runtime does not have, and a
# `.cfg` then fails with "reader.tag is not a function". Pin the line.
npm --prefix "$work" install --no-audit --no-fund --silent 'protobufjs-cli@^1'

runtime="$(grep -oE 'protobuf\.js v[0-9]+' "$static/vendor/config-checker/js/vendor/protobuf.min.js" | head -1 | grep -oE '[0-9]+$')"
generator="$(node -p "require('$work/node_modules/protobufjs/package.json').version.split('.')[0]")"
if [ "$runtime" != "$generator" ]; then
  echo "refusing: runtime is protobuf.js $runtime but the generator is $generator" >&2
  exit 1
fi
"$work/node_modules/.bin/pbjs" \
  -t static-module -w es6 --no-convert --no-delimited \
  -o "$work/gen.js" "$work/meshtastic.json"

# The generated file imports the runtime by a bare name, which a browser
# cannot resolve. Point it at the shim that hands over the vendored one.
# The generated file imports the runtime by a bare name, which a browser
# cannot resolve, and pbjs writes it as a namespace import. Both are
# normalised to a default import of the local shim.
sed -i -E 's|import (\* as )?\$protobuf from "protobufjs/minimal(\.js)?";|import $protobuf from "./protobuf-runtime.js";|' "$work/gen.js"

if grep -q 'protobufjs/minimal' "$work/gen.js"; then
  echo "refusing to install: the runtime import was not rewritten" >&2
  exit 1
fi

if grep -qE 'new Function|Function\(' "$work/gen.js"; then
  echo "refusing to install: the generated module still compiles code" >&2
  exit 1
fi

cp "$work/gen.js" "$static/meshtastic-static.js"
echo "wrote $static/meshtastic-static.js"
