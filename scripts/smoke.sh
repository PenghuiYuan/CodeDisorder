#!/usr/bin/env bash
# End-to-end smoke test. Assumes the API is reachable at $API_URL.
# Usage:  ./scripts/smoke.sh                   # default http://localhost:8000
#         API_URL=http://host:8000 ./scripts/smoke.sh
set -euo pipefail

API_URL="${API_URL:-http://localhost:8000}"

say() { printf '\033[1;36m== %s ==\033[0m\n' "$*"; }
ok()  { printf '  \033[32m✓\033[0m %s\n' "$*"; }
die() { printf '  \033[31m✗\033[0m %s\n' "$*"; exit 1; }

say "health check"
status=$(curl -sS -o /tmp/cf_health.json -w "%{http_code}" "$API_URL/api/health")
[[ "$status" == "200" ]] || die "health endpoint returned $status"
ok "$(cat /tmp/cf_health.json)"
curl -sS -D - -o /dev/null "$API_URL/api/health" | grep -qi 'cache-control: no-store' \
    && ok "Cache-Control: no-store header present" \
    || die "Cache-Control: no-store missing on /api/health"

say "presets listing"
curl -sS "$API_URL/api/presets" | python3 -c "
import json, sys
d = json.load(sys.stdin)
assert 'presets' in d and d['presets'], 'no presets in /api/presets'
ids = [p['id'] for p in d['presets']]
assert 'default' in ids, f'default preset missing; got {ids}'
print(f'  presets: {ids}')
"
ok "/api/presets returned 'default'"

say "POST /api/confuse — Python"
python3 - <<'PY' | curl -sS -X POST "$API_URL/api/confuse" \
    -H 'Content-Type: application/json' -d @- > /tmp/cf_py.json
import json
print(json.dumps({
    "language_in": "python",
    "language_out": "python",
    "preset": "default",
    "count": 1,
    "code": "def add(a, b):\n    return a + b\n",
}))
PY
python3 -c "
import json
d = json.load(open('/tmp/cf_py.json'))
assert d['status'] == 'ok', d
assert d['verify'] == 'syntax-ok', d
assert 'rename' in d['applied'], d
assert 'add' not in d['code'], 'identifier rename did not apply'
print(f'  applied={d[\"applied\"]}  verify={d[\"verify\"]}  bytes={len(d[\"code\"])}')
"
ok "Python round-trip succeeded"

say "POST /api/confuse — C++"
python3 - <<'PY' | curl -sS -X POST "$API_URL/api/confuse" \
    -H 'Content-Type: application/json' -d @- > /tmp/cf_cpp.json
import json
src = '''
#include <stdio.h>
int add_numbers(int a, int b) {
    int result = a + b;
    return result;
}
int main(void) {
    printf("%d\\n", add_numbers(1, 2));
    return 0;
}
'''
print(json.dumps({
    "language_in": "cpp",
    "language_out": "cpp",
    "preset": "default",
    "count": 1,
    "code": src,
}))
PY
python3 -c "
import json
d = json.load(open('/tmp/cf_cpp.json'))
assert d['status'] == 'ok', d
assert d['verify'] == 'compiled', d
assert 'rename' in d['applied'], d
print(f'  applied={d[\"applied\"]}  verify={d[\"verify\"]}  bytes={len(d[\"code\"])}')
"
ok "C++ round-trip compiled"

say "POST /api/confuse — Java (M1 stub: should return language_not_supported)"
python3 - <<'PY' | curl -sS -X POST "$API_URL/api/confuse" \
    -H 'Content-Type: application/json' -d @- > /tmp/cf_java.json
import json
print(json.dumps({
    "language_in": "java",
    "language_out": "java",
    "preset": "default",
    "code": "class A {}",
}))
PY
python3 -c "
import json
d = json.load(open('/tmp/cf_java.json'))
assert d['status'] == 'error', d
assert d['code'] == 'language_not_supported', d
print(f'  code={d[\"code\"]}  message={d[\"message\"]}')
"
ok "Java stub returns language_not_supported"

say "POST /api/confuse — payload too large"
big=$(python3 -c "print('x = 1\n' * (200 * 1024 // 4 + 100))")
python3 -c "
import json, sys
print(json.dumps({
    'language_in': 'python',
    'language_out': 'python',
    'preset': 'default',
    'code': '''$big''',
}))
" | curl -sS -o /tmp/cf_too_big.json -w '%{http_code}\n' -X POST \
    "$API_URL/api/confuse" -H 'Content-Type: application/json' -d @- \
    > /tmp/cf_too_big.status
status=$(cat /tmp/cf_too_big.status)
[[ "$status" == "413" ]] || die "expected 413 for oversized payload, got $status"
ok "413 returned for ~205KB payload"

printf '\n\033[1;32mAll smoke checks passed.\033[0m\n'
