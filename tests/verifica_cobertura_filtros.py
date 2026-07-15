# -*- coding: utf-8 -*-
"""Verifica estadistica.verificar_cobertura_filtros: detecta cuando un filtro usa
una variable mayormente EN BLANCO (patron de pregunta condicional del cuestionario,
ej. P206 real) que colapsaria la muestra al aplicarlo como filtro de poblacion -
SIN marcarlo como error (el filtro si tiene datos, solo pocos), y sin falsos
positivos en variables bien pobladas."""
import os, sys, csv, shutil
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(PROJ)
sys.path.insert(0, os.path.join(PROJ, 'scripts'))
fails = []

def check(nombre, cond, detalle=''):
    print(('  [OK] ' if cond else '  [FALLA] ') + nombre + ((' | ' + str(detalle)) if detalle and not cond else ''))
    if not cond:
        fails.append(nombre)

md = 'enaho_ztestA/microodatos_inei/enaho/2_organized/by_year/2092/modulos'
os.makedirs(md, exist_ok=True)

# PERSONA: P206 (pregunta condicional, 97% en blanco, igual que el caso real) +
# EDAD (variable normal, 100% poblada) para comparar
with open(os.path.join(md, 'PERSONA.csv'), 'w', newline='', encoding='latin-1') as fh:
    w = csv.writer(fh); w.writerow(['CONGLOME', 'VIVIENDA', 'HOGAR', 'CODPERSO', 'P206', 'EDAD'])
    for h in range(1, 971):   # 970 filas con P206 en blanco
        w.writerow([str(h), '1', '11', '1', '', '30'])
    for h in range(971, 1001):   # 30 filas (3%) con P206 poblado
        w.writerow([str(h), '1', '11', '1', '1' if h % 2 else '2', '30'])

import estadistica as EST

filtros = [
    {'archivo': 'PERSONA.csv', 'variable': 'P206', 'condicion': '== 1'},   # baja cobertura (~1.5%)
    {'archivo': 'PERSONA.csv', 'variable': 'EDAD', 'condicion': '>= 18'},  # cobertura completa
]
rep = EST.verificar_cobertura_filtros(filtros, '2092', 'enaho_ztestA')
print(rep)
check('detecta P206 como baja cobertura', any(r['variable'] == 'P206' for r in rep), rep)
check('NO marca EDAD (bien poblada) como baja cobertura', not any(r['variable'] == 'EDAD' for r in rep), rep)
p206 = next((r for r in rep if r['variable'] == 'P206'), None)
if p206:
    check('cobertura reportada es baja (~3%)', p206['cobertura_pct'] < 10, p206['cobertura_pct'])
    check('reporta con_dato y total_filas correctos', p206['con_dato'] == 30 and p206['total_filas'] == 1000, p206)

# umbral configurable: con umbral muy bajo, ni P206 deberia dispararse
rep_umbral_bajo = EST.verificar_cobertura_filtros(filtros, '2092', 'enaho_ztestA', umbral=0.01)
check('con umbral mas laxo, ya no se dispara', rep_umbral_bajo == [], rep_umbral_bajo)

shutil.rmtree('enaho_ztestA', ignore_errors=True)
print('\n' + ('TODO OK' if not fails else 'FALLARON: %s' % fails))
sys.exit(1 if fails else 0)
