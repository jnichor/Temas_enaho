# -*- coding: utf-8 -*-
"""
Sistema inteligente ENAHO — TUI
Identificación y propuesta de temas de investigación económicos a partir de la
Encuesta Nacional de Hogares.

Pasos 1–4 (SISTEMA, deterministas): scripts locales, sin IA.
Pasos 5–10 (razonamiento): corren con tu SUSCRIPCIÓN de Claude (claude -p headless),
                           anclados al catálogo real de datos. Sin API key.

Uso:  python sistema_enaho.py
"""
import os
import re
import sys
import glob
import json
import subprocess

from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.prompt import Prompt
from rich.columns import Columns
from rich.align import Align
from rich.text import Text
from rich import box

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import razonador as RZ  # noqa: E402
import estadistica as EST  # noqa: E402

console = Console()
PYENV = {**os.environ, 'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8'}
TEMAS_DIR = os.path.join(ROOT, 'temas')

PASOS = [
    ('1', 'Descargar la data (ENAHO)', 'sistema', True),
    ('2', 'Organizar la data (módulos / tablas / diccionarios)', 'sistema', True),
    ('3', 'Inspección (nivel de análisis y de identificación)', 'sistema', True),
    ('4', 'Documentación de los módulos (PDF + visor HTML)', 'sistema', True),
    ('5', 'Sugerencia de temas económicos', 'usuario', True),
    ('6', 'Análisis de los módulos asociados al tema', 'usuario', True),
    ('7', 'Selección de variables', 'usuario', True),
    ('8', 'Identificación de brechas o anomalías', 'sistema', True),
    ('9', 'Contraste con literatura y antecedentes', 'sistema', True),
    ('10', 'Puntuación (impacto, relevancia, factibilidad)', 'sistema', True),
]
LANE = {'sistema': 'cyan', 'usuario': 'yellow'}


# ---------------- estado / utilidades ----------------
def carpetas_enaho():
    return sorted(d for d in glob.glob('enaho_*') if os.path.isdir(d))


def estado_carpeta(base):
    by = os.path.join(base, 'microodatos_inei', 'enaho', '2_organized', 'by_year')
    años, org, doc, cat = [], False, False, False
    if os.path.isdir(by):
        for y in sorted(os.listdir(by)):
            yd = os.path.join(by, y)
            if not os.path.isdir(yd):
                continue
            años.append(y)
            if os.path.isdir(os.path.join(yd, 'modulos')):
                org = True
            if glob.glob(os.path.join(yd, '*.pdf')) or glob.glob(os.path.join(yd, '*.html')):
                doc = True
            if glob.glob(os.path.join(yd, 'catalogo_*.json')):
                cat = True
    return años, org, doc, cat


def slug(s):
    s = re.sub(r'[^a-zA-Z0-9]+', '-', s.lower()).strip('-')
    return s[:60] or 'tema'


def run_script(args, titulo):
    console.rule(f"[bold]{titulo}")
    try:
        proc = subprocess.Popen([sys.executable, *args], cwd=ROOT, env=PYENV,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, encoding='utf-8', errors='replace', bufsize=1)
        for line in proc.stdout:
            console.print("  " + line.rstrip())
        proc.wait()
        ok = proc.returncode == 0
        console.print(f"[green]✓ {titulo} — completado[/]" if ok
                      else f"[red]✗ {titulo} — código {proc.returncode}[/]")
        return ok
    except Exception as e:
        console.print(f"[red]Error: {e}[/]")
        return False


# ---------------- UI ----------------
CYAN = "#2ec4d6"
GOLD = "#f0b429"
GREEN = "#3ddc84"
# fondos (look dashboard oscuro)
BG_HEAD = "#0f2a43"
BG_SYS = "#0d2530"
BG_USR = "#2a2510"
BG_BAR = "#15324d"
BG_STAT = "#0c1a26"


def _estado_global():
    cs = carpetas_enaho()
    años, org, doc, cat = set(), False, False, False
    for c in cs:
        a, o, d, k = estado_carpeta(c)
        años |= set(a); org |= o; doc |= d; cat |= k
    return cs, sorted(años), org, doc, cat


def header():
    titulo = Text("◆  S I S T E M A   I N T E L I G E N T E   E N A H O  ◆", style=f"bold {CYAN}")
    sub = Text("De los microdatos de la Encuesta Nacional de Hogares a un tema de investigación económico",
               style="italic grey78")
    console.print(Panel(Align.center(Group(titulo, Text(""), sub)),
                        border_style=CYAN, box=box.DOUBLE, padding=(1, 2), style=f"on {BG_HEAD}"))


def _carril(num_titulo, color, items, bg):
    tb = Table(box=None, show_header=False, pad_edge=False, expand=True)
    tb.add_column(justify="right", width=3)
    tb.add_column(ratio=1)
    for num, nombre, done in items:
        if done is True:
            mk, st = f"[bold {GREEN}]✓[/]", f"[{GREEN}]{nombre}[/]"
        elif done is False:
            mk, st = f"[grey54]{num}[/]", f"[grey54]{nombre}[/]"
        else:
            mk, st = f"[bold {color}]{num}[/]", f"[white]{nombre}[/]"
        tb.add_row(mk, st)
    return Panel(tb, title=f"[bold white on {color}] {num_titulo} [/]", border_style=color,
                 box=box.ROUNDED, padding=(1, 1), style=f"on {bg}")


def pipeline():
    cs, años, org, doc, cat = _estado_global()
    l1 = [('1', 'Descargar data', bool(cs)), ('2', 'Organizar', org),
          ('3', 'Inspección', cat), ('4', 'Documentar (PDF+HTML)', doc)]
    l2 = [('5', 'Sugerir temas', None), ('6', 'Analizar módulos', None),
          ('7', 'Selección de variables', None)]
    l3 = [('8', 'Brechas / anomalías', None), ('9', 'Literatura (web)', None),
          ('10', 'Puntuación', None), ('▸', 'Ficha de investigación', None)]
    console.print(Columns([
        _carril('① SISTEMA · Preparación', CYAN, l1, BG_SYS),
        _carril('② USUARIO · Exploración', GOLD, l2, BG_USR),
        _carril('③ SISTEMA · Evaluación', CYAN, l3, BG_SYS),
    ], equal=True, expand=True))


def barra_estado():
    cs, años, org, doc, cat = _estado_global()
    if not cs:
        console.print(Panel(Align.center("[grey70]Sin datos aún — empieza por[/] [bold white]1[/] [grey70]Descargar[/]"),
                            box=box.SIMPLE, style=f"on {BG_STAT}", border_style="grey30"))
        return
    ok = lambda b: f"[bold {GREEN}]✓[/]" if b else "[bold red]✗[/]"
    console.print(Panel(Align.center(
        f"[grey70]Datos[/] [white]{', '.join(cs)}[/]   [grey50]·[/]   [grey70]años[/] [white]{', '.join(años)}[/]   "
        f"[grey50]·[/]   organizado {ok(org)}   documentado {ok(doc)}   catálogo {ok(cat)}"),
        box=box.SIMPLE, style=f"on {BG_STAT}", border_style="grey30"))


def barra_acciones():
    txt = (f"[white]1[/] descargar     [white]2[/] organizar     [white]3[/] documentar     "
           f"[bold black on {GOLD}] 5 ▶ PROPONER TEMA (5–10) [/]     [white]c[/] catálogo     [white]q[/] salir")
    console.print(Panel(Align.center(txt), box=box.HEAVY, border_style=CYAN,
                        style=f"on {BG_BAR}", padding=(0, 1)))


# ---------------- pasos 1–4 ----------------
def paso_descargar():
    raw = Prompt.ask("[bold]Año(s) a descargar[/] (ej. 2024 · 2015-2020 · 2018 2019)")
    if raw.strip():
        run_script(['scripts/descargar.py'] + raw.split(), "Paso 1 · Descargar ENAHO")
        run_script(['scripts/ordenar.py'], "Paso 2 · Organizar data")


def paso_documentar():
    run_script(['scripts/generar_documentacion_pdf.py'], "Paso 3–4 · Documentación PDF")
    run_script(['scripts/generar_visor_html.py'], "Paso 4 · Visor HTML interactivo")
    run_script(['scripts/catalogo.py'], "Catálogo de grounding (para pasos 5–10)")


def regenerar_catalogo():
    run_script(['scripts/catalogo.py'], "Catálogo de grounding")


# ---------------- pasos 5–10 (IA, suscripción) ----------------
def _pensando(msg, fn):
    with console.status(f"[cyan]{msg}…[/]", spinner="dots"):
        return fn()


def elegir_año():
    años = RZ.años_disponibles()
    if not años:
        console.print("[yellow]No hay catálogo. Genera primero la documentación (opción 3) o el catálogo (c).[/]")
        return None
    if len(años) == 1:
        return años[0]
    return Prompt.ask("Año a usar", choices=años, default=años[-1])


def flujo_investigacion():
    year = elegir_año()
    if not year:
        return
    cat = RZ.load_catalogo(year)
    if not cat:
        console.print("[red]No se pudo cargar el catálogo.[/]")
        return

    # PASO 5
    modo = Prompt.ask("Opción [bold]A[/]=tú das el área (+ contexto opcional) · "
                      "[bold]B[/]=el sistema propone 3 áreas al azar",
                      choices=["A", "B", "a", "b"], default="A").upper()
    contexto = None
    try:
        if modo == "A":
            area = Prompt.ask("Área temática (ej. pobreza, empleo, educación, género)")
            contexto = Prompt.ask("Variables o contexto a considerar [dim](opcional, Enter para omitir)[/]",
                                  default="") or None
        else:
            areas = _pensando("Paso 5 · Proponiendo 3 áreas al azar", lambda: RZ.sugerir_areas(cat, 3))
            ta = Table(title="Paso 5 · Áreas temáticas propuestas", box=box.ROUNDED, show_lines=True)
            ta.add_column("#", style="bold"); ta.add_column("Área"); ta.add_column("Descripción", style="dim")
            for i, a in enumerate(areas, 1):
                ta.add_row(str(i), a.get('area', ''), a.get('descripcion', ''))
            console.print(ta)
            ia = Prompt.ask("Elige un área", choices=[str(i) for i in range(1, len(areas) + 1)], default="1")
            area = areas[int(ia) - 1].get('area')
        temas = _pensando("Paso 5 · Sugiriendo temas", lambda: RZ.sugerir_temas(cat, area, contexto, n=4))
    except Exception as e:
        console.print(f"[red]Falló el paso 5: {e}[/]")
        return
    t = Table(title="Paso 5 · Temas sugeridos", box=box.ROUNDED, show_lines=True)
    t.add_column("#", style="bold"); t.add_column("Tema"); t.add_column("Pregunta de investigación", style="dim")
    for i, tm in enumerate(temas, 1):
        t.add_row(str(i), tm.get('tema', ''), tm.get('pregunta_investigacion', ''))
    console.print(t)
    idx = Prompt.ask("Elige un tema", choices=[str(i) for i in range(1, len(temas) + 1)], default="1")
    tema = temas[int(idx) - 1]
    console.print(Panel(f"[bold]{tema.get('tema')}[/]\n[dim]{tema.get('justificacion','')}[/]\n"
                        f"Módulos: {', '.join(map(str, tema.get('modulos', [])))}", border_style="yellow"))

    if Prompt.ask("¿Continuar con el análisis (pasos 6–10)?", choices=["s", "n"], default="s") != "s":
        return

    # PASOS 6–10
    pasos = [
        ("Paso 6 · Análisis de módulos", lambda: RZ.analizar_tema(cat, tema), 'analisis'),
        ("Paso 7 · Selección de variables", lambda: RZ.seleccionar_variables(cat, tema), 'manifiesto'),
    ]
    res = {'tema': tema, 'anio': year}
    for titulo, fn, clave in pasos:
        try:
            res[clave] = _pensando(titulo, fn)
        except Exception as e:
            console.print(f"[red]Falló {titulo}: {e}[/]")
            return
        _mostrar(titulo, res[clave])

    # PLAN DE DATOS (filtros + merge) — cómo combinar la data
    try:
        res['filtros'] = _pensando("Plan de datos · filtros", lambda: RZ.sugerir_filtros(cat, tema, res['manifiesto']))
    except Exception:
        res['filtros'] = []
    res['plan_datos'] = RZ.plan_de_datos(cat, tema, res['manifiesto'], res['filtros'])
    _mostrar_plan_datos(res['plan_datos'])
    try:
        res['consolidacion'] = _pensando("Plan de datos · verificando consolidación",
                                         lambda: EST.revisar_consolidacion(cat, res['manifiesto'], year))
        _mostrar_consolidacion(res['consolidacion'])
    except Exception as e:
        console.print(f"[dim]Consolidación no verificada: {e}[/]")

    try:
        plan = _pensando("Paso 8 · Planificando brechas", lambda: RZ.plan_brechas(cat, tema, res['manifiesto']))
        res['plan_brechas'] = plan
        resultados = _pensando("Paso 8 · Calculando con pandas (datos reales)",
                               lambda: EST.calcular(plan, year))
        res['brechas_calculadas'] = resultados
        _mostrar_brechas(resultados)
        res['interpretacion'] = _pensando("Paso 8 · Interpretando los números",
                                          lambda: RZ.interpretar_brechas(tema, resultados))
        _mostrar("Paso 8 · Interpretación (sobre datos reales)", res['interpretacion'])
        res['literatura'] = _pensando("Paso 9 · Contraste con literatura",
                                      lambda: RZ.contraste_literatura(tema, res['interpretacion']))
        _mostrar("Paso 9 · Literatura y antecedentes", res['literatura'])
        res['puntuacion'] = _pensando("Paso 10 · Puntuación",
                                      lambda: RZ.puntuar(tema, res['interpretacion'], res['literatura'], res.get('analisis', {})))
    except Exception as e:
        console.print(f"[red]Falló un paso de razonamiento: {e}[/]")
    else:
        _panel_final(res['puntuacion'], tema)

    # guardar artefactos
    d = os.path.join(TEMAS_DIR, slug(tema.get('tema', 'tema')))
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, 'propuesta.json'), 'w', encoding='utf-8') as fh:
        json.dump(res, fh, ensure_ascii=False, indent=2)
    _ficha_final(res)
    console.print(f"[green]Propuesta guardada en[/] {os.path.relpath(d, ROOT)}/propuesta.json")


def _mostrar_brechas(resultados):
    for r in resultados:
        if r.get('error'):
            console.print(f"[red]• {r.get('brecha')}: no calculable ({r['error']})[/]")
            continue
        t = Table(title=f"{r.get('brecha')}  [dim]({r.get('estadistico')} de {r.get('outcome')} por {r.get('grupo')})[/]",
                  box=box.SIMPLE, title_style="bold cyan")
        t.add_column("Grupo"); t.add_column("Valor", justify="right"); t.add_column("n", justify="right")
        for g in r.get('grupos', []):
            t.add_row(g['etiqueta'], f"{g['valor']:,.2f}", f"{g['n']:,}")
        console.print(t)
        if 'brecha_relativa_pct' in r:
            console.print(f"  [bold]Brecha:[/] {r['brecha_absoluta']:,.2f} "
                          f"([bold]{r['brecha_relativa_pct']}%[/] relativa)\n")


def _mostrar(titulo, data):
    if isinstance(data, list):
        console.print(Panel(_json_corto(data), title=titulo, border_style="cyan"))
    else:
        body = "\n".join(f"[bold]{k}:[/] {v}" for k, v in data.items())
        console.print(Panel(body, title=titulo, border_style="cyan"))


def _json_corto(data):
    out = []
    for it in data:
        if isinstance(it, dict):
            out.append(" · ".join(f"{k}: {v}" for k, v in list(it.items())[:3]))
        else:
            out.append(str(it))
    return "\n".join("• " + x for x in out)


def _panel_final(p, tema):
    tot = p.get('puntaje_total', '?')
    body = (f"[bold yellow]{tema.get('tema')}[/]\n\n"
            f"Impacto social: {p.get('impacto_social', {}).get('puntaje')}  ·  "
            f"Relevancia: {p.get('relevancia_actual', {}).get('puntaje')}  ·  "
            f"Factibilidad: {p.get('factibilidad_datos', {}).get('puntaje')}  ·  "
            f"Originalidad: {p.get('originalidad', {}).get('puntaje')}\n"
            f"[bold]Puntaje total: {tot}[/]\n\n{p.get('veredicto', '')}")
    console.print(Panel(body, title="Paso 10 · Tema de investigación puntuado",
                        border_style="green", box=box.DOUBLE))


def _mostrar_plan_datos(plan):
    b = [f"[bold]Nivel de análisis:[/] {plan['nivel_de_analisis']}  ·  "
         f"[bold]Llaves de merge:[/] {'+'.join(plan['llaves_merge'])}",
         f"[bold]Archivo base:[/] {plan.get('archivo_base')}",
         "[bold]Secuencia de merge:[/]"]
    for p in plan['secuencia_merge']:
        b.append(f"  • [{p['tipo']}] {p['archivo']} ← join por {'+'.join(p['llaves_join'])} ({len(p['variables'])} vars)")
    if plan.get('filtros'):
        b.append("[bold]Filtros de población:[/]")
        for f in plan['filtros']:
            b.append(f"  • {f.get('variable')}: {f.get('condicion')} [dim]({f.get('motivo','')})[/]")
    else:
        b.append("[dim]Sin filtros (toda la población).[/]")
    console.print(Panel("\n".join(b), title="Plan de datos · merge y filtro", border_style="magenta"))


def _mostrar_consolidacion(rep):
    if not rep or not rep.get('modulos'):
        return
    b = ["[bold]Principio:[/] cada variable desde su módulo de origen; se avisa solo lo verificado."]
    for m in rep['modulos']:
        b.append(f"[bold]{m['modulo']}[/]")
        if m['redundantes_identicas']:
            vs = ', '.join(f"{r['var']} ({r['match_pct']}%)" for r in m['redundantes_identicas'])
            b.append(f"  [green]• duplicadas e idénticas al base:[/] {vs}")
        if m['difieren']:
            vs = ', '.join(f"{d['var']} ({d['match_pct']}%)" for d in m['difieren'])
            b.append(f"  [red]• DIFIEREN del base (usar fuente canónica, NO consolidar):[/] {vs}")
        if m['unicas_de_este_modulo']:
            b.append(f"  • aporta variables propias: {', '.join(m['unicas_de_este_modulo'])}")
        if m['consolidable']:
            b.append("  [yellow]→ merge consolidable[/] (no aporta nada único)")
            if m['nota_cobertura']:
                b.append(f"     [dim]{m['nota_cobertura']}[/]")
    console.print(Panel("\n".join(b), title="Consolidación de módulos (informada, tú decides)",
                        border_style="cyan"))


def _ficha_final(res):
    tema = res.get('tema', {})
    pds = res.get('plan_datos', {})
    p = res.get('puntuacion', {})
    manif = [v for v in res.get('manifiesto', []) if isinstance(v, dict)]
    vars_txt = "\n".join(f"  • {v.get('variable')} ({v.get('rol')}) — {v.get('archivo')}" for v in manif) or "  —"
    merge_txt = " → ".join(s['archivo'] for s in pds.get('secuencia_merge', []))
    filtros = ', '.join(f.get('condicion', '') for f in pds.get('filtros', [])) or 'ninguno'
    body = (f"[bold yellow]TEMA:[/] {tema.get('tema')}\n"
            f"[bold]Pregunta:[/] {tema.get('pregunta_investigacion', '')}\n\n"
            f"[bold]Módulos:[/] {', '.join(map(str, tema.get('modulos', [])))}\n"
            f"[bold]Variables a usar:[/]\n{vars_txt}\n\n"
            f"[bold]Merge:[/] nivel {pds.get('nivel_de_analisis')} por "
            f"{'+'.join(pds.get('llaves_merge', []))}\n  {merge_txt}\n"
            f"[bold]Filtros:[/] {filtros}\n\n"
            f"[bold]Puntaje:[/] {p.get('puntaje_total', '?')} — {p.get('veredicto', '')}")
    console.print(Panel(body, title="📋 FICHA DE INVESTIGACIÓN (entregable final)",
                        border_style="green", box=box.DOUBLE))


# ---------------- main ----------------
def main():
    os.chdir(ROOT)
    while True:
        console.clear()
        header()
        barra_estado()
        console.print()
        pipeline()
        console.print()
        barra_acciones()
        op = Prompt.ask(f"\n[bold {CYAN}]▶ Opción[/]", default="q").strip().lower()
        if op in ('q', 'quit', 'salir', '0'):
            console.print("[dim]Hasta luego.[/]")
            break
        elif op == '1':
            paso_descargar()
        elif op == '2':
            run_script(['scripts/ordenar.py'], "Paso 2 · Organizar data")
        elif op in ('3', '4'):
            paso_documentar()
        elif op in ('5', '6', '7', '8', '9', '10'):
            flujo_investigacion()
        elif op == 'c':
            regenerar_catalogo()
        else:
            console.print("[red]Opción no válida.[/]")
        if op != 'q':
            Prompt.ask("\n[dim]Enter para volver al menú[/]", default="")


if __name__ == '__main__':
    main()
