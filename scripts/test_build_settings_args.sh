#!/usr/bin/env bash
# Self-check for build-settings-args.sh:  bash scripts/test_build_settings_args.sh
set -euo pipefail
parser="$(dirname "$0")/build-settings-args.sh"

expect() { # expect <name> <expected-output> ; runs the parser with the current env
  local got
  got=$(bash "$parser"; printf x)
  got=${got%x}
  if [ "$got" != "$2" ]; then
    printf 'FAIL %s\n  expected: %q\n  got:      %q\n' "$1" "$2" "$got"
    exit 1
  fi
}

unset APP_BUILD_SETTINGS
expect "unset var" ""

APP_BUILD_SETTINGS="" expect "empty var" ""

APP_BUILD_SETTINGS=$'GOOGLE_PLACES_API_KEY=abc\n# note\n\nFOO=a=b c' \
  expect "comments, blanks, = and spaces in value" $'GOOGLE_PLACES_API_KEY=abc\nFOO=a=b c\n'

APP_BUILD_SETTINGS='1BAD=x' expect "invalid key dropped" ""

APP_BUILD_SETTINGS=$'A=1\r\nB=2\r\n' expect "CRLF line endings" $'A=1\nB=2\n'

echo "build-settings-args: ok"
