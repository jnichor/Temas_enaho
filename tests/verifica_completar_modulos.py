# -*- coding: utf-8 -*-
"""Verifica razonador.completar_modulos_por_valores: si el tema (Paso 5) menciona
un programa especifico (ej. 'Pension 65') que existe como codigo de VALOR
verificado en un modulo que no quedo incluido (caso real: se eligio 700A, pero
Pension 65 vive en 700B), lo agrega automaticamente - sin inventar nada, solo por
coincidencia real de palabras contra el diccionario. Sin falsos positivos en
temas no relacionados."""
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

# catalogo sintetico que replica el caso real: 200, 700A (elegido por el tema,
# programas alimentarios) y 700B (NO elegido, pero tiene el codigo de Pension 65)
CAT = {'anio': '2099', 'modulos': [
    {'codigo': '200', 'archivo': '0002-200.csv', 'titulo': 'Miembros del hogar',
     'variables': {'P208A': 'edad'}, 'valores': {}},
    {'codigo': '700A', 'archivo': '0037-700a.csv', 'titulo': 'Programas sociales no alimentarios',
     'variables': {'P703': 'programa'},
     'valores': {'P703': {'1': 'Vaso de Leche', '2': 'Comedor Popular'}}},
    {'codigo': '700B', 'archivo': '0037-700b.csv', 'titulo': 'Programas sociales',
     'variables': {'P712': 'programa'},
     'valores': {'P712': {'4': 'Programa de Apoyo Directo a los más Pobres – JUNTOS',
                          '5': 'Programa Pensión 65'}}},
    {'codigo': '601', 'archivo': '0007-601.csv', 'titulo': 'Sumaria de gastos',
     'variables': {'I601E': 'gasto'}, 'valores': {}},
]}

print('--- caso real: tema menciona Pension 65, modulo 700B no estaba incluido ---')
tema = {'tema': 'Efecto de la transferencia monetaria Pensión 65 sobre el consumo del hogar',
       'pregunta_investigacion': '¿Recibir la transferencia de Pensión 65 reduce la pobreza?',
       'modulos': ['200', '700A', '601']}
tema2, agregados = RZ.completar_modulos_por_valores(CAT, tema)
check('agrego el modulo 700B', any(a['modulo'] == '700B' for a in agregados), agregados)
check('el modulo 700B quedo en tema.modulos', '700B' in tema2['modulos'], tema2['modulos'])
check('identifico la variable y el codigo correctos', agregados[0]['variable'] == 'P712' and agregados[0]['codigo_valor'] == '5', agregados)
check('NO agrego 700A de nuevo (ya estaba)', sum(1 for a in agregados if a['modulo'] == '700A') == 0)

print('--- caso normal: tema NO relacionado no agrega nada de mas ---')
tema_normal = {'tema': 'Efecto de la educación del jefe de hogar sobre el ingreso laboral',
              'pregunta_investigacion': '¿Más años de estudio aumentan el ingreso?',
              'modulos': ['200', '601']}
tema_normal2, agregados_normal = RZ.completar_modulos_por_valores(CAT, tema_normal)
check('NO agrega 700A ni 700B a un tema no relacionado', agregados_normal == [], agregados_normal)
check('modulos no cambiaron', tema_normal2['modulos'] == ['200', '601'], tema_normal2['modulos'])

print('--- caso ya completo: si el modulo correcto YA estaba, no hace nada ---')
tema_completo = {'tema': 'Efecto de Pensión 65 sobre el consumo',
                 'pregunta_investigacion': 'x', 'modulos': ['200', '700B', '601']}
tema_completo2, agregados_completo = RZ.completar_modulos_por_valores(CAT, tema_completo)
check('no agrega nada si ya estaba incluido', agregados_completo == [], agregados_completo)
check('modulos quedan igual', tema_completo2['modulos'] == ['200', '700B', '601'], tema_completo2['modulos'])

print('\n' + ('TODO OK' if not fails else 'FALLARON: %s' % fails))
sys.exit(1 if fails else 0)
