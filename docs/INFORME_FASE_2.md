# Informe de cierre — fase 2 (implementación clean-room)

**Repositorio:** `asset-identity-gs1` · **Paquete:** `assetid` 0.1.0 · **Fecha:** 2026-11-16
**Entrada:** `SPEC.md` + `REGLAS_CLEAN_ROOM.md` · **Sin acceso a la fuente.**

## 1. Qué partes de la especificación se implementaron

| Sección de la spec | Estado | Dónde |
|---|---|---|
| §3.1 Componentes y rangos (CP 6–12, bloque 0–9999, serial 0–99 999 999, IAR 12) | Completa | `identity.Namespace`, `build_asset_reference` |
| §3.2 GIAI canónico (CP numérico, ≤ 30) y nota de conformidad | Completa; modo `strict` opcional exige bloque ≥ 1000 | `identity.build_giai`, `Namespace(strict=True)` |
| §3.3 Alias con control mod-43 (alfabeto Code 39, prefijo fijo, parseo por último/primer guion, `check_ok`) | Completa; prefijo nuevo `AID` | `checkchar`, `identity.build_alias/parse_alias` |
| §3.4 GS1 Digital Link e inversa | Completa | `identity.build_gs1_link`, `giai_from_gs1_link` |
| §3.5 EPC GIAI-96 (cabecera, filtro, tabla de particiones, relleno al decodificar, 4/8) | Completa | `epc` |
| §3.6 Conversiones puras y por registro | Completa | `identity.derive_identity`, `split_giai`, `registry` |
| §4 Autoridad de namespace, colisión (bloque y código), re-guardado, configuración incompleta, reservas con centinela | Completa | `registry.NamespaceRegistry`, `LabelRegistry.reserve/bind_reserved` |
| §5 Ciclo de vida, emisión idempotente, reimpresión, cierre en campo, validación de escaneo, baja, auditoría | Completa (4 eventos propuestos) | `lifecycle`, `registry.LabelRegistry`, `Store.events` |
| §6.1 Hojas A4 (3 presets, offset, nueva página, lote vacío, PDF vectorial) | Completa salvo PNG | `labels_pdf.render_sheet` |
| §6.2 Contenido de etiqueta (cabecera, número, descripción, Code128 ajustado, QR condicional, logo, individual) | Completa | `labels_pdf._draw_face`, `render_single` |
| §6.3 ZPL (`^RFW,H`, `^BCN`, escape de `^`/`~`, solo ASCII, lote) | Completa; `^BY` 2 o 1 según quepa | `zpl` |
| §7 API pública | Completa con nombres renombrados donde §11 lo exige; se añade `DuplicateAlias` | `assetid/__init__.py` |
| §8 Persistencia (tablas, únicos, aislamiento por tenant, `CREATE IF NOT EXISTS`, `ALTER` tolerante) | Completa | `registry.Store` |
| §9 Casos de prueba 1–23 | 23/23 cubiertos | `tests/` (véase §4 de este informe) |
| Reglas: licencia MIT, CI 3.11/3.12, ruff, gitleaks, tipado, metadatos, CHANGELOG, README bilingüe, sin `CLAUDE.md`/`AGENTS.md` | Cumplidas | raíz del repo |

## 2. Qué se dejó fuera y por qué

- **CLI** (paso 4 del plan): la spec no describe ninguna; `examples/demo.py`
  es el punto de entrada reproducible.
- **PNG opcional** (§6.1): reportlab exigiría un backend raster extra
  (`rlPyCairo`); se descarta para mantener dos dependencias.
- **Fuera de alcance declarado en §2**: resolvedor público del Digital Link,
  dashboard, telemetría, drivers UHF, GIAI-202, GS1-128/DataMatrix, interfaz web.
- **Tabla de activos del llamador**: la librería no la conoce; `reserve` y
  `next_inventory_number` aceptan `existing_numbers` para incluirla.

## 3. Decisiones propias

Las 31 decisiones están en [`DECISIONES.md`](DECISIONES.md). Las que más
conviene conocer:

1. Renombrado de todo identificador de §7 que §11 prohíbe (`block`,
   `tenant_code`, `gs1_link`, presets `a4-21/65/14`, estados en inglés).
2. Centinela `RESERVED:<tenant>:<número>` con tenant incluido.
3. `issue` con número reservado revincula la reserva en vez de acuñar.
4. `DuplicateAlias` como único error añadido a la lista de §7.
5. `parse_any` devuelve `UNKNOWN` en vez de lanzar.
6. Unicidad del código de tenant además del bloque.
7. `^BY1` en ZPL cuando el alias no cabe a `^BY2` en 50 mm.
8. Anti-fugas: coincidencia por palabra completa con límites alfanuméricos,
   historial barrido sin cabeceras de autor, exención sellada para la frase
   de atribución.

## 4. Resultados de tests

```
pytest                      148 passed
ruff check . / ruff format  All checks passed / 21 files already formatted
gitleaks (árbol e historial) no leaks found
```

Cobertura de los casos de §9:

| Caso | Test |
|---|---|
| 1 | `test_identity.py::test_normalize_inventory_number` |
| 2 | `test_checkchar.py` (determinismo, alfabeto, `é`) |
| 3 | `test_identity.py::test_asset_reference_*` |
| 4 | `test_identity.py::test_alias_*` |
| 5 | `test_identity.py::test_giai_validation` |
| 6 | `test_identity.py::test_gs1_link_and_inverse` |
| 7–9 | `test_epc.py` (ida y vuelta 6/7/10/12, cabecera y partición, errores) |
| 10 | `test_identity.py::test_same_serial_in_two_blocks_gives_distinct_forms` |
| 11 | `test_registry.py::test_block_used_by_another_tenant_is_rejected`, `test_resaving_own_namespace_*` |
| 12 | `test_registry.py::test_issue_is_idempotent_and_serials_are_consecutive` |
| 13 | `test_registry.py::test_issue_without_namespace_fails`, `test_disabled_namespace_blocks_issuing` |
| 14 | `test_registry.py::test_manual_placed_from_issued_is_illegal_but_retire_is_allowed`, `test_lifecycle.py` |
| 15 | `test_registry.py::test_reprint_twice`, `test_reprint_of_retired_label_only_counts` |
| 16 | `test_registry.py::test_resolve_by_every_form` |
| 17 | `test_registry.py::test_mark_placed_from_field` |
| 18 | `test_registry.py::test_verify_scan_detects_crossed_label` |
| 19 | `test_registry.py::test_reserve_three_then_next_number` |
| 20 | `test_registry.py::test_bind_reserved_to_real_asset` |
| 21 | `test_labels_pdf.py` (presets, offset 20, vacío, tildes, logo válido/inválido/data-URI) |
| 22 | `test_zpl.py` (`^RFW,H^FD`, `^BCN`, EPC inválido, `^`/`~`/`ñ`, lote de 2) |
| 23 | `test_no_leaks.py` (árbol + `git log -p`) |

Medidas orientativas (una ejecución, CPython 3.13): ~270 k ida-y-vuelta
EPC/s, ~2 100 emisiones/s en SQLite en memoria, 210 etiquetas con QR y logo
en ~4,4 s. Detalle y reproducción en el README.

## 5. Qué revisar en la fase 3

1. **Nombre de la cuenta.** `LICENSE` y `pyproject.toml` usan el handle de
   GitHub como titular/autor porque el nombre completo figura en la lista de
   palabras prohibidas de la spec. Si se prefiere el nombre real en la licencia,
   hay que añadir una exención sellada en `tests/test_no_leaks.py`.
2. **Cabeceras de autor del historial.** El test barre mensajes y parches
   (`--format=%B`), no autor/committer. El revisor debe decidir si el
   `git log` completo (con autores) cumple la regla, y si los *trailers* de
   coautoría de los commits encajan con la regla 11 («sin IA visible en el
   producto»). Si no, conviene reescribir el historial antes de publicar.
3. **Frase de atribución.** Es la única exención del barrido; aparece en los
   dos README y en ningún otro sitio.
4. **Similitud estructural inevitable con la spec**: la tabla de particiones
   GIAI-96 (norma pública), la geometría de los presets A4 (§6.1) y la tabla
   de transiciones (§5) se copian de la especificación tal cual; cualquier
   coincidencia con la fuente viene de ahí, no del código.
5. **Prefijos de prueba.** Todos los prefijos usados empiezan por `952` (rango
   de demostración GS1); no aparece ningún prefijo de prueba del origen.
6. **La lista sellada** es base64, no cifrado: es legible con un comando. Es lo
   que piden las reglas (ofuscada, no secreta), pero conviene que el revisor lo
   tenga presente al decidir la visibilidad pública.
7. **Sin datos reales**: no hay ficheros binarios ni CSV; los PDF/ZPL de ejemplo
   se generan con `examples/demo.py` y `examples/output/` está en `.gitignore`.
8. **Nombres**: comprobar que ningún identificador coincide de forma no trivial
   con la fuente; los únicos nombres tomados de la spec son los de las
   pseudofirmas de §7 que §11 no prohíbe (`compute_check_char`,
   `normalize_inventory_number`, `build_asset_reference`, `build_giai`,
   `build_alias`, `parse_alias`, `encode_giai96`, `decode_giai96`,
   `derive_identity`, `parse_any`, `issue`, `reserve`, `bind_reserved`,
   `mark`, `reprint`, `mark_placed_from_field`, `resolve_scanned`,
   `verify_scan`, `render_sheet`, `render_single`, `build_zpl`,
   `build_zpl_batch`, y las excepciones).
