#!/usr/bin/env bash
set -eu

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="${DIR}/.."
VENV_DIR="${ROOT_DIR}/venv"
PY="${VENV_DIR}/bin/python3"
OUT_DIR="${ROOT_DIR}/outputs"

mkdir -p "${OUT_DIR}"

if [ ! -x "${PY}" ]; then
  python3 -m venv "${VENV_DIR}"
  if [ -f "${ROOT_DIR}/requirements.txt" ]; then
    "${VENV_DIR}/bin/pip" install -q -r "${ROOT_DIR}/requirements.txt"
  else
    "${VENV_DIR}/bin/pip" install -q nvidia-ml-py psutil PyYAML python-dotenv
  fi
fi

STAMP="$(date +%Y%m%d_%H%M%S)"
OUTFILE="${OUT_DIR}/crashwatch_${STAMP}.csv"
printf '%s\n' "${OUTFILE}" > "${OUT_DIR}/crashwatch_latest_path.txt"
exec "${PY}" -u "${DIR}/monitor_realtime.py" --hz 1 --out "${OUTFILE}" --duration 0
