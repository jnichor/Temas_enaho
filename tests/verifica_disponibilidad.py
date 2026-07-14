# -*- coding: utf-8 -*-
"""Verifica el cierre del hueco de disponibilidad multi-anio (paso 7) con el
catalogo REAL 2024-2025 que esta en disco. Sin llamadas a IA."""
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

cob = ['2024', '2025']
mcat = RZ.catalogo_multianio(cob)
cat = RZ.load_catalogo('2025')
check('catalogos reales cargados', bool(mcat and cat))

# buscar en el catalogo real una variable SOLO-2025 y una COMUN del modulo 500
m500 = next(m for m in mcat['modulos'] if str(m['codigo']) == '500')
solo25 = next(k for k, v in m500['variables'].items() if v['anios'] == ['2025'])
comun = next(k for k, v in m500['variables'].items() if set(v['anios']) >= {'2024', '2025'})
arch25 = next(m['archivo'] for m in cat['modulos'] if str(m['codigo']) == '500')
print('  variable solo-2025:', solo25, '| comun:', comun, '| archivo:', arch25)

print('--- verificacion determinista post-paso 7 ---')
manif = [
    {'archivo': arch25, 'variable': comun, 'rol': 'dependiente'},
    {'archivo': arch25, 'variable': solo25, 'rol': 'control'},
    {'archivo': arch25, 'variable': 'CONGLOME', 'rol': 'identificacion'},
]
rep = RZ.disponibilidad_variables(mcat, cat, manif, cob)
check('flaggea SOLO la variable parcial', len(rep) == 1 and rep[0]['variable'] == solo25.upper(),
      rep)
check('indica el anio faltante (2024)', rep and rep[0]['faltan_en'] == ['2024'], rep)
check('indica donde SI existe (2025)', rep and rep[0]['anios_disponibles'] == ['2025'], rep)

print('--- regla multi-anio inyectada al prompt del paso 7 ---')
tema = {'modulos': ['500'], 'tema': 't', 'pregunta_investigacion': 'p'}
txt = RZ._restriccion_multianio(mcat, tema, cob)
check('la regla menciona la variable parcial', solo25 in txt, txt[:150])
check('la regla NO menciona la comun como prohibida', ('%s (solo' % comun) not in txt)
check('un solo anio => sin restriccion', RZ._restriccion_multianio(mcat, tema, ['2025']) == '')

print('--- ficha PDF con anotacion de variables parciales ---')
import ficha_pdf as FICHA
res = {'anios': cob, 'cobertura_anios': cob,
       'tema': {'tema': 'Test disponibilidad', 'pregunta_investigacion': 'p', 'modulos': ['500']},
       'manifiesto': manif, 'variables_parciales': rep,
       'plan_datos': {'nivel_de_analisis': 'persona', 'llaves_merge': ['CONGLOME'], 'archivo_base': arch25,
                      'secuencia_merge': [], 'filtros': [], 'explicacion': []},
       'puntuacion': {'puntaje_total': 1, 'veredicto': 'test'}}
out = FICHA.generar_ficha_pdf(res, cat, os.path.join('salidas', 'fichas', '_t_dispo.pdf'))
check('ficha PDF generada', os.path.exists(out))
import pdfplumber
with pdfplumber.open(out) as pdf:
    t = '\n'.join((p.extract_text() or '') for p in pdf.pages)
check('la ficha marca "solo años: 2025"', 'solo años: 2025' in t)
os.remove(out)

print('\n' + ('TODO OK' if not fails else 'FALLARON: %s' % fails))
sys.exit(1 if fails else 0)
