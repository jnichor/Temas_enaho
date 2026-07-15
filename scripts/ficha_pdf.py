# -*- coding: utf-8 -*-
"""Genera la FICHA DE INVESTIGACIÓN en PDF a partir del resultado del flujo 5–10.

Muestra: tema, módulos, VARIABLES (código + significado del diccionario ENAHO + rol),
plan de merge (con explicación y verificación), filtros, brechas medidas, diseño
causal (si existe), literatura y puntuación.
"""
import os
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable

NAVY = colors.HexColor('#1f3a5f')
ACCENT = colors.HexColor('#2e7d8c')
GOLD = colors.HexColor('#b8860b')
USABLE = A4[0] - 3.6 * cm


def _labels(cat):
    """{codigo_variable_upper: significado} desde el diccionario del catálogo."""
    lab = {}
    for m in cat.get('modulos', []):
        for k, v in (m.get('variables') or {}).items():
            if v and k.upper() not in lab:
                lab[k.upper()] = v
    return lab


def generar_ficha_pdf(res, cat, out_path):
    st = getSampleStyleSheet()
    h1 = ParagraphStyle('h1', parent=st['Title'], textColor=NAVY, fontSize=20, leading=24)
    h2 = ParagraphStyle('h2', parent=st['Heading2'], textColor=ACCENT, fontSize=13, spaceBefore=10, spaceAfter=3)
    body = ParagraphStyle('b', parent=st['BodyText'], fontSize=9.5, leading=13)
    small = ParagraphStyle('s', parent=st['BodyText'], fontSize=8, leading=10)
    cell = ParagraphStyle('c', parent=st['BodyText'], fontSize=7.6, leading=9.4)
    code = ParagraphStyle('code', parent=cell, fontName='Courier-Bold', textColor=NAVY)

    tema = res.get('tema') or {}
    pds = res.get('plan_datos') or {}
    p = res.get('puntuacion') or {}
    lab = _labels(cat)

    el = [Paragraph('Ficha de Investigación &mdash; ENAHO', h1),
          Paragraph('Año(s): %s' % res.get('anios', res.get('anio', '?')), body),
          Spacer(1, 4), HRFlowable(width=USABLE, thickness=1.2, color=ACCENT), Spacer(1, 8)]

    # Tema
    el += [Paragraph('Tema de investigación', h2),
           Paragraph('<b>%s</b>' % tema.get('tema', ''), body),
           Paragraph('<b>Pregunta:</b> %s' % tema.get('pregunta_investigacion', ''), body)]
    if tema.get('cobertura_anios'):
        el.append(Paragraph('<b>Años que cubre:</b> %s &nbsp; <i>(%s)</i>' %
                            (tema.get('cobertura_anios'), tema.get('motivo_cobertura', '')), body))

    # Diseño causal
    cau = res.get('causal') or {}
    if cau:
        el += [Paragraph('Diseño causal e identificación', h2)]
        esperado = tema.get('nivel_causal_esperado')
        real = cau.get('nivel_causal')
        rank = {'causal_fuerte': 0, 'causal_debil': 1, 'asociacion': 2}
        if esperado:
            linea = '<b>Solidez causal esperada (al proponer el tema):</b> %s' % esperado
            if tema.get('justificacion_causal'):
                linea += ' — %s' % tema['justificacion_causal']
            el.append(Paragraph(linea, small))
            if real and rank.get(real, 9) > rank.get(esperado, -1):
                el.append(Paragraph('<font color="#c62828">⚠ Al elegir las variables concretas, la estrategia '
                                    'real (%s) resultó menos sólida que lo esperado (%s).</font>' % (real, esperado), small))
        for k, lbl in [('pregunta_causal', 'Pregunta causal'), ('estrategia_identificacion', 'Estrategia de identificación'),
                       ('tratamiento', 'Tratamiento'), ('resultado', 'Variable resultado'),
                       ('controles', 'Controles'), ('supuestos', 'Supuestos clave'), ('amenazas', 'Amenazas a la validez')]:
            if cau.get(k):
                v = cau[k]
                v = ', '.join(v) if isinstance(v, list) else v
                el.append(Paragraph('<b>%s:</b> %s' % (lbl, v), small))

    # Variables (código + significado) — con aviso si no cubren todos los años
    parciales = {p['variable']: p for p in (res.get('variables_parciales') or [])}
    el += [Paragraph('Variables a utilizar (código y significado)', h2)]
    if parciales:
        el.append(Paragraph('⚠ Las variables marcadas NO existen en todos los años de cobertura; '
                            'esa parte del análisis queda limitada a los años indicados.', small))
    data = [['Código', 'Significado (diccionario ENAHO)', 'Rol', 'Módulo']]
    for v in res.get('manifiesto', []):
        if not isinstance(v, dict):
            continue
        cod = (v.get('variable') or '').upper()
        sig = lab.get(cod) or v.get('etiqueta') or '(sin etiqueta en diccionario)'
        if cod in parciales:
            p = parciales[cod]
            sig += ' — <font color="#c62828">⚠ solo años: %s</font>' % (
                ', '.join(p.get('anios_disponibles') or []) or '?')
        data.append([Paragraph(cod, code), Paragraph(sig, cell),
                     Paragraph(v.get('rol', ''), cell), Paragraph(str(v.get('archivo', '')), cell)])
    t = Table(data, colWidths=[70, 240, 70, 110], repeatRows=1)
    t.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, 0), NAVY), ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                           ('FONTSIZE', (0, 0), (-1, -1), 7.6), ('GRID', (0, 0), (-1, -1), 0.3, colors.grey),
                           ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                           ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f2f6f8')])]))
    el += [t]

    # Merge y filtros (con explicación + verificación)
    el += [Paragraph('Plan de datos: merge y filtros', h2)]
    el.append(Paragraph('<b>Nivel:</b> %s &nbsp;·&nbsp; <b>Llaves:</b> %s &nbsp;·&nbsp; <b>Base:</b> %s' %
                        (pds.get('nivel_de_analisis'), '+'.join(pds.get('llaves_merge', [])), pds.get('archivo_base')), small))
    for line in pds.get('explicacion', []):
        el.append(Paragraph('• %s' % line, small))
    for vm in res.get('verificacion_merge', []) or []:
        mark = '<font color="#2e7d32">✓</font>' if vm.get('ok') else '<font color="#c62828">⚠</font>'
        el.append(Paragraph('%s <b>%s</b>: %s' % (mark, vm.get('archivo'), vm.get('nota', '')), small))

    # Dataset final: el merge ejecutado de verdad (no solo el plan), con su QC
    de = res.get('dataset_export') or {}
    if de:
        _anio = lambda d: ' [%s]' % d['anio'] if d.get('anio') else ''
        el += [Paragraph('Dataset final (mergeado y limpio)', h2)]
        el.append(Paragraph('<b>%s</b> filas &times; <b>%s</b> columnas &nbsp;·&nbsp; duplicadas por llave: %s '
                            '&nbsp;·&nbsp; años: %s &nbsp;·&nbsp; archivo: %s' %
                            (de.get('filas'), len(de.get('columnas', [])), de.get('filas_duplicadas_por_llave'),
                             ', '.join(de.get('anios', [])), de.get('ruta')), small))
        for a_err in de.get('anios_con_error', []):
            el.append(Paragraph('<font color="#c62828">⚠ El año %s no se pudo materializar:</font> %s'
                                % (a_err['anio'], a_err['error']), small))
        for a in de.get('agregaciones', []):
            el.append(Paragraph('• %s.%s se agregó (%s) — el archivo original tenía varias filas por llave%s'
                                % (a['archivo'], a['variable'], a['funcion'], _anio(a)), small))
        for r in de.get('restricciones', []):
            el.append(Paragraph('• %s.%s se restringió a %s %s para aislar 1 fila por llave%s'
                                % (r['archivo'], r['variable'], r['restriccion']['variable'], r['restriccion']['condicion'], _anio(r)), small))
        for e in de.get('variables_excluidas', []):
            el.append(Paragraph('<font color="#c62828">⚠ %s.%s excluida del dataset:</font> %s%s'
                                % (e['archivo'], e['variable'], e['motivo'], _anio(e)), small))
        for f in de.get('filtros_omitidos', []):
            el.append(Paragraph('<font color="#c62828">⚠ Filtro NO aplicado (%s):</font> %s%s'
                                % (f['variable'], f['motivo'], _anio(f)), small))
        for fc in de.get('filtros_contradictorios', []):
            if fc.get('error'):
                continue
            combo = ' + '.join('%s %s' % (f['variable'], f['condicion']) for f in fc['filtros'])
            el.append(Paragraph('<font color="#c62828">⚠ Filtros contradictorios en %s (%s):</font> %s%s'
                                % (fc['archivo'], combo, fc['alerta'], _anio(fc)), small))
        for fb in de.get('filtros_baja_cobertura', []):
            if fb.get('error'):
                continue
            el.append(Paragraph('<font color="#c62828">⚠ %s.%s tiene solo %s%% de cobertura (%s/%s):</font> '
                                'posible pregunta condicional del cuestionario — revisa si colapsó la muestra%s'
                                % (fb['archivo'], fb['variable'], fb['cobertura_pct'], fb['con_dato'],
                                   fb['total_filas'], _anio(fb)), small))

    # Brechas medidas
    br = [b for b in (res.get('brechas') or []) if not b.get('error')]
    if br:
        el += [Paragraph('Brechas medidas (datos reales)', h2)]
        data = [['Brecha', 'Grupos (valor)', 'Brecha %']]
        for r in br:
            gs = '  '.join('%s=%s' % (g['etiqueta'], format(g['valor'], ',.0f')) for g in r.get('grupos', [])[:4])
            data.append([Paragraph(r.get('brecha', ''), cell), Paragraph(gs, cell),
                         Paragraph(str(r.get('brecha_relativa_pct', '—')), cell)])
        t = Table(data, colWidths=[200, 220, 70], repeatRows=1)
        t.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, 0), ACCENT), ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                               ('FONTSIZE', (0, 0), (-1, -1), 7.6), ('GRID', (0, 0), (-1, -1), 0.3, colors.grey),
                               ('VALIGN', (0, 0), (-1, -1), 'TOP')]))
        el += [t]

    # Evolución de brechas por año (si el tema cubre varios años)
    evo = res.get('brechas_por_anio') or {}
    if len(evo) > 1:
        el += [Paragraph('Evolución de brechas por año (brecha relativa %)', h2)]
        anios_e = sorted(evo)
        nombres = []
        for y in anios_e:
            for r in evo[y]:
                if r.get('brecha') and r['brecha'] not in nombres:
                    nombres.append(r['brecha'])
        data = [['Brecha'] + anios_e]
        for nom in nombres:
            fila = [Paragraph(nom, cell)]
            for y in anios_e:
                r = next((x for x in evo[y] if x.get('brecha') == nom), None)
                if r is None:
                    fila.append(Paragraph('—', cell))
                elif r.get('error'):
                    fila.append(Paragraph('no calculable', cell))
                else:
                    fila.append(Paragraph(str(r.get('brecha_relativa_pct', '—')), cell))
            data.append(fila)
        anchos = [220] + [int(270 / max(1, len(anios_e)))] * len(anios_e)
        t = Table(data, colWidths=anchos, repeatRows=1)
        t.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, 0), GOLD), ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                               ('FONTSIZE', (0, 0), (-1, -1), 7.6), ('GRID', (0, 0), (-1, -1), 0.3, colors.grey),
                               ('VALIGN', (0, 0), (-1, -1), 'TOP')]))
        el += [t]

    # Literatura
    lit = res.get('literatura') or {}
    if lit.get('referencias'):
        el += [Paragraph('Literatura y antecedentes', h2)]
        for r in lit['referencias'][:8]:
            el.append(Paragraph('• <b>%s</b> — %s' % (r.get('titulo', ''), r.get('url', '')), small))

    # Puntuación
    if p:
        el += [Paragraph('Puntuación', h2)]
        for k, lbl in [('impacto_social', 'Impacto social'), ('relevancia_actual', 'Relevancia actual'),
                       ('factibilidad_datos', 'Factibilidad de datos'), ('originalidad', 'Originalidad')]:
            d = p.get(k) or {}
            el.append(Paragraph('<b>%s:</b> %s — %s' % (lbl, d.get('puntaje', '?'), d.get('justificacion', '')), small))
        el.append(Spacer(1, 4))
        el.append(Paragraph('<b>Puntaje total: %s</b> &nbsp; %s' %
                            (p.get('puntaje_total', '?'), p.get('veredicto', '')), body))

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    doc = SimpleDocTemplate(out_path, pagesize=A4, title='Ficha de investigación ENAHO',
                            leftMargin=1.8 * cm, rightMargin=1.8 * cm, topMargin=1.6 * cm, bottomMargin=1.6 * cm)
    doc.build(el)
    return out_path
