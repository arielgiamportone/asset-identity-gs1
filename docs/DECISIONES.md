# Decisiones de diseño propias (fase 2)

Registro de todo lo que la especificación no fijaba y hubo que decidir durante
la implementación clean-room. Cada entrada indica qué se decidió, qué
alternativas se descartaron y por qué. La numeración de secciones (§) remite a
la especificación.

## Nombres públicos (regla 4: nombres nuevos)

| Elemento | Nombre elegido | Nota |
|---|---|---|
| Paquete | `assetid` | fijado por el encargo |
| Prefijo fijo del alias (§3.3) | `AID` | tres letras nuevas, mnemónico de *asset identity* |
| Módulos | `checkchar`, `epc`, `identity`, `lifecycle`, `registry`, `labels_pdf`, `zpl`, `synthetic`, `errors` | ninguno coincide con los nombres internos listados en §11 |
| Campos del namespace | `company_prefix`, `block`, `tenant_code`, `resolver_domain`, `scheme`, `strict` | las pseudofirmas de §7 usan nombres que §11 prohíbe; se renombran |
| Cuarta forma | `gs1_link` (`build_gs1_link`, `giai_from_gs1_link`, `CodeKind.GS1_LINK`) | el nombre con guion bajo de §7 está en la lista de §11 |
| Presets A4 (§6.1) | `"a4-21"`, `"a4-65"`, `"a4-14"` en `SHEET_PRESETS` | los nombres con guion bajo están en §11 |
| Estados (§5) | `ISSUED`, `PRINTED`, `PLACED`, `RETIRED` | traducción directa de EMITIDA/IMPRESA/COLOCADA/BAJA |
| Centinela de reserva (§4) | `RESERVED:<tenant>:<número>` | incluye el tenant para que la clave de activo siga siendo única entre tenants |

## Modelo de identidad

1. **Serial inicial = 1.** El caso 12 de la spec espera seriales 1 y 2 para los
   dos primeros activos; el serial 0 queda sin usar.
2. **`parse_any` no lanza.** Un valor irreconocible devuelve `CodeKind.UNKNOWN`
   en vez de una excepción, porque §5 pide tratar la lectura mala como hallazgo
   de campo y no como error de ingesta. La cadena vacía también es `UNKNOWN`.
3. **Ambigüedad EPC/GIAI.** Un valor de 24 dígitos que empieza por `34` se
   clasifica como EPC; el registro prueba primero la columna EPC y después la
   GIAI, así que la resolución sigue siendo correcta en ambos casos.
4. **`parse_alias` acepta minúsculas** en la entrada escaneada (se normaliza a
   mayúsculas), pero el prefijo sigue siendo obligatorio.
5. **Modo estricto opcional** (`Namespace(strict=True)`) exige bloque ≥ 1000,
   que es la condición de §3.2 para que la IAR no empiece por cero y un
   decodificador GIAI-96 de terceros devuelva los mismos dígitos. Por defecto
   no se exige, porque la propia librería rellena a 12 dígitos al decodificar.
6. **Filtro EPC 0..7.** La spec marca como [INFERIDO] que otros valores están
   reservados; se aceptan los 3 bits completos y se documenta.
7. **Decodificación rellenada.** `decode_giai96` devuelve el prefijo con los
   dígitos de su partición y la IAR con el máximo de dígitos de la partición;
   `Giai96Parts.giai` reconstruye el GIAI con los 12 últimos dígitos.
8. **Código de tenant 1..8 caracteres** `A-Z0-9`. La spec dice «3 letras
   típico»; se deja margen sin permitir guiones (romperían el parseo).
9. **Dominio resolvedor** validado como host simple (con puerto opcional), sin
   esquema ni barra final; `scheme` solo `https`/`http`.

## Registro y persistencia

10. **Unicidad del código de tenant además del bloque.** El alias solo es único
    entre tenants si el código lo es, así que `NamespaceRegistry.assign`
    rechaza también un código ya usado por otro tenant (misma excepción
    `NamespaceCollision`).
11. **Namespace incompleto = sin fila habilitada.** `Namespace` siempre está
    completo y validado; «configuración incompleta» se modela como ausencia de
    namespace o namespace deshabilitado (`set_enabled`). Emitir lanza
    `NamespaceIncomplete`; el render acepta `LabelFace` sin identidad (modo
    básico).
12. **Clave de activo global.** `asset_id` es único en toda la base, no solo
    por tenant, porque `mark`, `reprint` y `verify_scan` reciben solo el
    activo (firmas de §7).
13. **Emitir con número reservado vincula la reserva.** Si llega un alta con
    un número que está reservado, `issue` revincula la reserva (igual que
    `bind_reserved`) en lugar de acuñar un serial nuevo. Es la lectura literal
    de «al llegar el alta con ese número».
14. **`DuplicateAlias`.** Dos activos distintos del mismo tenant con el mismo
    número normalizado producirían el mismo alias; en vez de dejar escapar el
    `IntegrityError` de SQLite se lanza un error de dominio propio. Es el único
    error añadido a la lista de §7.
15. **`mark` no admite volver a `ISSUED`** ni transiciones fuera de la tabla
    de §5; `mark(PRINTED)` no cuenta reimpresión (eso lo hace `reprint`).
16. **Reserva y `existing_numbers`.** La librería no conoce la tabla de activos
    del llamador, así que `reserve` y `next_inventory_number` aceptan una lista
    opcional de números ya existentes para calcular el máximo observado. El
    patrón reconocido es `<prefijo>-NNNN` (guion opcional, dígitos variables).
17. **Transacciones `BEGIN IMMEDIATE`** para serializar la asignación de
    serial, como propone el [INFERIDO] de §5. El índice único `(block, serial)`
    y el alias único siguen como red.
18. **Auditoría en tabla propia** (`audit_events`) con los cuatro eventos
    propuestos en §5. Se expone por `Store.events()`.
19. **Migración tolerante.** La lista `_COLUMN_UPGRADES` añade columnas con
    `ALTER TABLE` solo si faltan; se cubre con un test que borra columnas y
    reabre la base.
20. **Reloj inyectable** (`Store(clock=...)`) para sellos deterministas en
    tests; por defecto UTC ISO-8601 sin microsegundos.

## Render

21. **Solo reportlab + Pillow.** Code128 y QR salen de los módulos de barras de
    reportlab (vectoriales); no se añaden `python-barcode` ni `qrcode`. PNG
    opcional queda fuera (reportlab necesitaría un backend raster adicional).
22. **Fuentes Type 1 de serie** (Helvetica); el texto se adapta a WinAnsi, así
    que tildes, ñ y «» salen bien y lo que no exista en esa tabla se sustituye.
23. **Desplazamiento inicial módulo celdas/hoja.** Un offset igual o mayor que
    la rejilla empieza en una hoja nueva en vez de generar páginas vacías.
24. **Lote vacío**: PDF de una página con aviso impreso y `UserWarning`.
25. **Alias en texto pequeño** sobre el Code128 en celdas altas; no lo pide la
    spec pero ayuda a transcribir a mano.
26. **Contornos opcionales** (`outlines=True`) para calibrar la geometría de
    la hoja sobre papel normal.
27. **ZPL `^BY`**: la spec fija `^BY2`, pero un alias de 17 caracteres a 2
    puntos por módulo mide unos 55 mm y no cabe en la etiqueta de 50 mm por
    defecto; se usa `^BY2` cuando cabe (estimación conservadora sin compresión
    Code C) y `^BY1` en caso contrario.
28. **ZPL geometría proporcional** a la altura de la etiqueta (30 mm = 1.0),
    con mínimos de tamaño de fuente y barra legibles a 203 dpi.

## Fuera de alcance deliberado

- CLI: la spec no describe ninguna; se incluye `examples/demo.py` como punto
  de entrada reproducible.
- PNG, GIAI-202, GS1-128/DataMatrix, resolvedor del Digital Link, interfaz web
  y drivers de lector (fuera de alcance en §2).

## Anti-fugas

29. **Lista sellada** en `tests/test_no_leaks.py` (base64 de un JSON con
    término y banderas). Coincidencia por palabra completa con límites
    alfanuméricos (el guion bajo no oculta un identificador), insensible a
    mayúsculas salvo para siglas cortas que colisionarían con palabras
    corrientes (marcadas `c`).
30. **El historial se barre con `git log -p --format=%B`**, es decir mensajes y
    parches pero no cabeceras de autor: el nombre de la cuenta propietaria del
    repositorio no es una fuga y aparece inevitablemente en las URL del
    `pyproject.toml`.
31. **Exención única:** la frase de atribución literal del README, también
    sellada, se elimina del texto antes del barrido.

## Correcciones tras la revisión de fase 3

32. **Constantes renombradas.** `MOD43_ALPHABET` pasa a `CHECK_ALPHABET` y
    `DEFAULT_PRESET` a `SHEET_PRESET_DEFAULT` en código, exports y tests, a
    petición del revisor, para alejar los nombres públicos de los de la
    fuente. Los valores no cambian.
33. **Autoría del historial.** Los ocho commits de la rama (incluido el
    inicial) se reescribieron para que autor y committer sean la cuenta del
    propietario (`arielgiamportone` con su correo *noreply* de GitHub),
    manteniendo mensajes y trailers. La identidad queda configurada en el
    repositorio para los commits posteriores. El test anti-fugas sigue sin
    barrer cabeceras de autor; con esta autoría ya no hay nada que exentar.
