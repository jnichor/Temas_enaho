# -*- coding: utf-8 -*-
"""Reproduce el caso real: modulo hogar-only (800a) + modulo persona (800b),
donde plan_de_datos podria elegir un BASE que no tiene CODPERSO aunque el
analisis completo sea a nivel persona."""
import os, sys
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(PROJ)
sys.path.insert(0, os.path.join(PROJ, 'scripts'))
import razonador as RZ

cat = {'modulos': [
    {'archivo': '800a.csv', 'llave_identificacion': ['CONGLOME', 'VIVIENDA', 'HOGAR']},   # hogar, MUCHAS vars
    {'archivo': '800b.csv', 'llave_identificacion': ['CONGLOME', 'VIVIENDA', 'HOGAR', 'CODPERSO']},  # persona, pocas vars
]}
manifiesto = [
    {'archivo': '800a.csv', 'variable': 'CONGLOME'}, {'archivo': '800a.csv', 'variable': 'VIVIENDA'},
    {'archivo': '800a.csv', 'variable': 'HOGAR'},
    {'archivo': '800a.csv', 'variable': 'V1'}, {'archivo': '800a.csv', 'variable': 'V2'},
    {'archivo': '800a.csv', 'variable': 'V3'}, {'archivo': '800a.csv', 'variable': 'V4'},  # 800a: 7 vars (mas que 800b)
    {'archivo': '800b.csv', 'variable': 'CODPERSO'}, {'archivo': '800b.csv', 'variable': 'V5'},
]
plan = RZ.plan_de_datos(cat, {}, manifiesto, [])
print('nivel_de_analisis:', plan['nivel_de_analisis'])
print('archivo_base      :', plan['archivo_base'])
print('llaves_merge      :', plan['llaves_merge'])
base_llave = set(cat['modulos'][0]['llave_identificacion'] if plan['archivo_base'] == '800a.csv'
                else cat['modulos'][1]['llave_identificacion'])
faltan = set(plan['llaves_merge']) - base_llave
if faltan:
    print('BUG CONFIRMADO: el base "%s" NO tiene las columnas %s que el plan dice usar para unir'
          % (plan['archivo_base'], faltan))
else:
    print('OK: el base tiene todas las llaves declaradas')
