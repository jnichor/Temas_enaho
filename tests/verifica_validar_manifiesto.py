# -*- coding: utf-8 -*-
"""Verifica razonador.validar_manifiesto: descarta entradas con archivo/variable
inventados (ej. el caso real: 'ADVERTENCIA_LIMITACIONES_CRITICAS' disfrazado de
item del manifiesto) SIN tocar las entradas reales."""
import os, sys
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(PROJ)
sys.path.insert(0, os.path.join(PROJ, 'scripts'))
fails = []

def check(nombre, cond, detalle=''):
    print(('  [OK] ' if cond else '  [FALLA] ') + nombre + ((' | ' + str(detalle)) if detalle and not cond else ''))
    if not cond:
        fails.append(nombre)

import razonador as RZ

cat = {'modulos': [
    {'archivo': 'HOGAR.csv', 'variables': {'CONGLOME': 'x', 'VIVIENDA': 'x', 'HOGAR': 'x', 'INGRESO': 'ingreso'}},
    {'archivo': 'PERSONA.csv', 'variables': {'CONGLOME': 'x', 'VIVIENDA': 'x', 'HOGAR': 'x', 'CODPERSO': 'x', 'EDAD': 'edad'}},
]}

manifiesto = [
    {'archivo': 'HOGAR.csv', 'variable': 'INGRESO', 'rol': 'dependiente'},
    {'archivo': 'PERSONA.csv', 'variable': 'EDAD', 'rol': 'control'},
    # el caso real que crasheo el pipeline:
    {'archivo': 'ADVERTENCIA_LIMITACIONES_CRITICAS', 'variable': 'N/A', 'rol': 'N/A'},
    # variable real pero de un archivo que no existe:
    {'archivo': 'NOEXISTE.csv', 'variable': 'INGRESO', 'rol': 'control'},
    # archivo real pero variable que no existe en el:
    {'archivo': 'HOGAR.csv', 'variable': 'NOEXISTE', 'rol': 'control'},
    # entrada sin archivo:
    {'variable': 'INGRESO', 'rol': 'control'},
]

validos, descartados = RZ.validar_manifiesto(cat, manifiesto)
check('quedan solo las 2 entradas reales', len(validos) == 2, validos)
check('INGRESO de HOGAR.csv se mantiene', any(v['archivo'] == 'HOGAR.csv' and v['variable'] == 'INGRESO' for v in validos))
check('EDAD de PERSONA.csv se mantiene', any(v['archivo'] == 'PERSONA.csv' and v['variable'] == 'EDAD' for v in validos))
check('se descartan las 4 entradas invalidas', len(descartados) == 4, descartados)
check('el archivo inventado (ADVERTENCIA...) se descarta con motivo claro',
      any('ADVERTENCIA_LIMITACIONES_CRITICAS' in d['motivo'] for d in descartados), descartados)

print('\n' + ('TODO OK' if not fails else 'FALLARON: %s' % fails))
sys.exit(1 if fails else 0)
