# Sistema Inteligente ENAHO

De los **microdatos de la Encuesta Nacional de Hogares (ENAHO)** del INEI a un **tema de investigación económico** concreto, viable y puntuado — todo desde una TUI (interfaz de terminal).

![Diagrama del sistema: identificación y propuesta de temas a partir de la ENAHO](docs/pipeline.png)

El sistema descarga y organiza la data, la documenta, y luego usa razonamiento (con tu suscripción de Claude, vía Claude Code en modo headless) para **proponer temas, seleccionar variables, medir brechas reales con pandas, contrastar con literatura web y puntuar** la propuesta.

---

## El pipeline (10 pasos, 3 carriles)

```
① SISTEMA · Preparación        ② USUARIO · Exploración        ③ SISTEMA · Evaluación
1 Descargar data               5 Sugerir temas                8 Brechas / anomalías (pandas)
2 Organizar                    6 Analizar módulos             9 Literatura (web)
3 Inspección                   7 Selección de variables       10 Puntuación
4 Documentación (PDF + HTML)                                  → 📋 Ficha de investigación
```

- **Pasos 1–4 (deterministas):** descarga (corte transversal, CSV), organización en `modulos/` + `tablas_descripcion/`, inspección (unidad de análisis y **llave de identificación verificada**), y documentación (PDF + visor HTML interactivo con diccionario de variables).
- **Pasos 5–10 (razonamiento):** corren con tu **suscripción de Claude** (`claude -p` headless, sin API key), siempre **anclados al catálogo real de datos** (grounding) para no inventar módulos ni variables. El paso 8 **calcula brechas reales** con pandas (ponderadas, limpiando códigos de no-respuesta); el paso 9 usa **búsqueda web** con fuentes verificables.

El entregable final es una **ficha** con: tema, módulos, variables, **plan de merge y filtros**, brechas medidas y puntuación (impacto / relevancia / factibilidad).

---

## Requisitos

- Python 3.9+
- [Claude Code](https://claude.com/claude-code) instalado y con sesión iniciada (los pasos 5–10 usan `claude -p` con tu suscripción)
- Dependencias Python:

```bash
pip install -r requirements.txt
```

---

## Uso

```bash
python sistema_enaho.py
```

Se abre la TUI (full-screen). Navega con teclado o mouse:

- **1** Descargar (te pide año(s): `2024`, `2015-2020`, `2018 2019`)
- **2** Organizar · **3·4** Documentar (genera PDF, visor HTML y catálogo)
- **5 ▶ Proponer tema** — el flujo estrella: corre los pasos 5→10 y entrega la ficha
- **v** Ver propuestas guardadas · **c** Regenerar catálogo · **q** Salir

Las salidas (documentación PDF, visor HTML y fichas de investigación) se escriben en `salidas/<año>/` y `salidas/fichas/`.

---

## Estructura

```
sistema_enaho.py            # TUI principal (Textual)
scripts/
  descargar.py              # paso 1 (PyPeruStats, CSV, corte transversal)
  ordenar.py                # paso 2 (modulos/ + tablas_descripcion/)
  generar_documentacion_pdf.py   # paso 3–4 (PDF)
  generar_visor_html.py     # paso 4 (visor HTML + inspección streaming)
  catalogo.py               # catálogo de grounding (JSON)
  razonador.py              # pasos 5–10 vía claude -p
  estadistica.py            # paso 8 (brechas reales con pandas)
.claude/agents/             # agentes de apoyo (descarga, ordenar, documentar, visor, revisión)
```

Los microdatos (`enaho_*/`) y las salidas generadas (`salidas/`, `temas/`) **no se versionan** (ver `.gitignore`): son pesados y re-generables.

---

## Notas de diseño

- **Grounding total:** el razonamiento se ancla al catálogo real; no propone lo que la data no soporta.
- **Memoria acotada:** la inspección lee en *streaming* (`polars.scan_csv`), así procesa archivos de varios GB (ej. el módulo de gastos, ~9M filas) sin cargarlos enteros en RAM.
- **Honestidad:** títulos desde el diccionario oficial del INEI; llaves verificadas contra los datos; literatura con URLs reales; lo no verificado se marca como tal.
