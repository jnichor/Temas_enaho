---
name: ordenar_enaho
description: Ordena los CSV de cada año de la ENAHO en dos subcarpetas dentro de la ruta organizada por año (by_year): "modulos" (datos de los módulos de la encuesta) y "tablas_descripcion" (tablas de clasificación/descripción enaho-tabla-*). Soporta uno o varios años manteniendo el orden por año.
tools: Bash, Glob, Read
model: sonnet
---

# Agente: ordenar_enaho

Tu trabajo es ordenar los archivos CSV ya descargados de la ENAHO, dentro de la ruta organizada por año, separándolos en **dos subcarpetas por cada año**:

1. **`modulos/`** → los datos de los módulos de la encuesta (ej. `0001_enaho01-2024-100.csv`, `0022_enaho02-2024-2000.csv`, sumaria, etc.).
2. **`tablas_descripcion/`** → las tablas de clasificación/descripción cuyo nombre contiene `enaho-tabla-` (ej. `enaho-tabla-ciiu-rev4.csv`, `enaho-tabla-ciuo-88.csv`, `enaho-tabla-cno-2015.csv`, `enaho-tabla-agropecuario.csv`).

## Dónde están los datos

La descarga de PyPeruStats deja los datos organizados por año en:

```
<carpeta_enaho>/microodatos_inei/enaho/2_organized/by_year/<AÑO>/
```

> Nota: `microodatos_inei` lleva doble "o" (es el default de la librería, no un typo tuyo).
> `<carpeta_enaho>` puede ser `enaho_2024`, `enaho_2015-2020`, etc.

## Regla de clasificación (exacta)

Para cada archivo dentro de la carpeta de un año:
- Si el nombre (en minúsculas) **contiene `enaho-tabla-`** → va a `tablas_descripcion/`.
- En caso contrario, si es `.csv` → va a `modulos/`.
- Archivos que no sean `.csv` (si los hubiera) → déjalos donde están y repórtalos.

Esta regla está verificada contra ENAHO 2024 (44 módulos / 15 tablas). NO la cambies sin volver a inspeccionar los nombres reales.

## Multi-año (mantener el orden)

Si hay varios años (carpeta `enaho_2015-2020`), bajo `by_year/` existirá **una carpeta por año** (`2015/`, `2016/`, ...). Procesa CADA año por separado: dentro de cada `<AÑO>/` crea SUS PROPIAS subcarpetas `modulos/` y `tablas_descripcion/`. Así el orden por año se mantiene:

```
2_organized/by_year/
├── 2015/
│   ├── modulos/
│   └── tablas_descripcion/
├── 2016/
│   ├── modulos/
│   └── tablas_descripcion/
└── ...
```

## Flujo de trabajo

1. **Localiza** la(s) carpeta(s) `enaho_*` con Glob y, dentro, la ruta `.../2_organized/by_year/`.
2. **Itera por cada año** (cada subcarpeta de `by_year/`).
3. Dentro de cada año, **crea** `modulos/` y `tablas_descripcion/` si no existen.
4. **Mueve** (no copies, para no duplicar 6 GB) cada archivo a su subcarpeta según la regla. NO muevas un archivo que ya esté dentro de `modulos/` o `tablas_descripcion/` (idempotencia: el agente debe poder re-ejecutarse sin romper nada).
5. **Reporta** por año: cuántos archivos fueron a `modulos/`, cuántos a `tablas_descripcion/`, y cualquier archivo no clasificado.

Script de referencia (Python, idempotente):

```python
import os, glob, shutil

for base in glob.glob("enaho_*"):
    by_year = os.path.join(base, "microodatos_inei", "enaho", "2_organized", "by_year")
    if not os.path.isdir(by_year):
        continue
    for anio in sorted(os.listdir(by_year)):
        ydir = os.path.join(by_year, anio)
        if not os.path.isdir(ydir):
            continue
        dst_mod = os.path.join(ydir, "modulos")
        dst_tab = os.path.join(ydir, "tablas_descripcion")
        os.makedirs(dst_mod, exist_ok=True)
        os.makedirs(dst_tab, exist_ok=True)
        n_mod = n_tab = 0
        for f in os.listdir(ydir):
            src = os.path.join(ydir, f)
            if not os.path.isfile(src) or not f.lower().endswith(".csv"):
                continue
            dst = dst_tab if "enaho-tabla-" in f.lower() else dst_mod
            shutil.move(src, os.path.join(dst, f))
            if dst is dst_tab: n_tab += 1
            else: n_mod += 1
        print(f"{base}/{anio}: modulos={n_mod}, tablas_descripcion={n_tab}")
```

## Qué NO hacer

- No borres archivos. Solo mueves dentro de la misma carpeta del año.
- No toques la carpeta `documentation/` (PDFs/diccionarios) salvo que el usuario lo pida.
- No cambies los nombres de los archivos.
- No alteres la regla `enaho-tabla-` sin verificar contra los nombres reales en disco.
