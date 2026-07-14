# -*- coding: utf-8 -*-
"""Verifica bugs 8-12 (estructura sintetica temporal, se limpia sola)."""
import os, sys, csv, shutil
import numpy as np

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(PROJ)
sys.path.insert(0, os.path.join(PROJ, 'scripts'))
sys.path.insert(0, PROJ)
fails = []

def check(nombre, cond, detalle=''):
    print(('  [OK] ' if cond else '  [FALLA] ') + nombre + ((' | ' + str(detalle)) if detalle and not cond else ''))
    if not cond:
        fails.append(nombre)

print('--- BUG 8: clasico eliminado y sin referencias ---')
check('sistema_enaho_clasico.py no existe', not os.path.exists('sistema_enaho_clasico.py'))
check('README sin referencia', 'clasico' not in open('README.md', encoding='utf-8').read().lower())
check('docstring sin referencia', 'clasico' not in open('sistema_enaho.py', encoding='utf-8').read().lower())

print('--- BUG 9: agentes sin drift ---')
va = open('.claude/agents/visor_enaho.md', encoding='utf-8').read()
da = open('.claude/agents/documentar_enaho.md', encoding='utf-8').read()
ra = open('.claude/agents/revision_identificacion.md', encoding='utf-8').read()
check('visor: menciona salidas/ y visor_enaho_', 'salidas/' in va and 'visor_enaho_' in va)
check('visor: sin nombre viejo', 'documentacion_enaho_año' not in va)
check('documentar: menciona salidas/', 'salidas/' in da and 'dentro de cada `by_year' not in da)
check('revision: sin pyreadstat/.dta', 'pyreadstat' not in ra and '.dta' not in ra)

print('--- BUG 10: ask() reporta stderr/codigo si claude falla ---')
import razonador as RZ
import subprocess as _sp
_orig = _sp.run
class _R:  # simula claude ausente/roto
    stdout = ''
    stderr = "'claude' is not recognized as an internal or external command"
    returncode = 1
_sp.run = lambda *a, **k: _R()
try:
    RZ.ask('hola')
    check('lanza RuntimeError', False)
except RuntimeError as e:
    check('lanza RuntimeError con stderr y codigo',
          'not recognized' in str(e) and '1' in str(e), str(e)[:120])
except Exception as e:
    check('lanza RuntimeError', False, type(e).__name__)
finally:
    _sp.run = _orig

print('--- BUG 11: nombre de carpeta con anios no contiguos ---')
sys.path.insert(0, os.path.join(PROJ, 'scripts'))
import descargar as D
check('un anio', D.carpeta_de([2024]) == 'enaho_2024', D.carpeta_de([2024]))
check('contiguos -> rango', D.carpeta_de([2021, 2022, 2023]) == 'enaho_2021-2023')
check('NO contiguos -> explicito', D.carpeta_de([2018, 2019, 2021]) == 'enaho_2018_2019_2021',
      D.carpeta_de([2018, 2019, 2021]))

print('--- BUG 12: nota por valores 9999 (sin alterar el calculo) ---')
md = 'enaho_ztest/microodatos_inei/enaho/2_organized/by_year/2099/modulos'
os.makedirs(md, exist_ok=True)
f = os.path.join(md, '0005_t-2099-500.csv')
vals = []
with open(f, 'w', newline='', encoding='latin-1') as fh:
    w = csv.writer(fh); w.writerow(['CONGLOME', 'VIVIENDA', 'HOGAR', 'CODPERSO', 'G', 'Y'])
    for h in range(1, 41):
        y = 9999 if h <= 6 else 100 + h     # 6 valores 9999 (>=5 -> nota)
        vals.append(float(y))
        w.writerow([str(h), '1', '11', '01', '1', str(y)])
    for h in range(1, 41):                   # grupo 2 normal
        w.writerow([str(h), '1', '11', '02', '2', str(200 + h)])
import estadistica as EST
r = EST.calcular([{'brecha': 't', 'outcome': {'archivo': '0005_t-2099-500.csv', 'variable': 'Y'},
                   'grupo': {'archivo': '0005_t-2099-500.csv', 'variable': 'G', 'etiquetas': {}},
                   'ponderador': None, 'estadistico': 'media'}], '2099')[0]
g1 = next(g for g in r['grupos'] if g['grupo'] == '1')
check('nota presente y menciona 9999', '9999' in (r.get('nota') or ''), r.get('nota'))
check('9999 NO se removieron (media los incluye)', g1['valor'] == round(float(np.mean(vals)), 2),
      (g1['valor'], round(float(np.mean(vals)), 2)))
shutil.rmtree('enaho_ztest', ignore_errors=True)

print('\n' + ('TODAS LAS PRUEBAS 8-12 OK' if not fails else 'FALLARON: %s' % fails))
sys.exit(1 if fails else 0)
