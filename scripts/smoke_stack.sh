#!/usr/bin/env bash
# Smoke test of a running stack (docker compose): login, reference data, music, a background
# task that goes through Redis -> worker -> database, SSE and the frontend.
#
#   scripts/smoke_stack.sh API_URL WEB_URL USER PASSWORD [extra curl options, e.g. -k]
#
# No API keys are needed: "analyze" fails on purpose with "PROXYAPI_KEY is not set", and that
# proves the worker picked the task up and wrote the result where the API can read it.
set -euo pipefail

API=${1:?API url}; WEB=${2:?web url}; USER_NAME=${3:?user}; PASSWORD=${4:?password}
shift 4
CURL=(curl -fsS --max-time 20 "$@")
JAR=$(mktemp)
fail() { echo "SMOKE FAIL: $*" >&2; exit 1; }
step() { echo "== $*"; }

step "login"
"${CURL[@]}" -c "$JAR" -H 'Content-Type: application/json' \
  -d "{\"username\":\"$USER_NAME\",\"password\":\"$PASSWORD\"}" "$API/api/auth/login" >/dev/null
[ "$("${CURL[@]}" -b "$JAR" "$API/api/auth/me" | jq -r .username)" = "$USER_NAME" ] || fail "me"
[ "$("${CURL[@]}" -o /dev/null -w '%{http_code}' -s "$API/api/projects" || true)" = "401" ] || fail "anonymous access is not rejected"

step "reference data and music"
META=$("${CURL[@]}" -b "$JAR" "$API/api/meta")
[ "$(echo "$META" | jq '.music | length')" -ge 10 ] || fail "music library"
[ "$(echo "$META" | jq '.templates | length')" -eq 3 ] || fail "templates"
"${CURL[@]}" -b "$JAR" "$API/api/music/calm-blue-whale" -r 0-3 | head -c 4 | grep -q OggS || fail "music file"

step "project and a background task"
ID=$("${CURL[@]}" -b "$JAR" -H 'Content-Type: application/json' \
  -d '{"script":"Лиса жила на краю леса. Каждое утро она встречала рассвет.","style":"watercolor","format":"9:16"}' \
  "$API/api/projects" | jq -r .id)
"${CURL[@]}" -b "$JAR" -X POST "$API/api/projects/$ID/analyze" >/dev/null
STATUS=analyzing
for _ in $(seq 1 40); do
  PROJECT=$("${CURL[@]}" -b "$JAR" "$API/api/projects/$ID")
  STATUS=$(echo "$PROJECT" | jq -r .status)
  [ "$STATUS" != "analyzing" ] && break
  sleep 1
done
[ "$STATUS" = "draft" ] || fail "analyze did not finish (status $STATUS): the worker did not pick the task up"
echo "$PROJECT" | jq -r .error | grep -q "PROXYAPI_KEY" || fail "unexpected analyze error: $(echo "$PROJECT" | jq -r .error)"

step "SSE progress stream"
"${CURL[@]}" -N -b "$JAR" "$API/api/projects/$ID/events" | head -n 1 | grep -q '^data: ' || fail "SSE"

step "frontend"
for _ in $(seq 1 60); do
  "${CURL[@]}" "$WEB/" 2>/dev/null | grep -q 'id="root"' && break
  sleep 2
done
"${CURL[@]}" "$WEB/" | grep -q 'id="root"' || fail "frontend page"
# the SPA fallback: a client-side route must return the same page
"${CURL[@]}" "$WEB/projects/1" | grep -q 'id="root"' || fail "SPA route"

step "cleanup"
"${CURL[@]}" -b "$JAR" -X DELETE "$API/api/projects/$ID" >/dev/null
echo "SMOKE OK"
