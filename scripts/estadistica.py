# -*- coding: utf-8 -*-
"""Paso 8 (motor de cálculo): ejecuta el PLAN de brechas sobre los datos REALES.

El plan lo produce el razonador (IA) anclado al catálogo; aquí solo se COMPUTA
con pandas, con ponderador (factor de expansión) cuando se indica. Determinista.

Un ítem del plan:
{
  "brecha": "Brecha de ingreso laboral por sexo",
  "outcome": {"archivo": "0005_enaho01a-2024-500.csv", "variable": "I524E1"},
  "grupo":   {"archivo": "0002_enaho01-2024-200.csv", "variable": "P207",
              "etiquetas": {"1": "Hombre", "2": "Mujer"}},
  "ponderador": {"archivo": "0005_enaho01a-2024-500.csv", "variable": "FACTOR07"},
  "estadistico": "media"   # media | mediana
}
"""
import os, glob
import numpy as np
import pandas as pd

KEYS4 = ["CONGLOME", "VIVIENDA", "HOGAR", "CODPERSO"]


def _path(archivo, year):
    base = glob.glob(os.path.join('enaho_*', 'microodatos_inei', 'enaho', '2_organized',
                                  'by_year', str(year), 'modulos', archivo))
    return base[0] if base else None


def _sniff(path):
    with open(path, encoding='latin-1') as fh:
        l = fh.readline()
    return ';' if l.count(';') > l.count(',') else ','


def _load(archivo, year, wanted):
    path = _path(archivo, year)
    if not path:
        raise FileNotFoundError(archivo)
    wanted = {w.upper() for w in wanted}
    df = pd.read_csv(path, sep=_sniff(path), encoding='latin-1', dtype=str,
                     usecols=lambda c: c.strip().upper() in wanted,
                     on_bad_lines='skip', keep_default_na=False)
    df.columns = [c.strip().upper() for c in df.columns]
    return df


def _cargar_factores(archivo, year):
    """Carga llaves + todas las columnas de factor de expansión (FAC*) del archivo."""
    path = _path(archivo, year)
    df = pd.read_csv(path, sep=_sniff(path), encoding='latin-1', dtype=str,
                     usecols=lambda c: c.strip().upper() in KEYS4 or c.strip().upper().startswith('FAC'),
                     on_bad_lines='skip', keep_default_na=False)
    df.columns = [c.strip().upper() for c in df.columns]
    return df


def _es_sentinela(s):
    """Códigos de no-respuesta del INEI: enteros de 5+ dígitos todos 9 (99999, 999999...)."""
    ent = str(s).strip().split('.')[0].lstrip('-')
    return ent.isdigit() and len(ent) >= 5 and set(ent) == {'9'}


def _weighted_median(x, w):
    o = np.argsort(x)
    x, w = np.asarray(x)[o], np.asarray(w)[o]
    cw = np.cumsum(w)
    if cw[-1] <= 0:
        return float(np.median(x))
    return float(x[np.searchsorted(cw, 0.5 * cw[-1])])


def _una_brecha(item, year):
    ov = item['outcome']['variable'].upper()
    gv = item['grupo']['variable'].upper()
    et = {str(k): v for k, v in (item['grupo'].get('etiquetas') or {}).items()}
    wv = (item.get('ponderador') or {}).get('variable')
    wv = wv.upper() if wv else None
    estad = (item.get('estadistico') or 'media').lower()

    of = _load(item['outcome']['archivo'], year, set(KEYS4) | {ov})
    gf = _load(item['grupo']['archivo'], year, set(KEYS4) | {gv})
    keys = [k for k in KEYS4 if k in of.columns and k in gf.columns]
    if not keys:
        raise ValueError("sin llaves comunes para merge")
    m = of.merge(gf, on=keys, how='inner')
    pond_usado = None
    if wv:
        warch = item['ponderador']['archivo']
        # carga todas las columnas FAC* del archivo del ponderador (robustez ante nombres)
        wf_full = _load(warch, year, set(KEYS4) | {c for c in (wv,)})
        if wv not in wf_full.columns:               # nombre dado no existe -> busca un FAC*
            wf_full = _cargar_factores(warch, year)
            cand = [c for c in wf_full.columns if c.startswith('FAC')]
            wv = cand[0] if cand else None
        if wv:
            wk = [k for k in KEYS4 if k in m.columns and k in wf_full.columns]
            if wk:
                m = m.merge(wf_full[wk + [wv]], on=wk, how='left')
                m['_w'] = pd.to_numeric(m[wv], errors='coerce').fillna(0.0)
                pond_usado = wv
    if pond_usado is None:
        m['_w'] = 1.0
    m[ov] = m[ov].mask(m[ov].map(_es_sentinela))      # neutraliza centinelas de missing (999999)
    m[ov] = pd.to_numeric(m[ov], errors='coerce')
    m = m.dropna(subset=[ov])
    m = m[m[gv].astype(str).str.strip() != '']

    grupos = []
    for g, sub in m.groupby(gv):
        x, w = sub[ov].to_numpy(float), sub['_w'].to_numpy(float)
        if estad == 'mediana':
            val = _weighted_median(x, w)
        else:
            val = float(np.average(x, weights=w)) if w.sum() > 0 else float(np.mean(x))
        grupos.append({'grupo': str(g), 'etiqueta': et.get(str(g), str(g)),
                       'valor': round(val, 2), 'n': int(len(sub))})
    grupos = [gp for gp in grupos if gp['n'] >= 30]   # ignora celdas con muy pocos casos
    grupos.sort(key=lambda d: d['valor'])
    out = {'brecha': item.get('brecha'), 'outcome': ov, 'grupo': gv,
           'estadistico': estad, 'ponderador': pond_usado or 'sin ponderar',
           'n_total': int(len(m)), 'grupos': grupos}
    vals = [gp['valor'] for gp in grupos]
    if len(vals) >= 2 and min(vals) != 0:
        out['brecha_absoluta'] = round(max(vals) - min(vals), 2)
        out['brecha_relativa_pct'] = round(100 * (max(vals) - min(vals)) / abs(min(vals)), 1)
    return out


def _nfilas(arch, year):
    return len(_load(arch, year, set(KEYS4)))


def _overlap_match(arch_a, arch_b, var, year):
    """% de coincidencia de 'var' entre dos módulos en su población común."""
    da = _load(arch_a, year, set(KEYS4) | {var}).rename(columns={var: '_A'})
    db = _load(arch_b, year, set(KEYS4) | {var}).rename(columns={var: '_B'})
    keys = [k for k in KEYS4 if k in da.columns and k in db.columns]
    if not keys:
        return None, 0
    m = da.merge(db, on=keys, how='inner')
    if len(m) == 0:
        return None, 0
    return float((m['_A'] == m['_B']).mean() * 100), len(m)


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
            df = _load(p['archivo'], year, set(HH))
            hh = [k for k in HH if k in df.columns]
            n = len(df)
            u = df.drop_duplicates(hh).shape[0] if hh else 0
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


def calcular(plan, year):
    res = []
    for item in plan:
        try:
            res.append(_una_brecha(item, year))
        except Exception as e:
            res.append({'brecha': item.get('brecha'), 'error': str(e)})
    return res
