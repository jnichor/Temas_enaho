# -*- coding: utf-8 -*-
"""Verifica que _guardar() sea async y delegue el I/O a un hilo (asyncio.to_thread),
y que siga escribiendo el propuesta.json correctamente."""
import os, sys, json, shutil, asyncio, importlib.util, inspect
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

check('_guardar es una corrutina (async)', inspect.iscoroutinefunction(app._guardar))
check('no quedan llamadas sin await a _guardar_progreso',
      'self._guardar_progreso(' not in open('sistema_enaho.py', encoding='utf-8').read()
      .replace('async def _guardar(self, res', 'X')  # excluye la definicion/uso interno legitimo
      .replace("return await asyncio.to_thread(self._guardar_progreso, res, estado, error)", ''))

async def t():
    res = {'anios': ['2099'], 'tema': {'tema': 'Test Async Ztest'}}
    d = await app._guardar(res)
    check('_guardar escribe el archivo (via hilo)', d and os.path.isfile(os.path.join(d, 'propuesta.json')))
    data = json.load(open(os.path.join(d, 'propuesta.json'), encoding='utf-8'))
    check('contenido correcto', data.get('estado') == 'en_progreso' and data.get('tema', {}).get('tema') == 'Test Async Ztest')
    d2 = await app._guardar(res, estado='completa')
    data2 = json.load(open(os.path.join(d2, 'propuesta.json'), encoding='utf-8'))
    check('estado=completa se guarda bien via el wrapper async', data2.get('estado') == 'completa')

asyncio.run(t())
shutil.rmtree(os.path.join('temas', 'test-async-ztest'), ignore_errors=True)
print('\n' + ('TODO OK' if not fails else 'FALLARON: %s' % fails))
sys.exit(1 if fails else 0)
