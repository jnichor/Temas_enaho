# Metodología: de las variables elegidas al dataset final

Este documento explica **cómo** el sistema selecciona variables, decide filtros, arma el merge y limpia los datos para producir el dataset final (Paso 11), y **por qué** cada regla existe. Complementa a la ficha PDF: la ficha explica qué pasó en *una* corrida puntual; esto explica la lógica general, siempre vigente.

Principio rector, válido para todo lo que sigue: **el sistema nunca inventa un código, una llave o una decisión de agregación que no pueda justificar con datos reales.** Cuando no puede verificarlo, excluye o avisa — no adivina.

---

## 1. Selección de variables (Paso 7)

`razonador.seleccionar_variables(cat, tema, mcat, cob)` le pide a la IA (modelo `haiku`, es una tarea mecánica: elegir de una lista ya acotada) que arme el **manifiesto**: la lista de variables a usar, cada una con:

- `archivo` y `variable` — deben existir en el catálogo real (`catalogo_<año>.json`); la IA no puede inventar nombres.
- `rol` — `dependiente` / `independiente` / `control` / `identificacion` / `ponderador`. Este rol importa más adelante: determina qué columnas se limpian numéricamente en el dataset final (sección 5).

Si el tema cubre varios años, `disponibilidad_variables(mcat, cat, manifiesto, cob)` revisa **de forma determinista** (no le pregunta a la IA) que cada variable elegida exista en TODOS los años de cobertura, no solo en el año representativo. Las que faltan en algún año quedan marcadas explícitamente, en vez de que el sistema descubra el hueco a mitad del cálculo.

---

## 2. Filtros de población (Paso 8 · plan de datos)

`razonador.sugerir_filtros(cat, tema, manifiesto)` (modelo `haiku`) propone las condiciones que definen la población de estudio (ej. edad ≥ 65, jefe de hogar, ocupados).

**Regla del código verificado.** El catálogo trae dos cosas distintas por variable:
- `variables`: el *significado* de la variable (ej. "P712: ¿de qué programa social recibió ayuda?").
- `valores`: cuando el diccionario oficial del INEI lo especifica, el *código exacto* de cada valor (ej. `P712 → {"5": "Programa Pensión 65"}`). Se extrae con `generar_visor_html.parse_valores_dictionary` y se guarda en `catalogo_<año>.json` al documentar (Paso 3-4).

La IA debe usar el código de `valores` cuando exista (`"condicion": "== 5"`), y si la variable categórica no aparece ahí, **debe devolver `"condicion": null`** en vez de inventar un código plausible (como `"= 'Sí'"`, que nunca se puede evaluar contra los datos). Antes de esta regla, la IA a veces adivinaba etiquetas humanas que después no servían para nada.

**Detección de contradicciones.** `estadistica.verificar_filtros(filtros, year, carpeta)` agrupa los filtros por archivo y, cuando hay 2 o más sobre el mismo archivo, calcula en los datos reales:
- cuántas filas deja cada filtro por separado,
- cuántas filas deja la combinación (AND) de todos.

Si cada uno por separado tiene datos pero la combinación da **0 filas**, es la firma típica de un patrón de salto del cuestionario ENAHO (una pregunta que solo se hace si otra NO aplica — ej. `P206` solo se pregunta cuando `P204==2`; pedir `P204==1` y `P206==1` juntos nunca puede tener respuesta). El sistema lo reporta como alerta explícita en vez de devolver un dataset vacío sin explicación. Esto **no** es algo que la IA pueda evitar sola: conoce el significado y el código de cada variable por separado, pero no la lógica de ramificación entre preguntas — por eso la verificación es determinista sobre datos reales, no otro intento de que la IA lo adivine.

---

## 3. Plan de merge (`razonador.plan_de_datos`) y su verificación

`plan_de_datos` es 100% determinista (sin IA): a partir de las llaves de identificación del catálogo decide el **nivel de análisis** (hogar o persona), elige el **archivo base** (el de más variables entre los que cubren todas las llaves necesarias) y arma la secuencia de merge (`left join` desde el base).

Cuando un archivo está a nivel hogar pero el análisis es a nivel persona, su valor se **replica** (broadcast) a cada integrante del hogar. Eso solo es válido si ese archivo tiene 1 fila por hogar — `estadistica.verificar_merge(plan, year, carpeta)` lo comprueba contra los datos reales (no contra lo que dice el catálogo) y marca `ok: false` si encuentra más de una fila por llave, con la advertencia explícita de que un broadcast ahí inflaría filas.

---

## 4. Resolución de niveles no compatibles (archivos a nivel ítem)

Un archivo puede fallar la verificación anterior porque en realidad es un registro a nivel **ítem/detalle** (ej. una fila por cada programa social recibido, no una por hogar). `razonador.plan_resolucion_niveles(cat, manifiesto, plan_datos, verificacion_merge)` (modelo `haiku`, se activa solo para los archivos que `verificar_merge` marcó problemáticos) decide, variable por variable, una de tres estrategias — siempre grounded en los códigos reales del catálogo, nunca inventados:

- **`agregar`**: la variable es numérica y tiene sentido sumarla/promediarla entre los ítems del mismo hogar (`suma` / `promedio` / `conteo` / `maximo`). Ej.: sumar montos de gasto por rubro.
- **`restringir`**: aísla 1 fila por llave filtrando por un código conocido — puede ser la MISMA variable (ej. `P712 == 5` para quedarse solo con el registro de Pensión 65) u otra variable de rol del mismo archivo (ej. jefe de hogar).
- **`excluir`**: ninguna opción es segura con los códigos disponibles; la variable queda fuera del dataset final, con el motivo explicado.

**Prioridad filtro > resolución.** Si un filtro de población (sección 2) ya apunta a la misma `(archivo, variable)` que necesita resolución de nivel, el filtro manda — no lo que haya propuesto `plan_resolucion_niveles`. Sin esto, la resolución podía transformar la columna en algo que ya no era lo que el filtro creía estar filtrando (ej. agregar como "conteo de programas" y después filtrar `== 5` sobre ese conteo, un resultado sin sentido), o incluso borrar sin querer al grupo de comparación completo. Esta decisión se implementa en `estadistica.materializar_dataset` y queda registrada en el reporte (`origen: "filtro"` vs `"plan_resolucion_niveles"`).

---

## 5. Limpieza de datos

Se aplican dos transformaciones, ambas centralizadas en `estadistica._limpia_numerica` (y en `_cond_mask` para condiciones, que limpia antes de comparar):

1. **Coma decimal → punto.** Algunos años/módulos de la ENAHO usan `,` como separador decimal (y a veces `;` como separador de columnas) en vez de `.`/`,`. Sin esta limpieza, castear a número da `null` en silencio.
2. **Centinelas de no-respuesta → nulo.** Códigos de 5 o más nueves (`99999`, `999999.9`, ...) se neutralizan antes de cualquier cálculo. Deliberadamente **no** se limpia `9999` (4 dígitos): puede ser un valor legítimo (ej. un monto de S/9999), así que en vez de asumir se deja y se avisa en una nota si aparece muchas veces.

En el dataset final, esta limpieza se aplica a las columnas del manifiesto con rol `dependiente` / `independiente` / `control` — las que ya salen numéricas y limpias de una agregación (sección 4) no se tocan dos veces.

---

## 6. Materialización del dataset final (Paso 11)

`estadistica.materializar_dataset(plan_datos, manifiesto, filtros, resolucion, year, out_path, carpeta)` ejecuta todo lo anterior de verdad (a diferencia de `calcular()`/`verificar_merge()`, que solo validan o calculan agregados puntuales por brecha):

1. Arma el archivo base y valida que tenga 1 fila por llave de análisis (si no, no continúa — no tiene sentido construir sobre una base duplicada).
2. Une cada archivo de la secuencia de merge, resolviendo los que lo necesiten (sección 4).
3. Trae e integra los filtros de población con condición verificada (sección 2); si un filtro necesita una variable que aún no está en el merge, la busca en su archivo de origen.
4. Limpia las columnas numéricas del manifiesto (sección 5).
5. Corre un **control de calidad sobre el resultado real**, no sobre la promesa del plan: filas duplicadas por llave, nulos por columna, qué se agregó/restringió/excluyó y qué filtros se aplicaron u omitieron (con motivo).
6. Escribe el CSV y devuelve ese reporte completo — se muestra en el TUI, en la ficha PDF y queda guardado en `propuesta.json`.

---

## Resumen de salvaguardas

| Riesgo | Quién lo detecta | Qué hace el sistema |
|---|---|---|
| Variable no existe en todos los años | `disponibilidad_variables` | Marca qué años faltan, no rompe el resto |
| Broadcast infla filas (archivo no único) | `verificar_merge` | Marca `ok: false` con la cifra real de filas/hogares |
| Archivo a nivel ítem sin forma segura de reducirlo | `plan_resolucion_niveles` + `materializar_dataset` | Excluye la variable con motivo, nunca agrega/restringe a ciegas |
| Filtro con código de valor no verificado | `sugerir_filtros` | Devuelve `condicion: null` en vez de inventar |
| Filtros mutuamente excluyentes (salto de cuestionario) | `verificar_filtros` | Alerta explícita con las filas individuales vs. combinadas |
| Filtro y resolución de nivel chocan en la misma variable | `materializar_dataset` | El filtro gana; no se re-aplica dos veces |
| Comas decimales / centinelas sin limpiar | `_limpia_numerica` / `_cond_mask` | Limpieza antes de castear o comparar, siempre |
