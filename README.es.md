# asset-identity-gs1

**Identidad GS1 para los activos físicos de un inventario: una identidad, cuatro formas equivalentes, unicidad sin servidor.**

[English version](README.md) · Paquete Python `assetid` · MIT · CI en Python 3.11 y 3.12

```python
from assetid import Namespace, derive_identity

ns = Namespace("9520012", block=1000, tenant_code="NOR", resolver_domain="verify.example.org")
identity = derive_identity(ns, serial=42, inventory_number="MOB-0042")

identity.giai      # '9520012100000000042'                      clave GS1 (AI 8004)
identity.alias     # 'AID-NOR-MOB0042-1'                        código de barras y personas, control mod-43
identity.epc       # '3416450E300000174876E82A'               GIAI-96 para chips RFID UHF
identity.gs1_link  # 'https://verify.example.org/8004/9520012100000000042'   carga del QR
```

Este repositorio es un **caso de estudio clean-room**: se reconstruyó a partir
de una especificación escrita, sin acceso al código original, y todos los datos
que contiene son sintéticos. Véase [Atribución](#atribución).

---

## El problema

Organizaciones públicas y privadas mantienen un inventario de activos físicos
(edificios, mobiliario, equipos, obras de arte) que hay que **rotular** y
después **reconocer en campo** con pistola láser, cámara de móvil o lector RFID
UHF. Tres cosas lo complican más que imprimir un código de barras:

1. **Varias sedes, varios tenants.** Cada sede etiqueta a su ritmo, a menudo sin
   conexión y en sus propias instalaciones. Dos sedes no pueden producir nunca
   el mismo código.
2. **Tres lectores, una identidad.** La pistola lee texto, el móvil lee una URL
   y el lector RFID devuelve 96 bits. Todos tienen que resolver al mismo activo.
3. **La etiqueta sobrevive al modelo de datos.** Los números de inventario se
   renumeran, los activos se vuelven a dar de alta, las etiquetas se imprimen
   antes de que el activo exista en el sistema. La identidad debe aguantar todo
   eso.

## Restricciones

- **Interoperable**: la clave canónica es un GIAI de GS1 (AI 8004), legible por
  cualquier sistema GS1; la forma RFID sigue el EPC Tag Data Standard.
- **Sin coordinación en tiempo de ejecución**: un tenant debe poder emitir e
  imprimir con la autoridad central inaccesible.
- **Chips baratos**: la forma RFID tiene que caber en memoria EPC de 96 bits
  (GIAI-96), lo que descarta referencias alfanuméricas.
- **Apta para campo**: el alias impreso lleva carácter de control visible para
  detectar un número mal tecleado antes de que llegue a la base de datos.
- **Python puro**, dependencias mínimas (reportlab, Pillow), persistencia SQLite.

## Arquitectura

```
            autoridad de namespace (una vez por tenant)
            ──────────────────────────────────────────
            prefijo de empresa · bloque · código de tenant · dominio resolvedor
                               │
                               ▼
   ┌──────────────── identidad (funciones puras) ───────────────┐
   │  (prefijo, bloque, serial) ──► referencia de activo (12)   │
   │                            ──► GIAI = prefijo ‖ referencia │
   │                            ──► EPC  = GIAI-96 (96 bits)    │
   │                            ──► GS1 Digital Link /8004/…    │
   │  (código de tenant, nº inventario) ──► alias + control     │
   └────────────────────────────────────────────────────────────┘
                               │
                               ▼
   ┌──────────────── registro (SQLite) ─────────────────────────┐
   │ NamespaceRegistry  asignar / colisión / habilitar          │
   │ LabelRegistry      emitir · reservar · vincular · marcar   │
   │                    reimprimir · cierre en campo · resolver │
   │ ciclo de vida      ISSUED → PRINTED → PLACED → RETIRED     │
   └────────────────────────────────────────────────────────────┘
                               │
                               ▼
   ┌──────────────── render ────────────────────────────────────┐
   │ labels_pdf   hojas A4 (21/65/14 por hoja), etiqueta suelta,│
   │              Code128 + QR + logo, PDF vectorial            │
   │ zpl          escritura ^RFW del EPC + cara impresa para    │
   │              impresoras-codificadoras RFID                 │
   └────────────────────────────────────────────────────────────┘
```

| Módulo | Responsabilidad |
|---|---|
| `assetid.identity` | `Namespace`, normalización, referencia de activo, GIAI, Digital Link, alias, `derive_identity`, `parse_any` |
| `assetid.checkchar` | carácter de control mod-43 (el algoritmo de Code 39) |
| `assetid.epc` | codificación y decodificación GIAI-96 con la tabla de particiones del TDS |
| `assetid.lifecycle` | máquina de estados y tabla de transiciones |
| `assetid.registry` | `Store` (SQLite), `NamespaceRegistry`, `LabelRegistry`, eventos de auditoría |
| `assetid.labels_pdf` | presets de hoja, `render_sheet`, `render_single`, `LabelFace` |
| `assetid.zpl` | `build_zpl`, `build_zpl_batch`, saneado de texto |
| `assetid.synthetic` | generadores deterministas de tenants, activos y logo |

### Unicidad por construcción

La referencia de activo de 12 dígitos es `bloque(4) ‖ serial(8)`. Una autoridad
central entrega a cada tenant **un bloque, una sola vez**; después el tenant
incrementa su serial en local. Bloques distintos dan GIAI y EPC distintos
aunque dos tenants lleguen al mismo serial, igual que los prefijos de las
direcciones MAC o los prefijos de empresa GS1. La autoridad solo comprueba
colisiones al asignar (`NamespaceCollision`, HTTP 409 en una API); al imprimir
no se consulta nada.

### Dos números, un registro

El **serial** alimenta el GIAI y el EPC y nunca cambia. El **número de
inventario** alimenta el alias (`AID-<TENANT>-<NÚMERO>-<control>`) porque es lo
que la gente reconoce. Los liga el registro, no la aritmética, así que una
renumeración nunca invalida un chip.

### Etiquetas antes que activos

Una sede puede reservar un lote de identidades (`M-0001`, `M-0002`, …) antes de
que existan los activos. Cada reserva consume un serial y vive bajo un
propietario centinela (`RESERVED:<tenant>:<número>`), de modo que no infla los
indicadores. Cuando por fin se da de alta el activo con ese número, la reserva
se vincula a él y la etiqueta ya está `PLACED`.

## Decisiones y alternativas descartadas

| Decisión | Descartada | Motivo |
|---|---|---|
| **GIAI** como clave canónica | SGTIN | Un bien patrimonial es un activo individual sin GTIN de producto; GIAI es la clave GS1 para activos propios y su referencia larga permite repartir tenants |
| **Partición** del namespace | Registro central consultado al imprimir | Las sedes imprimen offline y on-premise; la partición da unicidad por construcción y el verificador cloud queda como añadido |
| Referencia **numérica** fija | GIAI-202 (alfanumérico) | Cabe en chips de 96 bits y empaqueta bloque + serial |
| **Code128** | Code 39 | Más denso (cabe en celdas de 63 mm), minúsculas y símbolos, checksum interno |
| Control **mod-43** visible | mod-10 | El alias es alfanumérico; mod-43 cubre letras y guion |
| Alias del **nº de inventario**, GIAI del **serial** | Un único número | El operario reconoce su número; el serial sobrevive a renumeraciones; el registro los liga |
| QR = **GS1 Digital Link** | QR con el alias | Una carga que es a la vez URL de verificación y clave GS1 |
| Reserva con **centinela** | Activos vacíos de relleno | No contamina indicadores; el alta hereda el código ya pegado |
| reportlab para **Code128 y QR** | python-barcode + qrcode | Un solo backend vectorial, sin paso raster, menos dependencias |

Todo lo que la especificación dejaba abierto está registrado, con alternativas,
en [`docs/DECISIONES.md`](docs/DECISIONES.md).

## Qué se midió y cómo reproducirlo

Medido en una ejecución de los generadores sintéticos incluidos (CPython 3.13,
un núcleo, sin ajustes). Cifras orientativas, no benchmarks.

| Operación | Resultado |
|---|---|
| Ida y vuelta GIAI-96 (codificar + decodificar) | ~270 000 / s |
| Construcción de alias con carácter de control | ~720 000 / s |
| `LabelRegistry.issue` (SQLite en memoria / en disco) | ~2 100 / s · ~540 / s |
| `resolve_scanned` por Digital Link | ~70 000 / s |
| Render de 210 etiquetas (10 hojas de 21) con QR y logo | ~4,4 s, 264 KiB |
| Render de 210 etiquetas (65 por hoja, sin QR) | ~0,07 s |
| Lote ZPL de 210 etiquetas | ~1 ms |

El codificador QR domina el render de hojas (unos 20 ms por código); lotes de
cientos de etiquetas van bien, decenas de miles no son interactivos.

Reproducir:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest                      # 148 tests, incluido el barrido anti-fugas
ruff check . && ruff format --check .
python examples/demo.py     # escribe examples/output/{sheet-a4-21.pdf,single.pdf,batch.zpl,labels.sqlite}
```

La suite sigue uno a uno los 23 casos de prueba de la especificación
(`tests/test_identity.py`, `test_epc.py`, `test_registry.py`,
`test_labels_pdf.py`, `test_zpl.py`, `test_no_leaks.py`).

## Uso en pocas líneas

```python
from assetid import LabelFace, LabelRegistry, LabelState, Namespace, NamespaceRegistry, Store
from assetid import build_zpl_batch, render_sheet

store = Store("labels.sqlite")                       # ":memory:" por defecto
NamespaceRegistry(store).assign("sede-norte", Namespace("9520012", 1000, "NOR", "verify.example.org"))
registry = LabelRegistry(store)

label = registry.issue("sede-norte", asset_id="asset-17", inventory_number="MOB-0042", by="clerk")
registry.reprint("asset-17")                         # PRINTED, reprint_count == 1
registry.mark_placed_from_field("asset-17")          # PLACED (desde ISSUED pasa por PRINTED)
registry.verify_scan("asset-17", "AID-NOR-MOB0042-1")   # True / False (etiqueta cruzada) / None (sin lectura)

reserved = registry.reserve("sede-norte", 3)         # M-0001..M-0003 bajo un propietario centinela
registry.bind_reserved("sede-norte", "M-0002", "asset-18")

pdf = render_sheet([LabelFace.from_label(label, description="Silla de oficina")], "Ayuntamiento de Ejemplo")
zpl = build_zpl_batch([label], org_name="Ayuntamiento de Ejemplo")
```

## Límites conocidos

- **Decodificadores TDS estrictos.** Las reglas GIAI-96 de GS1 dicen que la
  referencia de activo no debe empezar por cero. Con un bloque por debajo de
  1000 la referencia rellenada sí empieza así (`0014…`), y un decodificador
  estricto de terceros devolverá menos dígitos. Esta librería rellena al
  decodificar; para conformidad total asigne bloques ≥ 1000 o use
  `Namespace(strict=True)`.
- **Valores de filtro** distintos de 0 se aceptan, pero su significado en
  GIAI-96 no está definido aquí.
- **La geometría de hoja** aproxima plantillas habituales de fabricante;
  calibre los presets (o use `outlines=True`) antes de una tirada real.
- **Sin salida PNG**, sin GIAI-202, sin GS1-128/DataMatrix, sin resolvedor
  público detrás del Digital Link, sin drivers de lector, sin interfaz web
  (todo fuera de alcance).
- **SQLite de un solo escritor.** La emisión se serializa con `BEGIN IMMEDIATE`;
  está pensada para la base de una sede, no para un servicio multiproceso.
- **Anchura de módulo ZPL**: baja a un punto (0,125 mm a 203 dpi) cuando un
  alias de 17 caracteres no cabe en la etiqueta de 50 mm por defecto; use
  etiquetas más anchas o 300 dpi.

## Cómo se construyó

Proceso clean-room en tres fases: (1) se redactó una especificación a partir
del sistema original, sin código; (2) este repositorio se implementó en una
sesión nueva solo con la especificación y las normas públicas, con un asistente
de programación con IA llevando la implementación bajo revisión; (3) una
revisión independiente compara ambos antes de publicar. El test anti-fugas de
`tests/test_no_leaks.py` guarda una lista sellada de términos que nunca pueden
aparecer en el árbol ni en el historial.

## Atribución

Patrones desarrollados durante mi trabajo en Intervalor Data y publicados con
autorización. Implementación independiente (clean-room) con datos sintéticos;
no contiene código ni datos de la empresa ni de sus clientes.

## Licencia

MIT, véase [LICENSE](LICENSE).
