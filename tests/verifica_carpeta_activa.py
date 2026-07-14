# -*- coding: utf-8 -*-
"""Verifica el selector de 'carpeta activa': arma DOS carpetas enaho_* con el
MISMO año duplicado (caso ambiguo real) y confirma que:
  1) info_carpetas()/estado_global() ven ambas carpetas por separado
  2) años_disponibles(carpeta) / load_catalogo(year, carpeta) SOLO ven la carpeta pedida
  3) estadistica._path/_scan honran `carpeta` -> calcular() con carpeta='A' lee SIEMPRE
     de A, incluso si 'B' ordena alfabéticamente antes (evita la inconsistencia
     catálogo-de-A-pero-datos-de-B que rompería el proposito del selector)
"""
import os, sys, json, csv, shutil, importlib.util
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(PROJ)
sys.path.insert(0, os.path.join(PROJ, 'scripts'))
fails = []

def check(nombre, cond, detalle=''):
    print(('  [OK] ' if cond else '  [FALLA] ') + nombre + ((' | ' + str(detalle)) if detalle and not cond else ''))
    if not cond:
        fails.append(nombre)

YEAR = '2098'
# 'enaho_A_zztest' ordena ANTES que 'enaho_B_zztest' alfabeticamente
CARPS = {'enaho_A_zztest': '111', 'enaho_B_zztest': '222'}  # marca en CONGLOME para distinguir origen

for nombre, marca in CARPS.items():
    base = os.path.join(nombre, 'microodatos_inei', 'enaho', '2_organized', 'by_year', YEAR)
    md = os.path.join(base, 'modulos')
    os.makedirs(md, exist_ok=True)
    with open(os.path.join(base, 'catalogo_%s.json' % YEAR), 'w', encoding='utf-8') as fh:
        json.dump({'anio': YEAR, 'modulos': [{
            'codigo': '200', 'archivo': 'M.csv', 'titulo': 'Test %s' % nombre,
            'unidad_analisis': 'hogar', 'llave_identificacion': ['CONGLOME', 'VIVIENDA', 'HOGAR'],
            'n_columnas': 3, 'familias_variables': [], 'variables': {'Y': 'Ingreso test'},
            'cobertura_geografica': 'nacional', 'meses': [], 'completitud_pct': 100}]}, fh)
    with open(os.path.join(md, 'M.csv'), 'w', newline='', encoding='latin-1') as fh:
        w = csv.writer(fh); w.writerow(['CONGLOME', 'VIVIENDA', 'HOGAR', 'G', 'Y', 'FACTOR07'])
        for h in range(1, 41):
            w.writerow([marca, '1', str(h), '1', str(int(marca) + h), '1.5'])
        for h in range(41, 81):
            w.writerow([marca, '1', str(h), '2', str(int(marca) + h + 1000), '1.5'])

try:
    spec = importlib.util.spec_from_file_location('app', 'sistema_enaho.py')
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    import razonador as RZ
    import estadistica as EST

    infos = {i['nombre']: i for i in m.info_carpetas()}
    check('info_carpetas ve ambas carpetas por separado',
          'enaho_A_zztest' in infos and 'enaho_B_zztest' in infos)
    check('cada carpeta reporta su propio año', infos['enaho_A_zztest']['anios'] == [YEAR])

    check('años_disponibles(A) ve el año', RZ.años_disponibles('enaho_A_zztest') == [YEAR])
    catA = RZ.load_catalogo(YEAR, 'enaho_A_zztest')
    catB = RZ.load_catalogo(YEAR, 'enaho_B_zztest')
    check('load_catalogo respeta la carpeta pedida (A != B)',
          catA['modulos'][0]['titulo'] != catB['modulos'][0]['titulo'])

    # el punto critico: calcular() con carpeta='A' debe leer el CSV de A (marca 111),
    # NUNCA el de B (marca 222), aunque B exista con el mismo año.
    item = {'brecha': 'test', 'outcome': {'archivo': 'M.csv', 'variable': 'Y'},
            'grupo': {'archivo': 'M.csv', 'variable': 'G', 'etiquetas': {}},
            'ponderador': {'archivo': 'M.csv', 'variable': 'FACTOR07'}, 'estadistico': 'media'}
    rA = EST.calcular([item], YEAR, 'enaho_A_zztest')[0]
    rB = EST.calcular([item], YEAR, 'enaho_B_zztest')[0]
    valA = rA['grupos'][0]['valor']
    valB = rB['grupos'][0]['valor']
    check('calcular(carpeta=A) usa datos de A (valor ~111+h, no ~222+h)',
          100 < valA < 200, valA)
    check('calcular(carpeta=B) usa datos de B (valor ~222+h)',
          200 < valB < 300, valB)
    check('A y B dan resultados DISTINTOS (si fueran iguales, el scoping no serviria de nada)',
          valA != valB, (valA, valB))
finally:
    for nombre in CARPS:
        shutil.rmtree(nombre, ignore_errors=True)

print('\n' + ('TODO OK' if not fails else 'FALLARON: %s' % fails))
sys.exit(1 if fails else 0)
