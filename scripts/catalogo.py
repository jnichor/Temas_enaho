# -*- coding: utf-8 -*-
"""Genera el CATÁLOGO de grounding (JSON) por año: la base de conocimiento que
ancla el razonamiento (pasos 5–10) a los datos REALES de la ENAHO.

Por cada archivo guarda: título oficial, unidad de análisis, llave verificada,
nº filas/columnas, cobertura geográfica/temporal, completitud, familias de
variables y el diccionario variable→significado.

Uso: python scripts/catalogo.py
Salida: <by_year>/<AÑO>/catalogo_<AÑO>.json
"""
import os, re, json
import pandas as pd

import generar_visor_html as G   # reutiliza inspect, parse de diccionario, etc.


def columnas_limpias(path, delim):
    try:
        return [c.strip().upper() for c in pd.read_csv(path, sep=delim, nrows=0, encoding='latin-1').columns]
    except Exception:
        return None


def construir(base, year, ydir):
    md = os.path.join(ydir, 'modulos')
    docs = os.path.join(base, 'microodatos_inei', 'enaho', '2_organized', 'documentation')
    text, dic_name = G._dic_text(docs)
    titulos = G.parse_titulos(text)
    vardic = G.parse_var_dictionary(text)
    files = sorted(f for f in os.listdir(md) if f.lower().endswith('.csv'))

    archivos = []
    for f in files:
        m = G.inspect(os.path.join(md, f))
        code = G.code_from_filename(f)
        raw = titulos.get(code) or titulos.get(re.sub(r'[A-Z]$', '', code))
        titulo = G.clean_title(raw) if raw else '(título no verificado)'
        vd = vardic.get(code) or vardic.get(re.sub(r'[A-Z]$', '', code)) or {}
        cols = columnas_limpias(os.path.join(md, f), m['delim']) or m['cols']
        variables = {c: (vd.get(c) or None) for c in cols}
        archivos.append({
            'archivo': f, 'codigo': code, 'titulo': titulo,
            'unidad_analisis': m['unidad'],
            'llave_identificacion': m['key'], 'llave_unica': m['unica'],
            'n_filas': m['nrows'], 'n_columnas': m['ncols'],
            'cobertura_geografica': m['geo'], 'meses': m['meses'],
            'completitud_pct': round(m['pct'], 1),
            'familias_variables': m['familias'],
            'variables': variables,
        })

    cat = {
        'anio': year, 'carpeta': base, 'fuente_diccionario': dic_name,
        'n_archivos': len(archivos), 'modulos': archivos,
    }
    out = os.path.join(ydir, 'catalogo_%s.json' % year)
    with open(out, 'w', encoding='utf-8') as fh:
        json.dump(cat, fh, ensure_ascii=False, indent=2)
    return out, len(archivos)


def main():
    hecho = 0
    for base, year, ydir in G.find_year_dirs():
        out, n = construir(base, year, ydir)
        print('CATÁLOGO:', out, '| módulos:', n)
        hecho += 1
    if not hecho:
        print('No hay carpetas enaho_* con datos organizados.')


if __name__ == '__main__':
    main()
