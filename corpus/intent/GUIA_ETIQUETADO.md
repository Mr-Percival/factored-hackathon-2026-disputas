# Guía de etiquetado · corpus de intención (es/pt)

Corpus **generado por el equipo** para entrenar y evaluar el router de intención (ADR 0009). No contiene
texto de clientes reales ni del dataset del organizador (ADR 0003: sus textos son plantillas y sus
etiquetas no son válidas). Cada enunciado es **un primer mensaje** del cliente al asistente, sin contexto
previo (`awaiting = null`). Las respuestas cortas a una pregunta del agente (sí/no/"la 2") no se etiquetan
aquí: las resuelve `RuleRouter` por contexto.

## Etiquetas (exactamente una por enunciado)
Orden de precedencia cuando hay más de una señal: **account_takeover > cancel_dispute > dispute_status >
dispute_charge > block_card > human_request > out_of_scope > closing > unknown**. Excepción: si el cliente
pide explícitamente un humano y *no* describe ningún problema concreto, es `human_request`.

> **v2 (2026-09-29).** El grafo sumó dos intenciones de usuario (#54): `dispute_status` y `cancel_dispute`.
> Se agregaron a esta guía; los enunciados existentes se re-revisaron contra las dos etiquetas nuevas
> (`review/schema_v2_relabel.jsonl`) y los nuevos ejemplos van en archivos de autores **nuevos** (F → train,
> G → test), sin tocar los archivos ya escritos ni mezclar autores entre splits.

| Etiqueta | Definición | Sí | No (y qué es) |
|---|---|---|---|
| `dispute_charge` | No reconoce / contesta **un cargo o movimiento concreto**: no lo hizo, cobro duplicado, monto distinto, servicio cancelado que se sigue cobrando, cajero que no entregó el dinero, compra que no llegó y se cobró. | "no reconozco un cargo de 350 en Amazon"; "me cobraron dos veces el súper"; "o caixa eletrônico não liberou o dinheiro mas debitou" | "¿cuánto cobran de comisión?" (`out_of_scope`); "reconozco el cargo pero quiero pagarlo en cuotas" (`out_of_scope`) |
| `dispute_status` | Pregunta por el **estado / avance / respuesta de una disputa o reclamo ya presentado** (con o sin número de caso `DSP-…`). | "¿en qué va mi reclamo DSP-4821?"; "hace 10 días abrí una disputa y nadie me responde"; "qual o andamento da minha contestação?" | "¿cuánto tarda una disputa en general?" (`out_of_scope`: pregunta informativa, no por su caso); "quiero abrir una disputa" (`dispute_charge`) |
| `cancel_dispute` | Quiere **retirar / cancelar una disputa ya presentada**, o avisa que el cargo que reclamó **sí era suyo**. | "quiero cancelar la disputa que abrí ayer"; "ya reconocí el cargo, era mío, retiren el reclamo"; "pode cancelar a contestação, era minha" | "cancelar mi tarjeta" (`block_card`); "reconozco el cargo pero quiero pagarlo en cuotas" (`out_of_scope`) |
| `block_card` | Quiere bloquear / congelar / cancelar **una tarjeta** (pérdida, robo, olvido, sospecha) **sin** mencionar un cargo desconocido concreto. | "perdí mi tarjeta, bloquéala"; "me robaron la cartera"; "quero bloquear meu cartão" | "quiero desbloquear mi tarjeta" (`out_of_scope`); "me robaron la tarjeta y hay un cargo que no hice" (`dispute_charge`) |
| `account_takeover` | Señales de **acceso indebido a la cuenta o credenciales**: alguien entró a la app/banca en línea, cambiaron clave/correo/teléfono, SIM swap, le pidieron el código/OTP por teléfono y lo dio, phishing. Tiene precedencia aunque mencione cargos. | "alguien cambió mi contraseña y no puedo entrar"; "passei o código do SMS para um suposto atendente" | "olvidé mi contraseña" (`out_of_scope`: no hay tercero) |
| `human_request` | Pide explícitamente una persona, asesor, ejecutivo, llamada, o rechaza al bot, sin describir un problema de disputa/bloqueo/acceso. | "quiero hablar con un asesor"; "me passa pra um atendente humano"; "no quiero un robot" | "quiero hablar con alguien porque no reconozco un cargo" (`dispute_charge`) |
| `out_of_scope` | Tema **bancario** que el agente no atiende: saldo, préstamos, límite, inversiones, seguros, transferencias, estados de cuenta, comisiones, desbloqueo, PIN, apertura de cuenta, envío de plástico, olvido de clave, reclamo por atención. | "¿cuál es mi saldo?"; "quero aumentar o limite"; "¿me explican la tasa del préstamo?" | "hola" (`unknown`) |
| `closing` | Cierre o agradecimiento sin pedido nuevo. | "gracias, eso era todo"; "valeu, tchau"; "listo, chau" | "gracias, pero todavía no me devolvieron el cargo" (`dispute_charge`) |
| `unknown` | Saludo solo, texto vago sin pedido ("tengo un problema"), no bancario, ruido, incompleto. | "hola buenas"; "tengo una duda"; "¿qué hora es?"; "asdf" | "hola, perdí la tarjeta" (`block_card`) |

## Campos del archivo (`*.jsonl`, un objeto por línea)
| Campo | Valor |
|---|---|
| `text` | El mensaje tal cual lo escribiría el cliente (sin datos reales: montos, comercios y fechas inventados; nunca números de tarjeta completos, emails ni teléfonos reales). |
| `intent` | Una de las 9 etiquetas. |
| `dialect` | `es-MX`, `es-CO`, `es-AR` (voseo), `pt-BR` o `mix` (portuñol / code-switching). |
| `family` | Id de la **familia de paráfrasis**: todos los enunciados que nacen de la misma idea semilla comparten familia (p. ej. `A-017`). Las familias nunca se parten entre splits. |
| `hard_negative` | `true` si está pensado para confundir (palabras clave de otra intención, negaciones, "desbloquear", "comisión", "cobran"…). |
| `style` | Texto libre corto: `chat`, `typos`, `formal`, `voz`, `terse`, `largo`, `emoji`… |

El `author` y el `id` (`<autor>-<línea>`) los agrega `scripts/train_intent.py` a partir del nombre y la línea del archivo.

## Reglas para quien escribe
1. Varía largo, registro, orden de la información y dialecto; incluye errores de tipeo reales, sin tildes,
   abreviaturas ("q", "pq", "vc", "tb"), mayúsculas y emojis ocasionales.
2. Cada familia = 1 idea semilla + 2–5 paráfrasis (misma etiqueta). No copies frases entre familias.
3. Quien escribe los archivos de **prueba** no lee `src/bankagent/understanding.py` (las reglas) ni los
   archivos de entrenamiento: así la prueba no se escribe "a favor" ni "en contra" de las reglas.
4. Si dudas de la etiqueta, aplica la precedencia; si sigue ambigua, no la incluyas.
