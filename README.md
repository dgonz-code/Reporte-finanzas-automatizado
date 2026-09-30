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

Si el formato cambia o algo no cuadra, el agente usa Claude como respaldo para extraer la cuenta corriente.

### Clasificación que aprende

Cada comercio se clasifica **una vez** y queda en la BBDD (`data/clasificaciones.db`, SQLite). Escalera, se detiene en el primer paso que resuelve:

1. **Lo que tú confirmaste** (fuente `usuario`): siempre manda, incluso sobre las reglas.
2. **Reglas** por palabra clave (`reglas_categorias.json`, editable).
3. **BBDD** con clasificaciones previas de IA/web de confianza alta.
4. **IA** (Sonnet 5.5, un solo llamado por lote): devuelve categoría y confianza 0–1.
5. **Búsqueda web** solo para lo que la IA dejó con confianza < 0.8 (se envían únicamente nombres de comercio).
6. **Te pregunta** lo que sigue dudoso y pesa (monto acumulado ≥ `REPORTE_ASK_MIN`). Tu respuesta se guarda y no se vuelve a preguntar.

Las transferencias a personas (TEF) se identifican por RUT y **no** se envían a IA ni web. Si el nombre coincide con el titular de la cuenta, se sugiere "Transferencia propia (interno)" para que no cuenten como ingreso/gasto.

Otras decisiones: el pago de la tarjeta desde la cuenta corriente se excluye del gasto (evita contarlo dos veces); las notas de crédito restan del gasto; los totales los calcula Python, el modelo nunca suma. Cada ejecución imprime tokens y costo estimado por llamada.

## Pruebas locales

```bash
pip install -r requirements.txt
cp .env.example .env    # ANTHROPIC_API_KEY, PDF_PASSWORD
mkdir entrada           # deja ahí tus cartolas (carpeta ignorada por git)

# 1) $0: solo tarjeta, sin LLM
PYTHONPATH=src python -m reporte.main --tarjeta entrada/tarjeta.xls --sin-llm --no-send

# 2) Solo tarjeta con LLM (categoriza comercios desconocidos + insights)
PYTHONPATH=src python -m reporte.main --tarjeta entrada/tarjeta.xls --no-send

# 3) Ambas cartolas (la clave del PDF va en PDF_PASSWORD, en tu .env)
PYTHONPATH=src python -m reporte.main --cuenta entrada/cartola.pdf --tarjeta entrada/tarjeta.xls --no-send

# 4) Igual, pero te consulta por consola las clasificaciones dudosas (y las aprende)
PYTHONPATH=src python -m reporte.main --cuenta entrada/cartola.pdf --tarjeta entrada/tarjeta.xls --no-send --preguntar

# Responder las dudas que quedaron pendientes en una ejecucion anterior
PYTHONPATH=src python -m reporte.clasificar
```

Salidas: `output/reporte-AAAA-MM.pdf` y `data/AAAA-MM/` (movimientos y resumen normalizados, base para tendencias y presupuesto).

## Gmail (modo automático)

En Google Cloud crea credenciales OAuth tipo "Aplicación de escritorio", habilita la Gmail API y guarda el archivo como `credentials.json`. Ajusta `GMAIL_QUERY_CUENTA` y `GMAIL_QUERY_TARJETA` con el remitente real de cada correo. Sin `--cuenta`/`--tarjeta`, el agente descarga los adjuntos y envía el reporte. La primera ejecución abre el navegador para autorizar y crea `token.json`.

`.github/workflows/monthly.yml` lo ejecuta el día 2 de cada mes. Requiere los secrets `ANTHROPIC_API_KEY`, `GOOGLE_CREDENTIALS_JSON`, `GOOGLE_TOKEN_JSON`, `GMAIL_QUERY_CUENTA`, `GMAIL_QUERY_TARJETA` y `PDF_PASSWORD`.

## Privacidad

Las cartolas se leen localmente. A la API de Anthropic solo van los nombres de comercios desconocidos (sin RUT ni personas) y los totales agregados para redactar el análisis; la cartola completa solo se envía si el parser falla y se usa el respaldo con IA. `credentials.json`, `token.json`, `.env`, `output/`, `data/` y `entrada/` están en `.gitignore`: no subas cartolas reales al repositorio.

## Pruebas

```bash
python -m pytest
```
