set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

for python_bin in "${SMDA_PYTHON:-}" /usr/local/bin/python3 /opt/homebrew/bin/python3 python3; do
    [ -n "$python_bin" ] || continue
    if "$python_bin" - <<'PY' >/dev/null 2>&1
import sys
raise SystemExit(0 if sys.version_info >= (3, 12) else 1)
PY
    then
        exec "$python_bin" "$script_dir/smda-scheduler-mcp.py"
    fi
done

echo "SMDA MCP requires Python >= 3.12. Set SMDA_PYTHON to a compatible interpreter." >&2
exit 1
