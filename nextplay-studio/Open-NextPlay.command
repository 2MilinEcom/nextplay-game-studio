#!/bin/zsh
APP_DIR="${0:A:h}"
if ! /usr/bin/curl -fsS http://127.0.0.1:8777/health >/dev/null 2>&1; then
  mkdir -p "$APP_DIR/../studio-data/logs"
  chmod 700 "$APP_DIR/../studio-data"
  nohup /bin/zsh -lic "exec \"$APP_DIR/start-nextplay-studio.sh\"" >>"$APP_DIR/../studio-data/logs/server.log" 2>&1 &
  for i in {1..20}; do
    /usr/bin/curl -fsS http://127.0.0.1:8777/health >/dev/null 2>&1 && break
    sleep 0.25
  done
fi
open http://127.0.0.1:8777
