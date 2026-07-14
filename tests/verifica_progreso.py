# -*- coding: utf-8 -*-
"""Verifica el guardado progresivo (_guardar_progreso) y la marca de estado en
'Ver propuestas guardadas'. Estructura temporal en temas/_ztest_* (se limpia sola)."""
import os, sys, json, shutil, asyncio, importlib.util
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(PROJ)
sys.path.insert(0, os.path.join(PROJ, 'scripts'))
fails = []

def check(nombre, cond, detalle=''):
    print(('  [OK] ' if cond else '  [FALLA] ') + nombre + ((' | ' + str(detalle)) if detalle and not cond else ''))
    if not cond:
        fails.append(nombre)

spec = importlib.util.spec_from_file_location('app', 'sistema_enaho.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

app = m.ENAHOApp()

print('--- _guardar_progreso ---')
res = {'anios': ['2099'], 'tema': None}
d = app._guardar_progreso(res)
check('sin tema -> no guarda (retorna None)', d is None, d)
check('sin tema -> no crea carpeta temas/tema', not os.path.isdir(os.path.join('temas', 'tema')))

res['tema'] = {'tema': 'Test Progreso Ztest'}
d = app._guardar_progreso(res)
check('con tema -> guarda y devuelve carpeta', bool(d) and os.path.isdir(d), d)
data = json.load(open(os.path.join(d, 'propuesta.json'), encoding='utf-8'))
check('estado inicial = en_progreso', data.get('estado') == 'en_progreso', data.get('estado'))
check('tiene timestamp', bool(data.get('actualizado')))

res['manifiesto'] = [{'variable': 'X'}]   # simula que avanzo un paso mas
app._guardar_progreso(res)
data = json.load(open(os.path.join(d, 'propuesta.json'), encoding='utf-8'))
check('el progreso posterior conserva lo anterior (manifiesto)', data.get('manifiesto') == [{'variable': 'X'}])

d2 = app._guardar_progreso(res, estado='incompleta', error='boom de prueba')
data = json.load(open(os.path.join(d2, 'propuesta.json'), encoding='utf-8'))
check('marca incompleta + guarda el error', data.get('estado') == 'incompleta' and data.get('error') == 'boom de prueba', data)

d3 = app._guardar_progreso(res, estado='completa')
data = json.load(open(os.path.join(d3, 'propuesta.json'), encoding='utf-8'))
check('marca completa al finalizar', data.get('estado') == 'completa')

print('--- marca de estado en "Ver propuestas guardadas" (pilot) ---')
# dos carpetas DISTINTAS: una incompleta, otra completa (la de arriba terminó en 'completa')
d_inc = os.path.join('temas', 'test-progreso-incompleto-ztest')
os.makedirs(d_inc, exist_ok=True)
json.dump({'tema': {'tema': 'Test Progreso Incompleto Ztest'}, 'estado': 'incompleta', 'error': 'boom'},
          open(os.path.join(d_inc, 'propuesta.json'), 'w', encoding='utf-8'))
d4 = os.path.join('temas', 'test-progreso-completo-ztest')
os.makedirs(d4, exist_ok=True)
json.dump({'tema': {'tema': 'Test Progreso Completo Ztest'}, 'estado': 'completa'},
          open(os.path.join(d4, 'propuesta.json'), 'w', encoding='utf-8'))

captured = {}
_orig_push = m.ENAHOApp.push_screen_wait
async def _fake_push(self, screen):
    if isinstance(screen, m.SelectScreen) and screen.titulo == 'Propuestas guardadas':
        captured['labels'] = [lbl for lbl, _ in screen.opciones]
        return None   # cancelar de inmediato
    return await _orig_push(self, screen)
m.ENAHOApp.push_screen_wait = _fake_push

async def t():
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press('v')
        await pilot.pause()

asyncio.run(t())
labels = captured.get('labels', [])
print('  opciones mostradas:', labels)
check('incompleta marcada en la lista', any('incompleta' in l for l in labels), labels)
check('completa marcada con ✓', any('✓' in l for l in labels), labels)

shutil.rmtree(os.path.join('temas', 'test-progreso-ztest'), ignore_errors=True)
shutil.rmtree(d_inc, ignore_errors=True)
shutil.rmtree(d4, ignore_errors=True)
print('\n' + ('TODO OK' if not fails else 'FALLARON: %s' % fails))
sys.exit(1 if fails else 0)
