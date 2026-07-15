# -*- coding: utf-8 -*-
"""Verifica que el puntaje_total ya NO lo calcule la IA libremente (antes hacia
un simple promedio de los 4 criterios, inflando temas con factibilidad casi nula
- el caso real: (9+9+3+8)/4=7.25 pese a que el propio texto decia 'el diseño RDD
es inviable'). Ahora se calcula determinista: factibilidad actua como compuerta
multiplicativa sobre la calidad de la idea (impacto+relevancia+originalidad)."""
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

print('--- caso real: factibilidad muy baja NO debe promediarse en partes iguales ---')
mock_resp_bajo = {
    'impacto_social': {'puntaje': 9, 'justificacion': 'x'},
    'relevancia_actual': {'puntaje': 9, 'justificacion': 'x'},
    'factibilidad_datos': {'puntaje': 3, 'justificacion': 'diseño RDD inviable con el catálogo actual'},
    'originalidad': {'puntaje': 8, 'justificacion': 'x'},
    'veredicto': 'El tema tiene mérito académico y de política pública elevados.',
}
razonador = RZ
_orig_ask_json = razonador.ask_json
razonador.ask_json = lambda prompt, **kw: dict(mock_resp_bajo)
try:
    out = RZ.puntuar({'tema': 't'}, [], {}, {})
    calidad_idea = (9 + 9 + 8) / 3
    esperado = round(calidad_idea * (3 / 10), 2)
    check('puntaje_total NO es el promedio simple (7.25)', out['puntaje_total'] != 7.25, out['puntaje_total'])
    check('puntaje_total es la formula determinista (calidad x factibilidad/10)',
          out['puntaje_total'] == esperado, (out['puntaje_total'], esperado))
    check('el puntaje bajo (2.6) refleja que el tema NO es viable', out['puntaje_total'] < 4, out['puntaje_total'])
    check('el veredicto avisa que es CONDICIONAL', 'CONDICIONAL' in out['veredicto'], out['veredicto'])
    check('el veredicto conserva la sintesis original de la IA', 'mérito académico' in out['veredicto'], out['veredicto'])
finally:
    razonador.ask_json = _orig_ask_json

print('--- caso normal: factibilidad alta no penaliza ---')
mock_resp_alto = {
    'impacto_social': {'puntaje': 8, 'justificacion': 'x'},
    'relevancia_actual': {'puntaje': 7, 'justificacion': 'x'},
    'factibilidad_datos': {'puntaje': 9, 'justificacion': 'todo disponible y verificado'},
    'originalidad': {'puntaje': 6, 'justificacion': 'x'},
    'veredicto': 'Tema solido y ejecutable.',
}
razonador.ask_json = lambda prompt, **kw: dict(mock_resp_alto)
try:
    out = RZ.puntuar({'tema': 't'}, [], {}, {})
    calidad_idea = (8 + 7 + 6) / 3
    esperado = round(calidad_idea * (9 / 10), 2)
    check('con factibilidad alta, el puntaje es casi la calidad de idea completa',
          out['puntaje_total'] == esperado, (out['puntaje_total'], esperado))
    check('NO se marca como CONDICIONAL', 'CONDICIONAL' not in out['veredicto'], out['veredicto'])
finally:
    razonador.ask_json = _orig_ask_json

print('\n' + ('TODO OK' if not fails else 'FALLARON: %s' % fails))
sys.exit(1 if fails else 0)
