# -*- coding: utf-8 -*-
"""Verifica el fallback de ponderador: 1 solo FAC* (silencioso) vs varios FAC*
(elige alfabeticamente y AVISA con las alternativas)."""
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

# Caso A: 1 solo FAC*
fa = os.path.join(md, 'A.csv')
with open(fa, 'w', newline='', encoding='latin-1') as fh:
    w = csv.writer(fh); w.writerow(['CONGLOME', 'VIVIENDA', 'HOGAR', 'G', 'Y', 'FACTOR07'])
    for h in range(1, 41):
        w.writerow([str(h), '1', '11', '1', str(100 + h), '1.5'])
    for h in range(41, 81):
        w.writerow([str(h), '1', '11', '2', str(200 + h), '1.5'])

# Caso B: 2 FAC* (FACPOB07 y FACTOR07) -> ambiguo, debe avisar
fb = os.path.join(md, 'B.csv')
with open(fb, 'w', newline='', encoding='latin-1') as fh:
    w = csv.writer(fh); w.writerow(['CONGLOME', 'VIVIENDA', 'HOGAR', 'G', 'Y', 'FACTOR07', 'FACPOB07'])
    for h in range(1, 41):
        w.writerow([str(h), '1', '11', '1', str(100 + h), '1.5', '2.0'])
    for h in range(41, 81):
        w.writerow([str(h), '1', '11', '2', str(200 + h), '1.5', '2.0'])

import estadistica as EST

item_a = {'brecha': 'A', 'outcome': {'archivo': 'A.csv', 'variable': 'Y'},
          'grupo': {'archivo': 'A.csv', 'variable': 'G', 'etiquetas': {}},
          'ponderador': {'archivo': 'A.csv', 'variable': 'NOEXISTE'}, 'estadistico': 'media'}
r = EST.calcular([item_a], '2099')[0]
check('caso A (1 FAC*): usa FACTOR07 sin nota', r.get('ponderador') == 'FACTOR07' and not r.get('nota'), r)

item_b = dict(item_a, outcome={'archivo': 'B.csv', 'variable': 'Y'},
             grupo={'archivo': 'B.csv', 'variable': 'G', 'etiquetas': {}},
             ponderador={'archivo': 'B.csv', 'variable': 'NOEXISTE'})
r = EST.calcular([item_b], '2099')[0]
check('caso B (2 FAC*): elige alfabetico (FACPOB07 < FACTOR07)', r.get('ponderador') == 'FACPOB07', r.get('ponderador'))
check('caso B: avisa la ambiguedad con ambas alternativas', bool(r.get('nota')) and 'FACTOR07' in r['nota'] and 'FACPOB07' in r['nota'], r.get('nota'))

shutil.rmtree('enaho_ztest', ignore_errors=True)
print('\n' + ('TODO OK' if not fails else 'FALLARON: %s' % fails))
sys.exit(1 if fails else 0)
