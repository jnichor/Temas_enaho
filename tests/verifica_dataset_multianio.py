# -*- coding: utf-8 -*-
"""Verifica que materializar_dataset cubra TODOS los años de un tema (bug real
encontrado por el usuario: antes solo exportaba el año representativo `rep`,
perdiendo el resto de la cobertura en silencio y sin columna de año)."""
import os, sys, csv, shutil
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(PROJ)
sys.path.insert(0, os.path.join(PROJ, 'scripts'))
fails = []

def check(nombre, cond, detalle=''):
    print(('  [OK] ' if cond else '  [FALLA] ') + nombre + ((' | ' + str(detalle)) if detalle and not cond else ''))
    if not cond:
        fails.append(nombre)

carp = 'enaho_ztest7'

def md_de(year):
    d = os.path.join(carp, 'microodatos_inei', 'enaho', '2_organized', 'by_year', year, 'modulos')
    os.makedirs(d, exist_ok=True)
    return d

# año 2090 (representativo, "rep"): 10 hogares, INGRESO empieza en 2000
md90 = md_de('2090')
with open(os.path.join(md90, 'HOGAR-2090.csv'), 'w', newline='', encoding='latin-1') as fh:
    w = csv.writer(fh); w.writerow(['CONGLOME', 'VIVIENDA', 'HOGAR', 'INGRESO'])
    for h in range(1, 11):
        w.writerow([str(h), '1', '11', str(2000 + h)])

# año 2091: 8 hogares (menos, para verificar que se suman filas de años DISTINTOS
# correctamente), INGRESO empieza en 5000 (para distinguir claramente de 2090)
md91 = md_de('2091')
with open(os.path.join(md91, 'HOGAR-2091.csv'), 'w', newline='', encoding='latin-1') as fh:
    w = csv.writer(fh); w.writerow(['CONGLOME', 'VIVIENDA', 'HOGAR', 'INGRESO'])
    for h in range(1, 9):
        w.writerow([str(h), '1', '11', str(5000 + h)])

# año 2092: base con FILAS DUPLICADAS a propósito (para que falle SOLO ese año)
md92 = md_de('2092')
with open(os.path.join(md92, 'HOGAR-2092.csv'), 'w', newline='', encoding='latin-1') as fh:
    w = csv.writer(fh); w.writerow(['CONGLOME', 'VIVIENDA', 'HOGAR', 'INGRESO'])
    w.writerow(['1', '1', '11', '9000'])
    w.writerow(['1', '1', '11', '9001'])  # llave repetida -> base invalido para este año

import estadistica as EST

plan_datos = {'nivel_de_analisis': 'hogar', 'llaves_merge': ['CONGLOME', 'VIVIENDA', 'HOGAR'],
              'archivo_base': 'HOGAR-2090.csv',
              'secuencia_merge': [{'archivo': 'HOGAR-2090.csv', 'tipo': 'base',
                                   'llaves_join': ['CONGLOME', 'VIVIENDA', 'HOGAR'], 'variables': ['INGRESO']}]}
manifiesto = [{'archivo': 'HOGAR-2090.csv', 'variable': 'INGRESO', 'rol': 'dependiente'}]

out_csv = os.path.join(carp, 'dataset_multianio.csv')
try:
    rep = EST.materializar_dataset(plan_datos, manifiesto, [], [], ['2090', '2091', '2092'], '2090', out_csv, carp)
    check('cubre los 3 años pedidos (aunque 1 falle)', rep['anios'] == ['2090', '2091', '2092'], rep['anios'])
    check('2092 (base duplicada) queda registrado como error, no tumba todo',
          any(a['anio'] == '2092' for a in rep['anios_con_error']), rep['anios_con_error'])
    check('filas = 10 (2090) + 8 (2091), sin el año que fallo', rep['filas'] == 18, rep['filas'])
    check('sin duplicados (ANIO+llave)', rep['filas_duplicadas_por_llave'] == 0, rep['filas_duplicadas_por_llave'])
    check('el CSV tiene columna ANIO', 'ANIO' in rep['columnas'], rep['columnas'])

    import polars as pl
    df = pl.read_csv(out_csv, infer_schema_length=0)
    check('hay filas con ANIO=2090', (df['ANIO'] == '2090').sum() == 10)
    check('hay filas con ANIO=2091', (df['ANIO'] == '2091').sum() == 8)
    check('NO hay filas de 2092 (fallo)', (df['ANIO'] == '2092').sum() == 0)
    ing90 = df.filter(pl.col('ANIO') == '2090')['INGRESO'].cast(pl.Float64).to_list()
    ing91 = df.filter(pl.col('ANIO') == '2091')['INGRESO'].cast(pl.Float64).to_list()
    check('los valores de INGRESO 2090 son los correctos (2001..2010)', sorted(ing90) == [2000.0 + i for i in range(1, 11)], sorted(ing90))
    check('los valores de INGRESO 2091 son los correctos (5001..5008), NO mezclados con 2090',
          sorted(ing91) == [5000.0 + i for i in range(1, 9)], sorted(ing91))
    # la misma llave (CONGLOME=1,VIVIENDA=1,HOGAR=11) existe en AMBOS años con valores DISTINTOS:
    # si el chequeo de duplicados no incluyera ANIO, esto se marcaria como duplicado por error.
    check('la misma llave en años distintos NO se marca como duplicado (chequeo incluye ANIO)',
          rep['filas_duplicadas_por_llave'] == 0)
finally:
    shutil.rmtree(carp, ignore_errors=True)

print('\n' + ('TODO OK' if not fails else 'FALLARON: %s' % fails))
sys.exit(1 if fails else 0)
