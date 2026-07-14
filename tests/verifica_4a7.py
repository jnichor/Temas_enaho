# -*- coding: utf-8 -*-
"""Verifica bugs 4-7 con datos sinteticos (se limpian al final).
Motor vs calculo directo en numpy sobre los MISMOS datos fuente."""
import os, sys, json, shutil, csv
import numpy as np

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(PROJ)
sys.path.insert(0, os.path.join(PROJ, 'scripts'))
sys.path.insert(0, PROJ)

A = 'enaho_ztesta/microodatos_inei/enaho/2_organized/by_year'
B = 'enaho_ztestb/microodatos_inei/enaho/2_organized/by_year'

# ---------- construir datos sinteticos ----------
def build_year(ydir, year, delta):
    md = os.path.join(ydir, 'modulos')
    os.makedirs(md, exist_ok=True)
    # 41 hogares; hogares 1-40 con 2 personas, hogar 41 con 1 persona (ING centinela)
    rows, ing_por = [], {}
    v = {'1': 100 + delta, '2': 200 + delta}
    for h in range(1, 41):
        for p, sexo in ((1, '1'), (2, '2')):
            ing = v[sexo] + (h - 1)          # grupo1: 100..139, grupo2: 200..239 (+delta)
            w = 1.0 if p == 1 else 2.0       # pesos heterogeneos: prueba ponderacion real
            rows.append([str(h), '1', '11', '0%d' % p, sexo, str(ing), str(w)])
            ing_por[(str(h), '0%d' % p)] = (sexo, float(ing), w)
    rows.append(['41', '1', '11', '01', '1', '999999', '1.0'])   # centinela: debe excluirse
    f500 = os.path.join(md, '0005_test-%s-500.csv' % year)
    with open(f500, 'w', newline='', encoding='latin-1') as fh:
        wtr = csv.writer(fh); wtr.writerow(['CONGLOME', 'VIVIENDA', 'HOGAR', 'CODPERSO', 'P207', 'ING', 'FAC500A'])
        wtr.writerows(rows)
    # sumaria: 1 fila por hogar (broadcast valido)
    fsum = os.path.join(md, '0034_sum-%s.csv' % year)
    with open(fsum, 'w', newline='', encoding='latin-1') as fh:
        wtr = csv.writer(fh); wtr.writerow(['CONGLOME', 'VIVIENDA', 'HOGAR', 'POBREZA'])
        for h in range(1, 42):
            wtr.writerow([str(h), '1', '11', '1' if h <= 20 else '2'])
    # item-level: 2 filas por hogar (grupo INVALIDO -> debe rechazarse)
    fitem = os.path.join(md, '0007_item-%s-601.csv' % year)
    with open(fitem, 'w', newline='', encoding='latin-1') as fh:
        wtr = csv.writer(fh); wtr.writerow(['CONGLOME', 'VIVIENDA', 'HOGAR', 'P601N', 'CAT'])
        for h in range(1, 42):
            wtr.writerow([str(h), '1', '11', '1', 'a']); wtr.writerow([str(h), '1', '11', '2', 'b'])
    json.dump({'anio': year, 'carpeta': os.path.basename(ydir), 'n_archivos': 3, 'modulos': []},
              open(os.path.join(ydir, 'catalogo_%s.json' % year), 'w', encoding='utf-8'))
    return ing_por

ing99 = build_year(os.path.join(A, '2099'), '2099', 0)
ing98 = build_year(os.path.join(A, '2098'), '2098', 10)
os.makedirs(os.path.join(B, '2099'), exist_ok=True)
json.dump({'anio': '2099', 'carpeta': 'enaho_ztestb', 'n_archivos': 0, 'modulos': []},
          open(os.path.join(B, '2099', 'catalogo_2099.json'), 'w', encoding='utf-8'))

import estadistica as EST
import razonador as RZ

F500, FSUM, FITEM = '0005_test-2099-500.csv', '0034_sum-2099.csv', '0007_item-2099-601.csv'
fails = []

def check(nombre, cond, detalle=''):
    print(('  [OK] ' if cond else '  [FALLA] ') + nombre + ((' | ' + str(detalle)) if detalle and not cond else ''))
    if not cond:
        fails.append(nombre)

# expected por numpy directo (excluye centinela)
def esperado(ings, grupo_de, estad):
    grupos = {}
    for k, (sexo, ing, w) in ings.items():
        g = grupo_de(k, sexo)
        grupos.setdefault(g, []).append((ing, w))
    out = {}
    for g, xs in grupos.items():
        x = np.array([a for a, _ in xs]); w = np.array([b for _, b in xs])
        if estad == 'media':
            out[g] = round(float(np.average(x, weights=w)), 2)
        else:
            o = np.argsort(x); x, w = x[o], w[o]
            out[g] = round(float(x[np.searchsorted(np.cumsum(w), 0.5 * w.sum())]), 2)
    return out

print('--- BUG 5+7: media ponderada, grupo en el MISMO archivo (+centinela excluido) ---')
item = {'brecha': 'ing por sexo', 'outcome': {'archivo': F500, 'variable': 'ING'},
        'grupo': {'archivo': F500, 'variable': 'P207', 'etiquetas': {'1': 'H', '2': 'M'}},
        'ponderador': {'archivo': F500, 'variable': 'FAC500A'}, 'estadistico': 'media'}
r = EST.calcular([item], '2099')[0]
exp = esperado(ing99, lambda k, s: s, 'media')
got = {g['grupo']: g['valor'] for g in r.get('grupos', [])}
check('sin error', not r.get('error'), r.get('error'))
check('media ponderada == numpy directo', got == exp, (got, exp))
check('centinela excluido (n=40 en grupo 1)', all(g['n'] == 40 for g in r['grupos']), r['grupos'])
check('ponderador usado FAC500A', r.get('ponderador') == 'FAC500A', r.get('ponderador'))

print('--- mediana ponderada ---')
item2 = dict(item, estadistico='mediana')
r2 = EST.calcular([item2], '2099')[0]
exp2 = esperado(ing99, lambda k, s: s, 'mediana')
got2 = {g['grupo']: g['valor'] for g in r2.get('grupos', [])}
check('mediana == numpy directo', got2 == exp2, (got2, exp2))

print('--- ponderador con nombre INEXISTENTE -> fallback a FAC* ---')
item3 = dict(item, ponderador={'archivo': F500, 'variable': 'FACTOR07'})
r3 = EST.calcular([item3], '2099')[0]
check('fallback a FAC500A', r3.get('ponderador') == 'FAC500A', r3.get('ponderador'))
check('valores iguales al ponderado', {g['grupo']: g['valor'] for g in r3['grupos']} == exp)

print('--- BUG 5: grupo hogar-level desde OTRO archivo (broadcast m:1 valido) ---')
item4 = {'brecha': 'ing por pobreza', 'outcome': {'archivo': F500, 'variable': 'ING'},
         'grupo': {'archivo': FSUM, 'variable': 'POBREZA', 'etiquetas': {}},
         'ponderador': {'archivo': F500, 'variable': 'FAC500A'}, 'estadistico': 'media'}
r4 = EST.calcular([item4], '2099')[0]
exp4 = esperado(ing99, lambda k, s: '1' if int(k[0]) <= 20 else '2', 'media')
got4 = {g['grupo']: g['valor'] for g in r4.get('grupos', [])}
check('broadcast valido calcula bien', got4 == exp4, (got4, exp4, r4.get('error')))

print('--- BUG 5: grupo ITEM-level (varias filas/llave) -> DEBE rechazarse ---')
item5 = {'brecha': 'mal nivel', 'outcome': {'archivo': F500, 'variable': 'ING'},
         'grupo': {'archivo': FITEM, 'variable': 'CAT', 'etiquetas': {}},
         'ponderador': None, 'estadistico': 'media'}
r5 = EST.calcular([item5], '2099')[0]
check('rechaza con error claro', 'niveles incompatibles' in (r5.get('error') or ''), r5)

print('--- BUG 6: calcular_multi en 2 anios + anio faltante ---')
multi = EST.calcular_multi([item], ['2098', '2099', '2097'], '2099')
g98 = {g['grupo']: g['valor'] for g in multi['2098'][0].get('grupos', [])}
exp98 = esperado(ing98, lambda k, s: s, 'media')
check('2099 correcto', {g['grupo']: g['valor'] for g in multi['2099'][0]['grupos']} == exp)
check('2098 correcto (archivo traducido)', g98 == exp98, (g98, exp98, multi['2098'][0].get('error')))
check('2097 faltante -> error explicito, no crash', bool(multi['2097'][0].get('error')), multi['2097'][0])

print('--- BUG 4: anio duplicado en 2 carpetas -> deteccion + eleccion determinista ---')
carps = RZ.carpetas_de_anio('2099')
check('detecta 2 carpetas', carps == ['enaho_ztesta', 'enaho_ztestb'], carps)
# el catalogo de A se escribio con carpeta='2099' (basename) y el de B con 'enaho_ztestb':
# si devuelve '2099', eligio A (la primera alfabetica), que es lo correcto.
cat = RZ.load_catalogo('2099')
check('elige la primera (alfabetica = ztesta)', cat and cat.get('carpeta') == '2099', cat and cat.get('carpeta'))

print('--- verificar_merge en streaming ---')
plan = {'secuencia_merge': [
    {'tipo': 'base', 'archivo': F500},
    {'tipo': 'left', 'archivo': FSUM, 'broadcast': True},
    {'tipo': 'left', 'archivo': FITEM, 'broadcast': True}]}
vm = {v['archivo']: v for v in EST.verificar_merge(plan, '2099')}
check('sumaria: broadcast valido', vm[FSUM]['ok'] is True)
check('item-level: broadcast rechazado', vm[FITEM]['ok'] is False, vm[FITEM]['nota'])

print('--- consolidacion (overlap streaming) ---')
n = EST._nfilas(F500, '2099')
check('_nfilas streaming', n == 81, n)
pct, nn = EST._overlap_match(F500, F500, 'P207', '2099')
check('_overlap_match streaming (identidad=100%)', pct == 100.0 and nn == 81, (pct, nn))

# ---------- limpieza ----------
shutil.rmtree('enaho_ztesta', ignore_errors=True)
shutil.rmtree('enaho_ztestb', ignore_errors=True)
print('\n' + ('TODAS LAS PRUEBAS OK (estructura sintetica eliminada)' if not fails
              else 'FALLARON: %s' % fails))
sys.exit(1 if fails else 0)
