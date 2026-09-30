# Reporte financiero automatizado

Agente que toma tus cartolas (cuenta corriente en PDF y tarjeta de crédito en XLS) y te entrega cada mes:

- un **correo** con los principales hallazgos, y
- un **PDF** con el análisis detallado (KPIs, gastos por categoría, mayores gastos, cargos repetidos, cuotas por vencer).

## Flujo

Dos fuentes, dos caminos (el objetivo es gastar el mínimo de tokens):

| Fuente | Cómo se lee | Costo de LLM |
|---|---|---|
| Tarjeta de crédito (`.xls` Scotiabank) | Parser determinista (`card_parser.py`); cuadra al peso con el "Monto Total Facturado" del banco | $0 |
| Cuenta corriente (`.pdf`) | Texto del PDF → Claude Sonnet 5.5 (esfuerzo `low`) | 1 llamada |
| Categorías | 1) reglas por palabra clave (`reglas_categorias.json`), 2) caché de comercios ya vistos (`data/merchant_cache.json`), 3) una sola llamada a Claude con lo que quede | casi $0 desde el 2º mes |
| Insights | Una llamada con solo los agregados (no la cartola) | 1 llamada corta |

Decisiones que evitan errores:
- El **pago de la tarjeta** desde la cuenta corriente se excluye de los gastos (si no, se contaría dos veces).
- Las **notas de crédito** restan del gasto; no cuentan como ingreso.
- Los totales se calculan en Python; el modelo nunca suma.
- Cada ejecución imprime tokens y costo estimado por llamada.

## Pruebas locales

```bash
pip install -r requirements.txt
cp .env.example .env    # ANTHROPIC_API_KEY, PDF_PASSWORD
mkdir entrada           # deja ahí tus cartolas (carpeta ignorada por git)

# 1) $0: solo tarjeta, sin LLM
PYTHONPATH=src python -m reporte.main --tarjeta entrada/tarjeta.xls --sin-llm --no-send

# 2) Solo tarjeta con LLM (categoriza comercios desconocidos + insights)
PYTHONPATH=src python -m reporte.main --tarjeta entrada/tarjeta.xls --no-send

# 3) Ambas cartolas
PYTHONPATH=src python -m reporte.main --cuenta entrada/cartola.pdf --tarjeta entrada/tarjeta.xls --no-send
```

Salidas: `output/reporte-AAAA-MM.pdf` y `data/AAAA-MM/` (movimientos y resumen normalizados, base para tendencias y presupuesto).

## Gmail (modo automático)

En Google Cloud crea credenciales OAuth tipo "Aplicación de escritorio", habilita la Gmail API y guarda el archivo como `credentials.json`. Ajusta `GMAIL_QUERY_CUENTA` y `GMAIL_QUERY_TARJETA` con el remitente real de cada correo. Sin `--cuenta`/`--tarjeta`, el agente descarga los adjuntos y envía el reporte. La primera ejecución abre el navegador para autorizar y crea `token.json`.

`.github/workflows/monthly.yml` lo ejecuta el día 2 de cada mes. Requiere los secrets `ANTHROPIC_API_KEY`, `GOOGLE_CREDENTIALS_JSON`, `GOOGLE_TOKEN_JSON`, `GMAIL_QUERY_CUENTA`, `GMAIL_QUERY_TARJETA` y `PDF_PASSWORD`.

## Privacidad

La cartola de la cuenta corriente se envía a la API de Anthropic para analizarla (la de tarjeta no: se lee con código; solo los nombres de comercios desconocidos y los agregados van al modelo). `credentials.json`, `token.json`, `.env`, `output/`, `data/` y `entrada/` están en `.gitignore`: no subas cartolas reales al repositorio.

## Pruebas

```bash
python -m pytest
```
