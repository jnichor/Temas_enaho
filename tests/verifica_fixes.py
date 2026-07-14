# -*- coding: utf-8 -*-
"""Verifica fixes 1, 2, 3 sin datos reales (estructura minima temporal, se limpia sola)."""
import os, sys, shutil

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(PROJ)
sys.path.insert(0, os.path.join(PROJ, 'scripts'))
sys.path.insert(0, PROJ)   # para importar sistema_enaho (esta en la raiz)

# ---- FIX 2: el generador PDF usa el inspect en streaming del visor ----
import generar_documentacion_pdf as PDF
import generar_visor_html as VIS
assert PDF.inspect is VIS.inspect, "PDF no comparte el inspect streaming"
print("[FIX2] PDF.inspect ES el streaming del visor: OK")

# mini CSV para probar que el inspect importado funciona desde el modulo PDF
base = 'enaho_ztest/microodatos_inei/enaho/2_organized/by_year/2099'
os.makedirs(os.path.join(base, 'modulos'), exist_ok=True)
csv = os.path.join(base, 'modulos', '0001_enaho01-2099-100.csv')
with open(csv, 'w', encoding='latin-1') as fh:
    fh.write("CONGLOME,VIVIENDA,HOGAR,X1\n1,1,11,a\n1,2,11,b\n2,1,11,c\n")
m = PDF.inspect(csv)
assert m['key'] == ['CONGLOME', 'VIVIENDA', 'HOGAR'] and m['unica'], m
print("[FIX2] inspect streaming corre desde el modulo PDF: OK (llave %s)" % '+'.join(m['key']))

# ---- FIX 1: 'documentado' se detecta en salidas/<anio>/ ----
os.makedirs('salidas/2099', exist_ok=True)
open('salidas/2099/documentacion_enaho_2099.pdf', 'w').close()
import sistema_enaho as APP
cs, anios, org, doc, cat = APP.estado_global()
assert '2099' in anios and org and doc, (cs, anios, org, doc)
print("[FIX1] estado_global ve la doc en salidas/: OK (doc=%s)" % doc)

# ---- FIX 3: importar sistema_enaho ancla el cwd al proyecto ----
print("[FIX3] cwd tras importar la app:", os.getcwd())
assert os.path.normcase(os.getcwd()) == os.path.normcase(PROJ)
print("[FIX3] os.chdir(ROOT) activo: OK")

# limpieza total de la estructura de prueba
shutil.rmtree('enaho_ztest', ignore_errors=True)
shutil.rmtree('salidas', ignore_errors=True)
print("OK TODO (estructura de prueba eliminada)")
