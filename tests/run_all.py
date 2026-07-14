# -*- coding: utf-8 -*-
"""Corre TODA la suite de regresión (tests/verifica_*.py) y reporta un resumen.

Uso: python tests/run_all.py

Cada test es autocontenido: arma su propia data sintética, la usa, y la borra
al terminar. Ninguno depende de datos reales de ENAHO ni de la suscripción de
Claude — corren rápido y se pueden ejecutar en cualquier checkout del repo.
"""
import os
import sys
import glob
import time
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
PYENV = {**os.environ, 'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8'}


def main():
    archivos = sorted(glob.glob(os.path.join(HERE, 'verifica_*.py')))
    if not archivos:
        print('No se encontraron tests (verifica_*.py) en', HERE)
        return 1

    resultados = []
    for f in archivos:
        nombre = os.path.basename(f)
        t0 = time.time()
        r = subprocess.run([sys.executable, f], capture_output=True, text=True,
                           encoding='utf-8', errors='replace', env=PYENV)
        dt = time.time() - t0
        ok = r.returncode == 0
        resultados.append((nombre, ok))
        print('%s  %-45s (%.1fs)' % ('OK  ' if ok else 'FAIL', nombre, dt))
        if not ok:
            salida = (r.stdout + r.stderr).strip().splitlines()
            for linea in salida[-15:]:
                print('    ' + linea)

    fallidos = [n for n, ok in resultados if not ok]
    print()
    print('%d/%d tests OK' % (len(resultados) - len(fallidos), len(resultados)))
    if fallidos:
        print('FALLARON:', ', '.join(fallidos))
    return 1 if fallidos else 0


if __name__ == '__main__':
    sys.exit(main())
