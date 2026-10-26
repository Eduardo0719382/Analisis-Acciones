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
- **Compra y venta de acciones:** pendiente, porque la bolsa estaba cerrada (ver la semana 1).
- **Ejecución en seco** de los 11 perfiles: el análisis y la validación funcionan. Las
  órdenes de acciones se rechazaron con «mercado cerrado» y las de cripto se simularon.

Lecciones:

- Alpaca exige 10 USD como mínimo por compra de cripto (P-021).
- El spread de las memecoins cuesta más que la comisión.
- Las cotizaciones IEX de acciones fuera de horario no sirven para medir el spread (D-080).
