# Arquitectura

> Un agente de disputas de cargos no reconocidos. **El modelo interpreta y redacta; el código decide y actúa.**

## 1. Vista general: 4 capas

```mermaid
flowchart LR
    U([Cliente<br/>es / pt]) -->|mensaje + token de sesión| G

    subgraph A[Agente · LangGraph]
        G[Guard<br/>inyección · PII] --> R[Entender<br/>intención + datos]
        R --> F[Buscar<br/>transacción / tarjeta]
        F --> D[Decidir<br/>política]
        D --> X[Actuar<br/>con confirmación]
        D --> H[Handoff<br/>a humano]
    end

    subgraph T[Herramientas bancarias · sandbox]
        TL[tools.py<br/>permisos por sesión]
        ID[identity.py<br/>sesiones con expiración]
    end

    subgraph P[Política]
        PY[policy.yaml<br/>reglas con ID]
    end

    subgraph DATA[Datos]
        S[(serving.duckdb<br/>solo lectura)]
        O[(ops<br/>disputas · bloqueos)]
    end

    F & D & X --> TL
    TL --> ID
    TL --> S
    TL --> O
    D --> PY
    H --> AG([Asesor humano<br/>paquete de handoff])
```

| Capa | Qué hace | Por qué así |
|---|---|---|
| Datos | Contrato por tabla, cuarentena, upsert incremental, linaje | Reproducible y auditable; los problemas se reportan, no se ocultan |
| Herramientas | Única puerta a los datos; derivan el cliente del token | Los permisos no dependen del prompt |
| Política | Reglas declarativas y versionadas | El modelo nunca decide la elegibilidad |
| Agente | Orquesta pasos explícitos | Cada transición está declarada y queda trazada |

## 2. Quién decide qué

| Decisión | Responsable | Tipo |
|---|---|---|
| ¿La sesión es válida? ¿El dato es suyo? | `identity.py` + `tools.py` | Código |
| ¿El mensaje es un ataque? | `guard.py` (`InjectionDetector`) | Patrones (default) · clasificador ONNX opt-in, evaluado en [ADR 0004](adr/0004-deteccion-inyeccion.md) |
| ¿Qué quiere el cliente? | `Router` (interfaz) | Reglas (línea base) · LLM · otro modelo |
| ¿Cuál es la transacción? | `search_transactions` + aclaración | Código; pregunta si hay más de una |
| ¿Procede la disputa o va a un humano? | `policy.yaml` | Reglas con ID |
| ¿Ejecutar la acción? | Cliente (confirmación) + `tools.py` (verificación) | Humano + código |
| ¿Cómo se dice? | `Writer` | Plantillas (línea base) · LLM + verificador *(próximo)* |

## 3. El grafo

Generado desde el código (`Agent.mermaid()`); cada nodo solo puede ir a los destinos declarados en `EDGES`.

```mermaid
flowchart TD
    START([inicio]) --> guard
    guard -->|sesión inválida / ataque| respond
    guard --> understand
    understand -->|"sí" a acción pendiente| act
    understand -->|"no"| cancel
    understand -->|elige opción| select_option
    understand -->|disputa| find_transaction
    understand -->|bloqueo| find_card
    understand -->|fuera de alcance| handoff
    understand -->|poca confianza| respond
    find_transaction -->|1 candidata| decide
    find_transaction -->|0 o varias: pregunta| respond
    find_transaction -->|herramienta caída| handoff
    select_option --> decide
    find_card --> respond
    decide -->|regla handoff| handoff
    decide -->|rechazo / pedir confirmación| respond
    act -->|verificado| respond
    act -->|no verificado| handoff
    cancel --> respond
    handoff --> respond
    respond --> END([fin del turno])
```

El estado persiste entre turnos (checkpointer por conversación). Así funcionan las aclaraciones ("¿cuál de estas?") y las confirmaciones ("¿confirmas?").

## 4. Una disputa de punta a punta

```mermaid
sequenceDiagram
    actor C as Cliente
    participant A as Agente
    participant T as Herramientas
    participant P as Política
    C->>A: "No reconozco un cargo de 77 dólares"
    A->>A: guard (sin ataque, PII enmascarada)
    A->>A: understand → disputa, monto≈77
    A->>T: search_transactions(token, 69–85)
    T-->>A: 1 transacción (solo del dueño del token)
    A->>T: get_transaction · get_profile · dispute_history
    A->>P: decide_dispute(hechos verificados)
    P-->>A: auto_with_confirmation (ninguna regla de bloqueo)
    A-->>C: "Encontré el cargo … ¿Confirmas?"
    C->>A: "sí"
    A->>T: open_dispute(confirmed) · block_card(confirmed)
    T-->>A: verified=true
    A-->>C: "Abrí la disputa DSP-… y bloqueé la tarjeta ****4111"
```

## 5. Datos: raw → serving

```mermaid
flowchart LR
    S3[(S3 organizador<br/>CSV particionado)] --> RAW[data/raw]
    RAW --> STG[staging<br/>proyección + normalización<br/>+ enmascarado]
    STG --> CHK{contrato<br/>tipos · obligatorios<br/>dominios · FKs}
    CHK -->|ok| UP[upsert por PK<br/>gana la versión más reciente]
    CHK -->|falla| Q[(quarantine_*<br/>fila + motivo)]
    UP --> SV[(serving.duckdb)]
    STG -.-> MAN[runs/&lt;run_id&gt;.json<br/>linaje: archivos, filas,<br/>cuarentena, advertencias]
```

- **Incremental por archivo:** el pipeline guarda qué archivos procesó. Un archivo nuevo, aunque sea de un día viejo (llegada tardía), se procesa y se hace upsert. Re-ejecutarlo no duplica nada.
- **Frescura:** foto fija con `as_of` = 2026-06-17. En producción serían particiones diarias con reproceso de 3 días y una alerta si `max(process_date)` tiene más de 2 días de atraso.
- **Minimización:** solo se cargan las columnas que el flujo usa y el número de tarjeta se enmascara al ingerir.
- Hallazgos de calidad: [`reports/EDA_findings.md`](../reports/EDA_findings.md).

## 6. Fronteras de confianza

```mermaid
flowchart LR
    subgraph NT[No confiable]
        MSG[Texto del cliente]
        DAT[Texto dentro de los datos<br/>ej. nombre de comercio]
        LLM[Salida del modelo]
    end
    subgraph TR[Confiable · código]
        GU[guard]
        TO[tools<br/>permisos por sesión]
        PO[policy.yaml]
        VE[verificación de acciones]
    end
    MSG --> GU --> LLM
    DAT -->|se trata como dato,<br/>nunca como instrucción| LLM
    LLM -->|solo propone: intención, slots, texto| TO
    TO --> PO --> VE
```

**Defensa en profundidad:** aunque el guard no detecte un ataque, el ataque no tiene con qué hacer daño. El cliente sale del token y no del texto, cada acción requiere confirmación y se verifica, y la política no está en el prompt. Por eso reportamos por separado la **detección** (el guard) y el **daño** (registros señuelo): ver [`reports/injection_eval.md`](../reports/injection_eval.md).
