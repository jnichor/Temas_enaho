# -*- coding: utf-8 -*-
"""Verifica la priorizacion causal (orden determinista + prompts + ficha PDF),
sin gastar cuota real: intercepta ask_json con respuestas sinteticas."""
import os, sys, json
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(PROJ)
sys.path.insert(0, os.path.join(PROJ, 'scripts'))
fails = []

def check(nombre, cond, detalle=''):
    print(('  [OK] ' if cond else '  [FALLA] ') + nombre + ((' | ' + str(detalle)) if detalle and not cond else ''))
    if not cond:
        fails.append(nombre)

import razonador as RZ

print('--- _ordenar_por_causalidad (funcion pura) ---')
desordenado = [
    {'tema': 'A', 'nivel_causal_esperado': 'asociacion'},
    {'tema': 'B', 'nivel_causal_esperado': 'causal_fuerte'},
    {'tema': 'C', 'nivel_causal_esperado': 'causal_debil'},
    {'tema': 'D'},  # sin nivel -> debe ir al final
    {'tema': 'E', 'nivel_causal_esperado': 'causal_fuerte'},
]
ordenado = RZ._ordenar_por_causalidad(desordenado)
orden_temas = [t['tema'] for t in ordenado]
check('fuerte primero (B y E), estable entre si', orden_temas[:2] == ['B', 'E'], orden_temas)
check('debil en medio (C)', orden_temas[2] == 'C', orden_temas)
check('asociacion despues (A)', orden_temas[3] == 'A', orden_temas)
check('sin nivel al final (D)', orden_temas[4] == 'D', orden_temas)

print('--- sugerir_temas: prompt formatea bien + aplica orden ---')
mock_resp = [
    {'tema': 'Tema asociacion', 'pregunta_investigacion': 'p', 'nivel_causal_esperado': 'asociacion',
     'justificacion_causal': 'no hay instrumento'},
    {'tema': 'Tema fuerte', 'pregunta_investigacion': 'p', 'nivel_causal_esperado': 'causal_fuerte',
     'justificacion_causal': 'corte por edad legal minima'},
]
import razonador
_orig_ask_json = razonador.ask_json
razonador.ask_json = lambda prompt, **kw: mock_resp
cat = {'anio': '2099', 'modulos': []}
try:
    temas = RZ.sugerir_temas(cat, area='empleo', n=2)
    check('sugerir_temas no crashea con el nuevo prompt', True)
    check('sugerir_temas reordena (fuerte primero)', temas[0]['tema'] == 'Tema fuerte', [t['tema'] for t in temas])
except Exception as e:
    check('sugerir_temas no crashea con el nuevo prompt', False, e)
finally:
    razonador.ask_json = _orig_ask_json

print('--- sugerir_temas_multi: idem ---')
razonador.ask_json = lambda prompt, **kw: mock_resp
mcat = {'anios': ['2098', '2099'], 'modulos': []}
try:
    temas = RZ.sugerir_temas_multi(mcat, area='empleo', n=2)
    check('sugerir_temas_multi no crashea', True)
    check('sugerir_temas_multi reordena (fuerte primero)', temas[0]['tema'] == 'Tema fuerte', [t['tema'] for t in temas])
except Exception as e:
    check('sugerir_temas_multi no crashea', False, e)
finally:
    razonador.ask_json = _orig_ask_json

print('--- ficha PDF: muestra nivel esperado vs real + aviso de degradacion ---')
import ficha_pdf as FICHA
cat_full = {'anio': '2099', 'modulos': []}
tema_deg = {'tema': 'Test degradacion', 'pregunta_investigacion': 'p', 'modulos': [],
           'nivel_causal_esperado': 'causal_fuerte', 'justificacion_causal': 'se esperaba un corte claro'}
res = {'anios': ['2099'], 'cobertura_anios': ['2099'], 'tema': tema_deg, 'manifiesto': [],
       'causal': {'nivel_causal': 'asociacion', 'estrategia_identificacion': 'OLS con controles'},
       'plan_datos': {'nivel_de_analisis': 'hogar', 'llaves_merge': ['CONGLOME'], 'archivo_base': 'x.csv',
                      'secuencia_merge': [], 'filtros': [], 'explicacion': []},
       'puntuacion': {'puntaje_total': 1, 'veredicto': 't'}}
out = FICHA.generar_ficha_pdf(res, cat_full, os.path.join('salidas', 'fichas', '_t_causal.pdf'))
import pdfplumber
with pdfplumber.open(out) as pdf:
    t = '\n'.join((p.extract_text() or '') for p in pdf.pages)
check('ficha muestra nivel esperado', 'esperada' in t.lower() and 'causal_fuerte' in t)
check('ficha avisa la degradacion (esperado>real)', 'menos sólida' in t or 'menos solida' in t.lower(), t[:600])
os.remove(out)

print('\n' + ('TODO OK' if not fails else 'FALLARON: %s' % fails))
sys.exit(1 if fails else 0)
