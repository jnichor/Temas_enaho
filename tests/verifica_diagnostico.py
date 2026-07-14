# -*- coding: utf-8 -*-
"""Verifica que el motor explique POR QUE una brecha sale con '-' (sin datos inventados)."""
import os, sys, csv, shutil
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(PROJ)
sys.path.insert(0, os.path.join(PROJ, 'scripts'))
fails = []

def check(nombre, cond, detalle=''):
    print(('  [OK] ' if cond else '  [FALLA] ') + nombre + ((' | ' + str(detalle)) if detalle and not cond else ''))
    if not cond:
        fails.append(nombre)

md = 'enaho_ztest/microodatos_inei/enaho/2_organized/by_year/2099/modulos'
os.makedirs(md, exist_ok=True)

# Caso A: una sola categoria de grupo (todos '1') -> "solo 1 categoria"
fa = os.path.join(md, 'A.csv')
with open(fa, 'w', newline='', encoding='latin-1') as fh:
    w = csv.writer(fh); w.writerow(['CONGLOME', 'VIVIENDA', 'HOGAR', 'G', 'Y'])
    for h in range(1, 51):
        w.writerow([str(h), '1', '11', '1', str(100 + h)])

# Caso B: 2 categorias pero una con <30 casos -> "categorias excluidas, tamaños:"
fb = os.path.join(md, 'B.csv')
with open(fb, 'w', newline='', encoding='latin-1') as fh:
    w = csv.writer(fh); w.writerow(['CONGLOME', 'VIVIENDA', 'HOGAR', 'G', 'Y'])
    for h in range(1, 41):
        w.writerow([str(h), '1', '11', '1', str(100 + h)])   # grupo 1: 40 casos (pasa)
    for h in range(41, 51):
        w.writerow([str(h), '1', '11', '2', str(200 + h)])   # grupo 2: 10 casos (se excluye)

# Caso C: sin match entre outcome y grupo (archivos distintos, cero overlap) -> "sin grupos"
fc1 = os.path.join(md, 'C1.csv')
with open(fc1, 'w', newline='', encoding='latin-1') as fh:
    w = csv.writer(fh); w.writerow(['CONGLOME', 'VIVIENDA', 'HOGAR', 'Y'])
    for h in range(1, 51):
        w.writerow([str(h), '1', '11', str(100 + h)])
fc2 = os.path.join(md, 'C2.csv')
with open(fc2, 'w', newline='', encoding='latin-1') as fh:
    w = csv.writer(fh); w.writerow(['CONGLOME', 'VIVIENDA', 'HOGAR', 'G'])
    for h in range(1000, 1010):    # llaves que NO coinciden con outcome (1..50)
        w.writerow([str(h), '1', '11', '1'])

import estadistica as EST

r = EST.calcular([{'brecha': 'A', 'outcome': {'archivo': 'A.csv', 'variable': 'Y'},
                   'grupo': {'archivo': 'A.csv', 'variable': 'G', 'etiquetas': {}},
                   'ponderador': None, 'estadistico': 'media'}], '2099')[0]
check('caso A: nota "solo 1 categoria"', 'solo 1 categoría' in (r.get('nota') or ''), r)
check('caso A: sin brecha_relativa_pct (no inventa)', 'brecha_relativa_pct' not in r)

r = EST.calcular([{'brecha': 'B', 'outcome': {'archivo': 'B.csv', 'variable': 'Y'},
                   'grupo': {'archivo': 'B.csv', 'variable': 'G', 'etiquetas': {}},
                   'ponderador': None, 'estadistico': 'media'}], '2099')[0]
check('caso B: nota de categorias excluidas con tamaños', 'excluyeron' in (r.get('nota') or '') and '10' in r['nota'], r)

r = EST.calcular([{'brecha': 'C', 'outcome': {'archivo': 'C1.csv', 'variable': 'Y'},
                   'grupo': {'archivo': 'C2.csv', 'variable': 'G', 'etiquetas': {}},
                   'ponderador': None, 'estadistico': 'media'}], '2099')[0]
check('caso C: nota "sin grupos" (0 overlap)', 'sin grupos' in (r.get('nota') or ''), r)

shutil.rmtree('enaho_ztest', ignore_errors=True)
print('\n' + ('TODO OK' if not fails else 'FALLARON: %s' % fails))
sys.exit(1 if fails else 0)
