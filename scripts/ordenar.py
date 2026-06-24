# -*- coding: utf-8 -*-
"""Paso 2: Ordenar los CSV de cada año en dos subcarpetas dentro de by_year/<AÑO>/:
    - modulos/             -> datos de los módulos de la encuesta
    - tablas_descripcion/  -> tablas de clasificación (enaho-tabla-*)

Idempotente: se puede re-ejecutar. Procesa todas las carpetas enaho_* presentes.

Uso: python scripts/ordenar.py
"""
import os, glob, shutil


def ordenar():
    resultados = []
    for base in glob.glob('enaho_*'):
        by_year = os.path.join(base, 'microodatos_inei', 'enaho', '2_organized', 'by_year')
        if not os.path.isdir(by_year):
            continue
        for anio in sorted(os.listdir(by_year)):
            ydir = os.path.join(by_year, anio)
            if not os.path.isdir(ydir):
                continue
            dst_mod = os.path.join(ydir, 'modulos')
            dst_tab = os.path.join(ydir, 'tablas_descripcion')
            os.makedirs(dst_mod, exist_ok=True)
            os.makedirs(dst_tab, exist_ok=True)
            n_mod = n_tab = 0
            for f in os.listdir(ydir):
                src = os.path.join(ydir, f)
                if not os.path.isfile(src) or not f.lower().endswith('.csv'):
                    continue
                dst = dst_tab if 'enaho-tabla-' in f.lower() else dst_mod
                shutil.move(src, os.path.join(dst, f))
                if dst is dst_tab:
                    n_tab += 1
                else:
                    n_mod += 1
            print('%s/%s: modulos=%d, tablas_descripcion=%d' % (base, anio, n_mod, n_tab))
            resultados.append((base, anio, n_mod, n_tab))
    if not resultados:
        print('No se encontraron carpetas enaho_* con datos organizados por año.')
    return resultados


if __name__ == '__main__':
    ordenar()
