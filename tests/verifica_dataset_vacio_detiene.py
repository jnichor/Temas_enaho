# -*- coding: utf-8 -*-
"""Verifica el nuevo guard: si el dataset final (Paso 11) sale con 0 filas,
action_proponer se DETIENE ahi (no sigue a brechas/interpretacion/literatura/
puntuacion) y la propuesta queda marcada 'incompleta' con un motivo claro -
en vez de terminar 'completa' con un dataset inservible, que es exactamente
lo que paso en la corrida real que motivo este fix."""
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

import razonador as RZ
import estadistica as EST

CAT = {'anio': '2099', 'modulos': [{
    'archivo': 'X.csv', 'codigo': '001', 'titulo': 'Test', 'unidad_analisis': 'hogar',
    'llave_identificacion': ['CONGLOME', 'VIVIENDA', 'HOGAR'], 'llave_unica': True,
    'n_filas': 10, 'n_columnas': 4, 'cobertura_geografica': 'nacional', 'meses': [],
    'completitud_pct': 100.0, 'familias_variables': [],
    'variables': {'CONGLOME': 'x', 'VIVIENDA': 'x', 'HOGAR': 'x', 'VAR1': 'variable de prueba'},
    'valores': {},
}]}
MCAT = {'anios': ['2099'], 'modulos': [{
    'codigo': '001', 'titulo': 'Test', 'unidad': 'hogar', 'llave': ['CONGLOME', 'VIVIENDA', 'HOGAR'],
    'archivo': 'X.csv', 'variables': {'VAR1': {'sig': 'variable de prueba', 'anios': ['2099']}},
}]}
TEMA = {'tema': 'Tema de prueba', 'pregunta_investigacion': 'p', 'modulos': ['001'],
       'variables_clave': ['VAR1'], 'cobertura_anios': ['2099'], 'motivo_cobertura': 'x',
       'nivel_causal_esperado': 'asociacion', 'justificacion_causal': 'x'}

# --- mocks deterministas: nada de esto gasta cuota real ---
RZ.años_disponibles = lambda carpeta=None: ['2099']
RZ.catalogo_multianio = lambda anios, carpeta=None: MCAT
RZ.load_catalogo = lambda year, carpeta=None: CAT
RZ.carpetas_de_anio = lambda year: ['enaho_ztest9']
RZ.sugerir_temas_multi = lambda mcat, area, contexto, n: [TEMA]
RZ.analizar_tema = lambda cat, tema: {'analisis': 'x'}
RZ.seleccionar_variables = lambda cat, tema, mcat, cob, contexto: [
    {'archivo': 'X.csv', 'variable': 'CONGLOME', 'rol': 'identificacion'},
    {'archivo': 'X.csv', 'variable': 'VIVIENDA', 'rol': 'identificacion'},
    {'archivo': 'X.csv', 'variable': 'HOGAR', 'rol': 'identificacion'},
    {'archivo': 'X.csv', 'variable': 'VAR1', 'rol': 'dependiente'},
]
RZ.diseno_causal = lambda cat, tema, manifiesto, cob: {'nivel_causal': 'asociacion', 'estrategia_identificacion': 'OLS'}
RZ.sugerir_filtros = lambda cat, tema, manifiesto: []
EST.verificar_filtros = lambda filtros, year, carpeta=None: []
EST.verificar_merge = lambda plan, year, carpeta=None: []
EST.revisar_consolidacion = lambda cat, manifiesto, year, carpeta=None: {}
# el punto critico del test: el dataset final sale con 0 filas
EST.materializar_dataset = lambda plan_datos, manifiesto, filtros, resolucion, anios, rep, out_path, carpeta=None: {
    'variables_excluidas': [], 'agregaciones': [], 'restricciones': [], 'filtros_aplicados': [],
    'filtros_omitidos': [], 'columnas_limpiadas': [], 'filtros_contradictorios': [], 'anios': anios,
    'anios_con_error': [], 'filas': 0, 'columnas': ['CONGLOME', 'VIVIENDA', 'HOGAR', 'VAR1'],
    'filas_duplicadas_por_llave': 0, 'nulos_por_columna': {}, 'ruta': out_path,
}
# si el guard NO se dispara, el flujo seguiria hasta plan_brechas: si eso llegara a
# llamarse, es que el fix no esta actuando -> falla el test explicitamente.
def _plan_brechas_no_deberia_llamarse(*a, **kw):
    raise AssertionError('plan_brechas se llamo: el guard de 0 filas NO detuvo el flujo')
RZ.plan_brechas = _plan_brechas_no_deberia_llamarse

_orig_push = m.ENAHOApp.push_screen_wait
async def _fake_push(self, screen):
    if isinstance(screen, m.AreaScreen):
        return ('A', 'finanzas', None)
    if isinstance(screen, m.SelectScreen) and 'Elige un tema' in screen.titulo:
        return TEMA
    return await _orig_push(self, screen)
m.ENAHOApp.push_screen_wait = _fake_push

async def t():
    app = m.ENAHOApp()   # instancia NUEVA por intento: no reusar una app entre run_test()
    async with app.run_test() as pilot:
        await pilot.pause()
        app.action_proponer()
        # esperar a que el worker ARRANQUE (se ponga busy) antes de esperar a que termine;
        # si no, "not app._busy" es cierto en la primerísima vuelta (todavia no arranco) y
        # el 'async with' se cierra mientras el worker sigue corriendo en segundo plano,
        # que despues intenta tocar una pantalla ya desmontada -> NoMatches('#status').
        for _ in range(200):
            await pilot.pause()
            if app._busy:
                break
        for _ in range(400):
            await pilot.pause()
            if not app._busy:
                break
        # settle extra: deja que cualquier callback tardio (call_from_thread, refresh
        # diferido) termine de correr ANTES de que 'async with' desmonte la pantalla.
        for _ in range(10):
            await pilot.pause()

# el harness de Textual a veces tiene una condicion de carrera propia al desmontar la
# app (NoMatches en '#status' durante el __aexit__ de run_test) que no depende de nuestra
# logica de negocio -- ya verificada correcta en corridas aisladas. Reintenta acotado en
# vez de fallar el test por un timing del arnes, no del codigo bajo prueba.
_ultimo_error = None
for _intento in range(3):
    try:
        asyncio.run(t())
        _ultimo_error = None
        break
    except Exception as e:
        _ultimo_error = e
if _ultimo_error is not None:
    raise _ultimo_error

slug = m.slug(TEMA['tema'])
prop_path = os.path.join('temas', slug, 'propuesta.json')
check('se guardo la propuesta', os.path.isfile(prop_path))
if os.path.isfile(prop_path):
    data = json.load(open(prop_path, encoding='utf-8'))
    check('estado quedo incompleta (NO completa)', data.get('estado') == 'incompleta', data.get('estado'))
    check('el error menciona el dataset de 0 filas', '0 filas' in (data.get('error') or ''), data.get('error'))
    check('NO llego a calcular brechas (se detuvo antes)', 'brechas' not in data, list(data.keys()))
    check('NO llego a puntuacion', 'puntuacion' not in data, list(data.keys()))
    check('SI alcanzo a guardar el dataset_export (para diagnosticar)', 'dataset_export' in data)

shutil.rmtree(os.path.join('temas', slug), ignore_errors=True)
out_csv = os.path.join('salidas', 'fichas', slug + '_dataset.csv')
if os.path.isfile(out_csv):
    os.remove(out_csv)

print('\n' + ('TODO OK' if not fails else 'FALLARON: %s' % fails))
sys.exit(1 if fails else 0)
