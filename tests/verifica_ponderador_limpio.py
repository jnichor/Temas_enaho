# -*- coding: utf-8 -*-
"""Verifica que el rol 'ponderador' tambien se limpie (coma decimal -> punto) en
materializar_dataset. Antes del fix, FACPOB07/FACTOR07 quedaban con coma sin
convertir en el CSV final porque 'ponderador' no estaba en roles_numericos."""
import os, sys, csv, shutil
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(PROJ)
sys.path.insert(0, os.path.join(PROJ, 'scripts'))
fails = []

def check(nombre, cond, detalle=''):
    print(('  [OK] ' if cond else '  [FALLA] ') + nombre + ((' | ' + str(detalle)) if detalle and not cond else ''))
    if not cond:
        fails.append(nombre)

md = 'enaho_ztest5/microodatos_inei/enaho/2_organized/by_year/2094/modulos'
os.makedirs(md, exist_ok=True)
with open(os.path.join(md, 'HOGAR.csv'), 'w', newline='', encoding='latin-1') as fh:
    w = csv.writer(fh); w.writerow(['CONGLOME', 'VIVIENDA', 'HOGAR', 'INGRESO', 'FACPOB07'])
    for h in range(1, 21):
        w.writerow([str(h), '1', '11', '%d,5' % (1000 + h), '%d,632446289063' % (100 + h)])

import estadistica as EST
plan_datos = {'nivel_de_analisis': 'hogar', 'llaves_merge': ['CONGLOME', 'VIVIENDA', 'HOGAR'],
              'archivo_base': 'HOGAR.csv',
              'secuencia_merge': [{'archivo': 'HOGAR.csv', 'tipo': 'base',
                                   'llaves_join': ['CONGLOME', 'VIVIENDA', 'HOGAR'],
                                   'variables': ['INGRESO', 'FACPOB07']}]}
manifiesto = [{'archivo': 'HOGAR.csv', 'variable': 'INGRESO', 'rol': 'dependiente'},
              {'archivo': 'HOGAR.csv', 'variable': 'FACPOB07', 'rol': 'ponderador'}]

out_csv = os.path.join('enaho_ztest5', 'dataset_test.csv')
try:
    rep = EST.materializar_dataset(plan_datos, manifiesto, [], [], ['2094'], '2094', out_csv, 'enaho_ztest5')
    check('FACPOB07 quedo en columnas_limpiadas', 'FACPOB07' in rep['columnas_limpiadas'], rep['columnas_limpiadas'])
    import polars as pl
    df = pl.read_csv(out_csv, infer_schema_length=0)
    con_coma = df['FACPOB07'].str.contains(',', literal=True).fill_null(False).sum()
    check('FACPOB07 sin comas decimales en el CSV final', con_coma == 0, con_coma)
    check('FACPOB07 parseable como float', float(df['FACPOB07'][0]) > 0)
finally:
    shutil.rmtree('enaho_ztest5', ignore_errors=True)

print('\n' + ('TODO OK' if not fails else 'FALLARON: %s' % fails))
sys.exit(1 if fails else 0)
