# -*- coding: utf-8 -*-
"""Reproduce el bug reportado por el usuario: grupo sacado de un archivo de
nivel PERSONA (varias filas por hogar) contra un outcome de nivel HOGAR.
Verifica:
  1) SIN restriccion: sigue fallando con 'niveles incompatibles' (regresion cero)
  2) CON restriccion valida (rol==1, "jefe de hogar"): se reduce a 1 fila/hogar
     y la brecha SI se calcula, usando SOLO el valor del jefe
  3) CON restriccion a una variable inexistente: se ignora, sigue fallando,
     pero el mensaje de error ahora incluye el diagnostico de la restriccion
"""
import os, sys, csv, shutil
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(PROJ)
sys.path.insert(0, os.path.join(PROJ, 'scripts'))
fails = []

def check(nombre, cond, detalle=''):
    print(('  [OK] ' if cond else '  [FALLA] ') + nombre + ((' | ' + str(detalle)) if detalle and not cond else ''))
    if not cond:
        fails.append(nombre)

md = 'enaho_ztest2/microodatos_inei/enaho/2_organized/by_year/2097/modulos'
os.makedirs(md, exist_ok=True)

# outcome: nivel HOGAR (0037-700, gasto), 1 fila por hogar
fo = os.path.join(md, 'HOGAR.csv')
with open(fo, 'w', newline='', encoding='latin-1') as fh:
    w = csv.writer(fh); w.writerow(['CONGLOME', 'VIVIENDA', 'HOGAR', 'GASTO', 'FACTOR07'])
    for h in range(1, 81):
        w.writerow([str(h), '1', '11', str(1000 + h), '1.5'])

# grupo: nivel PERSONA (0002-200), varias filas por hogar; ROL=1 es el jefe (unico por hogar)
# jefe tiene P207 (sexo) alternado H/M segun el hogar; otros miembros con sexo mezclado (ruido)
fg = os.path.join(md, 'PERSONA.csv')
with open(fg, 'w', newline='', encoding='latin-1') as fh:
    w = csv.writer(fh); w.writerow(['CONGLOME', 'VIVIENDA', 'HOGAR', 'CODPERSO', 'ROL', 'P207'])
    for h in range(1, 81):
        sexo_jefe = '1' if h <= 40 else '2'   # 40 hogares con jefe hombre, 40 con jefe mujer
        w.writerow([str(h), '1', '11', '1', '1', sexo_jefe])          # jefe de hogar
        w.writerow([str(h), '1', '11', '2', '2', '2' if sexo_jefe == '1' else '1'])  # conyuge (sexo opuesto, RUIDO)

import estadistica as EST

item_sin_restr = {'brecha': 'test', 'outcome': {'archivo': 'HOGAR.csv', 'variable': 'GASTO'},
                   'grupo': {'archivo': 'PERSONA.csv', 'variable': 'P207', 'etiquetas': {'1': 'Hombre', '2': 'Mujer'}},
                   'ponderador': {'archivo': 'HOGAR.csv', 'variable': 'FACTOR07'}, 'estadistico': 'media'}

# --- caso 1: SIN restriccion -> debe seguir fallando (regresion cero) ---
r1 = EST.calcular([item_sin_restr], '2097')[0]
check('sin restriccion: sigue fallando (niveles incompatibles)', 'error' in r1 and 'niveles incompatibles' in r1['error'], r1)

# --- caso 2: CON restriccion valida (ROL == 1) -> debe calcular la brecha ---
item_con_restr = dict(item_sin_restr, grupo=dict(item_sin_restr['grupo'], restriccion={'variable': 'ROL', 'condicion': '== 1'}))
r2 = EST.calcular([item_con_restr], '2097')[0]
check('con restriccion valida: NO hay error', 'error' not in r2, r2)
if 'error' not in r2:
    grupos = {g['etiqueta']: g['valor'] for g in r2['grupos']}
    # jefe hombre: hogares 1-40 (GASTO 1001..1040) -> media = 1020.5
    # jefe mujer:  hogares 41-80 (GASTO 1041..1080) -> media = 1060.5
    check('usa SOLO el valor del jefe (no mezcla con el conyuge)',
          abs(grupos.get('Hombre', 0) - 1020.5) < 0.01 and abs(grupos.get('Mujer', 0) - 1060.5) < 0.01,
          grupos)

# --- caso 3: restriccion a variable inexistente -> se ignora, sigue fallando, PERO con diagnostico ---
item_restr_mala = dict(item_sin_restr, grupo=dict(item_sin_restr['grupo'], restriccion={'variable': 'NOEXISTE', 'condicion': '== 1'}))
r3 = EST.calcular([item_restr_mala], '2097')[0]
check('restriccion invalida: sigue fallando igual que sin restriccion', 'error' in r3)
check('restriccion invalida: el error ahora explica que la restriccion no ayudo',
      'NOEXISTE' in r3.get('error', ''), r3.get('error'))

shutil.rmtree('enaho_ztest2', ignore_errors=True)
print('\n' + ('TODO OK' if not fails else 'FALLARON: %s' % fails))
sys.exit(1 if fails else 0)
