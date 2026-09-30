# Finanzas personales (local, en tu Mac)

Lee tus cartolas (cuenta corriente PDF + tarjeta de crédito XLS), las clasifica, cuadra los totales con el banco y te entrega un reporte con hallazgos, gráficos, historial y presupuesto. Todo corre en tu computador.

## Instalar en el Mac mini

1. Descarga el proyecto: `git clone https://github.com/dgonz-code/Reporte-finanzas-automatizado.git` (o el botón *Code → Download ZIP* de GitHub) y entra a la carpeta.
2. **Doble clic en `iniciar.command`.** La primera vez instala lo necesario (2–3 minutos) y abre la aplicación en tu navegador.
   - Si macOS dice que no puede abrirlo: clic derecho → *Abrir*. Si venía de un ZIP y no se ejecuta, en Terminal: `chmod +x iniciar.command`.
   - Requiere Python 3.9 o superior (`python3 --version`).
3. En la pantalla **Ajustes** (una sola vez):
   - **Gmail:** tu correo + una *contraseña de aplicación* (Cuenta de Google → Seguridad → Verificación en 2 pasos → Contraseñas de aplicaciones). Se guarda en el **Llavero de macOS**.
   - **Clave del PDF** de la cuenta corriente (también al Llavero).
   - **Claude (opcional):** ver más abajo.

## Uso mensual

1. **Reporte → Traer de Gmail** baja la cartola de la cuenta corriente (remitente `cartolas.info@scotiabank.cl`).
2. Descarga el `.xls` de la tarjeta desde el banco y **súbelo** en la misma pantalla (la tarjeta no llega por correo).
3. **Generar reporte.** Verás ingresos, gastos, balance, si cada cartola **cuadra con el banco**, hallazgos, alertas y gráficos. Puedes descargar el PDF o **enviártelo por correo**.
4. En **Clasificar** enseñas y corriges: eliges la categoría en el desplegable de cada comercio y **Guardar**. Queda aprendido y el reporte se actualiza al instante, sin volver a subir nada.
5. **Historial** muestra la evolución mes a mes y compara contra tu **presupuesto** por categoría.

Tus datos quedan en la carpeta `data/` (ignorada por git).

## Que se ejecute solo cada mes

1. Abre la aplicación una vez con `iniciar.command` (configura Gmail y la clave del PDF en Ajustes).
2. **Doble clic en `instalar_automatico.command`.** Programa una tarea de macOS (LaunchAgent) que corre del **día 2 al 8 de cada mes, 09:30**, y hace una prueba inmediata sin enviar correo.
3. Cada mes, solo tienes que **dejar el `.xls` de la tarjeta en la carpeta `entrada/`** de este proyecto. El resto es automático:
   - baja la cartola de Gmail y toma la tarjeta de `entrada/`;
   - si falta algo, te avisa con una **notificación de macOS** y **no envía nada a medias**; vuelve a intentarlo al día siguiente;
   - si ambos archivos son del mismo mes, genera el reporte y **te lo envía por correo**;
   - no reenvía lo mismo dos veces (se guarda una huella de los archivos procesados).
4. Las clasificaciones dudosas te las avisa en la notificación y en el correo; las resuelves cuando quieras en la pantalla **Clasificar**.

Notas: el modo desatendido **nunca usa IA** (nadie podría confirmar sus sugerencias). Deja el `.xls` dentro de la carpeta del proyecto y no en *Descargas*: macOS pide permisos especiales para leer esa carpeta desde tareas en segundo plano. El Mac debe estar encendido; si estaba dormido a la hora programada, macOS la ejecuta al despertar. Registro: `data/automatico.log`. Para desactivar: `desinstalar_automatico.command`.

## ¿Usa IA? Tú decides

**Por defecto no.** Leer las cartolas, calcular, cuadrar y reportar es todo código: gratis y sin enviar nada fuera. La IA solo sirve para sugerir la categoría de comercios desconocidos y redactar el resumen.

| Modo (Ajustes → Claude) | Qué usa | Costo |
|---|---|---|
| No usar IA (defecto) | Reglas + lo que tú enseñas | $0 |
| Usar mi plan de Claude | Claude Code instalado en el Mac y con sesión iniciada (`claude -p`) | Sin cargo adicional; cuenta contra el cupo del plan (~5.600 tokens de entrada con agosto) |

Con el modo Claude activo aparecen el botón **🤖 Pedir sugerencias a Claude** en *Clasificar* y la casilla de redacción en *Reporte*. Sus sugerencias quedan marcadas como "IA" para que las confirmes. El agente desactiva las herramientas de Claude Code: cada llamada usa ~1.500 tokens de contexto.

## Cómo aprende la clasificación

Escalera por comercio (se detiene en el primer paso que resuelve): **1) lo que tú elegiste** (manda siempre) → 2) reglas (`src/reporte/reglas_categorias.json`, editable) → 3) sugerencia previa de la IA con confianza alta → 4) IA si está activada → 5) te pregunta. Las transferencias entre personas se agrupan por **RUT**; si el nombre coincide con el titular de la cuenta se sugiere "Transferencia propia (interno)" para que no cuenten como ingreso/gasto. El pago de la tarjeta desde la cuenta corriente también se excluye (evita contarlo dos veces).

## Avanzado (terminal)

```bash
python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
cp .env.example .env
PYTHONPATH=src python -m reporte.main --cuenta entrada/cartola.pdf --tarjeta entrada/tarjeta.xls --no-send
PYTHONPATH=src python -m reporte.main --preguntar --no-send      # preguntas por consola
```
Opcional (`pip install -r requirements-extra.txt`): Gmail/Google Sheets por API de Google (`--sheets`, ver `src/reporte/sheets_client.py`) y modo API de Anthropic (`REPORTE_LLM=api`, **se paga aparte del plan**).

## Privacidad

Las cartolas se leen localmente. Con la IA apagada no sale nada de tu Mac, salvo el correo que tú envías. Con Claude activo solo van nombres de comercios desconocidos (sin RUT ni personas) y totales agregados. Las claves viven en el Llavero de macOS. `data/`, `entrada/`, `output/`, `.env`, `credentials.json` y `token.json` están en `.gitignore`: no subas cartolas reales al repositorio.

## Pruebas

```bash
python -m pytest
```
