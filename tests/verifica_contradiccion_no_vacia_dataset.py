# -*- coding: utf-8 -*-
"""Bug real encontrado regenerando una propuesta real: materializar_dataset
DETECTABA una contradiccion entre filtros (patron de salto del cuestionario,
ej. P204/P206) pero los APLICABA IGUAL, dando un dataset de 0 filas en vez de
omitir esos filtros especificos. Verifica que ahora los omite (no vacia el
dataset) y que un filtro NO relacionado con la contradiccion SI se sigue
aplicando normalmente."""
import os, sys, csv, shutil
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(PROJ)
sys.path.insert(0, os.path.join(PROJ, 'scripts'))
fails = []

def check(nombre, cond, detalle=''):
    print(('  [OK] ' if cond else '  [FALLA] ') + nombre + ((' | ' + str(detalle)) if detalle and not cond else ''))
    if not cond:
        fails.append(nombre)

md = 'enaho_ztest8/microodatos_inei/enaho/2_organized/by_year/2093/modulos'
os.makedirs(md, exist_ok=True)

# PERSONA: patron de salto real (P204/P206) + SEXO (no relacionado, para
# confirmar que un filtro sano se sigue aplicando aunque haya otra contradiccion)
with open(os.path.join(md, 'PERSONA.csv'), 'w', newline='', encoding='latin-1') as fh:
    w = csv.writer(fh); w.writerow(['CONGLOME', 'VIVIENDA', 'HOGAR', 'CODPERSO', 'P204', 'P206', 'SEXO', 'EDAD'])
    for h in range(1, 61):
        w.writerow([str(h), '1', '11', '1', '1', '', '1' if h % 2 else '2', '70'])   # P204=1 -> P206 vacio
    for h in range(61, 81):
        w.writerow([str(h), '1', '11', '1', '2', '1' if h % 2 else '2', '1', '70'])  # P204=2 -> P206 SI tiene valor

import estadistica as EST
plan_datos = {'nivel_de_analisis': 'persona', 'llaves_merge': ['CONGLOME', 'VIVIENDA', 'HOGAR', 'CODPERSO'],
              'archivo_base': 'PERSONA.csv',
              'secuencia_merge': [{'archivo': 'PERSONA.csv', 'tipo': 'base',
                                   'llaves_join': ['CONGLOME', 'VIVIENDA', 'HOGAR', 'CODPERSO'],
                                   'variables': ['EDAD']}]}
manifiesto = [{'archivo': 'PERSONA.csv', 'variable': 'EDAD', 'rol': 'dependiente'}]
filtros = [
    {'archivo': 'PERSONA.csv', 'variable': 'P204', 'condicion': '== 1'},
    {'archivo': 'PERSONA.csv', 'variable': 'P206', 'condicion': '== 1'},   # contradictorio con P204==1
    {'archivo': 'PERSONA.csv', 'variable': 'SEXO', 'condicion': '== 1'},   # sano, no relacionado
]

out_csv = os.path.join('enaho_ztest8', 'out.csv')
try:
    rep = EST.materializar_dataset(plan_datos, manifiesto, filtros, [], ['2093'], '2093', out_csv, 'enaho_ztest8')
    check('detecto la contradiccion', len(rep['filtros_contradictorios']) == 1, rep['filtros_contradictorios'])
    check('P204 y P206 quedan OMITIDOS (no aplicados), no vaciaron el dataset',
          {'P204', 'P206'} <= {f['variable'] for f in rep['filtros_omitidos']}, rep['filtros_omitidos'])
    check('SEXO (sano, no relacionado) SI se aplico normalmente',
          any(f['variable'] == 'SEXO' for f in rep['filtros_aplicados']), rep['filtros_aplicados'])
    check('el dataset NO quedo vacio y SI se redujo por SEXO==1 (no las 80 filas totales)',
          0 < rep['filas'] < 80, rep['filas'])
finally:
    shutil.rmtree('enaho_ztest8', ignore_errors=True)

print('\n' + ('TODO OK' if not fails else 'FALLARON: %s' % fails))
sys.exit(1 if fails else 0)
