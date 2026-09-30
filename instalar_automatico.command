#!/bin/bash
# Doble clic: programa el reporte para que se genere solo cada mes en este Mac.
cd "$(dirname "$0")" || exit 1
[ -x .venv/bin/python ] || { echo "Primero abre la aplicacion una vez con iniciar.command"; read -r -p "Enter para cerrar"; exit 1; }
.venv/bin/python -m reporte.launchd instalar || { read -r -p "Enter para cerrar"; exit 1; }
echo
echo "Prueba ahora (no envia correo; te mostrara una notificacion):"
PYTHONPATH=src .venv/bin/python -m reporte.automatico --forzar --sin-enviar
read -r -p "Enter para cerrar"
