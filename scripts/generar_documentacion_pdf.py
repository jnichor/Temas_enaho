import os, re, glob, datetime
import polars as pl
import pdfplumber
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
                                HRFlowable, PageBreak, KeepTogether)

HHKEYS = ["CONGLOME", "VIVIENDA", "HOGAR"]
ADMIN_EXACT = {"MES", "UBIGEO", "DOMINIO", "ESTRATO", "NCONGLOME", "SUB_CONGLOME",
               "PERIODO", "CODINFOR"} | set(HHKEYS) | {"CODPERSO"}

NAVY = colors.HexColor('#1f3a5f')
ACCENT = colors.HexColor('#2e7d8c')
PURPLE = colors.HexColor('#6d4c91')
LIGHT = colors.HexColor('#eef2f6')
ZEBRA = colors.HexColor('#f6f8fa')
GREY = colors.HexColor('#5b6670')
USABLE = A4[0] - 3.6 * cm   # ancho util con margenes


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
    t = re.sub(r'\s*\.\s*\d+\s*$', '', t)        # ". 103"
    t = re.sub(r'\(\s+', '(', t)                 # "( texto" -> "(texto"
    t = re.sub(r'\s+\)', ')', t)                 # "texto )" -> "texto)"
    t = re.sub(r'\(\s*\)', '', t)                # parentesis vacios
    if t.count('(') != t.count(')'):             # parentesis desbalanceados -> quitar todos
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


def parse_diccionario(docs_dir):
    titles = {}
    dics = sorted(glob.glob(os.path.join(docs_dir, "*Diccionario*.pdf")))
    if not dics:
        return titles, None
    dic = dics[0]
    with pdfplumber.open(dic) as pdf:
        text = "\n".join((p.extract_text() or "") for p in pdf.pages)
    pat = re.compile(r'ENAHO\d+\w?-\d{4}-([0-9A-Za-z\-]+?)(?:\.SAV)?\s*[:.]\s*(.+)', re.I)
    for l in text.splitlines():
        m = pat.search(l)
        if not m:
            continue
        code = m.group(1).upper().strip('.')
        title = m.group(2)
        title = re.sub(r'^SAV\s+', '', title, flags=re.I)
        title = re.sub(r'\.{2,}.*$', '', title)
        title = re.sub(r'\(M[OÓ]DULO.*$', '', title, flags=re.I).strip()
        if len(title) > 4 and (code not in titles or len(title) > len(titles[code])):
            titles[code] = title
    return titles, os.path.basename(dic)


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
        return 'persona x registro' if extra else 'persona'
    if extra:
        return 'hogar x registro/item'
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
    df = pl.read_csv(path, separator=delim, infer_schema_length=0,
                     encoding='utf8-lossy', truncate_ragged_lines=True)
    df.columns = [c.strip().upper() for c in df.columns]
    cols = df.columns
    n = df.height
    base = [k for k in HHKEYS + ['CODPERSO'] if k in cols]
    nuniq = lambda ks: df.select(ks).n_unique()

    if base and nuniq(base) == n:
        extra = []
    elif base:
        card = {c: df.select(pl.col(c).n_unique()).item() for c in cols if c not in base}
        pool = [c for c in card if card[c] < 0.5 * n]
        extra = _maxgain(base, pool, n, nuniq)
        if nuniq(base + extra) != n:
            extra = _maxgain(base, list(card), n, nuniq, budget=10)
        changed = True
        while changed:
            changed = False
            for c in list(extra):
                if nuniq(base + [x for x in extra if x != c]) == n:
                    extra.remove(c)
                    changed = True
    else:
        extra = []

    key = base + extra
    unica = bool(key) and nuniq(key) == n
    hh = [k for k in HHKEYS if k in cols]
    nhog = nuniq(hh) if len(hh) == 3 else None
    npers = nuniq(hh + ['CODPERSO']) if (nhog and 'CODPERSO' in cols) else None
    return {'delim': delim, 'ncols': len(cols), 'nrows': n, 'key': key,
            'unica': unica, 'extra': extra, 'unidad': derive_unidad(key),
            'cols': list(cols), 'nhog': nhog, 'npers': npers}


def diferencias_grupo(fs, info, max_vars=12):
    union_otros = {}
    for f in fs:
        otros = set()
        for g in fs:
            if g != f:
                otros |= set(info[g]['cols'])
        union_otros[f] = otros
    max_hog = max((info[f]['nhog'] or 0) for f in fs)
    fichas = []
    for f in fs:
        m = info[f]
        base_unit = m['npers'] if m['npers'] else m['nhog']
        gran = (m['nrows'] / base_unit) if base_unit else None
        if gran is None:
            nivel = 'estructura no estandar'
        elif gran <= 1.05:
            nivel = '1 fila por %s (resumen)' % ('persona' if m['npers'] else 'hogar')
        else:
            disc = m['extra'][-1] if m['extra'] else '?'
            nivel = '%.0f filas por %s (detalle; una por %s)' % (
                gran, 'persona' if m['npers'] else 'hogar', disc)
        propias = [c for c in m['cols'] if c not in union_otros[f] and not is_admin(c)]
        cobertura = m['nhog'] or 0
        fichas.append({'file': f, 'title': clean_title(m['title']), 'nivel': nivel,
                       'cobertura': cobertura, 'sub': cobertura < max_hog,
                       'propias': propias, 'max_vars': max_vars})
    comun = set.intersection(*[set(info[f]['key']) for f in fs]) if fs else set()
    comun_ord = [k for k in HHKEYS + ['CODPERSO'] if k in comun]
    return fichas, comun_ord


def build_pdf(base, year, ydir):
    md = os.path.join(ydir, 'modulos')
    docs = os.path.join(base, 'microodatos_inei', 'enaho', '2_organized', 'documentation')
    titles, dic = parse_diccionario(docs)
    files = sorted(f for f in os.listdir(md) if f.lower().endswith('.csv'))
    groups, info = {}, {}
    for f in files:
        pre = f.split('_')[0]
        groups.setdefault(pre, []).append(f)
        code = code_from_filename(f)
        meta = inspect(os.path.join(md, f))
        raw = titles.get(code) or titles.get(re.sub(r'[A-Z]$', '', code))
        meta['title'] = clean_title(raw) if raw else '(titulo no verificado)'
        meta['code'] = code
        info[f] = meta

    st = getSampleStyleSheet()
    title_st = ParagraphStyle('t', parent=st['Title'], textColor=NAVY, fontSize=24, leading=28)
    sub_st = ParagraphStyle('sub', parent=st['BodyText'], textColor=GREY, fontSize=10, leading=14)
    h2 = ParagraphStyle('h2', parent=st['Heading2'], textColor=NAVY, fontSize=14, spaceBefore=6, spaceAfter=2)
    small = ParagraphStyle('s', parent=st['BodyText'], fontSize=8, leading=10)
    cell = ParagraphStyle('c', parent=st['BodyText'], fontSize=7.2, leading=8.6)
    cellb = ParagraphStyle('cb', parent=cell, textColor=NAVY)
    whitehead = ParagraphStyle('wh', parent=st['BodyText'], fontSize=10, textColor=colors.white, leading=12)
    note = ParagraphStyle('n', parent=small, textColor=GREY)

    def band(text, color):
        tb = Table([[Paragraph('<b>%s</b>' % text, whitehead)]], colWidths=[USABLE])
        tb.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, -1), color),
                                ('LEFTPADDING', (0, 0), (-1, -1), 8),
                                ('TOPPADDING', (0, 0), (-1, -1), 5),
                                ('BOTTOMPADDING', (0, 0), (-1, -1), 5)]))
        return tb

    el = []
    # ---------- PORTADA ----------
    el += [Spacer(1, 4 * cm),
           Paragraph('Documentación ENAHO', title_st),
           Paragraph('Encuesta Nacional de Hogares &mdash; Año %s' % year, ParagraphStyle('y', parent=sub_st, fontSize=16, textColor=ACCENT)),
           Spacer(1, 0.6 * cm),
           HRFlowable(width=USABLE, thickness=1.2, color=ACCENT),
           Spacer(1, 0.5 * cm),
           Paragraph('Catálogo de los %d archivos de microdatos: de qué trata cada módulo, su unidad de '
                     'análisis y su <b>unidad de identificación verificada</b> (la llave mínima que identifica '
                     'una fila única). Incluye las diferencias, variable por variable, entre archivos de un mismo módulo.'
                     % len(files), sub_st),
           Spacer(1, 0.8 * cm),
           Paragraph('<b>Fuente de los títulos:</b> %s (diccionario oficial INEI)' % (dic or 'NO ENCONTRADO'), small),
           Paragraph('<b>Carpeta:</b> %s' % base, small),
           Paragraph('<b>Generado:</b> %s' % datetime.datetime.now().strftime('%Y-%m-%d'), small),
           PageBreak()]

    # ---------- RESUMEN ----------
    el += [Paragraph('Resumen de módulos', h2),
           HRFlowable(width=USABLE, thickness=0.8, color=ACCENT), Spacer(1, 6)]
    data = [['Mód.', 'Cód.', 'Título oficial', 'Unidad de análisis', 'Llave de identificación', 'Filas']]
    for pre in sorted(groups):
        for f in groups[pre]:
            m = info[f]
            llave = '+'.join(m['key']) + ('' if m['unica'] else '  (NO única)')
            data.append([pre, Paragraph(m['code'], cell), Paragraph(m['title'], cell),
                         Paragraph(m['unidad'], cell), Paragraph(llave, cellb),
                         '{:,}'.format(m['nrows'])])
    t = Table(data, colWidths=[32, 60, 162, 76, 112, 48], repeatRows=1)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), NAVY), ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTSIZE', (0, 0), (-1, 0), 8), ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 1), (-1, -1), 7.2),
        ('ALIGN', (5, 0), (5, -1), 'RIGHT'), ('ALIGN', (0, 0), (1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, ZEBRA]),
        ('LINEBELOW', (0, 0), (-1, 0), 0.6, NAVY),
        ('LINEBELOW', (0, 1), (-1, -1), 0.25, colors.HexColor('#d7dee5')),
        ('TOPPADDING', (0, 0), (-1, -1), 3), ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('LEFTPADDING', (0, 0), (-1, -1), 5),
    ]))
    el += [t, PageBreak()]

    # ---------- DETALLE ----------
    el += [Paragraph('Detalle por módulo', h2),
           HRFlowable(width=USABLE, thickness=0.8, color=ACCENT), Spacer(1, 6)]
    for pre in sorted(groups):
        fs = groups[pre]
        bloque = [band('Módulo %s  ·  %s' % (pre, info[fs[0]]['title']), NAVY), Spacer(1, 3)]
        for f in fs:
            m = info[f]
            ok = '<font color="#2e7d32">única ✓</font>' if m['unica'] else '<font color="#c62828">NO única ✗</font>'
            txt = ('<b>%s</b> &nbsp;<font color="#5b6670">(%s)</font><br/>'
                   'Unidad de análisis: <b>%s</b> &nbsp;|&nbsp; Identificación: <b>%s</b> &mdash; %s<br/>'
                   '<font color="#5b6670">%s filas &middot; %s columnas &middot; delimitador \'%s\'</font>' % (
                       m['code'], m['title'], m['unidad'], '+'.join(m['key']), ok,
                       '{:,}'.format(m['nrows']), m['ncols'], m['delim']))
            bloque += [Paragraph(txt, small), Spacer(1, 5)]
        el += [KeepTogether(bloque), Spacer(1, 6)]

    # ---------- DIFERENCIAS ----------
    multi = {p: fs for p, fs in groups.items() if len(fs) > 1}
    if multi:
        el += [PageBreak(), Paragraph('Diferencias entre archivos del mismo módulo', h2),
               HRFlowable(width=USABLE, thickness=0.8, color=PURPLE), Spacer(1, 4),
               Paragraph('Archivos que comparten prefijo parecen el mismo módulo, pero NO son iguales. '
                         'Para cada uno: en qué consiste, a cuántos hogares cubre y sus <b>variables propias</b> '
                         '(columnas que solo aparecen en ese archivo). Esas variables son la evidencia de en qué se diferencian.',
                         note), Spacer(1, 8)]
        for pre in sorted(multi):
            fichas, comun = diferencias_grupo(multi[pre], info)
            bloque = [band('Módulo %s' % pre, PURPLE), Spacer(1, 3)]
            if comun:
                bloque.append(Paragraph('Todos comparten <b>%s</b>. Lo que cambia entre archivos:' % '+'.join(comun), small))
                bloque.append(Spacer(1, 3))
            for fi in fichas:
                cov = '{:,}'.format(fi['cobertura']) + ' hogares' + (
                    ' <font color="#c62828">(subconjunto, no todos)</font>' if fi['sub'] else ' (todos)')
                if fi['propias']:
                    vs = fi['propias'][:fi['max_vars']]
                    extra = len(fi['propias']) - len(vs)
                    vstr = ', '.join(vs) + (' &hellip; (+%d más)' % extra if extra > 0 else '')
                    vline = 'Variables propias: <b>%s</b>' % vstr
                else:
                    vline = '<i>Sin variables propias: sus columnas también están en otro archivo del grupo.</i>'
                txt = ('<b>%s</b> &nbsp;<font color="#5b6670">%s</font><br/>'
                       '%s &middot; cubre %s<br/>%s' % (fi['code'] if False else code_from_filename(fi['file']),
                                                        fi['title'], fi['nivel'], cov, vline))
                bloque += [Paragraph(txt, small), Spacer(1, 5)]
            el += [KeepTogether(bloque), Spacer(1, 8)]

    # ---------- pie de pagina ----------
    def footer(canvas, d):
        canvas.saveState()
        canvas.setFont('Helvetica', 7)
        canvas.setFillColor(GREY)
        canvas.drawString(1.8 * cm, 1.1 * cm, 'Documentación ENAHO %s' % year)
        canvas.drawRightString(A4[0] - 1.8 * cm, 1.1 * cm, 'Página %d' % d.page)
        canvas.setStrokeColor(colors.HexColor('#d7dee5'))
        canvas.line(1.8 * cm, 1.4 * cm, A4[0] - 1.8 * cm, 1.4 * cm)
        canvas.restoreState()

    sal = os.path.join('salidas', str(year))
    os.makedirs(sal, exist_ok=True)
    out = os.path.join(sal, 'documentacion_enaho_%s.pdf' % year)
    doc = SimpleDocTemplate(out, pagesize=A4, title='Documentación ENAHO %s' % year,
                            leftMargin=1.8 * cm, rightMargin=1.8 * cm,
                            topMargin=1.6 * cm, bottomMargin=1.8 * cm)
    doc.build(el, onFirstPage=footer, onLaterPages=footer)
    return out, len(files), list(multi.keys())


if __name__ == '__main__':
    for base, year, ydir in find_year_dirs():
        out, n, multi = build_pdf(base, year, ydir)
        print('PDF:', out, '| archivos:', n, '| variantes:', multi)
