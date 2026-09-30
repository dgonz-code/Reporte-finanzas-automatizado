# Reporte financiero automatizado

Agente que toma tus cartolas (cuenta corriente en PDF y tarjeta de crédito en XLS) y te entrega cada mes:

- un **correo** con los principales hallazgos, y
- un **PDF** con el análisis detallado (KPIs, gastos por categoría, mayores gastos, cargos repetidos, cuotas por vencer).

## Flujo

Ambas cartolas se leen **con código, sin IA** (costo $0) y se validan contra los totales que declara el propio banco:

| Fuente | Lectura | Validación |
|---|---|---|
| Tarjeta (`.xls` Scotiabank) | `card_parser.py` | suma de cargos = "Monto Total Facturado" |
| Cuenta corriente (`.pdf`, con clave) | `account_parser.py`: el signo sale de la variación del saldo | abonos, cargos y saldo final = los declarados |

Si el formato cambia o algo no cuadra, y tienes la IA activada, se usa como respaldo para extraer la cuenta corriente; sin IA, se avisa y se usa lo leído.

### Clasificación que aprende

Cada comercio se clasifica **una vez** y queda en la BBDD (`data/clasificaciones.db`, SQLite). Escalera, se detiene en el primer paso que resuelve:

1. **Lo que tú confirmaste** (fuente `usuario`): siempre manda, incluso sobre las reglas.
2. **Reglas** por palabra clave (`reglas_categorias.json`, editable).
3. **BBDD** con clasificaciones previas de IA/web de confianza alta.
4. **IA** (solo si la activaste): un solo llamado por lote; devuelve categoría y confianza 0–1.
5. **Búsqueda web** (solo con `REPORTE_LLM=api` y `REPORTE_WEB=1`) para lo que la IA dejó con confianza < 0.8; se envían únicamente nombres de comercio.
6. **Te pregunta** lo que sigue dudoso y pesa (monto acumulado ≥ `REPORTE_ASK_MIN`). Tu respuesta se guarda y no se vuelve a preguntar.

Las transferencias a personas (TEF) se identifican por RUT y **no** se envían a IA ni web. Si el nombre coincide con el titular de la cuenta, se sugiere "Transferencia propia (interno)" para que no cuenten como ingreso/gasto.

Otras decisiones: el pago de la tarjeta desde la cuenta corriente se excluye del gasto (evita contarlo dos veces); las notas de crédito restan del gasto; los totales los calcula Python, el modelo nunca suma. Cada ejecución imprime tokens y costo estimado por llamada.

## Uso mensual

1. Descarga el `.xls` de la tarjeta desde el sitio del banco y déjalo en `entrada/` (o apunta `REPORTE_ENTRADA` a tu carpeta de Descargas; se toma el más reciente que calce con `REPORTE_TARJETA_GLOB`).
2. Ejecuta:

```bash
pip install -r requirements.txt
cp .env.example .env          # completa PDF_PASSWORD y lo que uses

PYTHONPATH=src python -m reporte.main --no-send               # prueba: solo genera output/reporte-AAAA-MM.pdf
PYTHONPATH=src python -m reporte.main --sheets                # guarda en Google Sheets y envia el correo
PYTHONPATH=src python -m reporte.main --preguntar --no-send   # te consulta las clasificaciones dudosas
PYTHONPATH=src python -m reporte.clasificar                   # responde las dudas pendientes de una corrida anterior
```

La cuenta corriente se baja sola de Gmail (remitente `cartolas.info@scotiabank.cl`). Sin Gmail configurado, toma el PDF más reciente de `entrada/`. También puedes pasar archivos a mano con `--cuenta` y `--tarjeta`.

## ¿Usa IA? Tú decides (`REPORTE_LLM`)

**Por defecto no.** Leer las cartolas, calcular totales, conciliar y armar el reporte es todo código: $0 y sin enviar nada a nadie. La IA solo sirve para dos cosas opcionales: adivinar la categoría de comercios que no reconocen las reglas y redactar el resumen.

| Valor | Qué usa | Costo |
|---|---|---|
| `none` (defecto) | Reglas + BBDD + tus respuestas (`--preguntar`) | $0 |
| `claude-code` | Tu plan de Claude, vía `claude -p` (requiere Claude Code con sesión iniciada) | Sin costo adicional; cuenta contra el cupo de tu plan. Con agosto: 2 llamadas, ~5.600 tokens de entrada |
| `api` | API de Anthropic | **Se paga aparte del plan de $20** (el plan no incluye la API) |

Con `claude-code` el agente desactiva las herramientas de Claude Code y usa un prompt propio, así que cada llamada carga ~1.500 tokens de contexto en vez de ~32.000.

## Google Sheets

`--sheets` guarda cada mes en una planilla con 4 pestañas: `Movimientos`, `Resumen` (una fila por mes), `Categorias` (formato largo, ideal para tablas dinámicas y gráficos de tendencia) y `Presupuesto` (la llenas tú: categoría y monto mensual). Volver a correr un mes reemplaza sus filas, no las duplica.

Configuración única: en Google Cloud crea credenciales OAuth tipo "Aplicación de escritorio", habilita **Gmail API** y **Google Sheets API**, y guarda el archivo como `credentials.json`. La primera ejecución abre el navegador para autorizar (si ya tenías un `token.json` de antes, bórralo: ahora pide el permiso de Sheets).

## Privacidad

Las cartolas se leen localmente. Con `REPORTE_LLM=none` no sale nada de tu computador (salvo el correo y Google Sheets si los usas). Con IA activada solo van nombres de comercios desconocidos (sin RUT ni personas) y totales agregados. `credentials.json`, `token.json`, `.env`, `output/`, `data/` y `entrada/` están en `.gitignore`: no subas cartolas reales al repositorio.

**Ejecución automática:** por ahora el flujo es local, porque la tarjeta se descarga a mano y la BBDD de clasificaciones debe persistir entre meses (un runner de GitHub Actions parte limpio cada vez).

## Pruebas

```bash
python -m pytest
```
