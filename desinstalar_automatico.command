#!/bin/bash
cd "$(dirname "$0")" || exit 1
PYTHONPATH=src .venv/bin/python -m reporte.launchd desinstalar
read -r -p "Enter para cerrar"
