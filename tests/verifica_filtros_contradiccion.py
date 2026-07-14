# -*- coding: utf-8 -*-
"""Verifica estadistica.verificar_filtros: detecta cuando dos filtros de un mismo
archivo son mutuamente excluyentes (patron de salto del cuestionario, ej. P204/P206
reales) SIN falsos positivos cuando la combinacion simplemente da una poblacion
mas chica pero real."""
import os, sys, csv, shutil
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(PROJ)
sys.path.insert(0, os.path.join(PROJ, 'scripts'))
fails = []

def check(nombre, cond, detalle=''):
    print(('  [OK] ' if cond else '  [FALLA] ') + nombre + ((' | ' + str(detalle)) if detalle and not cond else ''))
    if not cond:
        fails.append(nombre)

md = 'enaho_ztest4/microodatos_inei/enaho/2_organized/by_year/2095/modulos'
os.makedirs(md, exist_ok=True)

# PERSONA: replica el patron de salto real P204/P206:
#   P204 = 1 (residente habitual) o 2 (no habitual)
#   P206 SOLO se pregunta si P204==2 (skip pattern); si P204==1, P206 queda vacio.
# ademas SEXO (1/2) para el caso normal (no excluyente).
with open(os.path.join(md, 'PERSONA.csv'), 'w', newline='', encoding='latin-1') as fh:
    w = csv.writer(fh); w.writerow(['CONGLOME', 'VIVIENDA', 'HOGAR', 'CODPERSO', 'P204', 'P206', 'SEXO', 'EDAD'])
    for h in range(1, 61):
        w.writerow([str(h), '1', '11', '1', '1', '', '1' if h % 2 else '2', str(20 + (h % 50))])   # P204=1 -> P206 vacio
    for h in range(61, 81):
        w.writerow([str(h), '1', '11', '1', '2', '1' if h % 2 else '2', '1', str(20 + (h % 50))])  # P204=2 -> P206 SI tiene valor

import estadistica as EST

# caso 1: P204==1 y P206==1 -> deberian ser mutuamente excluyentes (0 combinado)
filtros_contradictorios = [
    {'archivo': 'PERSONA.csv', 'variable': 'P204', 'condicion': '== 1'},
    {'archivo': 'PERSONA.csv', 'variable': 'P206', 'condicion': '== 1'},
]
rep = EST.verificar_filtros(filtros_contradictorios, '2095', 'enaho_ztest4')
print(rep)
check('detecta la contradiccion P204/P206', len(rep) == 1 and rep[0]['archivo'] == 'PERSONA.csv', rep)
if rep:
    check('reporta que cada uno por separado SI tenia datos',
          all(n > 0 for n in rep[0]['filas_individuales'].values()), rep[0]['filas_individuales'])
    check('reporta 0 filas combinadas', rep[0]['filas_combinadas'] == 0)

# caso 2: SEXO==1 y EDAD>=30 -> combinacion normal, NO deberia dispararse (da datos reales)
filtros_normales = [
    {'archivo': 'PERSONA.csv', 'variable': 'SEXO', 'condicion': '== 1'},
    {'archivo': 'PERSONA.csv', 'variable': 'EDAD', 'condicion': '>= 30'},
]
rep2 = EST.verificar_filtros(filtros_normales, '2095', 'enaho_ztest4')
check('NO dispara falso positivo con una combinacion normal (no vacia)', rep2 == [], rep2)

# caso 3: un solo filtro por archivo -> no hay nada que combinar, no debe crashear
rep3 = EST.verificar_filtros([{'archivo': 'PERSONA.csv', 'variable': 'SEXO', 'condicion': '== 1'}], '2095', 'enaho_ztest4')
check('con un solo filtro no hace nada (nada que contradecir)', rep3 == [], rep3)

shutil.rmtree('enaho_ztest4', ignore_errors=True)
print('\n' + ('TODO OK' if not fails else 'FALLARON: %s' % fails))
sys.exit(1 if fails else 0)
