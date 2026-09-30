#!/bin/bash
# Doble clic: baja la ultima version de la aplicacion y la abre. Tus datos (carpeta data/) no se tocan.
cd "$(dirname "$0")" || exit 1
if [ ! -d .git ]; then
  echo "Esta carpeta aun no esta conectada a GitHub. Sigue los pasos de 'Actualizar la aplicacion' en el README."
  read -r -p "Enter para cerrar"; exit 1
fi
echo "Buscando actualizaciones..."
if git pull --ff-only; then
  echo "Listo."
else
  echo "No se pudo actualizar (revisa tu conexion o tus credenciales de GitHub)."
  read -r -p "Enter para cerrar"; exit 1
fi
exec ./iniciar.command
