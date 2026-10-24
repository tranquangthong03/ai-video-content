#!/usr/bin/env bash
# Generates Pydantic v2 (Python) and Zod (TypeScript) models from schemas/*.json.
# Source of truth: packages/script-schema/schemas. Never edit generated output by hand.
# Usage: codegen.sh          regenerate in place
#        codegen.sh --check  generate into a temp dir and fail if generated files drifted
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
HEADER="# AUTO-GENERATED — DO NOT EDIT. Run 'make codegen'."

# generate <py_out> <render_out> <web_out>
generate() {
  local py_out="$1" render_out="$2" web_out="$3"

  rm -rf "$py_out"
  uvx --from datamodel-code-generator datamodel-codegen \
    --input "$HERE/schemas" \
    --input-file-type jsonschema \
    --output "$py_out" \
    --output-model-type pydantic_v2.BaseModel \
    --target-python-version 3.12 \
    --use-annotated \
    --field-constraints \
    --strict-nullable \
    --enum-field-as-literal all \
    --use-union-operator \
    --use-standard-collections \
    --disable-timestamp \
    --custom-file-header "$HEADER" 2>&1 | grep -v -i "warn" || true
  # Package marker must carry the header too
  [ -s "$py_out/__init__.py" ] || echo "$HEADER" > "$py_out/__init__.py"

  [ -d "$HERE/node_modules/json-schema-to-zod" ] || pnpm install --filter @svai/script-schema --dir "$ROOT"
  (cd "$HERE" && node codegen-zod.mjs --py-layouts "$py_out" "$render_out=.js" "$web_out")
}

if [ "${1:-}" = "--check" ]; then
  TMP="$(mktemp -d)"
  trap 'rm -rf "$TMP"' EXIT
  generate "$TMP/py" "$TMP/render" "$TMP/web"
  status=0
  diff -r "$TMP/py" "$ROOT/services/api/app/schemas/generated" -x __pycache__ || status=1
  diff -r "$TMP/render" "$ROOT/apps/render/src/generated" || status=1
  diff -r "$TMP/web" "$ROOT/apps/web/lib/generated" || status=1
  if [ "$status" -ne 0 ]; then
    echo "Generated files are out of date. Run 'make codegen'." >&2
    exit 1
  fi
  echo "codegen up to date"
else
  generate "$ROOT/services/api/app/schemas/generated" \
    "$ROOT/apps/render/src/generated" \
    "$ROOT/apps/web/lib/generated"
fi
