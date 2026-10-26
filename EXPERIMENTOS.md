# Bitácora de experimentos — laboratorio en Alpaca paper

Once perfiles de 100 USD virtuales dentro de la cuenta **paper** de Alpaca (dinero ficticio).
Cada perfil es un agente Sonnet con su hipótesis; la revisión semanal (Opus) evalúa su
criterio y decide con los criterios de `laboratorio/revision_opus.md`. Solo se anota lo
ejecutado y verificado. Los datos completos de cada semana quedan en `experimentos/datos/`.
Nada de esto es asesoramiento financiero.

Referencias de cada perfil: comprar y mantener SPY, QQQ y BTC con los mismos 100 USD desde el
inicio de ese perfil (BTC con su comisión de compra).

## Perfiles

| Perfil | Hipótesis (resumen) | Frecuencia | Universo | Aviso de costes |
|---|---|---|---|---|
| P01 Ráfaga cripto | el impulso de 1 h paga el 0,5 % de ida y vuelta | 1 h | BTC, ETH, SOL | **alto**: hasta 4 órdenes/día a ~0,52 % la ida y vuelta |
| P02 Memecoins | rachas de impulso con volumen | 4 h | DOGE, SHIB, PEPE, BONK, WIF, TRUMP | **alto**: spreads de 0,3–1 %, ida y vuelta 0,8–1,5 % |
| P03 Reversión cripto | las caídas extremas rebotan a la media | 4 h | 9 cripto grandes | **medio-alto**: ida y vuelta 0,5–1,1 % |
| P04 DCA BTC/ETH | DCA reduce la caída frente a comprar todo de golpe | semanal | BTC, ETH | bajo (10 USD/semana, sin ventas) |
| P05 Magníficas en tendencia | seguir la tendencia diaria bate a QQQ con menos caída | diaria | QQQ + 7 Magníficas | bajo |
| P06 Elliott y patrones | rupturas confirmadas y ondas 3 dan buena relación beneficio/riesgo | diaria | 7 acciones + BTC, ETH, SOL | bajo-medio |
| P07 Valor (Graham) | PER bajo + márgenes + dividendo baten al mercado con menos volatilidad | semanal | 13 grandes empresas | bajo |
| P08 Agotamiento contrario | el agotamiento anticipa giros en ETF | diaria | SPY, QQQ, IWM, XLK, XLE, XLF, SMH | bajo |
| P09 Rotación mixta | rotar a los 2 mejores por impulso relativo | semanal | SPY, QQQ, GLD, TLT, BTC, ETH | bajo-medio |
| P10 Escéptico selectivo | operar solo con confluencia reduce la caída | diaria | 7 acciones + 6 cripto | bajo |
| P11 Largo plazo mensual | revisar una vez al mes rinde como QQQ con menos costes | mensual | 5 acciones + BTC, ETH | muy bajo |

Criterios de fallo de cada perfil: campo `fallo` en `laboratorio/perfiles.json`.

---

## Revisión 1 — 2026-10-26 (lunes, primer día de operación)

Revisión lanzada por la tarea programada el mismo día en que arrancaron los libros (primeras
decisiones entre las 06:31 y las 15:05 UTC). Informe con `--desde 2026-10-24`, a las
20:25 UTC. Datos: `experimentos/datos/2026-10-26/`.

| Perfil | Valor | Neto | Caída máx. | Oper. | Acierto | Costes | SPY · QQQ · BTC | Decisiones |
|---|---:|---:|---:|---:|---:|---:|---|---|
| P01 Ráfaga cripto | 100.00 | +0.00 % | 0.00 % | 0 | — | 0.00 | +0.67 · +1.02 · −0.42 % | 14 nada |
| P02 Memecoins | 100.00 | +0.00 % | 0.00 % | 0 | — | 0.00 | +0.67 · +1.02 · −0.59 % | 3 nada |
| P03 Reversión cripto | 100.00 | +0.00 % | 0.00 % | 0 | — | 0.00 | +0.67 · +1.02 · −0.59 % | 3 nada |
| P04 DCA BTC/ETH | 99.94 | −0.06 % | 0.06 % | 1 | — | 0.02 | +0.67 · +1.02 · −0.59 % | 1 compra |
| P05 Magníficas | 100.00 | +0.00 % | 0.00 % | 0 | — | 0.00 | −0.27 · −0.27 · −0.93 % | 1 nada |
| P06 Elliott y patrones | 100.00 | +0.00 % | 0.00 % | 0 | — | 0.00 | +0.67 · +1.02 · −0.59 % | 1 nada |
| P07 Valor (Graham) | 99.51 | −0.49 % | 0.49 % | 3 | — | 0.00 | −0.27 · −0.27 · −0.93 % | 1 compra |
| P08 Agotamiento ETF | 100.00 | +0.00 % | 0.00 % | 0 | — | 0.00 | −0.28 · −0.27 · −0.93 % | 1 nada |
| P09 Rotación mixta | 99.77 | −0.23 % | 0.23 % | 1 | — | 0.11 | +0.67 · +1.02 · −0.59 % | 1 compra |
| P10 Escéptico | 100.00 | +0.00 % | 0.00 % | 0 | — | 0.00 | +0.67 · +1.02 · −0.59 % | 1 nada |
| P11 Largo plazo | 99.61 | −0.39 % | 0.39 % | 5 | — | 0.03 | −0.27 · −0.26 · −0.93 % | 1 compra |

**Reconciliación:** sin descuadres ni órdenes actualizadas. Comisión de cripto estimada
2,053e-06 BTC, publicada 0 todavía (Alpaca la publica al día siguiente; se comprueba en la
próxima revisión).

### Decisiones

**Sin muestra suficiente, no se juzga ningún perfil**: todos tienen menos de un día de vida
(mínimo: 2 semanas y 10 decisiones; 5 los semanales; 3 meses el mensual). Ningún perfil
cumple condiciones de pausa: no hay descuadres, ni ≥ 3 rechazos, ni stops alcanzados.
**Los 11 se mantienen sin cambios**; `perfiles.json` no se toca.

### Auditoría del criterio

- **P01:** 14 turnos, todos «nada». La razón es coherente con la hipótesis: BTC, ETH y SOL
  están bajo sus medias y ninguna resistencia cercana ofrece el doble del coste de ~0,52 %.
  Dice qué le haría entrar. Se ajusta a su papel; no hay sobreoperación.
- **P02:** 3 × «nada». Las memecoins están bajo SMA20/50 y caen entre un 17 y un 29 % en 20
  días. Descarta WIF, en sobreventa con agotamiento 3/6, porque no es impulso y el historial
  es corto. Es disciplinado y desconfía de lo que no encaja en su estilo.
- **P03:** 3 × «nada». Exige a la vez RSI bajo, agotamiento y soporte. Descarta ADA (RSI 29,7)
  porque tiene la resistencia al 0,26 %, sin recorrido. Es correcto: no anticipa.
- **P04:** compró 10 USD de BTC según la alternancia y sin pausa, porque no había
  agotamiento alcista. Cumple al pie de la letra.
- **P05:** «nada». Solo AAPL está en tendencia, y publica resultados el 2026-11-02; su regla
  le veta comprar antes. Es coherente.
- **P06, P08 y P10:** «nada»:
  - P06 y P10 (07:27 UTC) solo podían operar cripto y no vieron patrón ni confluencia.
  - P08 no encontró ninguna señal de agotamiento en los ETF.
  - Los tres eligen bien el efectivo por defecto.
- **P07:** propuso 4 compras de 20 USD: JPM, VZ, BAC y GOOGL, todas con PER < 20. El ejecutor
  rechazó GOOGL por el **límite de 3 operaciones al día**. Es 1 rechazo por un límite mal
  leído; la pausa exige ≥ 3. El criterio de valor es correcto: no forzó un quinto nombre.
  Hay una tensión que vigilar:
  - Sus instrucciones piden 5 nombres o más.
  - Siendo semanal con 3 operaciones al día, tardará al menos 2 semanas en diversificar.
  - Si se repite, el límite se activaría «sin aportar» y sería motivo para ajustarlo.
  - Ahora tiene 3 nombres y ~40 USD en efectivo.
  - La compra de JPM se ejecutó a 335,09 con un bid/ask IEX de 330,22/350,97. Ese spread no
    es representativo (D-080). El precio está dentro del rango, pero explica parte del −0,49 %.
- **P09:** compró 45 USD de BTC como único líder con tendencia alcista. SPY no se podía
  comprar con la bolsa cerrada. Usa «impulso de 20 barras» y dice que BTC sube +26,5 %,
  mientras P01 y P02 ven BTC con −6 a −16 % en 20 días.
  - Lo probable es que P09 mire barras semanales, coherente con su frecuencia, pero **no se
    ha verificado**.
  - Si eran diarias, la tesis estaría mal leída.
  - En la próxima revisión hay que comprobar en las herramientas qué marco temporal recibe.
- **P11:** construyó la cartera (MSFT, GOOGL, AMZN, SPY y 12 USD de BTC), evitó NVDA por
  agotamiento 4/6 y dejó ETH por el límite de 5 operaciones. Planificó dentro del límite, sin
  rechazos.
  - Contradicción por aclarar: P11 ve MSFT, GOOGL y AMZN «sobre SMA20/50/200». P05, un
    minuto antes, ve GOOGL y AMZN bajo SMA50 y MSFT con cruce bajista del MACD.
  - Puede deberse a marcos temporales distintos según la frecuencia del perfil. **Sin
    verificar**: si es el mismo marco, uno de los dos leyó mal sus señales.

### Eliminados

Ninguno.

### Lecciones y qué vigilar

- Arranque prudente: 7 de 11 perfiles en efectivo. Las referencias se movieron menos de
  ±1,1 %, así que aún no se puede comparar nada.
- Los perfiles con 0 operaciones no tendrán acierto ni muestra hasta que el mercado les dé
  señales. Para P01, P02 y P03 eso puede tardar semanas en un mercado cripto bajista. No es
  un fallo mientras sus motivos sigan siendo coherentes.
- **Por verificar en la próxima revisión:**
  1. El marco temporal de «20 barras» en P09 y la contradicción de tendencias P05/P11.
  2. Si el límite de 3 operaciones al día de P07 vuelve a rechazar órdenes.
  3. La comisión de cripto publicada frente a la estimada.
  4. La diferencia de 1 centavo cuenta/libro observada en la Semana 0.

---

## Semana 0 — 2026-10-26: puesta en marcha

Todavía no hay resultados de los perfiles: sus libros empiezan en su primer turno.

Validaciones hechas, con un perfil de prueba y en un libro aparte, para no tocar los libros
reales:

- **Cuenta:** paper (número «PA…»), activa, 99 997,52 USD, sin posiciones al empezar.
- **Activos:** los 41 símbolos de los perfiles figuran en Alpaca como activos y operables
  (memecoins incluidas). Las acciones también admiten fracciones.
- **Compra y venta de cripto** (BTC):
  - Una compra de 11 USD por importe se ejecutó por 10,78 USD (0,000134714 BTC a
    80 053,33). Alpaca se quedó 0,25 % de la moneda en el momento, redondeado por cada
    ejecución parcial.
  - La venta (0,000134376 a 80 030,17) pagó 0,03 USD.
  - Ida y vuelta: −0,07 USD, igual en la cuenta y en el libro.
- **Segunda ida y vuelta de BTC** (10 USD, a petición del usuario):
  - Compra: 0,000122586 BTC a 79 970,89, con una comisión de 0,000000307 BTC.
  - Venta: 0,000122279 a 79 987,32, con una comisión de 0,03 USD.
  - Resultado: la cuenta −0,05 USD y el libro −0,06. Es 1 centavo de diferencia, porque la
    regla de redondeo de Alpaca no se puede fijar con dos muestras; el libro queda del lado
    prudente. La revisión debe vigilar si la diferencia se acumula.
- **Orden que nunca llegó** a Alpaca (rechazada por el mínimo de 10 USD): la reconciliación
  la marcó como «no enviada» y liberó lo reservado.
- **Compra y venta de acciones (validado 2026-10-26, bolsa abierta, perfil P91, AAPL):**
  - Compra 5 USD: filled, 0.014485517 acc. a 344.482 (bid/ask IEX 344.48/344.56); comisión 6.66e-07 USD; efectivo del libro 95.01.
  - Venta (liquidar): filled, 0.014485517 acc. a 344.578 (bid/ask IEX 344.62/344.73); comisión/tasas del libro 0.00010348897760461561 USD (SEC + CAT); efectivo del libro 100.0. Ambas ejecuciones quedaron dentro del bid/ask (la venta a 0.042 por debajo del bid; la compra 0.078 por debajo del ask).
  - Cuenta paper: efectivo 99943.47 antes y 99943.47 después (variación 0.00 a 2 decimales). Libro P91: 100.0 − 100 = 0.0. Diferencia cuenta/libro dentro del redondeo al centavo (las tasas del libro suman ≈0.0001 USD). Sin órdenes pendientes ni avisos.
  - Nota: `estado` muestra `pnl_realizado: -0.0` y resultado −0.0 % aunque la diferencia de precios (≈ +0.0014 USD) menos tasas debería dar un pequeño positivo; con 2 decimales no se distingue. No se corrigió nada.
- **Ejecución en seco** de los 11 perfiles: el análisis y la validación funcionan. Las
  órdenes de acciones se rechazaron con «mercado cerrado» y las de cripto se simularon.

Lecciones:

- Alpaca exige 10 USD como mínimo por compra de cripto (P-021).
- El spread de las memecoins cuesta más que la comisión.
- Las cotizaciones IEX de acciones fuera de horario no sirven para medir el spread (D-080).
