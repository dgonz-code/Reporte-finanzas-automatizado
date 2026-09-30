#!/bin/bash
# Doble clic para abrir la aplicacion. La primera vez instala lo necesario (2-3 minutos).
cd "$(dirname "$0")" || exit 1

if ! command -v python3 >/dev/null 2>&1; then
  osascript -e 'display alert "Falta Python 3" message "Instalalo desde python.org/downloads y vuelve a abrir este archivo."'
  exit 1
fi
if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)'; then
  osascript -e 'display alert "Python muy antiguo" message "Se necesita Python 3.9 o superior. Instala uno nuevo desde python.org/downloads."'
  exit 1
fi

[ -d .venv ] || python3 -m venv .venv
source .venv/bin/activate

# Reinstala solo si cambio requirements.txt
if [ ! -f .venv/.instalado ] || [ requirements.txt -nt .venv/.instalado ]; then
  echo "Instalando dependencias (solo la primera vez)..."
  pip install --quiet --upgrade pip && pip install --quiet -r requirements.txt && touch .venv/.instalado || {
    echo "No se pudo instalar. Revisa tu conexion a internet y vuelve a intentar."; read -r -p "Enter para cerrar"; exit 1; }
fi

# Evita que Streamlit pregunte un correo en la terminal
mkdir -p ~/.streamlit
[ -f ~/.streamlit/credentials.toml ] || printf '[general]\nemail = ""\n' > ~/.streamlit/credentials.toml

echo "Abriendo la aplicacion en tu navegador... (para cerrarla, cierra esta ventana)"
exec python -m streamlit run app.py --browser.gatherUsageStats false
