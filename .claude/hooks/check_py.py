# -*- coding: utf-8 -*-
"""Hook PostToolUse (Write|Edit): verificacion estatica barata tras editar un
.py del sistema ENAHO. NO usa la suscripcion de Claude (nada de claude -p).

1) Sintaxis: py_compile sobre el archivo editado.
2) Smoke test del TUI (python sistema_enaho.py test): detecta imports rotos
   entre modulos (ej. una funcion renombrada en razonador.py que rompe
   sistema_enaho.py), no solo errores de sintaxis dentro del mismo archivo.

Silencioso si todo esta OK; solo reporta cuando algo falla (via
hookSpecificOutput.additionalContext), para no ensuciar cada edicion.
"""
import sys
import os
import json
import subprocess
import py_compile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CORE = {'sistema_enaho.py'}


def _bajo_scripts(rel):
    return rel == 'sistema_enaho.py' or rel.startswith('scripts/') or rel.startswith('scripts\\')


def emit(msg):
    # decision:"block" = fallo OBLIGATORIO a resolver (no una nota que se puede
    # ignorar). El hook NUNCA intenta arreglar el codigo por su cuenta: solo
    # senala DONDE se rompio para que se corrija ahi, no en otro lado.
    print(json.dumps({
        'decision': 'block',
        'reason': msg,
        'hookSpecificOutput': {
            'hookEventName': 'PostToolUse',
            'additionalContext': msg,
        }
    }))


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return
    ti = data.get('tool_input', {}) or {}
    tr = data.get('tool_response', {}) or {}
    fp = tr.get('filePath') or ti.get('file_path')
    if not fp or not fp.lower().endswith('.py'):
        return
    fp = os.path.abspath(fp)
    if not fp.startswith(ROOT) or not os.path.isfile(fp):
        return
    rel = os.path.relpath(fp, ROOT).replace('\\', '/')
    if not _bajo_scripts(rel):
        return

    # 1) sintaxis
    try:
        py_compile.compile(fp, doraise=True)
    except py_compile.PyCompileError as e:
        emit('[check_py] ERROR DE SINTAXIS en %s:\n%s' % (rel, str(e.exc_value)[-800:]))
        return
    except Exception as e:
        emit('[check_py] no se pudo compilar %s: %s' % (rel, e))
        return

    # 2) smoke test del TUI (solo si el archivo es parte del sistema principal)
    try:
        env = dict(os.environ, PYTHONUTF8='1', PYTHONIOENCODING='utf-8')
        r = subprocess.run([sys.executable, 'sistema_enaho.py', 'test'],
                          cwd=ROOT, capture_output=True, text=True, timeout=45, env=env)
        out = (r.stdout or '') + (r.stderr or '')
        if 'SMOKE OK' not in out:
            emit('[check_py] el smoke test del TUI FALLO tras editar %s:\n%s'
                % (rel, out[-800:]))
    except Exception as e:
        emit('[check_py] no se pudo correr el smoke test: %s' % e)


if __name__ == '__main__':
    main()
