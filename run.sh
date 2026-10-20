#!/usr/bin/env bash
# Start the local EgyFy Parser server.

set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

has_indra() {
  "$1" -c "import indra_ocr" >/dev/null 2>&1
}

find_python() {
  local candidate
  for candidate in \
    "${EGYFY_PYTHON:-}" \
    "${INDRA_PYTHON:-}" \
    "$ROOT/.venv/bin/python" \
    "$ROOT/../indra/.venv/bin/python" \
    "${HOME:-}/indra/.venv/bin/python"; do
    if [[ -n "$candidate" && -x "$candidate" ]] && has_indra "$candidate"; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  if command -v python3 >/dev/null 2>&1 && has_indra python3; then
    command -v python3
    return 0
  fi
  return 1
}

PY="$(find_python || true)"
if [[ -z "$PY" ]]; then
  cat >&2 <<'EOF'
No Python environment with Indra OCR was found.

Create one from this directory:

  python3 -m venv .venv
  .venv/bin/pip install -r requirements.txt

Or point to an existing interpreter:

  EGYFY_PYTHON=/path/to/python ./run.sh
EOF
  exit 1
fi

exec "$PY" -m egyfy "$@"
