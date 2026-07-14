# -*- coding: utf-8 -*-
"""Prueba estadistica.materializar_dataset con datos sinteticos que cubren:
  - archivo ya unico por llave (HOGAR.csv) -> merge directo
  - archivo item-level con resolucion 'agregar' (GASTOITEM.csv, suma, con
    comas decimales y un centinela que NO debe sumarse)
  - archivo item-level con resolucion 'restringir' (JEFEDATA.csv, jefe==1)
  - archivo item-level SIN resolucion -> se excluye, no crashea (EXCLUIDA.csv)
  - filtro numerico que se aplica de verdad (ESTADO>=1 desde un archivo aparte)
  - filtro con condicion=None -> se omite con motivo (no crashea, no inventa)
  - limpieza final: 0 comas decimales, 0 centinelas, 0 filas duplicadas por llave
"""
import os, sys, csv, json, shutil
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(PROJ)
sys.path.insert(0, os.path.join(PROJ, 'scripts'))
fails = []

def check(nombre, cond, detalle=''):
    print(('  [OK] ' if cond else '  [FALLA] ') + nombre + ((' | ' + str(detalle)) if detalle and not cond else ''))
    if not cond:
        fails.append(nombre)

YEAR = '2096'
carp = 'enaho_ztest3'
md = os.path.join(carp, 'microodatos_inei', 'enaho', '2_organized', 'by_year', YEAR, 'modulos')
os.makedirs(md, exist_ok=True)
NH = 20  # hogares

def w(nombre, header, rows):
    with open(os.path.join(md, nombre), 'w', newline='', encoding='latin-1') as fh:
        wr = csv.writer(fh); wr.writerow(header)
        for r in rows:
            wr.writerow(r)

# BASE: persona-level, unica por (CONGLOME,VIVIENDA,HOGAR,CODPERSO)
persona_rows = []
for h in range(1, NH + 1):
    persona_rows.append([str(h), '1', '11', '1', '1', '1' if h % 2 else '2', '45,0'])  # jefe
    persona_rows.append([str(h), '1', '11', '2', '2', '2' if h % 2 else '1', '20,0'])  # otro miembro
w('PERSONA.csv', ['CONGLOME', 'VIVIENDA', 'HOGAR', 'CODPERSO', 'ROL', 'P207', 'EDAD'], persona_rows)

# HOGAR: unico por hogar, con comas y UN centinela
hogar_rows = []
for h in range(1, NH + 1):
    ingreso = '99999' if h == 5 else '%d,50' % (1000 + h)
    hogar_rows.append([str(h), '1', '11', ingreso])
w('HOGAR.csv', ['CONGLOME', 'VIVIENDA', 'HOGAR', 'INGRESO_HOG'], hogar_rows)

# GASTOITEM: 3 filas por hogar (item-level), GASTO con comas + 1 centinela por hogar
gasto_rows = []
gasto_esperado = {}
for h in range(1, NH + 1):
    items = [10.5, 20.0, 5.25]
    gasto_esperado[h] = sum(items)
    for i, v in enumerate(items):
        gasto_rows.append([str(h), '1', '11', str(i + 1), str(v).replace('.', ',')])
    gasto_rows.append([str(h), '1', '11', '9', '99999'])  # centinela: NO debe sumarse
w('GASTOITEM.csv', ['CONGLOME', 'VIVIENDA', 'HOGAR', 'ITEM', 'GASTO'], gasto_rows)

# JEFEDATA: 2 filas por hogar (persona-like), EDAD_JEFE distinta jefe/otro
jefe_rows = []
for h in range(1, NH + 1):
    jefe_rows.append([str(h), '1', '11', '1', '60,0'])   # jefe (ROL=1)
    jefe_rows.append([str(h), '1', '11', '2', '99,9'])   # otro (ruido, NO debe usarse)
w('JEFEDATA.csv', ['CONGLOME', 'VIVIENDA', 'HOGAR', 'ROL', 'EDAD_JEFE'], jefe_rows)

# EXCLUIDA: 2 filas por hogar, SIN resolucion -> debe excluirse sola
excl_rows = []
for h in range(1, NH + 1):
    excl_rows.append([str(h), '1', '11', '1', 'x'])
    excl_rows.append([str(h), '1', '11', '2', 'y'])
w('EXCLUIDA.csv', ['CONGLOME', 'VIVIENDA', 'HOGAR', 'SUBITEM', 'RUIDO'], excl_rows)

# FILTROFILE: unico por hogar, ESTADO (1 para h<=15, 2 para el resto)
filtro_rows = [[str(h), '1', '11', '1' if h <= 15 else '2'] for h in range(1, NH + 1)]
w('FILTROFILE.csv', ['CONGLOME', 'VIVIENDA', 'HOGAR', 'ESTADO'], filtro_rows)

# PROGRAMA: item-level (varias filas por hogar, un codigo de programa por fila).
# h<=10 recibio el programa 2 (ademas del 1); h>10 NO lo recibio (solo el 1 o el 3).
# El filtro pide "== 2" (recibio el programa 2) sobre la MISMA variable que el plan
# de resolucion quiere resolver con 'agregar:conteo' -> el filtro debe ganar.
prog_rows = []
for h in range(1, NH + 1):
    prog_rows.append([str(h), '1', '11', '1'])
    prog_rows.append([str(h), '1', '11', '2' if h <= 10 else '3'])
w('PROGRAMA.csv', ['CONGLOME', 'VIVIENDA', 'HOGAR', 'COD_PROG'], prog_rows)

import estadistica as EST

plan_datos = {
    'nivel_de_analisis': 'persona',
    'llaves_merge': ['CONGLOME', 'VIVIENDA', 'HOGAR', 'CODPERSO'],
    'archivo_base': 'PERSONA.csv',
    'secuencia_merge': [
        {'archivo': 'PERSONA.csv', 'tipo': 'base', 'llaves_join': ['CONGLOME', 'VIVIENDA', 'HOGAR', 'CODPERSO'], 'variables': ['EDAD']},
        {'archivo': 'HOGAR.csv', 'tipo': 'left', 'llaves_join': ['CONGLOME', 'VIVIENDA', 'HOGAR'], 'variables': ['INGRESO_HOG'], 'broadcast': True},
        {'archivo': 'GASTOITEM.csv', 'tipo': 'left', 'llaves_join': ['CONGLOME', 'VIVIENDA', 'HOGAR'], 'variables': ['GASTO'], 'broadcast': True},
        {'archivo': 'JEFEDATA.csv', 'tipo': 'left', 'llaves_join': ['CONGLOME', 'VIVIENDA', 'HOGAR'], 'variables': ['EDAD_JEFE'], 'broadcast': True},
        {'archivo': 'EXCLUIDA.csv', 'tipo': 'left', 'llaves_join': ['CONGLOME', 'VIVIENDA', 'HOGAR'], 'variables': ['RUIDO'], 'broadcast': True},
        {'archivo': 'PROGRAMA.csv', 'tipo': 'left', 'llaves_join': ['CONGLOME', 'VIVIENDA', 'HOGAR'], 'variables': ['COD_PROG'], 'broadcast': True},
    ],
}
manifiesto = [
    {'archivo': 'PERSONA.csv', 'variable': 'EDAD', 'rol': 'control'},
    {'archivo': 'HOGAR.csv', 'variable': 'INGRESO_HOG', 'rol': 'dependiente'},
    {'archivo': 'GASTOITEM.csv', 'variable': 'GASTO', 'rol': 'independiente'},
    {'archivo': 'JEFEDATA.csv', 'variable': 'EDAD_JEFE', 'rol': 'control'},
    {'archivo': 'EXCLUIDA.csv', 'variable': 'RUIDO', 'rol': 'control'},
    {'archivo': 'PROGRAMA.csv', 'variable': 'COD_PROG', 'rol': 'independiente'},
]
resolucion = [
    {'archivo': 'GASTOITEM.csv', 'variable': 'GASTO', 'estrategia': 'agregar', 'funcion': 'suma'},
    {'archivo': 'JEFEDATA.csv', 'variable': 'EDAD_JEFE', 'estrategia': 'restringir',
     'restriccion': {'variable': 'ROL', 'condicion': '== 1'}},
    # EXCLUIDA/RUIDO: sin entrada -> debe excluirse sola
    {'archivo': 'PROGRAMA.csv', 'variable': 'COD_PROG', 'estrategia': 'agregar', 'funcion': 'conteo'},  # el filtro debe ganarle a esto
]
filtros = [
    {'archivo': 'PERSONA.csv', 'variable': 'EDAD', 'condicion': '>= 10'},                # ya en el merge, trivial
    {'archivo': 'FILTROFILE.csv', 'variable': 'ESTADO', 'condicion': '== 1'},            # hay que traerlo
    {'archivo': 'PERSONA.csv', 'variable': 'P207', 'condicion': None, 'motivo': 'código sin confirmar'},
    {'archivo': 'PROGRAMA.csv', 'variable': 'COD_PROG', 'condicion': '== 2', 'motivo': 'recibió el programa 2'},
]

out_csv = os.path.join(os.path.dirname(md), 'dataset_test.csv')
try:
    rep = EST.materializar_dataset(plan_datos, manifiesto, filtros, resolucion, [YEAR], YEAR, out_csv, carp)
    print(json.dumps({k: v for k, v in rep.items() if k != 'columnas'}, ensure_ascii=False, indent=2))

    check('filas duplicadas por llave = 0', rep['filas_duplicadas_por_llave'] == 0, rep['filas_duplicadas_por_llave'])
    check('GASTO se agrego (nota en agregaciones)',
          any(a['archivo'] == 'GASTOITEM.csv' and a['variable'] == 'GASTO' for a in rep['agregaciones']))
    check('EDAD_JEFE se resolvio con restriccion',
          any(r['archivo'] == 'JEFEDATA.csv' and r['variable'] == 'EDAD_JEFE' for r in rep['restricciones']))
    check('RUIDO (EXCLUIDA.csv) se excluyo sin resolucion',
          any(e['archivo'] == 'EXCLUIDA.csv' and e['variable'] == 'RUIDO' for e in rep['variables_excluidas']))
    check('RUIDO no quedo en el dataset final', 'RUIDO' not in rep['columnas'])
    check('filtro ESTADO se aplico', any(f['variable'] == 'ESTADO' for f in rep['filtros_aplicados']))
    check('filtro P207 (condicion None) se omitio con motivo',
          any(f['variable'] == 'P207' for f in rep['filtros_omitidos']))
    check('columnas limpiadas incluye INGRESO_HOG y EDAD_JEFE (no via agregacion)',
          'INGRESO_HOG' in rep['columnas_limpiadas'] and 'EDAD_JEFE' in rep['columnas_limpiadas'], rep['columnas_limpiadas'])
    check('el filtro sobre COD_PROG le gano a la resolucion (agregar:conteo) para esa misma variable',
          any(r['archivo'] == 'PROGRAMA.csv' and r['variable'] == 'COD_PROG' and r['origen'] == 'filtro'
              for r in rep['restricciones']), rep['restricciones'])
    check('COD_PROG NO aparece en agregaciones (el filtro le gano, no se conto)',
          not any(a['variable'] == 'COD_PROG' for a in rep['agregaciones']), rep['agregaciones'])
    check('el filtro de COD_PROG no se aplica DOS VECES (no aparece en el post-merge, ya se conto arriba)',
          sum(1 for f in rep['filtros_aplicados'] if f['variable'] == 'COD_PROG') == 1, rep['filtros_aplicados'])

    import polars as pl
    df = pl.read_csv(out_csv, infer_schema_length=0)
    # filtro ESTADO==1 deja solo hogares 1..15 -> 15 hogares * 2 personas = 30 filas
    check('el filtro ESTADO realmente redujo las filas (30 filas esperadas)', df.height == 30, df.height)
    # GASTO agregado correcto para un hogar (10.5+20.0+5.25=35.75), el centinela NO debe sumarse
    ghogar1 = df.filter(pl.col('HOGAR') == '11').filter(pl.col('CONGLOME') == '1')
    gasto_vals = set(ghogar1['GASTO'].to_list())
    check('GASTO ya viene limpio y sumado (35.75, sin duplicar por CODPERSO)',
          gasto_vals == {'35.75'}, gasto_vals)
    # EDAD_JEFE: el jefe (rol=1) tenia 60,0 -> limpio 60.0 para AMBOS miembros del hogar (broadcast)
    edad_jefe_vals = set(ghogar1['EDAD_JEFE'].to_list())
    check('EDAD_JEFE usa SOLO el valor del jefe (60.0), no el ruido del otro miembro (99.9)',
          edad_jefe_vals == {'60.0'}, edad_jefe_vals)
    # INGRESO_HOG: comas limpias, y el hogar 5 (centinela) debe quedar null/vacio si sigue en la muestra filtrada
    ingreso_col = df['INGRESO_HOG'].to_list()
    check('INGRESO_HOG sin comas decimales (todas con punto o vacio)',
          all((',' not in (v or '')) for v in ingreso_col))
    # hogares 11..15 (dentro del filtro ESTADO<=15) NO recibieron el programa 2 -> deben
    # seguir presentes en el dataset final con COD_PROG=null, NO haber sido eliminados
    # (si el filtro se hubiera aplicado tambien post-merge, estos hogares desaparecerian)
    h13 = df.filter(pl.col('HOGAR') == '11').filter(pl.col('CONGLOME') == '13')
    check('hogar sin el programa 2 SIGUE en el dataset (no se perdio el grupo de comparacion)',
          h13.height == 2, h13.height)
    check('a ese hogar COD_PROG le queda null (no 3, no conteo)',
          set(h13['COD_PROG'].to_list()) in ({None}, {''}), h13['COD_PROG'].to_list())
    h1 = df.filter(pl.col('HOGAR') == '11').filter(pl.col('CONGLOME') == '1')
    check('hogar QUE SI recibio el programa 2 queda con COD_PROG=2', set(h1['COD_PROG'].to_list()) == {'2.0'}, h1['COD_PROG'].to_list())
finally:
    shutil.rmtree(carp, ignore_errors=True)
    if os.path.isfile(out_csv):
        os.remove(out_csv)

print('\n' + ('TODO OK' if not fails else 'FALLARON: %s' % fails))
sys.exit(1 if fails else 0)
