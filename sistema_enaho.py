# -*- coding: utf-8 -*-
"""
Sistema inteligente ENAHO — TUI (Textual, full-screen)
Identificación y propuesta de temas de investigación económicos a partir de la
Encuesta Nacional de Hogares.

Pasos 1–4 (deterministas) + pasos 5–10 (razonamiento con tu suscripción de Claude).
Reusa toda la lógica de scripts/. Lanza con:  python sistema_enaho.py
"""
import os
import sys
import re
import json
import glob
import asyncio
import subprocess

from rich.panel import Panel
from rich.table import Table
from rich import box

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import (Header, Footer, Button, Static, RichLog, Input,
                             RadioSet, RadioButton, ListView, ListItem, Label, SelectionList)
from textual import work

ROOT = os.path.dirname(os.path.abspath(__file__))
# Los módulos de scripts/ (estadistica, ficha_pdf) y las salidas usan rutas
# RELATIVAS al proyecto: anclar el cwd para que funcione lanzado desde cualquier lugar.
os.chdir(ROOT)
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import razonador as RZ          # noqa: E402
import estadistica as EST       # noqa: E402
import ficha_pdf as FICHA       # noqa: E402

PYENV = {**os.environ, 'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8'}


# ----------------------------- estado de datos -----------------------------
def carpetas_enaho():
    return sorted(d for d in glob.glob(os.path.join(ROOT, 'enaho_*')) if os.path.isdir(d))


def estado_global():
    cs = [os.path.basename(c) for c in carpetas_enaho()]
    años, org, doc, cat = set(), False, False, False
    for c in carpetas_enaho():
        by = os.path.join(c, 'microodatos_inei', 'enaho', '2_organized', 'by_year')
        if os.path.isdir(by):
            for y in sorted(os.listdir(by)):
                yd = os.path.join(by, y)
                if not os.path.isdir(yd):
                    continue
                años.add(y)
                org = org or os.path.isdir(os.path.join(yd, 'modulos'))
                # la documentación se escribe en salidas/<año>/ (by_year/ queda como legado)
                sal = os.path.join(ROOT, 'salidas', y)
                doc = doc or bool(glob.glob(os.path.join(sal, '*.pdf')) or glob.glob(os.path.join(sal, '*.html'))
                                  or glob.glob(os.path.join(yd, '*.pdf')) or glob.glob(os.path.join(yd, '*.html')))
                cat = cat or bool(glob.glob(os.path.join(yd, 'catalogo_*.json')))
    return cs, sorted(años), org, doc, cat


def slug(s):
    return (re.sub(r'[^a-zA-Z0-9]+', '-', s.lower()).strip('-')[:60]) or 'tema'


# ----------------------------- pantallas modales -----------------------------
class TextScreen(ModalScreen):
    """Pide un texto simple (ej. años a descargar)."""
    def __init__(self, titulo, placeholder=""):
        super().__init__()
        self.titulo = titulo
        self.ph = placeholder

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(self.titulo, classes="dtitle")
            yield Input(placeholder=self.ph, id="txt")
            with Horizontal(classes="drow"):
                yield Button("Aceptar", variant="primary", id="ok")
                yield Button("Cancelar", id="cancel")

    def on_button_pressed(self, e: Button.Pressed):
        if e.button.id == "cancel":
            self.dismiss(None)
        else:
            self.dismiss(self.query_one("#txt", Input).value.strip())

    def on_input_submitted(self, e: Input.Submitted):
        self.dismiss(e.value.strip())


class AreaScreen(ModalScreen):
    """Paso 5: opción A (área + contexto) o B (3 áreas al azar)."""
    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label("Paso 5 — ¿Cómo eliges el área?", classes="dtitle")
            yield RadioSet(
                RadioButton("A · Yo doy el área temática", value=True, id="A"),
                RadioButton("B · El sistema propone 3 áreas al azar", id="B"),
                id="modo")
            yield Input(placeholder="Área temática (solo opción A) — ej. empleo, pobreza, salud", id="area")
            yield Input(placeholder="Contexto / variables a considerar (opcional)", id="ctx")
            with Horizontal(classes="drow"):
                yield Button("Continuar", variant="primary", id="ok")
                yield Button("Cancelar", id="cancel")

    def on_button_pressed(self, e: Button.Pressed):
        if e.button.id == "cancel":
            self.dismiss(None)
            return
        modo = "B" if self.query_one("#B", RadioButton).value else "A"
        area = self.query_one("#area", Input).value.strip() or None
        ctx = self.query_one("#ctx", Input).value.strip() or None
        self.dismiss((modo, area, ctx))


class SelectScreen(ModalScreen):
    """Elige una opción de una lista. opciones: list[(label, value)]."""
    def __init__(self, titulo, opciones):
        super().__init__()
        self.titulo = titulo
        self.opciones = opciones

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(self.titulo, classes="dtitle")
            yield ListView(*[ListItem(Label(lbl)) for lbl, _ in self.opciones], id="lst")
            yield Button("Cancelar", id="cancel")

    def on_list_view_selected(self, e: ListView.Selected):
        self.dismiss(self.opciones[e.list_view.index][1])

    def on_button_pressed(self, e: Button.Pressed):
        if e.button.id == "cancel":
            self.dismiss(None)


class YearMultiScreen(ModalScreen):
    """Selección de UNO o VARIOS años (multi-año)."""
    def __init__(self, anios):
        super().__init__()
        self.anios = anios

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label("Elige uno o varios años (espacio para marcar)", classes="dtitle")
            yield SelectionList(*[(a, a, i == len(self.anios) - 1) for i, a in enumerate(self.anios)], id="years")
            with Horizontal(classes="drow"):
                yield Button("Continuar", variant="primary", id="ok")
                yield Button("Cancelar", id="cancel")

    def on_button_pressed(self, e: Button.Pressed):
        if e.button.id == "cancel":
            self.dismiss(None)
            return
        sel = list(self.query_one("#years", SelectionList).selected)
        self.dismiss(sorted(sel) or None)


# ----------------------------- app principal -----------------------------
class ENAHOApp(App):
    TITLE = "Sistema Inteligente ENAHO"
    SUB_TITLE = "microdatos → tema de investigación económico"
    CSS = """
    Screen { background: #0b1622; }
    #sidebar {
        width: 38; background: #0d2530;
        border-right: thick #2ec4d6; padding: 1 1;
    }
    .lane { width: 100%; padding: 0 1; margin: 1 0 0 0; text-style: bold; }
    .sys { color: #0b1622; background: #2ec4d6; }
    .usr { color: #0b1622; background: #f0b429; }
    .util { color: #0b1622; background: #8a93a0; }
    #sidebar Button { width: 100%; margin: 0 0; border: none; height: 1; background: #0d2530; color: #d7e3ea; }
    #sidebar Button:hover { background: #14404f; color: white; }
    #sidebar Button.cta { color: #0b1622; background: #f0b429; text-style: bold; }
    #sidebar Button.cta:hover { background: #ffc94d; }
    #content { background: #0c1a26; border: round #2ec4d6; padding: 0 1; }
    #log { background: #0c1a26; }
    #status { dock: top; height: 1; background: #102a3a; color: #9fb3c0; padding: 0 1; }
    #dialog {
        width: 100; max-width: 95%; height: auto; padding: 1 2; background: #102a3a;
        border: thick #2ec4d6; margin: 2 4;
    }
    .dtitle { text-style: bold; color: #2ec4d6; margin: 0 0 1 0; }
    .drow { height: auto; margin: 1 0 0 0; }
    .drow Button { margin: 0 1 0 0; }
    #dialog Input { margin: 1 0 0 0; }
    #lst { height: auto; max-height: 18; margin: 1 0; }
    /* opciones largas: envolver en varias líneas en vez de cortarse */
    #lst ListItem { height: auto; padding: 0 1; }
    #lst Label { width: 1fr; }
    """
    BINDINGS = [
        Binding("1", "descargar", "Descargar"),
        Binding("2", "organizar", "Organizar"),
        Binding("3", "documentar", "Documentar"),
        Binding("5", "proponer", "Proponer tema"),
        Binding("c", "catalogo", "Catálogo"),
        Binding("v", "propuestas", "Ver propuestas"),
        Binding("l", "limpiar", "Limpiar"),
        Binding("q", "quit", "Salir"),
    ]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal():
            with VerticalScroll(id="sidebar"):
                yield Static("① SISTEMA · Preparación", classes="lane sys")
                yield Button("1 · Descargar data", id="descargar")
                yield Button("2 · Organizar", id="organizar")
                yield Button("3·4 · Documentar (PDF+HTML)", id="documentar")
                yield Static("② USUARIO · Exploración", classes="lane usr")
                yield Button("5 ▶ Proponer tema (5–10)", id="proponer", classes="cta")
                yield Static("③ Utilidades", classes="lane util")
                yield Button("Ver propuestas guardadas", id="propuestas")
                yield Button("Regenerar catálogo", id="catalogo")
                yield Button("Limpiar consola", id="limpiar")
            with Vertical(id="content"):
                yield Static(id="status")
                yield RichLog(id="log", wrap=True, markup=True, highlight=True)
        yield Footer()

    _busy = None  # texto de la tarea en curso, o None si libre

    def on_mount(self):
        self._busy = None
        self._refresh_status()
        log = self.query_one("#log", RichLog)
        log.write(Panel(
            "[bold #2ec4d6]Bienvenido al Sistema Inteligente ENAHO[/]\n\n"
            "Usa la barra lateral o los atajos del pie. El flujo estrella es "
            "[bold #f0b429]5 ▶ Proponer tema[/]: corre los pasos 5–10 con tu suscripción "
            "de Claude y te entrega el tema, variables, merge/filtros y puntuación.",
            border_style="#2ec4d6", box=box.ROUNDED))

    def _refresh_status(self):
        if self._busy:
            self.query_one("#status", Static).update(f"[black on #f0b429] ⏳ {self._busy} [/]")
            return
        cs, años, org, doc, cat = estado_global()
        ok = lambda b: "[green]✓[/]" if b else "[red]✗[/]"
        txt = (f" Datos: {', '.join(cs) or '—'}   ·   años: {', '.join(años) or '—'}   ·   "
               f"organizado {ok(org)}  documentado {ok(doc)}  catálogo {ok(cat)}") if cs else \
              " Sin datos aún — empieza por [b]1 · Descargar[/]"
        self.query_one("#status", Static).update(txt)

    def _set_busy(self, msg):
        self._busy = msg
        for b in self.query("#sidebar Button"):
            b.disabled = True
        self._refresh_status()

    def _end_busy(self, ok=True, msg=""):
        self._busy = None
        for b in self.query("#sidebar Button"):
            b.disabled = False
        self._refresh_status()
        if msg:
            self.notify(msg, title="ENAHO", severity="information" if ok else "error", timeout=5)

    # ---------- dispatch ----------
    def on_button_pressed(self, e: Button.Pressed):
        if self._busy:
            self.notify("Hay una tarea en curso, espera a que termine.", severity="warning", timeout=3)
            return
        getattr(self, f"action_{e.button.id}", lambda: None)()

    def action_limpiar(self):
        self.query_one("#log", RichLog).clear()

    # ---------- pasos 1–4 (scripts en SECUENCIA, un solo hilo) ----------
    @work(thread=True, exclusive=True)
    def _run_jobs(self, jobs):
        log = self.query_one("#log", RichLog)
        allok = True
        for args, titulo in jobs:
            self.call_from_thread(self._set_busy, titulo)
            self.call_from_thread(log.write, f"[bold #2ec4d6]▶ {titulo}[/]")
            try:
                proc = subprocess.Popen([sys.executable, *args], cwd=ROOT, env=PYENV,
                                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        text=True, encoding='utf-8', errors='replace', bufsize=1)
                for line in proc.stdout:
                    self.call_from_thread(log.write, "  " + line.rstrip())
                proc.wait()
                ok = proc.returncode == 0
            except Exception as ex:
                ok = False
                self.call_from_thread(log.write, f"[red]Error: {ex}[/]")
            allok = allok and ok
            self.call_from_thread(log.write,
                                  f"[green]✓ {titulo}[/]" if ok else f"[red]✗ {titulo}[/]")
        self.call_from_thread(self._end_busy, allok,
                              "Tareas completadas" if allok else "Terminó con errores")

    @work
    async def action_descargar(self):
        años = await self.push_screen_wait(TextScreen(
            "Año(s) a descargar", "ej. 2024  ·  2015-2020  ·  2018 2019"))
        if años:
            self._run_jobs([(['scripts/descargar.py'] + años.split(), "Paso 1 · Descargar"),
                            (['scripts/ordenar.py'], "Paso 2 · Organizar")])

    def action_organizar(self):
        self._run_jobs([(['scripts/ordenar.py'], "Paso 2 · Organizar")])

    def action_documentar(self):
        self._run_jobs([(['scripts/generar_documentacion_pdf.py'], "Paso 3–4 · Documentación PDF"),
                        (['scripts/generar_visor_html.py'], "Paso 4 · Visor HTML"),
                        (['scripts/catalogo.py'], "Catálogo de grounding")])

    def action_catalogo(self):
        self._run_jobs([(['scripts/catalogo.py'], "Catálogo de grounding")])

    @work(exclusive=True)
    async def action_propuestas(self):
        log = self.query_one("#log", RichLog)
        props = sorted(glob.glob(os.path.join(ROOT, 'temas', '*', 'propuesta.json')))
        if not props:
            self.notify("Aún no hay propuestas guardadas. Corre el paso 5.", severity="warning")
            return
        pick = await self.push_screen_wait(SelectScreen(
            "Propuestas guardadas",
            [(os.path.basename(os.path.dirname(p)).replace('-', ' '), p) for p in props]))
        if not pick:
            return
        with open(pick, encoding='utf-8') as fh:
            res = json.load(fh)
        log.write(self._ficha(res))

    # ---------- pasos 5–10 (razonamiento, worker async) ----------
    @work(exclusive=True)
    async def action_proponer(self):
        log = self.query_one("#log", RichLog)
        años = RZ.años_disponibles()
        if not años:
            log.write("[red]No hay catálogo. Corre primero 3·4 Documentar o c Catálogo.[/]")
            return
        sel_anios = [años[0]] if len(años) == 1 else await self.push_screen_wait(YearMultiScreen(años))
        if not sel_anios:
            return
        ar = await self.push_screen_wait(AreaScreen())
        if not ar:
            return
        modo, area, contexto = ar

        res = {'anios': sel_anios, 'tema': None}
        for y in sel_anios:   # aviso: el mismo año en varias carpetas = fuente ambigua
            carps = RZ.carpetas_de_anio(y)
            if len(carps) > 1:
                log.write(f"[yellow]⚠ El año {y} existe en {len(carps)} carpetas "
                          f"({', '.join(carps)}); se usará '{carps[0]}'. "
                          f"Elimina duplicados para no mezclar fuentes.[/]")
        try:
            self._set_busy("Cargando catálogo multi-año")
            mcat = await asyncio.to_thread(RZ.catalogo_multianio, sel_anios)
            rep = sel_anios[-1]
            cat = await asyncio.to_thread(RZ.load_catalogo, rep)
            self._busy = None
            self._refresh_status()   # que la barra no siga mostrando ⏳ durante el modal
            if not mcat or not cat:
                log.write("[red]No se pudo cargar el catálogo de esos años.[/]")
                return

            if modo == "B":
                self._set_busy("Paso 5 · proponiendo áreas")
                areas = await asyncio.to_thread(RZ.sugerir_areas, cat, 3)
                self._busy = None
                self._refresh_status()   # que la barra no siga mostrando ⏳ durante el modal
                area = await self.push_screen_wait(SelectScreen(
                    "Elige un área", [(a.get('area', ''), a.get('area')) for a in areas]))
                if not area:
                    return

            self._set_busy("Paso 5 · sugiriendo temas (multi-año)")
            temas = await asyncio.to_thread(RZ.sugerir_temas_multi, mcat, area, contexto, 4)
            self._busy = None
            self._refresh_status()   # que la barra no siga mostrando ⏳ durante el modal
            tema = await self.push_screen_wait(SelectScreen("Elige un tema de investigación", [
                ("%s  [años: %s]" % (t.get('tema', ''), '-'.join(map(str, t.get('cobertura_anios', sel_anios)))), t)
                for t in temas]))
            if not tema:
                return
            res['tema'] = tema
            cob = [str(a) for a in (tema.get('cobertura_anios') or sel_anios)]
            res['cobertura_anios'] = cob
            rep = cob[-1] if cob else rep
            cat = await asyncio.to_thread(RZ.load_catalogo, rep)
            log.write(Panel(f"[bold]{tema.get('tema')}[/]\n[dim]{tema.get('pregunta_investigacion','')}[/]\n"
                            f"[#2ec4d6]Cobertura:[/] {', '.join(cob)} — {tema.get('motivo_cobertura', '')}",
                            title="Tema elegido", border_style="#f0b429"))

            res['analisis'] = await self._paso(log, "Paso 6 · Análisis de módulos", RZ.analizar_tema, cat, tema)
            res['manifiesto'] = await self._paso(log, "Paso 7 · Selección de variables",
                                                 RZ.seleccionar_variables, cat, tema, mcat, cob)
            if len(cob) > 1:   # verificación determinista: cada variable debe existir en TODOS los años
                res['variables_parciales'] = RZ.disponibilidad_variables(mcat, cat, res['manifiesto'], cob)
                if res['variables_parciales']:
                    for f in res['variables_parciales']:
                        log.write(f"[yellow]⚠ {f['variable']} ({f.get('rol','')}) NO existe en: "
                                  f"{', '.join(f['faltan_en'])} — esa parte del análisis no cubrirá esos años.[/]")
                else:
                    log.write("[green]✓ Todas las variables seleccionadas existen en todos los años de cobertura.[/]")
            res['causal'] = await self._paso(log, "Diseño causal · identificación", RZ.diseno_causal, cat, tema, res['manifiesto'], cob)
            res['filtros'] = await self._paso(log, "Plan de datos · filtros", RZ.sugerir_filtros, cat, tema, res['manifiesto'])
            res['plan_datos'] = RZ.plan_de_datos(cat, tema, res['manifiesto'], res['filtros'])
            log.write(self._panel_plan(res['plan_datos']))
            res['verificacion_merge'] = await self._paso(log, "Plan de datos · verificar merge", EST.verificar_merge, res['plan_datos'], rep)
            for vm in res['verificacion_merge']:
                mk = "[green]✓[/]" if vm.get('ok') else "[red]⚠[/]"
                log.write(f"  {mk} {vm.get('archivo')}: {vm.get('nota')}")
            res['consolidacion'] = await self._paso(log, "Plan de datos · consolidación", EST.revisar_consolidacion, cat, res['manifiesto'], rep)
            plan = await self._paso(log, "Paso 8 · Planificando brechas", RZ.plan_brechas, cat, tema, res['manifiesto'])
            if len(cob) > 1:
                res['brechas_por_anio'] = await self._paso(
                    log, "Paso 8 · Calculando brechas en %d años" % len(cob),
                    EST.calcular_multi, plan, cob, rep)
                res['brechas'] = res['brechas_por_anio'].get(str(rep)) or []
                log.write(self._tabla_brechas(res['brechas']))
                log.write(self._tabla_evolucion(res['brechas_por_anio']))
                interp_input = res['brechas_por_anio']
            else:
                res['brechas'] = await self._paso(log, "Paso 8 · Calculando brechas", EST.calcular, plan, rep)
                log.write(self._tabla_brechas(res['brechas']))
                interp_input = res['brechas']
            res['interpretacion'] = await self._paso(log, "Paso 8 · Interpretando", RZ.interpretar_brechas, tema, interp_input)
            res['literatura'] = await self._paso(log, "Paso 9 · Literatura (web)", RZ.contraste_literatura, tema, res['interpretacion'])
            res['puntuacion'] = await self._paso(log, "Paso 10 · Puntuación", RZ.puntuar, tema, res['interpretacion'], res['literatura'], res['analisis'])
            log.write(self._ficha(res))
            d = os.path.join(ROOT, 'temas', slug(tema.get('tema', 'tema')))
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, 'propuesta.json'), 'w', encoding='utf-8') as fh:
                json.dump(res, fh, ensure_ascii=False, indent=2)
            self._set_busy("Generando ficha PDF")
            pdf_out = os.path.join('salidas', 'fichas', slug(tema.get('tema', 'tema')) + '.pdf')
            await asyncio.to_thread(FICHA.generar_ficha_pdf, res, cat, pdf_out)
            self._busy = None
            self._refresh_status()   # que la barra no siga mostrando ⏳ durante el modal
            log.write(f"[green]Ficha PDF:[/] {pdf_out}")
            log.write(f"[green]Propuesta:[/] temas/{os.path.basename(d)}/propuesta.json")
            self.notify("Propuesta lista 🎉 — ficha PDF en salidas/fichas/", title="ENAHO", timeout=7)
        except Exception as ex:
            log.write(f"[red]Falló un paso: {ex}[/]")
            self.notify("Falló el flujo de propuesta", severity="error", timeout=6)
        finally:
            self._end_busy()

    async def _paso(self, log, titulo, fn, *args):
        self._set_busy(titulo)
        log.write(f"[#2ec4d6]· {titulo}…[/]")
        return await asyncio.to_thread(fn, *args)

    # ---------- render de resultados (Rich dentro del RichLog) ----------
    def _panel_plan(self, plan):
        b = [f"Nivel: [b]{plan['nivel_de_analisis']}[/]  ·  llaves: [b]{'+'.join(plan['llaves_merge'])}[/]",
             f"Base: {plan.get('archivo_base')}"]
        for p in plan['secuencia_merge']:
            b.append(f"  • [{p['tipo']}] {p['archivo']} ← {'+'.join(p['llaves_join'])} ({len(p['variables'])} vars)")
        if plan.get('filtros'):
            b.append("Filtros:")
            for f in plan['filtros']:
                b.append(f"  • {f.get('variable')}: {f.get('condicion')}")
        return Panel("\n".join(b), title="Plan de datos · merge y filtro", border_style="magenta", box=box.ROUNDED)

    def _tabla_brechas(self, resultados):
        t = Table(title="Paso 8 · Brechas (datos reales)", box=box.SIMPLE, title_style="bold cyan")
        t.add_column("Brecha"); t.add_column("Grupos (valor)"); t.add_column("Brecha %", justify="right")
        for r in resultados:
            if r.get('error'):
                t.add_row(r.get('brecha', ''), f"[red]{r['error']}[/]", "—")
                continue
            gs = "  ".join(f"{g['etiqueta']}={g['valor']:,.0f}" for g in r.get('grupos', [])[:4])
            t.add_row(r.get('brecha', ''), gs, str(r.get('brecha_relativa_pct', '—')))
        return t

    def _tabla_evolucion(self, por_anio):
        anios = sorted(por_anio)
        nombres = []
        for y in anios:
            for r in por_anio[y]:
                if r.get('brecha') and r['brecha'] not in nombres:
                    nombres.append(r['brecha'])
        t = Table(title="Paso 8 · Evolución de brechas por año (brecha relativa %)",
                  box=box.SIMPLE, title_style="bold cyan")
        t.add_column("Brecha")
        for y in anios:
            t.add_column(y, justify="right")
        for nom in nombres:
            fila = [nom]
            for y in anios:
                r = next((x for x in por_anio[y] if x.get('brecha') == nom), None)
                if r is None:
                    fila.append("—")
                elif r.get('error'):
                    fila.append("[red]err[/]")
                else:
                    fila.append(str(r.get('brecha_relativa_pct', '—')))
            t.add_row(*fila)
        return t

    def _ficha(self, res):
        tema, pds, p = res.get('tema', {}), res.get('plan_datos', {}), res.get('puntuacion', {})
        cau = res.get('causal') or {}
        manif = [v for v in res.get('manifiesto', []) if isinstance(v, dict)]
        vs = "\n".join(f"  • {v.get('variable')} ({v.get('rol')})" for v in manif[:12])
        if len(manif) > 12:
            vs += f"\n  … (+{len(manif) - 12} más)"
        cob = ', '.join(map(str, res.get('cobertura_anios') or res.get('anios', [])))
        body = (f"[bold #f0b429]{tema.get('tema')}[/]\n"
                f"[dim]{tema.get('pregunta_investigacion','')}[/]\n"
                f"[#2ec4d6]Años:[/] {cob}\n\n"
                f"[b]Diseño causal:[/] {cau.get('estrategia_identificacion','—')} "
                f"[dim]({cau.get('nivel_causal','?')})[/]\n"
                f"[b]Módulos:[/] {', '.join(map(str, tema.get('modulos', [])))}\n"
                f"[b]Variables:[/]\n{vs}\n\n"
                f"[b]Merge:[/] {pds.get('nivel_de_analisis')} por {'+'.join(pds.get('llaves_merge', []))}\n"
                f"[b]Filtros:[/] {', '.join(f.get('condicion','') for f in pds.get('filtros', [])) or 'ninguno'}\n\n"
                f"[b]Puntaje:[/] {p.get('puntaje_total','?')} — {p.get('veredicto','')}\n"
                f"[dim]Ficha completa en salidas/fichas/ (PDF)[/]")
        return Panel(body, title="📋 FICHA DE INVESTIGACIÓN", border_style="green", box=box.DOUBLE)


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'test':
        async def _smoke():
            app = ENAHOApp()
            async with app.run_test() as pilot:
                await pilot.pause()
            print("SMOKE OK · la app monta sin errores")
        asyncio.run(_smoke())
    else:
        ENAHOApp().run()
