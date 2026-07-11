# -*- coding: utf-8 -*-
"""Paso 1: Descargar la ENAHO (corte transversal, CSV) para el/los año(s) dados.

Uso:
    python scripts/descargar.py 2024
    python scripts/descargar.py 2015 2020        # rango (inclusive) -> enaho_2015-2020
    python scripts/descargar.py 2018 2019 2021    # lista -> enaho_2018-2021 (min-max)

Reglas:
- survey="enaho"  => corte transversal SIEMPRE (nunca enaho_panel).
- preferred_formats=["csv"].
- Carpeta: enaho_<año> (un año) o enaho_<min>-<max> (varios).
"""
import sys


def carpeta_de(years):
    if len(years) == 1:
        return 'enaho_%d' % years[0]
    lo, hi = min(years), max(years)
    if sorted(years) == list(range(lo, hi + 1)):        # contiguos -> rango
        return 'enaho_%d-%d' % (lo, hi)
    # no contiguos (ej. 2018 2019 2021): nombre explícito, no un rango engañoso
    return 'enaho_' + '_'.join(str(y) for y in sorted(years))


def parse_years(args):
    nums = []
    for a in args:
        a = a.strip()
        if '-' in a and a.replace('-', '').isdigit():       # "2015-2020"
            lo, hi = a.split('-')
            nums += list(range(int(lo), int(hi) + 1))
        elif a.isdigit():
            nums.append(int(a))
    if len(nums) == 2 and nums[1] - nums[0] > 1:            # "2015 2020" => rango
        nums = list(range(nums[0], nums[1] + 1))
    return sorted(set(nums))


def descargar(years, parallel=3):
    from perustats.inei import INEIFetcher
    carpeta = carpeta_de(years)
    print('Descargando ENAHO (corte transversal, CSV) años=%s -> %s' % (years, carpeta))
    fetcher = INEIFetcher(survey='enaho', years=years, master_directory='./%s' % carpeta,
                          preferred_formats=['csv'], parallel_jobs=parallel)
    # operation='move': no recopia ni duplica (evita el problema de re-copiar todo)
    fetcher.fetch_modules().download().organize(organize_by='year', operation='move')
    print('OK descarga ->', carpeta)
    return carpeta


if __name__ == '__main__':
    years = parse_years(sys.argv[1:])
    if not years:
        print('Indica el/los año(s). Ej: python scripts/descargar.py 2024')
        sys.exit(1)
    descargar(years)
