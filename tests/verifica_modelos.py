# -*- coding: utf-8 -*-
"""Verifica que cada funcion del razonador pase el modelo correcto a `claude -p`,
sin gastar cuota real: intercepta subprocess.run y captura el comando armado."""
import os, sys, json, subprocess as _sp
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(PROJ)
sys.path.insert(0, os.path.join(PROJ, 'scripts'))
fails = []

def check(nombre, cond, detalle=''):
    print(('  [OK] ' if cond else '  [FALLA] ') + nombre + ((' | ' + str(detalle)) if detalle and not cond else ''))
    if not cond:
        fails.append(nombre)

import razonador as RZ

captured = {}

class _R:
    def __init__(self, out):
        self.stdout, self.stderr, self.returncode = out, '', 0

def fake_run(cmd, **kw):
    captured['cmd'] = cmd
    return _R(kw['input'][:0] or '{}')  # respuesta minima valida (no se usa el contenido aqui)

_sp.run = fake_run

cat = {'anio': '2099', 'modulos': [{'codigo': '500', 'archivo': 'x.csv', 'titulo': 't',
      'unidad_analisis': 'persona', 'llave_identificacion': ['CONGLOME'],
      'cobertura_geografica': {}, 'meses': [], 'completitud_pct': 90, 'familias_variables': [],
      'variables': {'X': 'sig'}, 'n_columnas': 1}]}
tema = {'tema': 't', 'pregunta_investigacion': 'p', 'modulos': ['500']}

casos = [
    ('sugerir_areas', lambda: RZ.sugerir_areas(cat, 3), 'sonnet'),
    ('sugerir_temas', lambda: RZ.sugerir_temas(cat, 'empleo', None, 4), 'sonnet'),
    ('analizar_tema', lambda: RZ.analizar_tema(cat, tema), 'sonnet'),
    ('seleccionar_variables', lambda: RZ.seleccionar_variables(cat, tema), 'haiku'),
    ('diseno_causal', lambda: RZ.diseno_causal(cat, tema, [], ['2099']), 'sonnet'),
    ('sugerir_filtros', lambda: RZ.sugerir_filtros(cat, tema, []), 'haiku'),
    ('plan_brechas', lambda: RZ.plan_brechas(cat, tema, []), 'haiku'),
    ('interpretar_brechas', lambda: RZ.interpretar_brechas(tema, []), 'sonnet'),
    ('puntuar', lambda: RZ.puntuar(tema, {}, {}, {}), 'sonnet'),
]
for nombre, fn, esperado in casos:
    fn()
    cmd = captured.get('cmd', '')
    check('%s -> --model %s' % (nombre, esperado), ('--model %s' % esperado) in cmd, cmd)

# contraste_literatura: ademas debe llevar --allowedTools WebSearch
RZ.contraste_literatura(tema, {})
cmd = captured.get('cmd', '')
check('contraste_literatura -> --model sonnet', '--model sonnet' in cmd, cmd)
check('contraste_literatura -> conserva WebSearch', 'WebSearch' in cmd, cmd)

# sin modelo especificado -> ask() no agrega --model (comportamiento por defecto intacto)
RZ.ask('hola')
cmd = captured.get('cmd', '')
check('ask() sin model no agrega --model', '--model' not in cmd, cmd)

print('\n' + ('TODO OK' if not fails else 'FALLARON: %s' % fails))
sys.exit(1 if fails else 0)
