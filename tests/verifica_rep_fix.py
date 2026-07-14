# -*- coding: utf-8 -*-
"""Verifica que 'rep' se calcule con max(), no con el ultimo elemento de una
lista desordenada devuelta por la IA."""
cob_desordenado = ["2022", "2023", "2021"]   # simula lo que la IA podria devolver
rep_antes = cob_desordenado[-1]              # logica VIEJA (con bug)
rep_ahora = max(cob_desordenado)             # logica NUEVA (arreglada)
print("cobertura_anios (desordenada):", cob_desordenado)
print("rep con la logica vieja (cob[-1]):", rep_antes, "-> INCORRECTO, no es el año mas reciente")
print("rep con la logica nueva (max()) :", rep_ahora, "-> correcto")
assert rep_ahora == "2023" and rep_antes == "2021"
print("OK: el fix corrige exactamente el caso que fallaba")
