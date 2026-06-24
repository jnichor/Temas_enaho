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


# ---------- invocación de Claude (suscripción, headless) ----------
def ask(prompt, timeout=400, web=False):
    full = REGLA + "\n\n" + prompt
    cmd = 'claude -p --allowedTools "WebSearch"' if web else 'claude -p'
    r = subprocess.run(cmd, input=full, shell=True, cwd=ROOT, env=ENV,
                       capture_output=True, text=True, encoding='utf-8',
                       errors='replace', timeout=timeout)
    return (r.stdout or '').strip()


def ask_json(prompt, timeout=400, web=False):
    raw = ask(prompt, timeout, web=web)
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
def load_catalogo(year):
    for p in glob.glob(os.path.join(ROOT, 'enaho_*', 'microodatos_inei', 'enaho',
                                    '2_organized', 'by_year', str(year), 'catalogo_%s.json' % year)):
        with open(p, encoding='utf-8') as fh:
            return json.load(fh)
    return None


def años_disponibles():
    años = []
    for p in glob.glob(os.path.join(ROOT, 'enaho_*', 'microodatos_inei', 'enaho',
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
                        'variables': {k: v for k, v in m['variables'].items()}})
    return sel


# ---------- PASO 5A: el sistema propone ÁREAS temáticas al azar ----------
def sugerir_areas(cat, n=3):
    prompt = (
        "PASO 5 (opción B) — Propón %d ÁREAS temáticas económicas DISTINTAS y variadas (al azar, "
        "no solo las obvias) que los datos de la ENAHO %s permitan investigar.\n\n"
        "Catálogo de módulos disponibles (grounding):\n%s\n\n"
        "Devuelve JSON: [{\"area\": str, \"descripcion\": str, \"modulos_relevantes\": [codigos]}]"
        % (n, cat['anio'], json.dumps(_compacto(cat), ensure_ascii=False)))
    return ask_json(prompt)


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
        "Para cada tema indica los módulos (códigos) y variables que lo sustentan.\n"
        "Devuelve JSON: [{\"tema\": str, \"pregunta_investigacion\": str, \"justificacion\": str, "
        "\"modulos\": [codigos], \"variables_clave\": [str]}]"
        % (cat['anio'], foco, extra, json.dumps(_compacto(cat), ensure_ascii=False), n))
    return ask_json(prompt)


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
    return ask_json(prompt)


# ---------- PASO 7: selección de variables ----------
def seleccionar_variables(cat, tema):
    det = _modulos_detalle(cat, tema.get('modulos', []))
    prompt = (
        "PASO 7 — Selección de variables para el tema.\n"
        "Tema: %s\nPregunta: %s\n\n"
        "Variables reales disponibles por módulo:\n%s\n\n"
        "Selecciona las variables necesarias. Usa SOLO nombres que existan arriba. "
        "Incluye SIEMPRE las variables de la llave de identificación (CONGLOME, VIVIENDA, HOGAR y CODPERSO "
        "si es a nivel persona) necesarias para el MERGE entre módulos, además del factor de expansión. "
        "Asigna un rol a cada una (dependiente / independiente / control / identificacion / ponderador).\n"
        "Devuelve JSON: [{\"archivo\": str, \"variable\": str, \"etiqueta\": str, \"rol\": str, \"por_que\": str}]"
        % (tema.get('tema'), tema.get('pregunta_investigacion'),
           json.dumps(det, ensure_ascii=False)))
    return ask_json(prompt)


# ---------- PLAN DE DATOS: filtros (IA) + merge (determinista) ----------
def sugerir_filtros(cat, tema, manifiesto):
    det = _modulos_detalle(cat, tema.get('modulos', []))
    prompt = (
        "PLAN DE DATOS — Propón los FILTROS de población para responder el tema, usando SOLO "
        "variables que existan en los módulos.\nTema: %s\nVariables disponibles:\n%s\n\n"
        "Ej: ocupados, PEA, edad>=14, residentes habituales. Expresa cada filtro como condición sobre "
        "una variable concreta. Si no hace falta filtrar, devuelve lista vacía.\n"
        "Devuelve JSON: [{\"archivo\": str, \"variable\": str, \"condicion\": str, \"motivo\": str}]"
        % (tema.get('tema'), json.dumps(det, ensure_ascii=False)))
    return ask_json(prompt)


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
    base = max(archivos, key=lambda a: len(by_file[a])) if archivos else None
    pasos = []
    for a in sorted(archivos, key=lambda a: (a != base, a)):
        disp = llave_de.get(a) or llaves_merge
        k = [x for x in llaves_merge if x in disp] or ['CONGLOME', 'VIVIENDA', 'HOGAR']
        pasos.append({'archivo': a, 'llaves_join': k, 'tipo': 'base' if a == base else 'left',
                      'variables': by_file[a]})
    return {'nivel_de_analisis': 'persona' if persona else 'hogar',
            'llaves_merge': llaves_merge, 'archivo_base': base,
            'secuencia_merge': pasos, 'filtros': filtros}


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
        "- estadistico: 'media' o 'mediana' (prefiere 'mediana' para ingresos/gastos: es robusta a valores extremos).\n"
        "Cada brecha = UNA variable de grupo con sus categorías (el motor agrupa por ella). "
        "NO crees brechas 'filtradas' (ej. 'solo urbano'): usa la variable de área como grupo y obtendrás urbano y rural juntas. "
        "Cada brecha debe usar un grupo DISTINTO (sexo, área, dominio, nivel educativo, etc.).\n"
        "Devuelve JSON: [{\"brecha\": str, \"outcome\": {\"archivo\": str, \"variable\": str}, "
        "\"grupo\": {\"archivo\": str, \"variable\": str, \"etiquetas\": {codigo: etiqueta}}, "
        "\"ponderador\": {\"archivo\": str, \"variable\": str}, \"estadistico\": \"media|mediana\", "
        "\"hipotesis\": str}]"
        % (tema.get('tema'), json.dumps(manifiesto, ensure_ascii=False),
           json.dumps(det, ensure_ascii=False)))
    return ask_json(prompt)


# ---------- PASO 8b: interpretación de los números REALES ----------
def interpretar_brechas(tema, resultados):
    prompt = (
        "PASO 8 (interpretación) — Estos son RESULTADOS REALES calculados sobre los microdatos "
        "(medias/medianas ponderadas por grupo y brechas). Interprétalos con rigor; NO inventes "
        "cifras nuevas, usa solo estas.\n"
        "Tema: %s\nResultados:\n%s\n\n"
        "Devuelve JSON: {\"hallazgos\": [str], \"brechas_relevantes\": [str], "
        "\"anomalias\": [str], \"limitaciones\": [str]}"
        % (tema.get('tema'), json.dumps(resultados, ensure_ascii=False)))
    return ask_json(prompt)


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
    return ask_json(prompt, timeout=500, web=True)


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
    return ask_json(prompt)


if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == 'test':
        print(ask('Responde SOLO con este JSON exacto: {"ok": true}'))
