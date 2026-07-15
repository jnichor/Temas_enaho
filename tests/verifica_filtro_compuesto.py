# -*- coding: utf-8 -*-
"""Verifica el soporte nuevo de _cond_mask para listas de valores discretos
('== 7 or == 8', '7 or 8', 'in [7,8,9]') - el caso real que se perdio en la
corrida de estacionalidad agropecuaria (ESTRATO == 7 or == 8, "rural"). Confirma
que lo genuinamente no reconocible SIGUE sin aplicarse (nunca se adivina), y que
las condiciones simples de siempre no se rompieron."""
import os, sys, csv, shutil
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(PROJ)
sys.path.insert(0, os.path.join(PROJ, 'scripts'))
fails = []

def check(nombre, cond, detalle=''):
    print(('  [OK] ' if cond else '  [FALLA] ') + nombre + ((' | ' + str(detalle)) if detalle and not cond else ''))
    if not cond:
        fails.append(nombre)

md = 'enaho_ztestB/microodatos_inei/enaho/2_organized/by_year/2091/modulos'
os.makedirs(md, exist_ok=True)
with open(os.path.join(md, 'HOGAR.csv'), 'w', newline='', encoding='latin-1') as fh:
    w = csv.writer(fh); w.writerow(['CONGLOME', 'VIVIENDA', 'HOGAR', 'ESTRATO', 'EDAD'])
    for h in range(1, 9):
        w.writerow([str(h), '1', '11', str(h), '30,0'])   # ESTRATO 1..8

import estadistica as EST
import polars as pl

lf = EST._scan('HOGAR.csv', '2091', 'enaho_ztestB')
df = lf.collect(engine='streaming')

print('--- caso real: "== 7 or == 8" (rural, el que se perdio) ---')
mask = EST._cond_mask(pl.col('ESTRATO'), '== 7 or == 8')
check('reconoce la condicion (no es None)', mask is not None)
if mask is not None:
    r = df.filter(mask)
    check('deja exactamente ESTRATO 7 y 8', sorted(r['ESTRATO'].to_list()) == ['7', '8'], r['ESTRATO'].to_list())

print('--- variante sin operador: "7 or 8" ---')
mask2 = EST._cond_mask(pl.col('ESTRATO'), '7 or 8')
check('tambien la reconoce sin "=="', mask2 is not None)
if mask2 is not None:
    check('mismo resultado', sorted(df.filter(mask2)['ESTRATO'].to_list()) == ['7', '8'])

print('--- variante "in [...]" ---')
mask3 = EST._cond_mask(pl.col('ESTRATO'), 'in [7, 8]')
check('reconoce "in [7, 8]"', mask3 is not None)
if mask3 is not None:
    check('mismo resultado', sorted(df.filter(mask3)['ESTRATO'].to_list()) == ['7', '8'])

print('--- 3 valores ---')
mask4 = EST._cond_mask(pl.col('ESTRATO'), '== 1 or == 2 or == 3')
if mask4 is not None:
    check('3 valores OK', sorted(df.filter(mask4)['ESTRATO'].to_list()) == ['1', '2', '3'], df.filter(mask4)['ESTRATO'].to_list())

print('--- condicion simple de SIEMPRE (regresion) ---')
mask5 = EST._cond_mask(pl.col('EDAD'), '>= 30')
check('condicion simple sigue funcionando (con coma decimal limpia)', mask5 is not None and df.filter(mask5).height == 8)

print('--- NO reconocible: sigue sin adivinar ---')
check('"!= 7 or != 8" NO se reconoce (semantica ambigua)', EST._cond_mask(pl.col('ESTRATO'), '!= 7 or != 8') is None)
check('texto libre NO se reconoce', EST._cond_mask(pl.col('ESTRATO'), 'zona rural') is None)
check('"between 4 and 6" NO se reconoce', EST._cond_mask(pl.col('ESTRATO'), 'between 4 and 6') is None)

shutil.rmtree('enaho_ztestB', ignore_errors=True)
print('\n' + ('TODO OK' if not fails else 'FALLARON: %s' % fails))
sys.exit(1 if fails else 0)
