#!/usr/bin/env bash
set -eu

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="${DIR}/.."
VENV_DIR="${ROOT_DIR}/venv"
PY="${VENV_DIR}/bin/python3"
OUT_DIR="${ROOT_DIR}/outputs"
UNIT_NAME="crashwatch.service"
UNIT_SRC="${DIR}/crashwatch.service"
UNIT_DST="${HOME}/.config/systemd/user/crashwatch.service"

mkdir -p "${OUT_DIR}"
mkdir -p "${HOME}/.config/systemd/user"

ensure_venv() {
  if [ -x "${PY}" ]; then
    return 0
  fi
  python3 -m venv "${VENV_DIR}"
  if [ -f "${ROOT_DIR}/requirements.txt" ]; then
    "${VENV_DIR}/bin/pip" install -q -r "${ROOT_DIR}/requirements.txt"
  else
    "${VENV_DIR}/bin/pip" install -q nvidia-ml-py psutil PyYAML python-dotenv
  fi
}

refresh_unit() {
  cp "${UNIT_SRC}" "${UNIT_DST}"
  systemctl --user daemon-reload
}

active_csv() {
  if [ -f "${OUT_DIR}/crashwatch_latest_path.txt" ]; then
    cat "${OUT_DIR}/crashwatch_latest_path.txt"
    return 0
  fi
  ls -1t "${OUT_DIR}"/crashwatch_*.csv 2>/dev/null | head -1
}

cmd_start() {
  ensure_venv
  refresh_unit
  systemctl --user enable --now "${UNIT_NAME}"
  sleep 1
  echo "crashwatch: avviato"
  echo "  unit    : ${UNIT_NAME}"
  echo "  enabled : $(systemctl --user is-enabled "${UNIT_NAME}" 2>/dev/null || echo unknown)"
  echo "  active  : $(systemctl --user is-active "${UNIT_NAME}" 2>/dev/null || echo unknown)"
  echo "  outfile : $(active_csv)"
}

cmd_stop() {
  systemctl --user stop "${UNIT_NAME}" 2>/dev/null || true
  echo "crashwatch: fermato"
}

cmd_status() {
  echo "crashwatch: $(systemctl --user is-active "${UNIT_NAME}" 2>/dev/null || echo unknown)"
  echo "  enabled : $(systemctl --user is-enabled "${UNIT_NAME}" 2>/dev/null || echo unknown)"
  echo "  last csv : $(active_csv || true)"
  systemctl --user status "${UNIT_NAME}" --no-pager 2>/dev/null | sed -n '1,10p' || true
}

cmd_tail() {
  local out
  out="$(active_csv || true)"
  if [ -z "${out}" ] || [ ! -f "${out}" ]; then
    echo "crashwatch: nessun CSV presente"
    return 1
  fi
  echo "# ${out}"
  tail -20 "${out}"
}

cmd_stats() {
  local out
  out="$(active_csv || true)"
  if [ -z "${out}" ] || [ ! -f "${out}" ]; then
    echo "crashwatch: nessun CSV presente"
    return 1
  fi
  echo "# ${out}"
  awk -F, 'NR>1 {
      g=$3+0; p=$4+0; c=$11+0;
      if(NR==2 || g>maxg) maxg=g;
      if(NR==2 || p>maxp) maxp=p;
      if(NR==2 || c>maxc) maxc=c;
      if(NR==2 || g<ming) ming=g;
      if(NR==2 || p<minp) minp=p;
      if(NR==2 || c<minc) minc=c;
      ng++; totg+=g; totp+=p; totc+=c
  } END {
      if(ng == 0) { print "samples  = 0"; exit 0 }
      printf "samples  = %d\n", ng
      printf "GPU temp  max %.1f C  min %.1f C  avg %.1f C\n", maxg, ming, totg/ng
      printf "GPU power max %.2f W min %.2f W avg %.2f W\n", maxp, minp, totp/ng
      printf "CPU temp  max %.1f C  min %.1f C  avg %.1f C\n", maxc, minc, totc/ng
  }' "${out}"
}

cmd_path() {
  active_csv
}

cmd_restart() {
  refresh_unit
  systemctl --user restart "${UNIT_NAME}"
  sleep 1
  cmd_status
}

case "${1:-}" in
  start) cmd_start ;;
  stop) cmd_stop ;;
  status) cmd_status ;;
  tail) cmd_tail ;;
  stats) cmd_stats ;;
  path) cmd_path ;;
  restart) cmd_restart ;;
  *)
    echo "Uso: $0 {start|stop|status|tail|stats|path|restart}" >&2
    exit 2
    ;;
esac
