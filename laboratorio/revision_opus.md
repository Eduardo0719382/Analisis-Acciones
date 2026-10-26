# Protocolo de la revisión semanal (Opus)

Se ejecuta el **sábado** (tras el cierre del viernes) o cuando el usuario la pida. Evalúa el
**criterio** de cada agente, no solo su resultado, y decide con los criterios escritos aquí
**de antemano**. Cuenta paper, dinero ficticio; nunca cuenta real.

Repositorio: `C:\Users\eduar\Documents\Analisis-Acciones`, rama `lab/experimentos` (nunca
`main` ni la rama por defecto). `lab` = `.venv\Scripts\python.exe -m analisis_acciones.app.lab_cli`.

## 1. Reunir los datos (solo lectura)

1. `git checkout lab/experimentos` y `git status` (no pises cambios ajenos; si hay cambios sin
   commit que no son tuyos, detente y avisa).
2. `lab reconciliar` (descuadres y comisiones de cripto publicadas frente a estimadas).
3. `lab informe --desde <fecha ISO del sábado anterior>` y `lab informe --json`.
4. Para cada perfil: `lab decisiones Pxx --desde <misma fecha>` (motivo, propuesta, qué hizo
   el ejecutor y qué rechazó, precio real y costes).
5. Lee `EXPERIMENTOS.md` (semanas anteriores) y `laboratorio/perfiles.json`.

## 2. Métricas por perfil

Del informe: rentabilidad neta de costes, caída máxima, nº de operaciones, % de acierto
(ventas con resultado positivo), costes pagados y diferencia con comprar y mantener SPY, QQQ y
BTC desde el inicio del perfil. No calcules nada que el informe no dé; un valor ausente es
«—», nunca una estimación.

## 3. Auditar el criterio

Para cada perfil, con sus decisiones y motivos:

- ¿Respetó su personalidad e hipótesis, o hizo otra cosa?
- ¿Vendió por pánico (venta con pérdida sin señal ni stop y recompra en < 48 h)?
- ¿Sobreoperó (muchas operaciones cuyo objetivo apenas superaba el coste)?
- ¿Ignoró sus propias señales (las herramientas decían una cosa y el motivo otra sin explicar)?
- ¿La tesis tenía sentido aunque perdiera? Una pérdida con buen criterio no es un fallo.
- ¿Cuántas órdenes rechazó el ejecutor y por qué (límites mal leídos, formato)?

## 4. Decidir (criterios fijos)

**Muestra mínima** antes de eliminar: al menos 2 semanas de vida **y** 10 decisiones reales
(5 para semanales; los mensuales, 3 meses). Sin muestra, dilo explícitamente: «sin muestra
suficiente, no se juzga».

| Acción | Cuándo |
|---|---|
| **Eliminar** | Con muestra suficiente: cumple su propio criterio de `fallo`; o pierde > 15 % neto y queda detrás de las tres referencias 3 semanas seguidas; o los costes superan el 50 % de su ganancia bruta 3 semanas seguidas. |
| **Pausar** (`estado: "pausado"`, solo vende) | Descuadre de reconciliación sin explicar en sus activos; ≥ 3 rechazos por formato o límites mal leídos en la semana; o alcanzó `stop_perfil_pct`. |
| **Ajustar** (instrucciones, límites u horario) | Criterio inconsistente con su hipótesis, sobreoperación, ventas por pánico, o un límite que se activa sin aportar. |
| **Mantener** | Todo lo demás, incluso con una mala semana sin muestra suficiente. |

- **Máximo 1–2 cambios por perfil por semana**, para saber qué causó qué. Anota el antes y
  el después.
- Eliminar = `estado: "eliminado"` en `perfiles.json` (nunca se borra el perfil ni sus datos).
  Sus posiciones las vende la siguiente ejecución diaria (`lab grupo` lo indica en `liquidar`)
  o tú con `lab liquidar Pxx --send` si el mercado de esas posiciones está abierto. Sus
  100 USD virtuales quedan libres.
- Un perfil nuevo usa el siguiente id libre (P12, P13…), con una hipótesis **distinta** de
  las vivas y de las eliminadas, y sus límites completos. Su libro empieza en su primer turno.
- Si cambias una `frecuencia` y eso requiere otro horario, actualiza la tarea programada
  correspondiente (`lab-1h`, `lab-4h`, `lab-diario`) y dilo.

## 5. Registrar y subir

1. `lab exportar experimentos/datos/<AAAA-MM-DD>` (copia de los libros, órdenes, decisiones y
   precios: los datos de los eliminados se conservan aquí para siempre).
2. Actualiza `EXPERIMENTOS.md`: añade la semana arriba con
   - la tabla del informe;
   - por perfil: decisión (mantener / ajustar / pausar / eliminar), por qué, y si no había
     muestra suficiente;
   - auditoría del criterio (2–4 líneas por perfil, con ejemplos de decisiones);
   - perfiles eliminados con su historial completo (resumen y ruta de sus datos exportados);
   - lecciones aprendidas.
3. Si cambió alguna decisión de diseño, añade la entrada siguiente en `DECISIONS.md`.
4. `git add laboratorio/perfiles.json EXPERIMENTOS.md experimentos/ DECISIONS.md`,
   commit descriptivo («Revisión semanal AAAA-MM-DD: P03 ajustado (…), P02 eliminado (…)»),
   y `git push origin lab/experimentos`. Nunca a `main` ni con `--force`.
5. Resume: qué funcionó, qué cambió y por qué, y qué vigilar la semana siguiente. Reporta
   solo lo ejecutado y verificado.
