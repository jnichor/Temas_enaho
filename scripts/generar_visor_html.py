# -*- coding: utf-8 -*-
import os, re, glob, datetime, html, collections
import polars as pl
import pandas as pd
import pdfplumber

HHKEYS = ["CONGLOME", "VIVIENDA", "HOGAR"]
ADMIN_EXACT = {"MES", "UBIGEO", "DOMINIO", "ESTRATO", "NCONGLOME", "SUB_CONGLOME",
               "PERIODO", "CODINFOR"} | set(HHKEYS) | {"CODPERSO"}
PREVIEW_ROWS = 25


def is_admin(c):
    if c in ADMIN_EXACT or c.startswith("FACTOR") or c.startswith("TICUEST"):
        return True
    return ("AÑO" in c) or ("A�O" in c) or c == "AO"


def clean_title(t):
    if not t:
        return '(sin titulo)'
    t = re.sub(r'M[OÓ]DULO\s*P?GTA?\.?\s*\d+[A-Za-z]?', '', t, flags=re.I)
    t = re.sub(r'M[OÓ]DULO\s*\d+[A-Za-z]?', '', t, flags=re.I)
    t = re.sub(r'…|\.\.\.', '', t)
    t = re.sub(r'\s*\.\s*\d+\s*$', '', t)
    t = re.sub(r'\(\s+', '(', t)
    t = re.sub(r'\s+\)', ')', t)
    t = re.sub(r'\(\s*\)', '', t)
    if t.count('(') != t.count(')'):
        t = t.replace('(', '').replace(')', '')
    t = re.sub(r'\s{2,}', ' ', t).strip(' .,-')
    letters = [c for c in t if c.isalpha()]
    if letters and sum(c.isupper() for c in letters) / len(letters) > 0.7:
        t = t.title()
    return t or '(sin titulo)'


def find_year_dirs():
    for base in glob.glob("enaho_*"):
        by = os.path.join(base, "microodatos_inei", "enaho", "2_organized", "by_year")
        if os.path.isdir(by):
            for y in sorted(os.listdir(by)):
                yd = os.path.join(by, y)
                if os.path.isdir(os.path.join(yd, "modulos")):
                    yield base, y, yd


def _dic_text(docs_dir):
    dics = sorted(glob.glob(os.path.join(docs_dir, "*Diccionario*.pdf")))
    if not dics:
        return None, None
    with pdfplumber.open(dics[0]) as pdf:
        return "\n".join((pg.extract_text() or "") for pg in pdf.pages), os.path.basename(dics[0])


def parse_titulos(text):
    titles = {}
    if not text:
        return titles
    pat = re.compile(r'ENAHO\d+\w?-\d{4}-([0-9A-Za-z\-]+?)(?:\.SAV)?\s*[:.]\s*(.+)', re.I)
    for l in text.splitlines():
        m = pat.search(l)
        if not m:
            continue
        code = m.group(1).upper().strip('.')
        title = re.sub(r'^SAV\s+', '', m.group(2), flags=re.I)
        title = re.sub(r'\.{2,}.*$', '', title)
        title = re.sub(r'\(M[OÓ]DULO.*$', '', title, flags=re.I).strip()
        if len(title) > 4 and (code not in titles or len(title) > len(titles[code])):
            titles[code] = title
    return titles


VARDEF = re.compile(r'^([A-ZÑ][A-ZÑ0-9_\$]{1,30})\s+(\d{1,3})\s+(\d)\s+([CNAF])\s+(.+)$')
ARCH = re.compile(r'Archivo:\s*([A-Za-z0-9\-]+)', re.I)
SKIPLINE = re.compile(r'^(Rango|\d+[\.\)]|\d+\s+Missing|Missing|Encuesta Nacional|Archivo:|'
                      r'Variable\s+Tama|Diccionario de Datos|ARCHIVO DEL|\d+\s*$)', re.I)


def parse_var_dictionary(text):
    """{code: {VARNAME: etiqueta}} desde el cuerpo del diccionario oficial."""
    dic = {}
    if not text:
        return dic
    cur, lastvar = None, None
    for raw in text.splitlines():
        l = raw.strip()
        a = ARCH.search(l)
        if a:
            arch = a.group(1)
            m = re.search(r'-\d{4}-(.+)$', arch)
            cur = (m.group(1).upper() if m else ('SUMARIA' if 'SUMARIA' in arch.upper() else arch.upper()))
            dic.setdefault(cur, {})
            lastvar = None
            continue
        if cur is None:
            continue
        m = VARDEF.match(l)
        if m:
            dic[cur][m.group(1)] = m.group(5).strip()
            lastvar = m.group(1)
        elif lastvar and not SKIPLINE.match(l) and len(l) > 3 and not l[0].isdigit():
            if len(dic[cur][lastvar]) < 110:
                dic[cur][lastvar] += ' ' + l
        else:
            lastvar = None
    return dic


def code_from_filename(fn):
    name = fn[:-4] if fn.lower().endswith('.csv') else fn
    if 'sumaria' in name.lower():
        m = re.search(r'sumaria-\d{4}-?(.*)', name, re.I)
        suf = (m.group(1) if m else '').upper()
        return 'SUMARIA' + (('-' + suf) if suf else '')
    m = re.search(r'-\d{4}-(.+)$', name)
    return (m.group(1).upper() if m else name.upper())


def sniff_delim(path):
    with open(path, encoding='latin-1') as fh:
        line = fh.readline()
    return ';' if line.count(';') > line.count(',') else ','


def derive_unidad(key):
    has_person = 'CODPERSO' in key
    extra = [k for k in key if k not in HHKEYS + ['CODPERSO']]
    if has_person:
        return 'persona × registro' if extra else 'persona'
    if extra:
        return 'hogar × registro/ítem'
    if all(k in key for k in HHKEYS):
        return 'hogar'
    return 'indeterminada'


def _maxgain(base, pool, n, nuniq, budget=8):
    extra = []
    for _ in range(budget):
        cur = nuniq(base + extra)
        best, bestu = None, cur
        for c in pool:
            if c in extra:
                continue
            u = nuniq(base + extra + [c])
            if u > bestu:
                bestu, best = u, c
        if best is None:
            break
        extra.append(best)
        if nuniq(base + extra) == n:
            break
    return extra


def inspect(path):
    delim = sniff_delim(path)
    # LAZY / STREAMING: nunca materializa el archivo entero en RAM (clave para
    # módulos enormes como el 601 con ~9M filas / 1.3 GB).
    lf = pl.scan_csv(path, separator=delim, infer_schema_length=0,
                     encoding='utf8-lossy', truncate_ragged_lines=True)
    orig = lf.collect_schema().names()
    cols = [c.strip().upper() for c in orig]
    lf = lf.rename({o: c for o, c in zip(orig, cols)})

    def _collect(expr):
        return lf.select(expr).collect(engine='streaming')

    # UNA sola pasada: nº filas + cardinalidad + vacíos por columna (+ depto)
    aggs = [pl.len().alias('__n')]
    for i, c in enumerate(cols):
        aggs.append(pl.col(c).n_unique().alias('u%d' % i))
        aggs.append((pl.col(c).is_null() | (pl.col(c).str.strip_chars() == '')).sum().alias('e%d' % i))
    if 'UBIGEO' in cols:
        aggs.append(pl.col('UBIGEO').str.slice(0, 2).n_unique().alias('__dep'))
    row = _collect(aggs)
    n = int(row['__n'][0])
    card = {c: int(row['u%d' % i][0]) for i, c in enumerate(cols)}
    empties = {c: int(row['e%d' % i][0]) for i, c in enumerate(cols)}

    _cache = {}

    def nuniq(ks):                       # combinaciones únicas (memoizado; 1 pasada c/u)
        k = tuple(ks)
        if k in _cache:
            return _cache[k]
        v = card[ks[0]] if len(ks) == 1 else int(_collect(pl.struct(ks).n_unique().alias('u'))['u'][0])
        _cache[k] = v
        return v

    base = [k for k in HHKEYS + ['CODPERSO'] if k in cols]
    extra = []
    if base and nuniq(base) != n:
        remaining = [c for c in cols if c not in base]
        pool = [c for c in remaining if card[c] < 0.5 * n] or remaining
        for _ in range(10):
            cur = nuniq(base + extra)
            if cur == n:
                break
            cands = [c for c in pool if c not in extra]
            if not cands:
                break
            # 1 sola pasada streaming: unicidad de base+extra+[c] para CADA candidato
            r = _collect([pl.struct(base + extra + [c]).n_unique().alias('c%d' % i)
                          for i, c in enumerate(cands)])
            vals = [int(r['c%d' % i][0]) for i in range(len(cands))]
            bi = max(range(len(cands)), key=lambda i: vals[i])
            if vals[bi] <= cur:                      # no mejora; amplía a todas las columnas
                if pool is not remaining:
                    pool = remaining
                    continue
                break
            extra.append(cands[bi])
            _cache[tuple(base + extra)] = vals[bi]
        # minimizar: quita columnas redundantes (base fija)
        changed = True
        while changed:
            changed = False
            for c in list(extra):
                if nuniq(base + [x for x in extra if x != c]) == n:
                    extra.remove(c)
                    changed = True
    key = base + extra
    unica = bool(key) and nuniq(key) == n
    hh = [k for k in HHKEYS if k in cols]
    nhog = nuniq(hh) if len(hh) == 3 else None
    npers = nuniq(hh + ['CODPERSO']) if (nhog and 'CODPERSO' in cols) else None

    # --- cobertura geografica ---
    geo = {}
    if 'UBIGEO' in cols:
        geo['ubigeo'] = card['UBIGEO']
        geo['dep'] = int(row['__dep'][0])
    if 'DOMINIO' in cols:
        geo['dom'] = card['DOMINIO']
    # --- cobertura temporal (por MES; el año lo pone el visor) ---
    meses = None
    if 'MES' in cols:
        vals = _collect(pl.col('MES').unique())['MES'].to_list()
        meses = sorted({int(x) for x in vals if str(x).strip().isdigit()})
    # --- calidad / completitud (vacio = null o cadena vacia) ---
    total = n * len(cols)
    pct = 100.0 * (1 - sum(empties.values()) / total) if total else 100.0
    cols_complete = sum(1 for c in cols if empties[c] == 0)
    worst = sorted(((c, empties[c]) for c in cols if not is_admin(c)), key=lambda kv: -kv[1])[:3]
    worst = [(c, round(100.0 * e / n, 0)) for c, e in worst if e > 0 and n]
    dup_key = (n - nuniq(key)) if key else None
    # --- familias de variables ---
    fam = collections.Counter()
    n_ident = 0
    for c in cols:
        if is_admin(c):
            n_ident += 1
            continue
        mm = re.match(r'^([A-ZÑ]+\d*)', c)
        fam[mm.group(1) if mm else c] += 1
    familias = fam.most_common(6)

    return {'delim': delim, 'ncols': len(cols), 'nrows': n, 'key': key,
            'unica': unica, 'extra': extra, 'unidad': derive_unidad(key),
            'cols': list(cols), 'nhog': nhog, 'npers': npers,
            'geo': geo, 'meses': meses, 'pct': pct, 'cols_complete': cols_complete,
            'worst': worst, 'dup_key': dup_key, 'familias': familias,
            'n_ident': n_ident, 'n_content': len(cols) - n_ident}


def esc(s):
    return html.escape(str(s))


def preview(path, delim):
    df = pd.read_csv(path, sep=delim, nrows=PREVIEW_ROWS, dtype=str,
                     encoding='latin-1', on_bad_lines='skip', keep_default_na=False)
    df.columns = [c.strip().upper() for c in df.columns]
    return df.to_html(index=False, border=0, classes='preview', na_rep='', escape=True), list(df.columns)


def nivel_de(m):
    base_unit = m['npers'] if m['npers'] else m['nhog']
    gran = (m['nrows'] / base_unit) if base_unit else None
    if gran is None:
        return 'estructura no estándar'
    if gran <= 1.05:
        return '1 fila por %s (resumen)' % ('persona' if m['npers'] else 'hogar')
    disc = m['extra'][-1] if m['extra'] else '?'
    return '%.0f filas por %s (detalle; una por %s)' % (gran, 'persona' if m['npers'] else 'hogar', disc)


def render_detalle(m, year):
    g = m['geo']
    gt = []
    if g.get('ubigeo') is not None:
        gt.append('%s distritos (UBIGEO)' % '{:,}'.format(g['ubigeo']))
    if g.get('dep') is not None:
        gt.append('%d departamentos' % g['dep'])
    if g.get('dom') is not None:
        gt.append('%d dominios' % g['dom'])
    geo_s = ', '.join(gt) if gt else 'sin variables geográficas (UBIGEO/DOMINIO)'
    mm = m['meses']
    if mm:
        mes_s = ('meses %02d–%02d' % (min(mm), max(mm))) if len(mm) > 1 else ('mes %02d' % mm[0])
    else:
        mes_s = 'sin variable de mes'
    fam_s = ', '.join('%s (%d)' % (f, c) for f, c in m['familias']) or '—'
    worst_s = ('; con más vacíos: ' + ', '.join('%s (%.0f%%)' % (c, p) for c, p in m['worst'])) if m['worst'] else ''
    dup = '—' if m['dup_key'] is None else ('0' if m['dup_key'] == 0 else '{:,}'.format(m['dup_key']))
    return ('<div class="detail">'
            '<div><b>Unidad de análisis:</b> %s &mdash; identificada por <span class="mono">%s</span></div>'
            '<div><b>Qué variables contiene:</b> %d en total = %d de identificación/geográficas + %d de contenido. '
            'Bloques temáticos: <span class="mono">%s</span> <span class="muted">(detalle completo en «Diccionario de variables» abajo)</span></div>'
            '<div><b>Cobertura geográfica:</b> %s</div>'
            '<div><b>Cobertura temporal:</b> año %s, %s</div>'
            '<div><b>Calidad y completitud:</b> %.1f%% de celdas con dato &middot; %d/%d columnas sin vacíos &middot; '
            '%s filas duplicadas en la llave%s</div>'
            '<div class="muted">Un %% bajo de celdas con dato es normal en la ENAHO: muchas preguntas son '
            'condicionales (saltos de patrón), por lo que su vacío es legítimo, no un error. La llave sin '
            'duplicados es el indicador real de integridad.</div>'
            '</div>' % (esc(m['unidad']), esc('+'.join(m['key'])),
                        m['ncols'], m['n_ident'], m['n_content'], esc(fam_s),
                        esc(geo_s), esc(year), esc(mes_s),
                        m['pct'], m['cols_complete'], m['ncols'], dup, esc(worst_s)))


def razones(fs, info, max_vars=8):
    """Bullets: por qué difiere cada archivo del grupo."""
    union_otros = {}
    for f in fs:
        otros = set()
        for g in fs:
            if g != f:
                otros |= set(info[g]['cols'])
        union_otros[f] = otros
    max_hog = max((info[f]['nhog'] or 0) for f in fs)
    comun = set.intersection(*[set(info[f]['key']) for f in fs]) if fs else set()
    comun_ord = [k for k in HHKEYS + ['CODPERSO'] if k in comun]
    bullets = []
    for f in fs:
        m = info[f]
        propias = [c for c in m['cols'] if c not in union_otros[f] and not is_admin(c)]
        vs = (', '.join(propias[:max_vars]) + (' …' if len(propias) > max_vars else '')) if propias else '—'
        cob = '{:,}'.format(m['nhog'] or 0) + ' hogares' + (
            ' <b>(subconjunto, no todos)</b>' if (m['nhog'] or 0) < max_hog else ' (todos)')
        bullets.append('<li><b>%s</b> — %s · %s · cubre %s · variables propias: <span class="mono">%s</span></li>'
                       % (esc(code_from_filename(f)), esc(m['title']), esc(nivel_de(m)), cob, esc(vs)))
    return comun_ord, bullets


CSS = """
* { box-sizing: border-box; }
body { font-family:-apple-system,'Segoe UI',Roboto,Arial,sans-serif; color:#1f2a37; margin:0; background:#f4f6f8; }
.wrap { max-width:1100px; margin:0 auto; padding:28px 22px 80px; }
header h1 { color:#1f3a5f; margin:0 0 4px; font-size:30px; }
header .sub { color:#2e7d8c; font-size:18px; font-weight:600; margin-bottom:14px; }
header .lead { color:#5b6670; line-height:1.5; max-width:800px; }
header .meta { color:#5b6670; font-size:13px; margin-top:12px; }
hr { border:none; border-top:2px solid #2e7d8c; margin:18px 0 26px; }
.toolbar { position:sticky; top:0; background:#f4f6f8; padding:10px 0; z-index:5; }
#q { width:100%; padding:10px 12px; border:1px solid #cbd5e0; border-radius:8px; font-size:14px; }
h2.mod { color:#1f3a5f; font-size:17px; margin:26px 0 6px; padding-bottom:6px; border-bottom:1px solid #d7dee5; }
.mono { font-family:'Cascadia Code',Consolas,monospace; }
.why { background:#fff8e6; border:1px solid #f0e0a8; border-left:4px solid #e0a800; border-radius:8px; padding:9px 14px; margin:4px 0 12px; }
.why h4 { margin:0 0 5px; color:#8a6d00; font-size:13px; }
.why .shared { color:#6b6b55; font-size:12px; margin:0 0 5px; }
.why ul { margin:0; padding-left:18px; }
.why li { margin:3px 0; font-size:12.5px; line-height:1.45; color:#4a4a3a; }
details { background:#fff; border:1px solid #e1e7ec; border-radius:8px; margin:8px 0; overflow:hidden; }
details[open] { box-shadow:0 2px 10px rgba(31,58,95,.08); }
summary { cursor:pointer; padding:11px 14px; list-style:none; display:flex; flex-wrap:wrap; align-items:center; gap:9px; }
summary::-webkit-details-marker { display:none; }
summary::before { content:'▸'; color:#2e7d8c; font-weight:700; }
details[open] > summary::before { content:'▾'; }
.fname { font-family:'Cascadia Code',Consolas,monospace; font-weight:700; color:#1f3a5f; }
.tags { color:#5b6670; font-size:12.5px; }
.tag { background:#eef2f6; border-radius:5px; padding:1px 7px; margin-left:4px; white-space:nowrap; }
.tag.key { font-family:Consolas,monospace; color:#1f3a5f; }
.body { padding:0 14px 14px; }
.body .info { color:#5b6670; font-size:12.5px; margin:6px 0 8px; }
.detail { background:#f4f9fa; border:1px solid #d6e6ea; border-radius:8px; padding:9px 13px; margin:6px 0 10px; font-size:12.5px; line-height:1.55; }
.detail div { margin:2px 0; }
.detail b { color:#1f3a5f; }
.muted { color:#8a949e; }
details.dict { margin:8px 0; border:1px dashed #b9c6d1; background:#fafcfe; }
details.dict > summary { padding:8px 12px; color:#2e7d8c; font-weight:600; }
details.dict > summary::before { content:'📖 '; }
.dictwrap { max-height:300px; overflow:auto; }
table.dict { border-collapse:collapse; width:100%; font-size:12px; }
table.dict th { position:sticky; top:0; background:#2e7d8c; color:#fff; text-align:left; padding:5px 10px; }
table.dict td { padding:4px 10px; border-bottom:1px solid #eef2f6; vertical-align:top; }
table.dict td.v { font-family:Consolas,monospace; color:#1f3a5f; white-space:nowrap; font-weight:600; }
table.dict td.nolab { color:#aab2bb; font-style:italic; }
table.dict tr:nth-child(even) td { background:#f4f9fa; }
.tablewrap { overflow:auto; max-height:430px; border:1px solid #e1e7ec; border-radius:6px; }
table.preview { border-collapse:collapse; font-size:12px; width:100%; }
table.preview th { position:sticky; top:0; background:#1f3a5f; color:#fff; padding:6px 9px; text-align:left; white-space:nowrap; }
table.preview td { padding:5px 9px; border-bottom:1px solid #eef2f6; white-space:nowrap; }
table.preview tr:nth-child(even) td { background:#f6f8fa; }
.note { color:#8a949e; font-size:11.5px; margin-top:6px; }
"""

JS = """
const q=document.getElementById('q');
q.addEventListener('input',()=>{const v=q.value.toLowerCase();
 document.querySelectorAll('.fileblock').forEach(d=>{
   const t=d.getAttribute('data-search');
   d.style.display=t.includes(v)?'':'none';});
 document.querySelectorAll('h2.mod').forEach(h=>{
   let n=h.nextElementSibling,vis=false;
   while(n&&!n.classList.contains('mod')){if((n.classList.contains('fileblock')||n.classList.contains('why'))&&n.style.display!=='none')vis=true;n=n.nextElementSibling;}
   h.style.display=vis?'':'none';});});
"""


def build_html(base, year, ydir):
    md = os.path.join(ydir, 'modulos')
    docs = os.path.join(base, 'microodatos_inei', 'enaho', '2_organized', 'documentation')
    text, dic_name = _dic_text(docs)
    titles = parse_titulos(text)
    vardic = parse_var_dictionary(text)
    files = sorted(f for f in os.listdir(md) if f.lower().endswith('.csv'))
    groups, info = {}, {}
    for f in files:
        groups.setdefault(f.split('_')[0], []).append(f)
        meta = inspect(os.path.join(md, f))
        code = code_from_filename(f)
        raw = titles.get(code) or titles.get(re.sub(r'[A-Z]$', '', code))
        meta['title'] = clean_title(raw) if raw else '(título no verificado)'
        meta['code'] = code
        info[f] = meta

    P = ['<!DOCTYPE html><html lang="es"><head><meta charset="utf-8">',
         '<meta name="viewport" content="width=device-width, initial-scale=1">',
         '<title>Documentación ENAHO %s</title><style>%s</style></head><body><div class="wrap">' % (year, CSS),
         '<header><h1>Documentación ENAHO</h1>',
         '<div class="sub">Encuesta Nacional de Hogares — Año %s</div>' % year,
         '<div class="lead">Catálogo interactivo de los %d archivos de microdatos. Haz clic en un archivo '
         'para ver su <b>vista previa de datos</b> (pandas) y el <b>diccionario de variables</b> '
         '(significado de cada columna, según el diccionario oficial). En los módulos con varios archivos '
         'verás los <b>motivos por los que difieren</b>.</div>' % len(files),
         '<div class="meta"><b>Fuente:</b> %s · <b>Carpeta:</b> %s · <b>Generado:</b> %s</div>'
         % (esc(dic_name or 'NO ENCONTRADO'), esc(base), datetime.datetime.now().strftime('%Y-%m-%d')),
         '</header><hr>',
         '<div class="toolbar"><input id="q" type="search" placeholder="Filtrar por archivo, título o variable…"></div>']

    for pre in sorted(groups):
        fs = groups[pre]
        P.append('<h2 class="mod">Módulo %s — %s</h2>' % (esc(pre), esc(info[fs[0]]['title'])))

        if len(fs) > 1:
            comun, bullets = razones(fs, info)
            shared = ('<p class="shared">Todos comparten <span class="mono">%s</span>. Difieren en:</p>'
                      % esc('+'.join(comun))) if comun else ''
            P.append('<div class="why"><h4>¿Por qué hay %d archivos y en qué se diferencian?</h4>%s<ul>%s</ul></div>'
                     % (len(fs), shared, ''.join(bullets)))

        for f in fs:
            m = info[f]
            code = m['code']
            vd = vardic.get(code) or vardic.get(re.sub(r'[A-Z]$', '', code)) or {}
            keytag = '+'.join(m['key'])
            unica = '✓ única' if m['unica'] else '✗ NO única'
            tags = ('<span class="tag">%s</span><span class="tag key">%s — %s</span>'
                    '<span class="tag">%s filas</span><span class="tag">%s cols</span>'
                    % (esc(m['unidad']), esc(keytag), unica, '{:,}'.format(m['nrows']), m['ncols']))
            try:
                tabla, cols = preview(os.path.join(md, f), m['delim'])
            except Exception as e:
                tabla, cols = ('<p class="note">No se pudo generar la vista previa: %s</p>' % esc(e), [])
            con = sum(1 for c in cols if vd.get(c))
            rows = []
            for c in cols:
                lab = vd.get(c)
                if lab:
                    rows.append('<tr><td class="v">%s</td><td>%s</td></tr>' % (esc(c), esc(lab)))
                else:
                    rows.append('<tr><td class="v">%s</td><td class="nolab">(sin etiqueta en el diccionario)</td></tr>' % esc(c))
            dict_html = ('<details class="dict"><summary>Diccionario de variables (%d/%d con etiqueta)</summary>'
                         '<div class="dictwrap"><table class="dict"><tr><th>Variable</th><th>Significado</th></tr>%s</table></div>'
                         '</details>' % (con, len(cols), ''.join(rows)))
            info_line = ('<div class="info">%s &middot; delimitador <code>%s</code> &middot; '
                         'mostrando %d de %s filas</div>' % (esc(m['title']), esc(m['delim']), PREVIEW_ROWS, '{:,}'.format(m['nrows'])))
            detalle = render_detalle(m, year)
            search = esc((f + ' ' + m['title'] + ' ' + keytag).lower())
            P.append('<details class="fileblock" data-search="%s"><summary><span class="fname">%s</span>%s</summary>'
                     '<div class="body">%s%s%s<div class="tablewrap">%s</div>'
                     '<div class="note">Vista previa (solo lectura). Análisis completo con pandas: '
                     '<code>pd.read_csv(r"%s", sep="%s", encoding="latin-1")</code></div></div></details>'
                     % (search, esc(f), tags, info_line, detalle, dict_html, tabla, esc(os.path.join(md, f)), esc(m['delim'])))

    P.append('<script>%s</script></div></body></html>' % JS)
    out = os.path.join(ydir, 'documentacion_enaho_año%s.html' % year)
    with open(out, 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(P))
    return out, len(files)


if __name__ == '__main__':
    for base, year, ydir in find_year_dirs():
        out, n = build_html(base, year, ydir)
        print('HTML:', out, '| archivos:', n)
