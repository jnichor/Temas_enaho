# -*- coding: utf-8 -*-
"""Paso 8 (motor de cálculo): ejecuta el PLAN de brechas sobre los datos REALES.

El plan lo produce el razonador (IA) anclado al catálogo; aquí solo se COMPUTA.
Determinista. Implementado sobre polars en modo STREAMING: nunca materializa un
archivo entero en RAM (módulos como el 601 tienen ~9M filas / 1.3 GB); solo se
colecta el frame final de 3 columnas [grupo, outcome, peso].

Garantías de correctitud:
- Valida NIVELES antes del merge (m:1): si el archivo de grupo tiene varias
  filas por llave, el join multiplicaría filas e inflaría la estadística; en ese
  caso se reporta un error claro en vez de calcular mal.
- Neutraliza centinelas de no-respuesta del INEI (99999, 999999.9, ...).
- Pondera con el factor de expansión (con fallback a cualquier FAC* del archivo).
- `calcular_multi` ejecuta el mismo plan en varios años (traduce el año en los
  nombres de archivo) para ver la evolución de las brechas.

Un ítem del plan:
{
  "brecha": "Brecha de ingreso laboral por sexo",
  "outcome": {"archivo": "0005_enaho01a-2023-500.csv", "variable": "P524A1"},
  "grupo":   {"archivo": "0002_enaho01-2023-200.csv", "variable": "P207",
              "etiquetas": {"1": "Hombre", "2": "Mujer"},
              "restriccion": {"variable": "P203", "condicion": "== 1"}},  # opcional
  "ponderador": {"archivo": "0005_enaho01a-2023-500.csv", "variable": "FAC500A"},
  "estadistico": "media"   # media | mediana
}

Si 'grupo' viene de un archivo de nivel MÁS FINO que 'outcome' (ej. grupo a nivel
persona, outcome a nivel hogar), la variable de grupo sola tiene varias filas por
hogar. 'restriccion' (opcional, propuesta por el razonador) aísla UNA fila por
llave de outcome (ej. el jefe/jefa de hogar) ANTES del chequeo de niveles.
"""
import os, re, glob, copy
import numpy as np
import polars as pl

KEYS4 = ["CONGLOME", "VIVIENDA", "HOGAR", "CODPERSO"]
# no-respuesta INEI: parte entera de 5+ nueves (99999, 999999.9, ...).
# Tradeoff deliberado: '9999' (4 dígitos) NO se limpia porque puede ser un valor
# legítimo (ej. un monto de 9999 soles); si abunda, se emite una NOTA en el
# resultado para que el usuario lo verifique contra el diccionario.
SENTINELA = r'^\s*-?9{5,}(\.\d*)?\s*$'


# ----------------------------- acceso a archivos -----------------------------
def _path(archivo, year, carpeta=None):
    # sorted(): resolución DETERMINISTA cuando el mismo año existe en varias
    # carpetas enaho_* (misma regla que razonador.load_catalogo). `carpeta` acota
    # la búsqueda a la carpeta activa elegida en el TUI, para no leer datos de una
    # carpeta distinta a la del catálogo que originó el plan.
    base = carpeta if carpeta else 'enaho_*'
    hits = sorted(glob.glob(os.path.join(base, 'microodatos_inei', 'enaho', '2_organized',
                                         'by_year', str(year), 'modulos', archivo)))
    return hits[0] if hits else None


def _sniff(path):
    with open(path, encoding='latin-1') as fh:
        l = fh.readline()
    return ';' if l.count(';') > l.count(',') else ','


def _scan(archivo, year, carpeta=None):
    """LazyFrame en streaming con columnas normalizadas a MAYÚSCULAS. No lee datos aún."""
    path = _path(archivo, year, carpeta)
    if not path:
        raise FileNotFoundError(archivo)
    lf = pl.scan_csv(path, separator=_sniff(path), infer_schema_length=0,
                     encoding='utf8-lossy', truncate_ragged_lines=True)
    names = lf.collect_schema().names()
    return lf.rename({o: o.strip().upper() for o in names})


def _cols(lf):
    return lf.collect_schema().names()


def _dup_en_llaves(lf, keys):
    """True si hay más de una fila por combinación de llaves (agregado en streaming)."""
    d = (lf.select(keys).group_by(keys).len()
           .filter(pl.col('len') > 1).limit(1).collect(engine='streaming'))
    return d.height > 0


def _cond_mask(col, condicion):
    """Convierte una condición numérica simple ('== 1', '!= 1', '>= 65', ...) en una
    máscara polars. Sin eval(): solo reconoce el patrón operador+número; si la condición
    no matchea ese patrón devuelve None (el llamador decide qué hacer). Limpia coma
    decimal ANTES de castear (igual que _limpia_numerica): sin esto, una columna cruda
    como "45,0" castea a null y el filtro descarta la fila entera en silencio."""
    m = re.match(r'^\s*(==|!=|>=|<=|>|<|=)?\s*(-?\d+(?:[.,]\d+)?)\s*$', condicion or '')
    if not m:
        return None
    op, val = m.group(1) or '==', float(m.group(2).replace(',', '.'))
    c = col.str.replace(',', '.', literal=True).cast(pl.Float64, strict=False)
    return {'==': c == val, '=': c == val, '!=': c != val,
            '>=': c >= val, '<=': c <= val, '>': c > val, '<': c < val}[op]


def _weighted_median(x, w):
    o = np.argsort(x)
    x, w = np.asarray(x)[o], np.asarray(w)[o]
    cw = np.cumsum(w)
    if cw[-1] <= 0:
        return float(np.median(x))
    return float(x[np.searchsorted(cw, 0.5 * cw[-1])])


# ----------------------------- una brecha -----------------------------
def _una_brecha(item, year, carpeta=None):
    ov = item['outcome']['variable'].upper()
    gv = item['grupo']['variable'].upper()
    et = {str(k): v for k, v in (item['grupo'].get('etiquetas') or {}).items()}
    estad = (item.get('estadistico') or 'media').lower()
    arch_o = item['outcome']['archivo']
    arch_g = item['grupo']['archivo']

    lo = _scan(arch_o, year, carpeta)
    co = _cols(lo)
    if ov not in co:
        raise ValueError("outcome %s no existe en %s" % (ov, arch_o))
    keys_o = [k for k in KEYS4 if k in co]

    # --- ponderador: resolver archivo y nombre (fallback a FAC*, determinista) ---
    p = item.get('ponderador') or {}
    warch = p.get('archivo') or arch_o
    wv = (p.get('variable') or '').upper() or None
    w_cols = co if warch == arch_o else _cols(_scan(warch, year, carpeta))
    notas_iniciales = []
    if wv and wv in w_cols:
        wname = wv
    else:
        candidatos = sorted(c for c in w_cols if c.startswith('FAC'))  # orden alfabético = determinista
        wname = candidatos[0] if candidatos else None
        if len(candidatos) > 1:
            notas_iniciales.append(
                'había %d factores de expansión candidatos en %s (%s); se usó %s por defecto '
                '(orden alfabético) — verifica que sea el correcto para tu análisis'
                % (len(candidatos), warch, ', '.join(candidatos), wname))
    nota_pond = ' | '.join(notas_iniciales) if notas_iniciales else None

    # --- outcome (+grupo y/o peso si viven en el mismo archivo) ---
    sel = list(dict.fromkeys(
        keys_o + [ov]
        + ([gv] if arch_g == arch_o else [])
        + ([wname] if (wname and warch == arch_o) else [])))
    faltan = [c for c in sel if c not in co]
    if faltan:
        raise ValueError("variables %s no existen en %s" % (faltan, arch_o))
    lf = lo.select(sel)

    # --- grupo desde OTRO archivo: validar NIVELES (m:1) antes de unir ---
    nota_restr = None
    if arch_g != arch_o:
        lg = _scan(arch_g, year, carpeta)
        cg = _cols(lg)
        if gv not in cg:
            raise ValueError("variable de grupo %s no existe en %s" % (gv, arch_g))
        keys = [k for k in KEYS4 if k in co and k in cg]
        if not keys:
            raise ValueError("sin llaves comunes para merge")
        # restricción propuesta por el razonador (ej. "jefe de hogar"): reduce el archivo de
        # grupo a 1 fila por llave ANTES del chequeo m:1, cuando grupo es de nivel más fino que outcome.
        restr = item['grupo'].get('restriccion') or {}
        rvar = (restr.get('variable') or '').upper() or None
        if rvar and rvar in cg and restr.get('condicion'):
            mask = _cond_mask(pl.col(rvar), restr['condicion'])
            if mask is not None:
                lg = lg.filter(mask)
            else:
                nota_restr = ('la restricción de grupo "%s %s" no se pudo interpretar; se ignoró'
                              % (rvar, restr['condicion']))
        elif rvar:
            nota_restr = 'la restricción de grupo "%s" no existe en %s; se ignoró' % (rvar, arch_g)
        lg = lg.select(keys + [gv]).unique()
        if _dup_en_llaves(lg, keys):
            raise ValueError(
                ("niveles incompatibles: '%s' tiene varias filas por %s; unirlo "
                 "multiplicaría filas e inflaría la estadística. Usa una variable de "
                 "grupo del mismo archivo del outcome o de un módulo con 1 fila por esa llave."
                 % (arch_g, '+'.join(keys)))
                + ((' (%s; tampoco alcanzó para reducirlo a 1 fila por llave)' % nota_restr) if nota_restr else ''))
        lf = lf.join(lg, on=keys, how='inner')

    # --- peso desde OTRO archivo ---
    if wname and warch != arch_o:
        lw = _scan(warch, year, carpeta)
        cw_ = _cols(lw)
        wk = [k for k in KEYS4 if k in _cols(lf) and k in cw_]
        if wk:
            lw = lw.select(wk + [wname]).unique()
            if _dup_en_llaves(lw, wk):
                nota_pond = 'ponderador omitido: %s tiene varias filas por %s' % (warch, '+'.join(wk))
                wname = None
            else:
                lf = lf.join(lw, on=wk, how='left')
        else:
            wname = None

    # --- limpieza + colecta SOLO de [grupo, outcome, peso] (streaming) ---
    # normaliza coma decimal -> punto ANTES de castear: algunos años/archivos de la
    # ENAHO usan ';' como separador de columnas Y ',' como separador decimal
    # (ej. 609-2025: "1203,07678222656"); sin esto, cast(Float64) los vuelve NULL
    # en silencio y toda la brecha sale vacía sin ningún error visible.
    lf = lf.with_columns(pl.col(ov).str.replace(',', '.', literal=True).alias(ov))
    lf = lf.with_columns(
        pl.when(pl.col(ov).str.contains(SENTINELA)).then(pl.lit(None)).otherwise(pl.col(ov)).alias(ov))
    lf = lf.with_columns(pl.col(ov).cast(pl.Float64, strict=False).alias('_y'))
    if wname:
        lf = lf.with_columns(pl.col(wname).str.replace(',', '.', literal=True)
                             .cast(pl.Float64, strict=False).fill_null(0.0).alias('_w'))
    else:
        lf = lf.with_columns(pl.lit(1.0).alias('_w'))
    lf = (lf.drop_nulls(['_y'])
            .drop_nulls([gv])
            .filter(pl.col(gv).str.strip_chars() != ''))
    df = lf.select([gv, '_y', '_w']).collect(engine='streaming')

    pre_filtro = []   # grupos ANTES del corte n>=30, para poder diagnosticar sin adivinar
    for name, sub in df.group_by(gv):
        g = name[0] if isinstance(name, tuple) else name
        x, w = sub['_y'].to_numpy(), sub['_w'].to_numpy()
        if estad == 'mediana':
            val = _weighted_median(x, w)
        else:
            val = float(np.average(x, weights=w)) if w.sum() > 0 else float(np.mean(x))
        pre_filtro.append({'grupo': str(g), 'etiqueta': et.get(str(g), str(g)),
                           'valor': round(val, 2), 'n': int(sub.height)})
    grupos = [gp for gp in pre_filtro if gp['n'] >= 30]   # ignora celdas con muy pocos casos
    grupos.sort(key=lambda d: d['valor'])
    out = {'brecha': item.get('brecha'), 'outcome': ov, 'grupo': gv,
           'estadistico': estad, 'ponderador': wname or 'sin ponderar',
           'anio': str(year), 'n_total': int(df.height), 'grupos': grupos}
    notas = [n for n in (nota_pond, nota_restr) if n]
    n9999 = int((df['_y'] == 9999.0).sum())     # posible código de missing de 4 dígitos
    if n9999 >= 5:
        notas.append('%d valores exactamente 9999 en %s: podría ser código de no respuesta '
                     'de 4 dígitos (verificar en el diccionario); se MANTUVIERON en el cálculo — '
                     'la mediana es robusta a esto, la media no' % (n9999, ov))
    vals = [gp['valor'] for gp in grupos]
    if len(vals) >= 2 and min(vals) != 0:
        out['brecha_absoluta'] = round(max(vals) - min(vals), 2)
        out['brecha_relativa_pct'] = round(100 * (max(vals) - min(vals)) / abs(min(vals)), 1)
    else:
        # diagnóstico honesto: por qué no se pudo calcular la brecha, sin adivinar
        descartados = [gp for gp in pre_filtro if gp['n'] < 30]
        if not pre_filtro:
            notas.append('sin grupos: el merge outcome↔grupo no produjo ninguna fila '
                         '(revisar si %s y %s comparten población real en %s)' % (ov, gv, year))
        elif len(pre_filtro) < 2:
            notas.append('solo 1 categoría de %s presente en los datos (%s); no hay con qué comparar'
                         % (gv, pre_filtro[0]['grupo']))
        elif descartados:
            notas.append('%d de %d categorías de %s tienen menos de 30 casos y se excluyeron '
                         '(tamaños: %s); quedaron insuficientes para la brecha'
                         % (len(descartados), len(pre_filtro), gv,
                            ', '.join('%s=%d' % (g['grupo'], g['n']) for g in pre_filtro)))
        elif len(vals) >= 2 and min(vals) == 0:
            notas.append('el grupo de menor valor dio exactamente 0; la brecha relativa (%) '
                         'no es calculable con un valor base de 0')
    if notas:
        out['nota'] = ' | '.join(notas)
    return out


def calcular(plan, year, carpeta=None):
    res = []
    for item in plan:
        try:
            res.append(_una_brecha(item, year, carpeta))
        except Exception as e:
            res.append({'brecha': item.get('brecha'), 'anio': str(year), 'error': str(e)})
    return res


# ----------------------------- multi-año -----------------------------
def _plan_para_anio(plan, rep, year):
    """Traduce los nombres de archivo del plan (construidos con el año `rep`) a otro año."""
    if str(rep) == str(year):
        return plan
    p2 = copy.deepcopy(plan)
    for item in p2:
        for k in ('outcome', 'grupo', 'ponderador'):
            d = item.get(k)
            if isinstance(d, dict) and d.get('archivo'):
                d['archivo'] = d['archivo'].replace(str(rep), str(year))
    return p2


def calcular_multi(plan, anios, rep, carpeta=None):
    """Ejecuta el MISMO plan de brechas en cada año de cobertura (evolución temporal).
    Los años sin archivo/variable quedan como error explícito, no rompen el resto."""
    return {str(y): calcular(_plan_para_anio(plan, rep, y), y, carpeta) for y in anios}


# ----------------------------- verificaciones -----------------------------
def _nfilas(arch, year, carpeta=None):
    return int(_scan(arch, year, carpeta).select(pl.len()).collect(engine='streaming').item())


def _overlap_match(arch_a, arch_b, var, year, carpeta=None):
    """% de coincidencia de 'var' entre dos módulos en su población común (streaming)."""
    la, lb = _scan(arch_a, year, carpeta), _scan(arch_b, year, carpeta)
    ca, cb = _cols(la), _cols(lb)
    if var not in ca or var not in cb:
        return None, 0
    keys = [k for k in KEYS4 if k in ca and k in cb]
    if not keys:
        return None, 0
    j = (la.select(keys + [var]).rename({var: '_A'})
           .join(lb.select(keys + [var]).rename({var: '_B'}), on=keys, how='inner'))
    r = j.select(((pl.col('_A') == pl.col('_B')).cast(pl.Float64).mean() * 100).alias('pct'),
                 pl.len().alias('n')).collect(engine='streaming')
    n = int(r['n'][0])
    if n == 0 or r['pct'][0] is None:
        return None, 0
    return float(r['pct'][0]), n


def revisar_consolidacion(cat, manifiesto, year, carpeta=None):
    """Fuente canónica por defecto + aviso de consolidación VERIFICADA.
    Para cada módulo secundario del merge, revisa si sus variables seleccionadas
    también están en el módulo base y si son idénticas en el overlap. Marca:
    - merge evitable (todas sus vars son redundantes idénticas),
    - variables que DIFIEREN (ahí importa la fuente canónica: no consolidar)."""
    cols_de = {m['archivo']: {c.upper() for c in m['variables']} for m in cat['modulos']}
    by_file = {}
    for v in manifiesto:
        if isinstance(v, dict) and v.get('archivo') and v.get('variable'):
            by_file.setdefault(v['archivo'], []).append(v['variable'].upper())
    archivos = list(by_file)
    if not archivos:
        return {}
    base = max(archivos, key=lambda a: len(by_file[a]))
    cob = {a: _nfilas(a, year, carpeta) for a in archivos}
    rep = {'base': base, 'coberturas': cob, 'modulos': [], 'consolidables': []}
    for a in archivos:
        if a == base:
            continue
        red, dif, prop = [], [], []
        for var in by_file[a]:
            if var in {'CONGLOME', 'VIVIENDA', 'HOGAR', 'CODPERSO'}:
                continue
            if var in cols_de.get(base, set()):
                pct, n = _overlap_match(a, base, var, year, carpeta)
                if pct is None:
                    prop.append(var)
                elif pct >= 99.5:
                    red.append({'var': var, 'match_pct': round(pct, 1)})
                else:
                    dif.append({'var': var, 'match_pct': round(pct, 1)})
            else:
                prop.append(var)
        consolidable = (not prop and not dif)   # todo lo que aporta ya está idéntico en el base
        nota = ''
        if consolidable and cob[base] < cob[a]:
            nota = ('consolidar restringe la muestra a la población del módulo base (%d) '
                    'vs %d en este módulo; OK solo si tu población objetivo es la del base '
                    '(tus filtros lo confirman).' % (cob[base], cob[a]))
        rep['modulos'].append({'modulo': a, 'redundantes_identicas': red, 'difieren': dif,
                               'unicas_de_este_modulo': prop, 'consolidable': consolidable,
                               'nota_cobertura': nota})
        if consolidable:
            rep['consolidables'].append(a)
    return rep


def verificar_merge(plan, year, carpeta=None):
    """Verifica que cada paso de merge sea válido: si es broadcast hogar→persona,
    la llave de hogar debe ser ÚNICA en ese archivo (1 fila por hogar) para no inflar filas."""
    HH = ['CONGLOME', 'VIVIENDA', 'HOGAR']
    rep = []
    for p in plan.get('secuencia_merge', []):
        if p.get('tipo') == 'base':
            continue
        if not p.get('broadcast'):
            rep.append({'archivo': p['archivo'], 'broadcast': False, 'ok': True,
                        'nota': 'merge directo (misma unidad de análisis), sin replicación'})
            continue
        try:
            lf = _scan(p['archivo'], year, carpeta)
            hh = [k for k in HH if k in _cols(lf)]
            r = lf.select(pl.len().alias('n'),
                          pl.struct(hh).n_unique().alias('u')).collect(engine='streaming')
            n, u = int(r['n'][0]), int(r['u'][0])
            ok = (u == n and n > 0)
            rep.append({'archivo': p['archivo'], 'broadcast': True, 'ok': ok,
                        'filas': n, 'hogares': u,
                        'nota': ('llave de hogar ÚNICA → broadcast válido: se asigna 1 valor del hogar a '
                                 'cada individuo sin duplicar filas'
                                 if ok else
                                 'ADVERTENCIA: la llave de hogar NO es única (%s filas, %s hogares) → el '
                                 'broadcast inflaría filas; primero hay que agregar a nivel hogar' % (n, u))})
        except Exception as e:
            rep.append({'archivo': p['archivo'], 'broadcast': True, 'ok': False,
                        'nota': 'no verificable: %s' % e})
    return rep


def verificar_filtros(filtros, year, carpeta=None):
    """Verifica, ARCHIVO por archivo, que los filtros con condición numérica no se
    contradigan entre sí. El caso típico en la ENAHO: dos preguntas son mutuamente
    excluyentes por el patrón de SALTO del cuestionario (una solo se pregunta si la
    otra no aplica, ej. P204 y P206) — sugerir_filtros() no conoce ese patrón de
    salto, solo el significado y los códigos de cada variable por separado. Firma de
    esta contradicción: dos filtros por sí solos SÍ tienen datos, pero JUNTOS dan
    0 filas — eso no es un resultado real de la población, es una combinación
    imposible de responder.

    Revisa PARES, no el combinado de TODOS los filtros de un archivo: si hubiera un
    tercer filtro sano (ej. sexo) en el mismo archivo, combinarlo con el AND completo
    también daría 0 (por la contradicción de los otros dos) y lo señalaría como
    parte del problema sin tener nada que ver — el filtro sano quedaría descartado
    sin motivo."""
    por_archivo = {}
    for f in (filtros or []):
        var = (f.get('variable') or '').upper()
        cond = f.get('condicion')
        arch = f.get('archivo')
        if arch and var and cond:
            por_archivo.setdefault(arch, []).append((var, cond))
    rep = []
    for arch, pares in por_archivo.items():
        if len(pares) < 2:
            continue
        try:
            lf = _scan(arch, year, carpeta)
            cols = _cols(lf)
            info = {}
            for var, cond in pares:
                if var not in cols or var in info:
                    continue
                m = _cond_mask(pl.col(var), cond)
                if m is None:
                    continue
                n = int(lf.filter(m).select(pl.len()).collect(engine='streaming').item())
                info[var] = {'cond': cond, 'mask': m, 'n': n}
            vars_ = list(info)
            for i in range(len(vars_)):
                for j in range(i + 1, len(vars_)):
                    v1, v2 = vars_[i], vars_[j]
                    if info[v1]['n'] == 0 or info[v2]['n'] == 0:
                        continue   # ya viene vacío por si solo; no es una contradicción entre AMBOS
                    combinado = int(lf.filter(info[v1]['mask'] & info[v2]['mask'])
                                    .select(pl.len()).collect(engine='streaming').item())
                    if combinado == 0:
                        rep.append({
                            'archivo': arch,
                            'filtros': [{'variable': v1, 'condicion': info[v1]['cond']},
                                       {'variable': v2, 'condicion': info[v2]['cond']}],
                            'filas_individuales': {v1: info[v1]['n'], v2: info[v2]['n']},
                            'filas_combinadas': 0,
                            'alerta': ('estos filtros por separado SÍ tienen datos, pero JUNTOS no dejan '
                                      'ninguna fila; probablemente son mutuamente excluyentes por el '
                                      'patrón de salto del cuestionario (una pregunta que solo se hace si '
                                      'la otra no aplica), no un resultado real de la población — verifica '
                                      'el diccionario antes de combinarlos, o aplícalos por separado')})
        except Exception as e:
            rep.append({'archivo': arch, 'error': str(e)})
    return rep


def verificar_cobertura_filtros(filtros, year, carpeta=None, umbral=0.5):
    """Para cada filtro, chequea si su variable está mayormente EN BLANCO en el
    archivo de origen — patrón típico de una pregunta de SEGUIMIENTO CONDICIONAL
    del cuestionario (ej. 'solo se pregunta si X'). Un filtro así, usado como si
    fuera una restricción poblacional amplia, colapsa la muestra al pequeño
    subgrupo al que se le hizo esa pregunta en particular, no a la población que
    realmente se buscaba filtrar. A diferencia de verificar_filtros() (que detecta
    combinaciones IMPOSIBLES, 0 filas), esto no da 0 — el filtro sí tiene datos,
    solo que muy pocos, así que no hay forma de saber automáticamente si es un
    error o intencional: se reporta como advertencia, no se descarta solo."""
    rep = []
    for f in (filtros or []):
        var = (f.get('variable') or '').upper()
        cond = f.get('condicion')
        arch = f.get('archivo')
        if not (arch and var and cond):
            continue
        try:
            lf = _scan(arch, year, carpeta)
            cols = _cols(lf)
            if var not in cols:
                continue
            r = lf.select(
                pl.len().alias('total'),
                (pl.col(var).is_not_null() & (pl.col(var).str.strip_chars() != '')).sum().alias('con_dato'),
            ).collect(engine='streaming')
            total, con_dato = int(r['total'][0]), int(r['con_dato'][0])
            cobertura = (con_dato / total) if total else 0.0
            if cobertura < umbral:
                rep.append({
                    'archivo': arch, 'variable': var, 'condicion': cond,
                    'cobertura_pct': round(cobertura * 100, 1), 'total_filas': total, 'con_dato': con_dato,
                    'alerta': ('"%s" tiene valor en solo %.1f%% de las filas de %s (%d de %d) — probable '
                              'pregunta condicional del cuestionario, no aplicable a todos; usarla como '
                              'filtro de población puede colapsar la muestra al subgrupo al que se le '
                              'preguntó, no a la población que realmente se buscaba filtrar. Verifica en '
                              'el diccionario si aplica solo bajo alguna condición antes de confiar en el '
                              'tamaño de muestra resultante'
                              % (var, cobertura * 100, arch, con_dato, total))})
        except Exception as e:
            rep.append({'archivo': arch, 'variable': var, 'error': str(e)})
    return rep


# ----------------------------- exportar dataset final -----------------------------
def _limpia_numerica(col):
    """comas decimales -> punto, centinelas de no-respuesta -> null, cast Float64.
    Mismo criterio que _una_brecha, para que el dataset final quede consistente
    con lo que ya se usa en el cálculo de brechas."""
    c = col.str.replace(',', '.', literal=True)
    c = pl.when(c.str.contains(SENTINELA)).then(pl.lit(None)).otherwise(c)
    return c.cast(pl.Float64, strict=False)


def _archivo_para_anio(archivo, rep, year):
    """Traduce el nombre de archivo (que embebe el año, ej. '...-2025-700b.csv') de
    `rep` a `year`. Misma convención que _plan_para_anio (brechas multi-año)."""
    if not archivo or str(rep) == str(year):
        return archivo
    return archivo.replace(str(rep), str(year))


def _plan_datos_para_anio(plan_datos, rep, year):
    if str(rep) == str(year):
        return plan_datos
    p2 = copy.deepcopy(plan_datos)
    if p2.get('archivo_base'):
        p2['archivo_base'] = _archivo_para_anio(p2['archivo_base'], rep, year)
    for p in p2.get('secuencia_merge', []):
        if p.get('archivo'):
            p['archivo'] = _archivo_para_anio(p['archivo'], rep, year)
    return p2


def _lista_para_anio(items, rep, year):
    """Traduce el 'archivo' de cada elemento de filtros/resolución a otro año."""
    if str(rep) == str(year):
        return items
    out = copy.deepcopy(items or [])
    for it in out:
        if it.get('archivo'):
            it['archivo'] = _archivo_para_anio(it['archivo'], rep, year)
    return out


def materializar_dataset(plan_datos, manifiesto, filtros, resolucion, anios, rep, out_path, carpeta=None):
    """Ejecuta DE VERDAD el plan de datos (a diferencia de calcular()/verificar_merge(),
    que solo validan o computan agregados por brecha): arma el dataset final con TODAS
    las variables del manifiesto mergeadas, resolviendo con `resolucion` (ver
    razonador.plan_resolucion_niveles) los archivos que no tienen 1 fila por llave,
    aplica los filtros de población que tengan condición verificada, limpia cada
    columna numérica del manifiesto y lo escribe en `out_path`. Devuelve un reporte
    (nunca falla en silencio: todo lo que no se pudo resolver queda listado, no se
    adivina).

    `anios` es la lista de TODOS los años de cobertura del tema (no solo `rep`, el año
    representativo con el que se construyeron plan_datos/filtros/resolucion): si el tema
    cubre varios años, se materializa CADA UNO (traduciendo los nombres de archivo de
    `rep` a ese año) y se apilan con una columna 'ANIO' — antes solo se exportaba el año
    representativo, perdiendo silenciosamente el resto de la cobertura."""
    anios = [str(a) for a in (anios if isinstance(anios, (list, tuple, set)) else [anios])]
    rep = str(rep)
    reporte = {'variables_excluidas': [], 'agregaciones': [], 'restricciones': [],
              'filtros_aplicados': [], 'filtros_omitidos': [], 'columnas_limpiadas': set(),
              'filtros_contradictorios': [], 'filtros_baja_cobertura': [],
              'anios': anios, 'anios_con_error': []}
    dfs = []
    for year in anios:
        try:
            pd_y = _plan_datos_para_anio(plan_datos, rep, year)
            manifiesto_y = _lista_para_anio(manifiesto, rep, year)
            filtros_y = _lista_para_anio(filtros, rep, year)
            resolucion_y = _lista_para_anio(resolucion, rep, year)
            df_y, rep_y = _materializar_un_anio(pd_y, manifiesto_y, filtros_y, resolucion_y, year, carpeta)
        except Exception as e:
            reporte['anios_con_error'].append({'anio': year, 'error': str(e)})
            continue
        dfs.append(df_y.with_columns(pl.lit(year).alias('ANIO')))
        for k in ('variables_excluidas', 'agregaciones', 'restricciones', 'filtros_aplicados',
                 'filtros_omitidos', 'filtros_contradictorios', 'filtros_baja_cobertura'):
            for item in rep_y.get(k, []):
                reporte[k].append(dict(item, anio=year))
        reporte['columnas_limpiadas'] |= set(rep_y.get('columnas_limpiadas', []))

    if not dfs:
        raise ValueError("ningún año de cobertura (%s) pudo materializarse: %s"
                         % (', '.join(anios), reporte['anios_con_error']))
    df = pl.concat(dfs, how='diagonal_relaxed')
    reporte['columnas_limpiadas'] = sorted(reporte['columnas_limpiadas'])

    llaves_con_anio = ['ANIO'] + plan_datos['llaves_merge']
    dup_final = df.group_by(llaves_con_anio).len().filter(pl.col('len') > 1).height
    nulos = {c: int(df[c].null_count()) for c in df.columns if df[c].null_count() > 0}
    reporte.update({'filas': df.height, 'columnas': df.columns,
                    'filas_duplicadas_por_llave': dup_final, 'nulos_por_columna': nulos})
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    df.write_csv(out_path)
    reporte['ruta'] = out_path
    return reporte


def _materializar_un_anio(plan_datos, manifiesto, filtros, resolucion, year, carpeta=None):
    """El motor real para UN año (lo que antes era materializar_dataset completo).
    Devuelve (DataFrame, reporte_parcial) SIN escribir a disco — eso lo hace el wrapper
    multi-año de arriba, que apila los años y agrega la columna 'ANIO'."""
    llaves_merge = plan_datos['llaves_merge']
    base = plan_datos['archivo_base']
    res_de = {}
    for r in (resolucion or []):
        if r.get('archivo') and r.get('variable'):
            res_de[(r['archivo'], r['variable'].upper())] = r
    # si un filtro apunta a la MISMA (archivo, variable) que necesita resolución de nivel,
    # el filtro manda: define qué código deja 1 fila por llave (ej. P712 == 5 = "Programa
    # Pensión 65"). Sin esto, la resolución (ej. "agregar: conteo") podía transformar la
    # columna en algo que ya NO significa lo que el filtro cree que está filtrando, y el
    # filtro posterior sobre esa columna transformada habría dado un resultado silenciosamente
    # distinto al pedido (ej. filtrar "conteo de programas == 5" en vez de "recibió el programa 5").
    contradicciones = verificar_filtros(filtros, year, carpeta)
    # variables involucradas en una contradicción detectada: NO se aplican solas, ni siquiera como
    # restricción de nivel (abajo). Detectar y seguir aplicando igual (como se hacía antes) llevaba
    # al peor resultado posible: un dataset de 0 filas, silenciándose entre el resto del reporte en
    # vez de detener el daño.
    vars_contradictorias = {(c['archivo'], f['variable'].upper())
                            for c in contradicciones for f in c['filtros']}

    filtro_de = {}
    for f in (filtros or []):
        var = (f.get('variable') or '').upper()
        if f.get('archivo') and var and f.get('condicion') and (f['archivo'], var) not in vars_contradictorias:
            filtro_de[(f['archivo'], var)] = f['condicion']
    filtros_ya_aplicados_en_merge = set()   # (archivo, variable) ya resueltos como restricción arriba:
    # NO se re-aplican en el paso de filtros post-merge, porque para entonces la columna ya solo
    # contiene el valor filtrado o null (por el LEFT JOIN) — re-filtrar "== 5" ahí borraría también
    # a todos los hogares NO tratados (null), perdiendo el grupo de comparación sin que nadie lo pida.

    reporte = {'variables_excluidas': [], 'agregaciones': [], 'restricciones': [],
              'filtros_aplicados': [], 'filtros_omitidos': [], 'columnas_limpiadas': [],
              'filtros_contradictorios': contradicciones,
              'filtros_baja_cobertura': verificar_cobertura_filtros(filtros, year, carpeta)}
    ya_limpias = set()   # columnas que ya salen numéricas y limpias de una agregación

    def _prep_archivo(archivo, cols_deseadas, join_keys):
        lf = _scan(archivo, year, carpeta)
        cols = _cols(lf)
        keys = [k for k in join_keys if k in cols]
        vars_ok = list(dict.fromkeys(c for c in cols_deseadas if c in cols))
        if not keys or not vars_ok:
            return None, keys
        if not _dup_en_llaves(lf.select(keys), keys):
            return lf.select(list(dict.fromkeys(keys + vars_ok))), keys
        # llave NO única en este archivo (nivel ítem/detalle): resolver CADA variable.
        piezas = []
        for var in vars_ok:
            cond_filtro = filtro_de.get((archivo, var))
            r = ({'estrategia': 'restringir', 'restriccion': {'variable': var, 'condicion': cond_filtro},
                 'motivo': 'condición tomada del filtro de población sobre esta misma variable'}
                 if cond_filtro else res_de.get((archivo, var)))
            if not r or r.get('estrategia') == 'excluir':
                reporte['variables_excluidas'].append(
                    {'archivo': archivo, 'variable': var, 'motivo': (r or {}).get('motivo', 'sin resolución de nivel')})
                continue
            if r['estrategia'] == 'restringir':
                restr = r.get('restriccion') or {}
                rvar = (restr.get('variable') or '').upper()
                if not (rvar and rvar in cols and restr.get('condicion')):
                    reporte['variables_excluidas'].append(
                        {'archivo': archivo, 'variable': var,
                         'motivo': 'restricción inválida o variable "%s" inexistente en %s' % (rvar, archivo)})
                    continue
                mask = _cond_mask(pl.col(rvar), restr['condicion'])
                if mask is None:
                    reporte['variables_excluidas'].append(
                        {'archivo': archivo, 'variable': var,
                         'motivo': 'condición de restricción "%s" no interpretable' % restr['condicion']})
                    continue
                sub = lf.select(list(dict.fromkeys(keys + [rvar, var]))).filter(mask).select(keys + [var])
                if _dup_en_llaves(sub, keys):
                    reporte['variables_excluidas'].append(
                        {'archivo': archivo, 'variable': var,
                         'motivo': 'la restricción "%s %s" no aisló 1 fila por llave' % (rvar, restr['condicion'])})
                    continue
                reporte['restricciones'].append({'archivo': archivo, 'variable': var, 'restriccion': restr,
                                                 'origen': 'filtro' if cond_filtro else 'plan_resolucion_niveles'})
                if cond_filtro:
                    filtros_ya_aplicados_en_merge.add((archivo, var))
                    reporte['filtros_aplicados'].append({'variable': var, 'condicion': cond_filtro,
                                                         'nota': 'aplicado al armar el merge (resolución de nivel), no post-merge'})
                piezas.append(sub)
            elif r['estrategia'] == 'agregar':
                func = (r.get('funcion') or 'suma').lower()
                limpio = _limpia_numerica(pl.col(var))
                agg = {'suma': limpio.sum(), 'promedio': limpio.mean(), 'maximo': limpio.max(),
                      'conteo': pl.col(var).count()}.get(func)
                if agg is None:
                    reporte['variables_excluidas'].append(
                        {'archivo': archivo, 'variable': var, 'motivo': 'función "%s" no reconocida' % func})
                    continue
                sub = lf.select(keys + [var]).group_by(keys).agg(agg.alias(var))
                reporte['agregaciones'].append({'archivo': archivo, 'variable': var, 'funcion': func})
                ya_limpias.add(var)
                piezas.append(sub)
            else:
                reporte['variables_excluidas'].append(
                    {'archivo': archivo, 'variable': var, 'motivo': 'estrategia desconocida: %s' % r.get('estrategia')})
        if not piezas:
            return None, keys
        out = piezas[0]
        for extra in piezas[1:]:
            out = out.join(extra, on=keys, how='left')
        return out, keys

    # --- base: debe tener 1 fila por llave de análisis; si no, no hay dataset posible ---
    by_file = {}
    for v in manifiesto:
        if isinstance(v, dict) and v.get('archivo') and v.get('variable'):
            by_file.setdefault(v['archivo'], []).append(v['variable'].upper())
    lf_base, keys_base = _prep_archivo(base, by_file.get(base, []), llaves_merge)
    if lf_base is None or _dup_en_llaves(_scan(base, year, carpeta).select(keys_base), keys_base):
        raise ValueError(
            "el archivo base '%s' no tiene 1 fila por llave de análisis (%s); no se puede "
            "construir el dataset final sobre una base con filas duplicadas" % (base, '+'.join(llaves_merge)))
    lf = lf_base

    for p in plan_datos['secuencia_merge']:
        if p['tipo'] == 'base':
            continue
        sub, keys = _prep_archivo(p['archivo'], [v.upper() for v in p['variables']], p['llaves_join'])
        if sub is not None and keys:
            lf = lf.join(sub, on=keys, how='left')

    # --- filtros de población (solo los que traen condición numérica verificada) ---
    cols_actuales = set(_cols(lf))
    for f in (filtros or []):
        var = (f.get('variable') or '').upper()
        cond = f.get('condicion')
        arch_f = f.get('archivo')
        if not var or not arch_f:
            continue
        if (arch_f, var) in vars_contradictorias:
            reporte['filtros_omitidos'].append(
                {'variable': var, 'motivo': 'forma parte de una combinación de filtros que se contradice '
                 '(ver filtros_contradictorios); no se aplica solo para no vaciar el dataset a ciegas'})
            continue
        if (arch_f, var) in filtros_ya_aplicados_en_merge:
            continue   # ya se aplicó como restricción de nivel al armar el merge (ver arriba)
        if not cond:
            reporte['filtros_omitidos'].append(
                {'variable': var, 'motivo': f.get('motivo') or 'condición no verificada (código sin confirmar)'})
            continue
        if var not in cols_actuales:
            lf_f = _scan(arch_f, year, carpeta)
            cols_f = _cols(lf_f)
            keys_f = [k for k in llaves_merge if k in cols_f]
            if var not in cols_f or not keys_f:
                reporte['filtros_omitidos'].append(
                    {'variable': var, 'motivo': 'variable o llaves no encontradas en %s' % arch_f})
                continue
            sub_f = lf_f.select(list(dict.fromkeys(keys_f + [var])))
            if _dup_en_llaves(sub_f, keys_f):
                reporte['filtros_omitidos'].append(
                    {'variable': var, 'motivo': '"%s" tiene varias filas por llave en %s; sin forma segura de reducirlo para este filtro' % (var, arch_f)})
                continue
            lf = lf.join(sub_f, on=keys_f, how='left')
            cols_actuales.add(var)
        mask = _cond_mask(pl.col(var), cond)
        if mask is None:
            reporte['filtros_omitidos'].append(
                {'variable': var, 'motivo': 'condición "%s" no es un patrón numérico reconocible' % cond})
            continue
        lf = lf.filter(mask)
        reporte['filtros_aplicados'].append({'variable': var, 'condicion': cond})

    # --- limpieza: variables numéricas del manifiesto que NO salieron ya limpias de una agregación ---
    # 'ponderador' (factor de expansión) es SIEMPRE numérico y hace falta limpio para poder
    # usarlo en cualquier análisis ponderado fuera del sistema; sin él en la lista, el CSV final
    # exportaba el ponderador con coma decimal sin convertir (ej. "656,63" en vez de "656.63").
    roles_numericos = {'dependiente', 'independiente', 'control', 'ponderador'}
    a_limpiar = {v['variable'].upper() for v in manifiesto
                if isinstance(v, dict) and (v.get('rol') or '').lower() in roles_numericos and v.get('variable')}
    cols_final = _cols(lf)
    for c in cols_final:
        if c in a_limpiar and c not in ya_limpias:
            lf = lf.with_columns(_limpia_numerica(pl.col(c)).alias(c))
            reporte['columnas_limpiadas'].append(c)

    df = lf.collect(engine='streaming')

    # --- QC de ESTE año: nunca afirmar "limpio" sin volver a comprobarlo sobre el resultado ---
    # (el chequeo combinado con 'ANIO' lo hace el wrapper multi-año, después de apilar)
    reporte['filas'] = df.height
    reporte['filas_duplicadas_por_llave'] = df.group_by(llaves_merge).len().filter(pl.col('len') > 1).height
    return df, reporte
