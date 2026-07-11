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
              "etiquetas": {"1": "Hombre", "2": "Mujer"}},
  "ponderador": {"archivo": "0005_enaho01a-2023-500.csv", "variable": "FAC500A"},
  "estadistico": "media"   # media | mediana
}
"""
import os, glob, copy
import numpy as np
import polars as pl

KEYS4 = ["CONGLOME", "VIVIENDA", "HOGAR", "CODPERSO"]
# no-respuesta INEI: parte entera de 5+ nueves (99999, 999999.9, ...).
# Tradeoff deliberado: '9999' (4 dígitos) NO se limpia porque puede ser un valor
# legítimo (ej. un monto de 9999 soles); si abunda, se emite una NOTA en el
# resultado para que el usuario lo verifique contra el diccionario.
SENTINELA = r'^\s*-?9{5,}(\.\d*)?\s*$'


# ----------------------------- acceso a archivos -----------------------------
def _path(archivo, year):
    # sorted(): resolución DETERMINISTA cuando el mismo año existe en varias
    # carpetas enaho_* (misma regla que razonador.load_catalogo).
    hits = sorted(glob.glob(os.path.join('enaho_*', 'microodatos_inei', 'enaho', '2_organized',
                                         'by_year', str(year), 'modulos', archivo)))
    return hits[0] if hits else None


def _sniff(path):
    with open(path, encoding='latin-1') as fh:
        l = fh.readline()
    return ';' if l.count(';') > l.count(',') else ','


def _scan(archivo, year):
    """LazyFrame en streaming con columnas normalizadas a MAYÚSCULAS. No lee datos aún."""
    path = _path(archivo, year)
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


def _weighted_median(x, w):
    o = np.argsort(x)
    x, w = np.asarray(x)[o], np.asarray(w)[o]
    cw = np.cumsum(w)
    if cw[-1] <= 0:
        return float(np.median(x))
    return float(x[np.searchsorted(cw, 0.5 * cw[-1])])


# ----------------------------- una brecha -----------------------------
def _una_brecha(item, year):
    ov = item['outcome']['variable'].upper()
    gv = item['grupo']['variable'].upper()
    et = {str(k): v for k, v in (item['grupo'].get('etiquetas') or {}).items()}
    estad = (item.get('estadistico') or 'media').lower()
    arch_o = item['outcome']['archivo']
    arch_g = item['grupo']['archivo']

    lo = _scan(arch_o, year)
    co = _cols(lo)
    if ov not in co:
        raise ValueError("outcome %s no existe en %s" % (ov, arch_o))
    keys_o = [k for k in KEYS4 if k in co]

    # --- ponderador: resolver archivo y nombre (fallback a cualquier FAC*) ---
    p = item.get('ponderador') or {}
    warch = p.get('archivo') or arch_o
    wv = (p.get('variable') or '').upper() or None
    w_cols = co if warch == arch_o else _cols(_scan(warch, year))
    wname = wv if (wv and wv in w_cols) else next((c for c in w_cols if c.startswith('FAC')), None)
    nota_pond = None

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
    if arch_g != arch_o:
        lg = _scan(arch_g, year)
        cg = _cols(lg)
        if gv not in cg:
            raise ValueError("variable de grupo %s no existe en %s" % (gv, arch_g))
        keys = [k for k in KEYS4 if k in co and k in cg]
        if not keys:
            raise ValueError("sin llaves comunes para merge")
        lg = lg.select(keys + [gv]).unique()
        if _dup_en_llaves(lg, keys):
            raise ValueError(
                "niveles incompatibles: '%s' tiene varias filas por %s; unirlo "
                "multiplicaría filas e inflaría la estadística. Usa una variable de "
                "grupo del mismo archivo del outcome o de un módulo con 1 fila por esa llave."
                % (arch_g, '+'.join(keys)))
        lf = lf.join(lg, on=keys, how='inner')

    # --- peso desde OTRO archivo ---
    if wname and warch != arch_o:
        lw = _scan(warch, year)
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
    notas = [nota_pond] if nota_pond else []
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


def calcular(plan, year):
    res = []
    for item in plan:
        try:
            res.append(_una_brecha(item, year))
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


def calcular_multi(plan, anios, rep):
    """Ejecuta el MISMO plan de brechas en cada año de cobertura (evolución temporal).
    Los años sin archivo/variable quedan como error explícito, no rompen el resto."""
    return {str(y): calcular(_plan_para_anio(plan, rep, y), y) for y in anios}


# ----------------------------- verificaciones -----------------------------
def _nfilas(arch, year):
    return int(_scan(arch, year).select(pl.len()).collect(engine='streaming').item())


def _overlap_match(arch_a, arch_b, var, year):
    """% de coincidencia de 'var' entre dos módulos en su población común (streaming)."""
    la, lb = _scan(arch_a, year), _scan(arch_b, year)
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


def revisar_consolidacion(cat, manifiesto, year):
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
    cob = {a: _nfilas(a, year) for a in archivos}
    rep = {'base': base, 'coberturas': cob, 'modulos': [], 'consolidables': []}
    for a in archivos:
        if a == base:
            continue
        red, dif, prop = [], [], []
        for var in by_file[a]:
            if var in {'CONGLOME', 'VIVIENDA', 'HOGAR', 'CODPERSO'}:
                continue
            if var in cols_de.get(base, set()):
                pct, n = _overlap_match(a, base, var, year)
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


def verificar_merge(plan, year):
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
            lf = _scan(p['archivo'], year)
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
