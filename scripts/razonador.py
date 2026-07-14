# -*- coding: utf-8 -*-
"""Razonador: pasos 5–10 del sistema, ejecutados con la SUSCRIPCIÓN de Claude
(Claude Code en modo headless `claude -p`, sin API key).

Principio rector: GROUNDING. Todo razonamiento se ancla al catálogo real de
datos (catalogo_<año>.json). El LLM no debe proponer módulos/variables que no
existan. Cada paso devuelve un artefacto JSON (los "contratos" entre pasos).
"""
import os, re, json, glob, subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV = {**os.environ, 'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8'}

REGLA = ("Eres un economista investigador experto en la ENAHO del Perú. "
         "Usa EXCLUSIVAMENTE los módulos y variables del catálogo que se te da. "
         "NUNCA inventes módulos, variables ni cifras. Si algo no está en los datos, dilo. "
         "Responde SIEMPRE en español y SOLO con JSON válido, sin texto adicional ni ```.")


# ---------- asignación de modelo por paso (estrategia "conservador", elegida por el usuario) ----------
# sonnet: todo lo creativo/de juicio (temas/áreas, análisis, diseño causal, interpretar
#         brechas, literatura, puntuación) — es donde más importa la calidad.
# haiku:  SOLO lo más mecánico — elegir de listas ya acotadas por el catálogo
#         (seleccionar variables, filtros, plan de brechas).
MODELOS = {
    'sugerir_areas': 'sonnet', 'sugerir_temas': 'sonnet', 'sugerir_temas_multi': 'sonnet',
    'analizar_tema': 'sonnet', 'diseno_causal': 'sonnet', 'interpretar_brechas': 'sonnet',
    'contraste_literatura': 'sonnet', 'puntuar': 'sonnet',
    'seleccionar_variables': 'haiku', 'sugerir_filtros': 'haiku', 'plan_brechas': 'haiku',
    'plan_resolucion_niveles': 'haiku',
}


# ---------- invocación de Claude (suscripción, headless) ----------
def ask(prompt, timeout=400, web=False, model=None):
    full = REGLA + "\n\n" + prompt
    cmd = 'claude -p'
    if model:
        cmd += ' --model %s' % model
    if web:
        cmd += ' --allowedTools "WebSearch"'
    r = subprocess.run(cmd, input=full, shell=True, cwd=ROOT, env=ENV,
                       capture_output=True, text=True, encoding='utf-8',
                       errors='replace', timeout=timeout)
    out = (r.stdout or '').strip()
    if not out:
        # sin stdout no hay nada que parsear: reporta la causa REAL (stderr/código),
        # no el críptico "no se pudo extraer JSON" de antes
        err = (r.stderr or '').strip()
        raise RuntimeError(
            "claude -p no devolvió salida (código %s)%s. ¿Claude Code está instalado y con sesión iniciada?"
            % (r.returncode, ('; stderr: ' + err[:400]) if err else ''))
    return out


def ask_json(prompt, timeout=400, web=False, model=None):
    raw = ask(prompt, timeout, web=web, model=model)
    return _extract_json(raw)


def _extract_json(raw):
    s = raw.strip()
    s = re.sub(r'^```(?:json)?', '', s).strip()
    s = re.sub(r'```$', '', s).strip()
    try:
        return json.loads(s)
    except Exception:
        pass
    for op, cl in (('[', ']'), ('{', '}')):
        i, j = s.find(op), s.rfind(cl)
        if i != -1 and j != -1 and j > i:
            try:
                return json.loads(s[i:j + 1])
            except Exception:
                continue
    raise ValueError("No se pudo extraer JSON de la respuesta:\n" + raw[:500])


# ---------- catálogo (grounding) ----------
def _rutas_catalogo(year, carpeta=None):
    # sorted(): si el mismo año existe en varias carpetas enaho_* Y no se pidió una
    # carpeta concreta, la elección es DETERMINISTA (alfabética), consistente con
    # estadistica._path. `carpeta` (ej. "enaho_2015-2020") acota la búsqueda a esa
    # carpeta específica, la que el usuario eligió como "carpeta activa" en el TUI.
    base = carpeta if carpeta else 'enaho_*'
    return sorted(glob.glob(os.path.join(ROOT, base, 'microodatos_inei', 'enaho',
                                         '2_organized', 'by_year', str(year), 'catalogo_%s.json' % year)))


def load_catalogo(year, carpeta=None):
    hits = _rutas_catalogo(year, carpeta)
    if not hits:
        return None
    with open(hits[0], encoding='utf-8') as fh:
        return json.load(fh)


def carpetas_de_anio(year):
    """Carpetas enaho_* que contienen catálogo para ese año (>1 = duplicado ambiguo)."""
    out = []
    for p in _rutas_catalogo(year):
        rel = os.path.relpath(p, ROOT)
        out.append(rel.split(os.sep)[0])
    return out


def años_disponibles(carpeta=None):
    base = carpeta if carpeta else 'enaho_*'
    años = []
    for p in glob.glob(os.path.join(ROOT, base, 'microodatos_inei', 'enaho',
                                    '2_organized', 'by_year', '*', 'catalogo_*.json')):
        m = re.search(r'catalogo_(\d+)\.json$', p)
        if m:
            años.append(m.group(1))
    return sorted(set(años))


def _compacto(cat, max_vars=8):
    out = []
    for m in cat['modulos']:
        labels = [v for v in m['variables'].values() if v][:max_vars]
        out.append({'codigo': m['codigo'], 'titulo': m['titulo'],
                    'unidad': m['unidad_analisis'], 'llave': m['llave_identificacion'],
                    'n_variables': m['n_columnas'],
                    'familias': m['familias_variables'], 'ejemplos_variables': labels})
    return out


def _modulos_detalle(cat, codigos):
    sel = []
    cods = {c.upper() for c in codigos}
    for m in cat['modulos']:
        if m['codigo'].upper() in cods:
            sel.append({'codigo': m['codigo'], 'archivo': m['archivo'], 'titulo': m['titulo'],
                        'unidad': m['unidad_analisis'], 'llave': m['llave_identificacion'],
                        'cobertura_geografica': m['cobertura_geografica'], 'meses': m['meses'],
                        'completitud_pct': m['completitud_pct'],
                        'variables': {k: v for k, v in m['variables'].items()},
                        'valores': m.get('valores', {})})
    return sel


# ---------- MULTI-AÑO: grounding con disponibilidad de variables por año ----------
def load_catalogos(anios, carpeta=None):
    out = []
    for a in anios:
        c = load_catalogo(str(a), carpeta)
        if c:
            out.append((str(a), c))
    return out


def catalogo_multianio(anios, carpeta=None):
    """Une los catálogos de varios años. Para cada variable registra en qué AÑOS existe."""
    cats = load_catalogos(anios, carpeta)
    if not cats:
        return None
    años = [a for a, _ in cats]
    mods = {}
    for a, cat in cats:
        for m in cat['modulos']:
            cod = m['codigo']
            d = mods.setdefault(cod, {'codigo': cod, 'titulo': m['titulo'], 'unidad': m['unidad_analisis'],
                                      'llave': m['llave_identificacion'], 'archivo': m['archivo'], 'variables': {}})
            for vcode, sig in m['variables'].items():
                vv = d['variables'].setdefault(vcode.upper(), {'sig': sig, 'anios': set()})
                vv['anios'].add(a)
                if sig and not vv['sig']:
                    vv['sig'] = sig
    modulos = []
    for cod, d in mods.items():
        d['variables'] = {k: {'sig': v['sig'], 'anios': sorted(v['anios'])} for k, v in d['variables'].items()}
        modulos.append(d)
    return {'anios': años, 'modulos': modulos, 'n_archivos': len(modulos)}


def _compacto_multi(mcat, max_vars=8):
    años = set(mcat['anios'])
    out = []
    for m in mcat['modulos']:
        ejemplos, nuevas = [], []
        for code, info in m['variables'].items():
            if not info['sig']:
                continue
            if set(info['anios']) != años:
                nuevas.append('%s (solo %s)' % (code, ','.join(info['anios'])))
            elif len(ejemplos) < max_vars:
                ejemplos.append('%s=%s' % (code, info['sig'][:38]))
        out.append({'codigo': m['codigo'], 'titulo': m['titulo'], 'unidad': m['unidad'],
                    'llave': m['llave'], 'ejemplos_variables': ejemplos,
                    'variables_no_en_todos_los_anios': nuevas[:12]})
    return out


def sugerir_temas_multi(mcat, area=None, contexto=None, n=4):
    años = mcat['anios']
    foco = ("Área temática: '%s'." % area) if area else "Áreas económicas variadas."
    extra = ("\nContexto del usuario (tenlo MUY en cuenta): %s" % contexto) if contexto else ""
    prompt = (
        "PASO 5 (multi-año) — Propón %d temas de investigación económicos CAUSALES con la ENAHO. %s%s\n"
        "Años disponibles: %s.\n\n"
        "Catálogo (con disponibilidad de variables por año):\n%s\n\n"
        "REGLAS:\n"
        "- Plantea preguntas CAUSALES (efecto de X sobre Y), no solo descripciones.\n"
        "- Algunas variables NO existen en todos los años (campo 'variables_no_en_todos_los_anios'). "
        "Para cada tema, 'cobertura_anios' = los años que el tema realmente puede cubrir según las variables que usa; "
        "'motivo_cobertura' = por qué (ej. 'la variable X existe solo desde 2022, así que el tema cubre 2022–2023').\n"
        "- Solo combina módulos enlazables por sus llaves.\n"
        "- %s\n"
        "Devuelve JSON: [{\"tema\": str, \"pregunta_investigacion\": str, \"justificacion\": str, "
        "\"modulos\": [codigos], \"variables_clave\": [str], \"cobertura_anios\": [años], \"motivo_cobertura\": str, "
        "\"nivel_causal_esperado\": \"causal_fuerte|causal_debil|asociacion\", \"justificacion_causal\": str}]"
        % (n, foco, extra, ', '.join(años), json.dumps(_compacto_multi(mcat), ensure_ascii=False),
           _REGLA_PRIORIDAD_CAUSAL))
    temas = ask_json(prompt, model=MODELOS['sugerir_temas_multi'])
    return _ordenar_por_causalidad(temas)


# ---------- PASO CAUSAL: estrategia de identificación ----------
def diseno_causal(cat, tema, manifiesto, anios):
    det = _modulos_detalle(cat, tema.get('modulos', []))
    prompt = (
        "DISEÑO CAUSAL — Define la estrategia de identificación causal del tema con datos ENAHO "
        "(cortes transversales repetidos; años: %s).\n"
        "Tema: %s\nVariables disponibles:\n%s\n\n"
        "Define tratamiento, variable resultado, controles (de las variables del manifiesto) y la estrategia: "
        "OLS con controles (selección sobre observables), variables instrumentales, "
        "diferencias-en-diferencias (si hay variación temporal/de política entre años), o matching. "
        "Sé HONESTO: con cortes transversales la causalidad es limitada; si solo permite asociación condicional, dilo "
        "en 'nivel_causal'.\n"
        "Devuelve JSON: {\"pregunta_causal\": str, \"tratamiento\": str, \"resultado\": str, "
        "\"controles\": [str], \"estrategia_identificacion\": str, \"supuestos\": [str], \"amenazas\": [str], "
        "\"nivel_causal\": \"asociacion|causal_debil|causal_fuerte\"}"
        % (', '.join(map(str, anios)), tema.get('tema'), json.dumps(det, ensure_ascii=False)))
    return ask_json(prompt, model=MODELOS['diseno_causal'])


# ---------- prioridad causal: fuerte > débil > asociación ----------
_RANK_CAUSAL = {'causal_fuerte': 0, 'causal_debil': 1, 'asociacion': 2}


def _ordenar_por_causalidad(temas):
    """Orden DETERMINISTA (no confía en que la IA los devuelva ya ordenados):
    causal_fuerte primero, luego causal_debil, luego asociacion/desconocido al final.
    Estable: dentro del mismo nivel conserva el orden original."""
    return sorted(temas, key=lambda t: _RANK_CAUSAL.get(t.get('nivel_causal_esperado'), 3))


_REGLA_PRIORIDAD_CAUSAL = (
    "PRIORIDAD CAUSAL (crítico): para cada tema, evalúa ANTES de proponerlo si existe una "
    "estrategia de identificación PLAUSIBLE con las variables del catálogo: un instrumento válido "
    "(variable que afecte el tratamiento pero no el resultado por otra vía), una discontinuidad/corte "
    "claro (regla de elegibilidad por edad/ingreso/geografía), o una comparación de grupos con variación "
    "creíble. Clasifica cada tema en 'nivel_causal_esperado': "
    "'causal_fuerte' (instrumento/discontinuidad plausible y defendible), "
    "'causal_debil' (solo selección sobre observables, supuestos fuertes no verificables), o "
    "'asociacion' (no hay estrategia de identificación, solo correlación condicional). "
    "PRIORIZA proponer temas 'causal_fuerte' primero; si no encuentras ninguno plausible con estos "
    "datos, propón 'causal_debil' antes que 'asociacion'. Sé honesto: no inventes un instrumento que no "
    "se sostenga. Incluye 'justificacion_causal': por qué ese nivel (cuál es el instrumento/corte, o por "
    "qué no lo hay).\n")


# ---------- PASO 5A: el sistema propone ÁREAS temáticas al azar ----------
def sugerir_areas(cat, n=3):
    prompt = (
        "PASO 5 (opción B) — Propón %d ÁREAS temáticas económicas DISTINTAS y variadas (al azar, "
        "no solo las obvias) que los datos de la ENAHO %s permitan investigar.\n\n"
        "Catálogo de módulos disponibles (grounding):\n%s\n\n"
        "Devuelve JSON: [{\"area\": str, \"descripcion\": str, \"modulos_relevantes\": [codigos]}]"
        % (n, cat['anio'], json.dumps(_compacto(cat), ensure_ascii=False)))
    return ask_json(prompt, model=MODELOS['sugerir_areas'])


# ---------- PASO 5B: sugerencia de temas (dado un área + contexto opcional) ----------
def sugerir_temas(cat, area=None, contexto=None, n=4):
    foco = ("Enfócate en el área temática: '%s'." % area) if area else \
        "Propón temas de áreas económicas variadas (pobreza, empleo, ingresos, educación, salud, informalidad, género, etc.)."
    extra = ("\nRecomendaciones/contexto del usuario (tenlos MUY en cuenta): %s" % contexto) if contexto else ""
    prompt = (
        "PASO 5 — Sugerencia de temas de investigación económicos a partir de la ENAHO %s.\n%s%s\n\n"
        "Catálogo de módulos disponibles (grounding):\n%s\n\n"
        "Propón %d temas de investigación CONCRETOS y RESPONDIBLES con estos datos. "
        "IMPORTANTE: considera la unidad de análisis y la 'llave' de identificación de cada módulo; "
        "propón SOLO combinaciones de módulos ENLAZABLES entre sí por sus llaves comunes "
        "(a nivel hogar: CONGLOME+VIVIENDA+HOGAR; o persona: +CODPERSO). No combines módulos que no se puedan mergear.\n"
        "%s\n"
        "Para cada tema indica los módulos (códigos) y variables que lo sustentan.\n"
        "Devuelve JSON: [{\"tema\": str, \"pregunta_investigacion\": str, \"justificacion\": str, "
        "\"modulos\": [codigos], \"variables_clave\": [str], "
        "\"nivel_causal_esperado\": \"causal_fuerte|causal_debil|asociacion\", \"justificacion_causal\": str}]"
        % (cat['anio'], foco, extra, json.dumps(_compacto(cat), ensure_ascii=False), n, _REGLA_PRIORIDAD_CAUSAL))
    temas = ask_json(prompt, model=MODELOS['sugerir_temas'])
    return _ordenar_por_causalidad(temas)


# ---------- PASO 6: análisis de los módulos asociados al tema ----------
def analizar_tema(cat, tema):
    det = _modulos_detalle(cat, tema.get('modulos', []))
    prompt = (
        "PASO 6 — Análisis de los módulos asociados al tema.\n"
        "Tema: %s\nPregunta: %s\n\n"
        "Detalle real de los módulos (variables, cobertura, completitud):\n%s\n\n"
        "Analiza para este tema, SOLO con esta evidencia, en JSON:\n"
        "{\"que_variables_contiene\": str, \"cobertura_geografica_temporal\": str, "
        "\"poblacion_estudiada\": str, \"nivel_de_detalle\": str, "
        "\"calidad_y_completitud\": str, \"viable\": bool, \"observaciones\": str}"
        % (tema.get('tema'), tema.get('pregunta_investigacion'),
           json.dumps(det, ensure_ascii=False)))
    return ask_json(prompt, model=MODELOS['analizar_tema'])  # sonnet: análisis de evidencia (conservador)


# ---------- PASO 7: selección de variables ----------
def _restriccion_multianio(mcat, tema, cob):
    """Lista (determinista) de variables de los módulos del tema que NO existen en
    todos los años de cobertura, para que el paso 7 las evite."""
    if not (mcat and cob) or len(cob) < 2:
        return ''   # con un solo año, el catálogo del año ya limita las opciones
    cob = [str(a) for a in cob]
    mods = {str(m['codigo']).upper(): m for m in mcat['modulos']}
    parciales = []
    for c in {str(x).upper() for x in (tema.get('modulos') or [])}:
        m = mods.get(c)
        if not m:
            continue
        for var, info in m['variables'].items():
            dispo = sorted(set(info['anios']) & set(cob))
            if set(cob) - set(info['anios']):
                parciales.append('%s (solo %s)' % (var, ','.join(dispo) if dispo else 'otros años'))
    if not parciales:
        return ''
    return ("\nREGLA MULTI-AÑO (crítica): el tema cubre los años %s y las variables elegidas deben "
            "existir en TODOS esos años para que el análisis sea comparable. Estas variables NO "
            "cumplen — NO las selecciones salvo que sean imprescindibles (y si lo haces, adviértelo "
            "en 'por_que'): %s\n" % (', '.join(cob), '; '.join(sorted(parciales)[:60])))


def seleccionar_variables(cat, tema, mcat=None, cob=None, contexto=None):
    det = _modulos_detalle(cat, tema.get('modulos', []))
    extra = ("\nContexto/recomendaciones del usuario (tenlo MUY en cuenta, ej. si pide variables o "
            "controles específicos): %s" % contexto) if contexto else ""
    prompt = (
        "PASO 7 — Selección de variables para el tema.\n"
        "Tema: %s\nPregunta: %s\n%s%s\n"
        "Variables reales disponibles por módulo:\n%s\n\n"
        "Selecciona las variables necesarias. Usa SOLO nombres que existan arriba. "
        "Incluye SIEMPRE las variables de la llave de identificación (CONGLOME, VIVIENDA, HOGAR y CODPERSO "
        "si es a nivel persona) necesarias para el MERGE entre módulos, además del factor de expansión.\n"
        "NO te limites al mínimo indispensable (tratamiento + resultado + llaves): un dataset de "
        "investigación útil necesita CONTROLES para análisis de robustez y heterogeneidad. Si existen en "
        "los módulos ya elegidos y tienen sentido para el tema, incluí también: características "
        "geográficas (área urbana/rural, región/dominio), demográficas del hogar o de su jefe (sexo, edad, "
        "nivel educativo, tamaño del hogar), u otros controles estándar en la literatura del tema. "
        "Prioridad: tratamiento, resultado e identificación primero; después agregá controles "
        "razonables — no una lista exhaustiva de todo el módulo, pero tampoco solo 2 o 3 variables.\n"
        "Asigna un rol a cada una (dependiente / independiente / control / identificacion / ponderador).\n"
        "Devuelve JSON: [{\"archivo\": str, \"variable\": str, \"etiqueta\": str, \"rol\": str, \"por_que\": str}]"
        % (tema.get('tema'), tema.get('pregunta_investigacion'),
           _restriccion_multianio(mcat, tema, cob), extra,
           json.dumps(det, ensure_ascii=False)))
    return ask_json(prompt, model=MODELOS['seleccionar_variables'])


def disponibilidad_variables(mcat, cat, manifiesto, cob):
    """Verificación DETERMINISTA post-paso 7: ¿cada variable del manifiesto existe en
    TODOS los años de cobertura? Devuelve solo las que faltan en algún año."""
    cob = [str(a) for a in cob]
    cod_de = {m['archivo']: str(m['codigo']).upper() for m in cat['modulos']}
    mods = {str(m['codigo']).upper(): m for m in mcat['modulos']}
    out = []
    for v in manifiesto:
        if not isinstance(v, dict) or not v.get('variable'):
            continue
        var = v['variable'].upper()
        info = None
        m = mods.get(cod_de.get(v.get('archivo'), ''))
        if m:
            info = m['variables'].get(var)
        if info is None:                      # fallback: buscarla en cualquier módulo
            for mm in mods.values():
                if var in mm['variables']:
                    info = mm['variables'][var]
                    break
        anios = sorted(set(info['anios']) & set(cob)) if info else []
        faltan = [a for a in cob if a not in anios]
        if faltan:
            out.append({'variable': var, 'archivo': v.get('archivo'), 'rol': v.get('rol'),
                        'anios_disponibles': anios, 'faltan_en': faltan})
    return out


def validar_manifiesto(cat, manifiesto):
    """Verificación DETERMINISTA post-paso 7, MÁS BÁSICA que disponibilidad_variables:
    ¿cada entrada del manifiesto es un (archivo, variable) que REALMENTE existe en el
    catálogo del año representativo? A veces la IA devuelve una entrada que no es una
    variable real (ej. un aviso o limitación disfrazado de ítem del manifiesto, con un
    'archivo' inventado) — sin este filtro, esa entrada llega intacta a plan_de_datos/
    verificar_merge/materializar_dataset, que asumen que todo 'archivo' existe en disco,
    y truena con un FileNotFoundError en vez de un error claro. Devuelve
    (manifiesto_valido, descartados) — nunca falla en silencio: lo que se descarta queda
    listado con el motivo."""
    cols_de = {m['archivo']: {c.upper() for c in m['variables']} for m in cat['modulos']}
    validos, descartados = [], []
    for v in manifiesto:
        if not isinstance(v, dict) or not v.get('archivo') or not v.get('variable'):
            descartados.append({'item': v, 'motivo': 'entrada sin archivo/variable definidos'})
            continue
        arch, var = v['archivo'], v['variable'].upper()
        if arch not in cols_de:
            descartados.append({'item': v, 'motivo': 'el archivo "%s" no existe en el catálogo' % arch})
            continue
        if var not in cols_de[arch]:
            descartados.append({'item': v, 'motivo': 'la variable "%s" no existe en %s' % (var, arch)})
            continue
        validos.append(v)
    return validos, descartados


# ---------- PLAN DE DATOS: filtros (IA) + merge (determinista) ----------
def sugerir_filtros(cat, tema, manifiesto):
    det = _modulos_detalle(cat, tema.get('modulos', []))
    prompt = (
        "PLAN DE DATOS — Propón los FILTROS de población para responder el tema, usando SOLO "
        "variables que existan en los módulos.\nTema: %s\nVariables disponibles:\n%s\n\n"
        "Ej: ocupados, PEA, edad>=14, residentes habituales. Expresa cada filtro como condición sobre "
        "una variable concreta. Si no hace falta filtrar, devuelve lista vacía.\n"
        "REGLA ESTRICTA sobre 'condicion': cada módulo trae 'valores' {variable: {código: etiqueta}} SOLO "
        "para las variables categóricas que sí tienen su lista de códigos verificada en el diccionario "
        "oficial. Por eso:\n"
        "  - Si la condición es sobre una variable NUMÉRICA continua (edad, ingreso, etc.), usa un número "
        "real: \"condicion\": \">= 65\".\n"
        "  - Si la condición depende del CÓDIGO de una variable categórica, búscalo en 'valores' de ESE "
        "módulo y usa el código NUMÉRICO real (ej. si 'valores' dice {\"1\":\"Sí\"}, la condición es "
        "\"== 1\", NUNCA \"= 'Sí'\").\n"
        "  - Si la variable categórica NO aparece en 'valores' (no hay lista de códigos verificada), NO "
        "INVENTES el código: pon \"condicion\": null y explica en 'motivo' qué condición hace falta y que "
        "su código debe verificarse en el diccionario oficial antes de aplicarla.\n"
        "Devuelve JSON: [{\"archivo\": str, \"variable\": str, \"condicion\": str|null, \"motivo\": str}]"
        % (tema.get('tema'), json.dumps(det, ensure_ascii=False)))
    return ask_json(prompt, model=MODELOS['sugerir_filtros'])


def plan_de_datos(cat, tema, manifiesto, filtros):
    """Merge DETERMINISTA a partir de las llaves de identificación del catálogo."""
    llave_de = {m['archivo']: m['llave_identificacion'] for m in cat['modulos']}
    by_file = {}
    for v in manifiesto:
        if isinstance(v, dict) and v.get('archivo') and v.get('variable'):
            by_file.setdefault(v['archivo'], []).append(v['variable'])
    archivos = list(by_file)
    persona = any('CODPERSO' in (llave_de.get(a) or []) for a in archivos)
    llaves_merge = ['CONGLOME', 'VIVIENDA', 'HOGAR'] + (['CODPERSO'] if persona else [])
    # el base DEBE tener TODAS las llaves_merge (mismo nivel que el análisis, o más fino):
    # si el análisis es a nivel persona, un archivo de nivel hogar (sin CODPERSO) no puede
    # ser base, porque los demás archivos de persona no tendrían con qué unirse a él.
    candidatos = [a for a in archivos if set(llaves_merge) <= set(llave_de.get(a) or [])] or archivos
    base = max(candidatos, key=lambda a: len(by_file[a])) if candidatos else None
    nivel_analisis = 'persona' if persona else 'hogar'
    pasos, explicacion = [], []
    for a in sorted(archivos, key=lambda a: (a != base, a)):
        disp = llave_de.get(a) or llaves_merge
        k = [x for x in llaves_merge if x in disp] or ['CONGLOME', 'VIVIENDA', 'HOGAR']
        nivel_a = 'persona' if 'CODPERSO' in (llave_de.get(a) or []) else 'hogar'
        # broadcast: archivo de HOGAR unido a un análisis a nivel PERSONA -> se replica a cada individuo
        broadcast = (nivel_analisis == 'persona' and nivel_a == 'hogar')
        pasos.append({'archivo': a, 'llaves_join': k, 'tipo': 'base' if a == base else 'left',
                      'nivel': nivel_a, 'broadcast': broadcast, 'variables': by_file[a]})

    explicacion.append("El análisis se hace a nivel %s; las filas se identifican por %s." %
                       (nivel_analisis.upper(), '+'.join(llaves_merge)))
    explicacion.append("Se parte del archivo base '%s' y se le unen los demás (LEFT JOIN) por sus llaves comunes." % base)
    for p in pasos:
        if p['tipo'] == 'base':
            continue
        if p['broadcast']:
            explicacion.append(
                "'%s' está a nivel HOGAR: se une por %s y su valor se REPLICA a cada individuo del hogar "
                "(broadcast). Es válido solo si esas llaves son únicas en ese archivo (1 fila por hogar); "
                "el sistema lo verifica para no inflar filas." % (p['archivo'], '+'.join(p['llaves_join'])))
        else:
            explicacion.append("'%s' está a nivel %s: merge directo por %s (misma unidad, sin replicar)."
                               % (p['archivo'], p['nivel'], '+'.join(p['llaves_join'])))
    if filtros:
        aplicables = [f for f in filtros if f.get('condicion')]
        pendientes = [f for f in filtros if not f.get('condicion')]
        if aplicables:
            explicacion.append("Luego se filtra la población: %s." %
                               '; '.join('%s %s' % (f.get('variable'), f['condicion']) for f in aplicables))
        if pendientes:
            explicacion.append("Filtros PENDIENTES de verificar código (no se aplican solos): %s." %
                               '; '.join('%s (%s)' % (f.get('variable'), f.get('motivo', '')) for f in pendientes))
    return {'nivel_de_analisis': nivel_analisis,
            'llaves_merge': llaves_merge, 'archivo_base': base,
            'secuencia_merge': pasos, 'filtros': filtros, 'explicacion': explicacion}


# ---------- RESOLUCIÓN DE NIVELES: exportar el dataset final requiere que cada ----------
# archivo del merge tenga EXACTAMENTE 1 fila por llave; verificar_merge() detecta cuáles
# NO la tienen (broadcast con llave no única = archivo a nivel ítem/detalle). Para esos,
# decide cómo reducirlos: agregar (suma/promedio/...), restringir a 1 fila (ej. jefe de
# hogar), o excluir si ninguna opción es segura.
def plan_resolucion_niveles(cat, manifiesto, plan_datos, verificacion_merge):
    problematicos = {vm['archivo'] for vm in (verificacion_merge or [])
                     if vm.get('broadcast') and not vm.get('ok')}
    if not problematicos:
        return []
    by_file = {}
    for v in manifiesto:
        if isinstance(v, dict) and v.get('archivo') in problematicos and v.get('variable'):
            by_file.setdefault(v['archivo'], []).append(v)
    if not by_file:
        return []
    mods = {m['archivo']: m for m in cat['modulos']}
    detalle = []
    for arch, vars_ in by_file.items():
        m = mods.get(arch, {})
        detalle.append({'archivo': arch, 'titulo': m.get('titulo'), 'llave': m.get('llave_identificacion'),
                        'variables_a_resolver': [{'variable': v['variable'], 'rol': v.get('rol'),
                                                  'significado': (m.get('variables') or {}).get(v['variable'].upper()),
                                                  'valores_de_esta_variable': (m.get('valores') or {}).get(v['variable'].upper())}
                                                 for v in vars_],
                        'todas_las_variables_del_archivo': m.get('variables', {}),
                        'valores_conocidos': m.get('valores', {})})
    llaves_merge = plan_datos['llaves_merge']
    prompt = (
        "Estos archivos tienen MÁS DE UNA FILA por %s (son registros a nivel ítem/detalle — ej. uno por "
        "rubro de gasto o por evento — no 1 fila por llave), pero el plan de datos necesita usarlos a ese "
        "nivel para el dataset final. Para CADA variable en 'variables_a_resolver', decide EXACTAMENTE una "
        "estrategia:\n"
        "- \"agregar\": la variable es NUMÉRICA y tiene sentido sumarla/promediarla entre los ítems del "
        "mismo hogar/persona (ej. sumar montos de gasto por rubro → gasto total). Indica \"funcion\": "
        "\"suma\"|\"promedio\"|\"conteo\"|\"maximo\".\n"
        "- \"restringir\": aísla 1 fila por llave filtrando por un código conocido. Puede ser (a) la MISMA "
        "variable a resolver, si 'valores_de_esta_variable' identifica un código específico que responde al "
        "tema (ej. una variable de programa/categoría con código \"5\":\"Programa Pensión 65\" → "
        "restriccion={\"variable\": esa misma variable, \"condicion\": \"== 5\"}), o (b) OTRA variable REAL "
        "en 'valores_conocidos' de ese archivo que identifique un rol/registro único (ej. jefe de hogar). "
        "El código SIEMPRE debe salir de 'valores_de_esta_variable' o 'valores_conocidos' — si el código que "
        "necesitas no aparece ahí, NO LO INVENTES.\n"
        "- \"excluir\": ninguna de las dos es segura con los códigos disponibles; explica el motivo.\n\n"
        "Archivos y variables a resolver:\n%s\n\n"
        "Devuelve JSON: [{\"archivo\": str, \"variable\": str, \"estrategia\": \"agregar\"|\"restringir\"|\"excluir\", "
        "\"funcion\": str|null, \"restriccion\": {\"variable\": str, \"condicion\": str}|null, \"motivo\": str}]"
        % ('+'.join(llaves_merge), json.dumps(detalle, ensure_ascii=False)))
    return ask_json(prompt, model=MODELOS['plan_resolucion_niveles'])


# ---------- PASO 8a: PLAN de brechas (computable) ----------
def plan_brechas(cat, tema, manifiesto):
    det = _modulos_detalle(cat, tema.get('modulos', []))
    prompt = (
        "PASO 8 (planificación) — Diseña un PLAN COMPUTABLE de brechas para el tema.\n"
        "Tema: %s\n\nVariables seleccionadas (manifiesto):\n%s\n\n"
        "Detalle real de módulos (archivos, variables con etiqueta, llaves):\n%s\n\n"
        "Para cada brecha define EXACTAMENTE qué calcular, usando SOLO archivos y variables que existan arriba:\n"
        "- outcome: una variable NUMÉRICA (ingreso, gasto, horas, etc.) con su archivo.\n"
        "- grupo: una variable CATEGÓRICA de pocas categorías (sexo, área, dominio, etc.) con su archivo "
        "y un mapa 'etiquetas' {codigo: etiqueta} según el diccionario (ej. P207: {\"1\":\"Hombre\",\"2\":\"Mujer\"}).\n"
        "- ponderador: una variable de factor de expansión existente (ej. FACTOR07) con su archivo (o null).\n"
        "- estadistico: 'media' o 'mediana' (prefiere 'mediana' para ingresos/gastos: es robusta a valores extremos; "
        "el motor limpia centinelas de 5+ nueves, pero códigos de missing de 4 dígitos como 9999 NO se limpian).\n"
        "REGLA DE NIVELES (obligatoria): mira 'unidad' y 'llave' de cada módulo en el detalle. El archivo de "
        "'grupo' debe tener EXACTAMENTE 1 fila por llave del archivo de 'outcome' (mismo nivel de análisis). "
        "Si el archivo de 'grupo' es de nivel MÁS FINO que el de 'outcome' (ej. grupo a nivel persona — varias "
        "filas por hogar — y outcome a nivel hogar), la variable de grupo sola NO alcanza: agrega "
        "\"restriccion\": {\"variable\": str, \"condicion\": str} DENTRO de \"grupo\", con una variable REAL de "
        "ESE MISMO archivo (ej. relación de parentesco/rol dentro del hogar) y una condición numérica simple "
        "(ej. \"== 1\") que aísle UNA sola fila por llave del outcome (ej. el jefe/jefa de hogar). Usa solo "
        "variables que existan en el detalle de módulos; si ninguna permite esa reducción, NO propongas esa "
        "brecha. Si 'grupo' y 'outcome' ya están al mismo nivel, deja \"restriccion\": null.\n"
        "Cada brecha = UNA variable de grupo con sus categorías (el motor agrupa por ella). "
        "NO crees brechas 'filtradas' (ej. 'solo urbano'): usa la variable de área como grupo y obtendrás urbano y rural juntas. "
        "Cada brecha debe usar un grupo DISTINTO (sexo, área, dominio, nivel educativo, etc.).\n"
        "Devuelve JSON: [{\"brecha\": str, \"outcome\": {\"archivo\": str, \"variable\": str}, "
        "\"grupo\": {\"archivo\": str, \"variable\": str, \"etiquetas\": {codigo: etiqueta}, "
        "\"restriccion\": {\"variable\": str, \"condicion\": str} | null}, "
        "\"ponderador\": {\"archivo\": str, \"variable\": str}, \"estadistico\": \"media|mediana\", "
        "\"hipotesis\": str}]"
        % (tema.get('tema'), json.dumps(manifiesto, ensure_ascii=False),
           json.dumps(det, ensure_ascii=False)))
    return ask_json(prompt, model=MODELOS['plan_brechas'])


# ---------- PASO 8b: interpretación de los números REALES ----------
def interpretar_brechas(tema, resultados):
    prompt = (
        "PASO 8 (interpretación) — Estos son RESULTADOS REALES calculados sobre los microdatos "
        "(medias/medianas ponderadas por grupo y brechas). Si vienen desglosados POR AÑO, analiza "
        "también la EVOLUCIÓN temporal de cada brecha (¿crece, cae, estable?). Interprétalos con "
        "rigor; NO inventes cifras nuevas, usa solo estas.\n"
        "Tema: %s\nResultados:\n%s\n\n"
        "Devuelve JSON: {\"hallazgos\": [str], \"brechas_relevantes\": [str], "
        "\"anomalias\": [str], \"limitaciones\": [str]}"
        % (tema.get('tema'), json.dumps(resultados, ensure_ascii=False)))
    return ask_json(prompt, model=MODELOS['interpretar_brechas'])


# ---------- PASO 9: contraste con literatura y antecedentes (con WEB) ----------
def contraste_literatura(tema, brechas):
    prompt = (
        "PASO 9 — Contraste con literatura y antecedentes. USA BÚSQUEDA WEB (WebSearch) para "
        "encontrar evidencia REAL y reciente (INEI, BCRP, MEF, CEPAL, papers académicos) sobre el "
        "tema y sus brechas/hallazgos.\n"
        "Tema: %s\nHallazgos sobre los datos:\n%s\n\n"
        "Resume qué se sabe, qué VACÍOS quedan (la oportunidad de investigación) y lista referencias "
        "REALES encontradas en la búsqueda, cada una con su URL. "
        "REGLA ESTRICTA: no inventes URLs ni citas; incluye SOLO lo que la búsqueda web devolvió. "
        "Si una afirmación no tiene respaldo encontrado, márcala como no verificada.\n"
        "Devuelve JSON: {\"que_se_sabe\": [str], \"vacios_oportunidad\": [str], "
        "\"referencias\": [{\"titulo\": str, \"url\": str, \"aporte\": str}], \"nivel_certeza\": str}"
        % (tema.get('tema'), json.dumps(brechas, ensure_ascii=False)))
    return ask_json(prompt, timeout=500, web=True, model=MODELOS['contraste_literatura'])


# ---------- PASO 10: puntuación ----------
def puntuar(tema, brechas, literatura, factibilidad):
    prompt = (
        "PASO 10 — Puntuación del tema de investigación (0–10 cada criterio).\n"
        "Tema: %s\nBrechas:\n%s\nLiteratura:\n%s\nFactibilidad de datos (de los pasos previos): %s\n\n"
        "Puntúa con criterios EXPLÍCITOS: impacto_social, relevancia_actual, factibilidad_datos, "
        "originalidad. Justifica cada puntaje con la evidencia anterior, sin inventar.\n"
        "Devuelve JSON: {\"impacto_social\": {\"puntaje\": num, \"justificacion\": str}, "
        "\"relevancia_actual\": {\"puntaje\": num, \"justificacion\": str}, "
        "\"factibilidad_datos\": {\"puntaje\": num, \"justificacion\": str}, "
        "\"originalidad\": {\"puntaje\": num, \"justificacion\": str}, "
        "\"puntaje_total\": num, \"veredicto\": str}"
        % (tema.get('tema'), json.dumps(brechas, ensure_ascii=False),
           json.dumps(literatura, ensure_ascii=False), json.dumps(factibilidad, ensure_ascii=False)))
    return ask_json(prompt, model=MODELOS['puntuar'])


if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == 'test':
        print(ask('Responde SOLO con este JSON exacto: {"ok": true}'))
