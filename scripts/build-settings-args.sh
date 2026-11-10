#!/usr/bin/env bash
# Prints the xcodebuild build settings in $APP_BUILD_SETTINGS, one KEY=VALUE per line.
# Input is dotenv-style lines; blank lines, # comments and lines whose key is not
# [A-Za-z_][A-Za-z0-9_]* are dropped. Unset or empty prints nothing. Always exits 0.
# bash 3.2-safe (the macOS runner's /bin/bash). Self-check: scripts/test_build_settings_args.sh
while IFS= read -r line; do
  line=${line%$'\r'}
  if [[ $line =~ ^[A-Za-z_][A-Za-z0-9_]*= ]]; then printf '%s\n' "$line"; fi
done < <(printf '%s\n' "${APP_BUILD_SETTINGS-}")
exit 0
