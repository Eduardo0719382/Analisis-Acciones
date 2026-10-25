# Análisis de Acciones

Aplicación de escritorio (Windows primero) para el análisis técnico de acciones:
gráficos, indicadores, listas de seguimiento y, más adelante, análisis por reglas,
alertas y backtesting.

> Herramienta de análisis. **No constituye asesoramiento financiero** y no ejecuta
> operaciones reales.

- Plan y alcance: [`PLAN.md`](PLAN.md)
- Decisiones de arquitectura: [`DECISIONS.md`](DECISIONS.md)
- Problemas encontrados y soluciones: [`PROBLEMS.md`](PROBLEMS.md)
- Gráficos: [TradingView Lightweight Charts™](https://www.tradingview.com/lightweight-charts/)
  (Apache 2.0, incluido en `src/analisis_acciones/charts/web/` con su licencia y aviso).

## Instalador de Windows (sin Python)

Cada cambio en GitHub genera un instalador `AnalisisAcciones-<versión>-setup.exe`
(flujo *Windows installer* en la pestaña **Actions**; descárguelo desde «Artifacts»). Las
versiones etiquetadas (`v*`) lo publican además en **Releases**. Instala por usuario (no
requiere administrador), crea accesos en el menú Inicio y, opcionalmente, en el escritorio.
Los datos (`%LOCALAPPDATA%\AnalisisAcciones`) se conservan al actualizar o desinstalar.
La versión instalada se actualiza instalando el nuevo instalador encima.

Windows puede mostrar el aviso de SmartScreen porque el instalador no está firmado
digitalmente: «Más información» → «Ejecutar de todas formas».

## Requisitos

- Python 3.12 o superior
- Windows 10/11 (también funciona en Linux y macOS)

## Instalación para desarrollo

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows  (Linux/macOS: source .venv/bin/activate)
pip install -e ".[dev]"
```

## Abrir con doble clic (Windows)

Haga doble clic en **`Abrir.bat`**. La primera vez crea el entorno e instala el programa
(tarda unos minutos y muestra una ventana negra); después abre directamente la aplicación.
Para tener un acceso directo: clic derecho sobre `Abrir.bat` → *Enviar a* → *Escritorio
(crear acceso directo)*.

## Ejecutar desde la consola

```bash
analisis-acciones
# o bien
python -m analisis_acciones
```

Los datos (base de datos SQLite y registros) se guardan en el directorio de datos del
usuario (`%LOCALAPPDATA%\AnalisisAcciones` en Windows). Puede cambiarse con la variable
`ANALISIS_ACCIONES_HOME` (véase `.env.example`).

**Pasar todo a otro PC (copia de seguridad):** *Archivo → Crear copia de seguridad…* guarda en
un único archivo `.sqlite3` las listas, alertas, dibujos, carteras simuladas, configuración y
datos de mercado guardados. En el otro PC, *Archivo → Restaurar copia de seguridad…* comprueba
el archivo (integridad, que sea de este programa y no de una versión más nueva), muestra qué
contiene y lo aplica al reiniciar; los datos que había se guardan aparte
(`analisis_acciones.sqlite3.antes-de-restaurar`).

**Si el programa se cierra solo:** al volver a abrirlo avisa de que la sesión anterior terminó
de forma inesperada e indica la carpeta de registros (`logs\analisis_acciones.log` y
`logs\crash.log` dentro del directorio de datos). Si ocurre dos veces seguidas activa solo
*Ver → Gráficos compatibles (sin aceleración)*, que evita los fallos de algunas tarjetas
gráficas; también puede activarlo a mano (se aplica al reiniciar). Si el gráfico se queda en
blanco porque su motor se detuvo, se recarga automáticamente.

## Uso

- **Guía de uso** (*Ayuda → Guía de uso*, F1): explica dentro del programa cada parte, cómo
  leerla, los atajos de teclado, un glosario y los límites.
- **Atajos:** F1 guía · Ctrl+F buscar · F5 actualizar el activo · Ctrl+I indicadores ·
  Ctrl+1…9 pestañas del panel derecho · Ctrl+D resumen del día · Ctrl+E escáner · Ctrl+B
  backtesting · Ctrl+Mayús+B backtesting de patrones · Ctrl+Mayús+P cartera simulada ·
  Ctrl+Mayús+C comparar · Ctrl+O importar CSV · Ctrl+Q salir. El menú *Herramientas* agrupa
  primero el análisis de la lista (escáner, escaneo diario, avisos), después la simulación
  (backtesting, cartera) y al final la comparación.
- **Resumen del día** (*Ver → Resumen del día…*, Ctrl+D; se abre al iniciar si la lista de
  seguimiento tiene activos, lo que se puede desactivar): estado del mercado, cuántos activos de
  la lista suben y bajan (y los que más), una tarjeta por activo con su cambio y su evolución
  reciente, y los avisos de los últimos días (alertas y novedades del escaneo diario). Al pulsar
  un activo se abre en el gráfico.
- **Buscar:** escriba un ticker (p. ej. `AAPL`) o el nombre de una empresa en el cuadro de
  búsqueda. Use ↑/↓ y Enter, o haga clic en un resultado. Con el cuadro vacío se muestran
  los símbolos recientes.
- **Criptomonedas:** busque por nombre («bitcoin») o escriba el par de Yahoo Finance, moneda y
  divisa de cotización separadas por un guion: `BTC-USD`, `ETH-EUR`, `SOL-USD`. Cotizan todos
  los días a todas horas: la vela diaria va de 00:00 a 00:00 UTC (la del día en curso se
  considera sin cerrar) y las velas intradía se muestran en hora UTC, sin cortes de fin de
  semana. Gráfico, indicadores, análisis, agotamiento, proyección, Elliott, patrones, alertas,
  escáner, comparación (volatilidad anualizada con 365 días) y backtesting funcionan igual que
  con acciones. No tienen datos fundamentales de empresa. En la cartera simulada se pueden
  comprar y vender; si la cartera tiene criptomonedas su valor se calcula todos los días
  (las acciones mantienen el cierre del viernes durante el fin de semana).
- **Intervalo:** 15 minutos, 1 hora, Diario, Semanal o Mensual (los dos últimos se calculan a
  partir de los datos diarios). Intradía: solo horario regular (9:30–16:00 de Nueva York, que es
  la hora que muestra el gráfico); Yahoo ofrece unos 60 días de barras de 15 minutos y unos 2 años
  de barras horarias. El programa guarda las que descarga, así que el historial crece con el uso.
  Todas las herramientas (indicadores, análisis, proyección, Elliott, patrones, backtesting)
  funcionan también en intradía. Los dibujos se guardan por fecha de sesión y por eso solo están
  en los gráficos diario, semanal y mensual. Las alertas y el escáner usan sesiones diarias
  cerradas.
- **Gráfico:** velas o línea (selector junto al intervalo). Rueda del ratón = zoom; arrastrar =
  desplazarse; la leyenda superior muestra apertura, máximo, mínimo, cierre, cambio y volumen
  de la barra bajo el cursor. El volumen aparece en un panel propio bajo el precio.
- **Indicadores:** botón *Indicadores*. Sobre el precio: SMA, EMA, Bandas de Bollinger,
  Ichimoku (nube coloreada: verde si Senkou A está sobre B, roja si no; proyectada 26 barras
  hacia delante y la Chikou 26 hacia atrás) y
  Supertrend (verde/rojo según la dirección). En paneles propios: RSI, MACD, ATR, Estocástico,
  RSI estocástico, ADX (+DI/-DI) y OBV; edite sus parámetros, ocúltelos o quítelos. También
  **VWAP** (en intradía se reinicia cada sesión; en diario usa las últimas N barras) y
  **Fibonacci automático** (retrocesos del último tramo relevante, detectado con ZigZag).
- **Comparar con un índice:** *Ver → Comparar con índice (SPY)* dibuja en el mismo gráfico la
  evolución del índice o ETF de referencia durante las últimas 250 barras, partiendo del precio
  del activo, y la barra de estado indica la rentabilidad de ambos y la diferencia. *Ver →
  Índice de referencia…* permite usar otro (QQQ, DIA, IWM, ^GSPC…).
- **Perfil de volumen:** *Ver → Perfil de volumen* dibuja a la derecha del gráfico cuánto volumen
  se negoció en cada franja de precio durante las últimas 250 barras, con el POC (precio con más
  volumen) y la zona de valor (70 % del volumen).
  **Plantillas:** en la ventana de indicadores, «Plantilla» carga conjuntos listos
  (Tendencia, Momento, Volatilidad, Intradía, Ichimoku) o los suyos propios («Guardar como…»).
  La configuración se guarda. Las fórmulas y convenciones están documentadas en
  `src/analisis_acciones/indicators/functions.py` y verificadas contra implementaciones de
  referencia independientes.
- **Listas de seguimiento (panel izquierdo):** lista «Favoritos» por defecto; menú «⋯» para
  crear, renombrar o eliminar listas. «+» añade el activo del gráfico, «-» (o Supr) lo quita,
  ▲/▼ reordenan, ⟳ actualiza. Cada fila muestra el último cierre diario y su cambio %; un
  clic abre el activo. Todo se guarda localmente.
- **Análisis (pestaña del panel derecho):** reglas fijas y explicables sobre la última barra
  cerrada: tendencia (EMA 20/50 con separación mínima de 0,5 %), RSI 14 en 70/30, cruces
  EMA 20/50 y MACD/señal recientes (5 barras), volumen > 2× su media de 20, cambio de ATR
  ±30 % en 20 barras y rupturas del máximo/mínimo de 20 barras. Cada señal muestra la regla y
  los valores que la producen. Son descripciones de los datos, no recomendaciones.
- **Agotamiento (pestaña del panel derecho):** si el activo está en tendencia, indica cuántas
  señales de agotamiento muestra (de 6, cada una con sus valores): RSI en sobrecompra o
  sobreventa, divergencia del RSI, precio a más de 3 ATR de su media de 50, volumen que se
  apaga, cierre fuera de la banda de Bollinger y movimiento de 20 sesiones inusualmente rápido.
  Con 3 o más habla de «señales de agotamiento». Debajo muestra **qué pasó antes en ese mismo
  activo** con esa situación (a 10 y 20 sesiones: cuántas veces giró y la variación mediana)
  frente a un día cualquiera de la misma tendencia, con una prueba estadística que indica si la
  diferencia puede deberse al azar. No dice cuándo terminará una tendencia ni es una
  recomendación. El escáner tiene la columna y el filtro «Agotamiento», y el escaneo diario
  avisa cuando aparecen estas señales en un activo de la lista. *Marcar en el gráfico las veces
  anteriores* dibuja una flecha donde empezaron las señales en el pasado (▼ encima: fin posible
  de una subida; ▲ debajo: de una bajada; el número es cuántas condiciones se cumplían).
  **Umbrales…** cambia el RSI de sobrecompra/sobreventa, la distancia en ATR, el volumen, el
  movimiento inusual y las condiciones necesarias; el historial se recalcula y se muestra junto
  al de los valores por defecto. Los mismos umbrales usan el escáner y el escaneo diario.
- **Proyección (pestaña del panel derecho):** rangos estadísticos para las próximas N barras,
  dibujados sobre el gráfico (P5, P25, mediana, P75, P95). *Cono de volatilidad*: parte del
  último cierre, sin tendencia supuesta, con la volatilidad de la ventana elegida. *Canal de
  regresión*: prolonga la tendencia lineal (logarítmica) de la ventana con bandas de ±1 y ±2
  desviaciones de los residuos. Cada proyección incluye una **calibración histórica**: se repite
  el mismo cálculo en fechas pasadas usando solo los datos disponibles entonces y se indica
  cuántas veces el precio real terminó dentro del rango del 90 % y del 50 %. No es una
  predicción: es un rango de escenarios con supuestos explícitos.
- **Elliott (pestaña del panel derecho):** «Buscar ondas» localiza los giros del precio con un
  ZigZag (umbral automático según la volatilidad, o el que usted elija) y busca **impulsos
  1-2-3-4-5 y correcciones A-B-C pasadas** que cumplan las reglas clásicas (la onda 2 no
  retrocede más allá del inicio de la 1, la onda 3 no es la más corta, la onda 4 no entra en
  el territorio de la 1). También muestra las **posibles cuentas en curso** con sus niveles de
  Fibonacci de referencia y el precio que las invalidaría. Cada cuenta lista las reglas y pautas
  comprobadas con sus valores. Es una interpretación: suele haber varias cuentas posibles.
- **Patrones (pestaña del panel derecho):** «Buscar patrones» marca en el gráfico los
  **soportes y resistencias** (zonas donde el precio giró varias veces; «R ×4» = resistencia con
  4 toques) y detecta **doble techo/suelo, hombro-cabeza-hombro (normal e invertido),
  triángulos ascendentes, descendentes y simétricos, y banderas**. Cada patrón muestra las
  condiciones que cumple, la fecha de ruptura, el objetivo clásico y el nivel de invalidación.
  Un patrón solo se confirma cuando el precio cierra más allá de su línea de ruptura; antes
  aparece «en formación». El resumen indica, para ese activo, cuántos patrones pasados
  alcanzaron su objetivo y cuántos se invalidaron antes.
- **Alertas (pestaña del panel derecho):** precio por encima/debajo de X, cambio diario
  mayor/menor que X %, RSI por encima/debajo de X, cruces de EMAs, cruces MACD/señal y
  rupturas de máximo/mínimo de N barras. Se comprueban sobre barras diarias cerradas al iniciar
  el programa y cada 15 minutos mientras está abierto (o con «Comprobar ahora»). Avisan en la
  barra de estado, con una notificación de Windows y en el historial. Las alertas de nivel
  avisan una vez y se rearman cuando la condición deja de cumplirse.
  Cada alerta puede vigilar **velas diarias, de 1 hora o de 15 minutos** (campo «Velas»). Las
  intradía se comprueban cada 2 minutos sobre velas ya cerradas y el aviso indica la hora de la
  vela. Las alertas creadas desde Elliott o Patrones usan el intervalo del gráfico.
  En las pestañas **Elliott** y **Patrones**, «Crear alertas de precio» crea alertas para los
  objetivos y el nivel de invalidación de la cuenta, patrón o nivel seleccionado; cada alerta
  indica de dónde viene (p. ej. «Cierre > 125,46 (Elliott impulso alcista 1-2-3: …)»).
- **Agotamiento en varios activos:** *Herramientas → Agotamiento en varios activos…* mide, para
  cada activo de la lista (o los tickers que escriba, hasta 200), cuántas veces aparecieron
  señales de agotamiento de las subidas y de las bajadas, en qué % el precio giró después (a 10 o
  20 sesiones) frente a un día normal de la misma tendencia, la probabilidad de que la
  diferencia sea azar y una lectura («Anticipó bajadas/rebotes», «La subida/bajada siguió», «Sin
  diferencia», «Pocos casos»). Usa los umbrales de la pestaña Agotamiento. Exporta un informe
  visual (HTML o PDF, con barras «tras la señal» frente a «día normal») o un CSV.
- **Backtesting:** *Herramientas → Backtesting…* (Ctrl+B) sobre el activo e intervalo del
  gráfico. Estrategias: cruce de EMAs y reversión con RSI, con parámetros editables, capital,
  comisión (% y fija) y deslizamiento. Muestra capital final, rentabilidad, operaciones,
  ganadoras/perdedoras, % de acierto, caída máxima, factor de beneficio, comparación con
  comprar y mantener, curva de capital y lista de operaciones. Señal al cierre, ejecución en la
  apertura siguiente (sin ventaja de información futura). **Tendencia con salida por
  agotamiento:** compra cuando el cierre cruza al alza su media (50 por defecto) y vende cuando
  la cruza a la baja o, antes, en cuanto la subida muestra N señales de agotamiento. Se ejecuta
  también la misma estrategia sin esa salida y se dibuja como tercera curva, con la diferencia
  de rentabilidad y de caída máxima: así se ve qué habría pasado por salir al agotarse la subida
  (tras una salida por agotamiento solo se vuelve a entrar con un nuevo cruce al alza). La
  variante **«… y re-entrada»** vuelve a comprar en cuanto desaparecen las señales si el cierre
  sigue por encima de la media; se compara con la misma referencia.
- **Backtesting de patrones:** *Herramientas → Backtesting de patrones…* simula, en varios
  activos a la vez (hasta 30), qué habría pasado operando cada patrón chartista al confirmarse:
  entrada en la apertura siguiente, salida en el objetivo del patrón, en su invalidación (stop) o
  tras un plazo máximo; con comisión y deslizamiento; compras y ventas cortas o solo compras.
  Cada patrón se vuelve a detectar con los datos que había el día de su ruptura, de modo que la
  simulación no usa información del futuro. El resultado es un informe visual (resultado medio
  por patrón, cómo terminaron las operaciones, ventaja frente a entrar cualquier día, tablas por
  patrón y por activo, avisos de muestra pequeña), que se puede exportar a HTML o PDF, y la lista
  de operaciones (CSV).
- **Exportar:** *Archivo → Exportar gráfico como imagen (PNG)*, *Exportar datos (CSV)* (barras
  e indicadores visibles) y *Exportar informe (PDF)* (gráfico, detalles y análisis). En el
  backtesting, *Exportar resultados…* guarda operaciones, resumen y curva de capital en CSV.
  Los textos que empiezan por `=`, `+`, `-` o `@` se escriben precedidos de `'` para que una
  hoja de cálculo nunca los ejecute como fórmula.
- **Dibujo** (botón de la barra superior): línea horizontal (soporte/resistencia), línea de
  tendencia (2 clics), retroceso de Fibonacci (2 clics: inicio y fin del movimiento; niveles
  0–23,6–38,2–50–61,8–78,6–100 %) y notas. Esc cancela. Se guardan por activo; «Deshacer
  último dibujo» y «Borrar todos». Nota: tras un split, los precios históricos se reajustan y
  los dibujos antiguos pueden quedar desplazados.
- **Escáner:** *Herramientas → Escáner de la lista…* (Ctrl+E) aplica a la lista de seguimiento
  (o a los tickers que escriba, hasta 200, con barra de progreso y botón Cancelar) las mismas
  reglas del programa. Por cada activo muestra
  cierre, cambio, RSI 14, número de señales alcistas y bajistas (con el detalle al pasar el
  ratón), patrones en formación o con ruptura reciente, posible cuenta de Elliott y distancia al
  soporte y a la resistencia más cercanos. Se puede filtrar y ordenar por columnas; un doble clic
  abre el activo en el gráfico. Usa solo sesiones diarias cerradas.
  Con **Incluir fundamentales** añade PER, rentabilidad por dividendo, capitalización,
  crecimiento de ingresos y margen neto (Yahoo, guardados un día) y permite filtrar por **PER
  máximo**, **dividendo mínimo**, **capitalización mínima** (en miles de millones),
  **crecimiento de ingresos mínimo** y **margen neto mínimo** (estos dos admiten límites
  negativos). Un activo sin el dato (o con PER negativo por pérdidas) no pasa un filtro
  activo.
  **Exportar** guarda lo que muestra el filtro como:
  - **Informe visual (HTML o PDF):** resumen con casillas (cuántos activos tienen más señales
    alcistas o bajistas y cuántos tienen patrones) y una ficha por activo con una frase clara, un
    gráfico de velas de las últimas 90 sesiones (con volumen, medias de 20 y 50, soporte y
    resistencia), la barra de señales, el indicador RSI y
    los patrones. Incluye cómo leer cada ficha y un glosario. Alcista = ▲ azul, bajista = ▼ rojo
    (colores distinguibles también con daltonismo). El HTML no contiene scripts ni recursos
    externos.
  - **Datos (CSV)** para Excel u otra hoja de cálculo.
- **Escaneo diario automático:** *Herramientas → Escaneo diario automático de la lista*
  (activado por defecto). Mientras el programa está abierto, una vez por sesión cerrada (y al
  iniciarlo si falta la del último día) escanea la lista de seguimiento y **avisa solo de lo
  nuevo** respecto al escaneo anterior: patrones que aparecen o se rompen y señales nuevas. Los
  avisos llegan como las alertas (notificación de Windows e historial de la pestaña Alertas).
  *Ver el último escaneo diario…* abre los resultados para revisarlos o exportar el informe.
  La primera vez que se ve un activo solo se toma como referencia, sin avisar.
  **Avisos de resultados y dividendos:** con el escaneo diario activado, el programa avisa
  (por defecto 3 días antes) de la presentación de resultados y de la fecha ex-dividendo de los
  activos de la lista; cada fecha se avisa una vez (otra vez si la empresa la cambia). Los días
  de antelación se cambian en *Herramientas → Avisos de resultados y dividendos…* (0 = no
  avisar).
- **Cartera simulada:** *Herramientas → Cartera simulada…* para practicar sin dinero real. Se
  registran compras y ventas ficticias (ticker, cantidad, precio o «cierre del día», fecha,
  comisión, nota) en una o varias carteras con su capital inicial. Muestra el valor total, el
  resultado (realizado y latente), el efectivo, la comparación con el índice de referencia
  (con el mismo capital y fechas), la evolución diaria, las posiciones con su peso y la lista de
  operaciones. Se exporta a HTML, PDF o CSV. No permite ventas en corto ni gastar más efectivo
  del disponible.
  - **Comparar con varios índices:** el campo *Comparar con* admite hasta 3 referencias (p. ej.
    `SPY, QQQ, ^IBEX`), dibujadas con el mismo capital inicial y fechas que la cartera, y la
    tabla **Rentabilidad por año** compara la cartera con cada una (años incompletos marcados
    «parcial»).
  - **Importar operaciones reales (CSV del broker):** botón *Importar operaciones (CSV)…*.
    Columnas (español o inglés; separador `,` o `;`): fecha (`AAAA-MM-DD` o `DD/MM/AAAA`),
    ticker, operación (compra/venta, o el signo de la cantidad), cantidad, precio y,
    opcionalmente, comisión, divisa y nota. Antes de importar muestra lo que se añadirá, las
    filas descartadas con su motivo y el capital inicial mínimo necesario; se puede añadir a la
    cartera actual o crear una nueva. Las fechas `MM/DD/AAAA` (estilo EE. UU.) se rechazan para
    no confundir día y mes. Luego se analizan con el diario, las estadísticas y el informe.
    También lee **movimientos de efectivo** (columna operación: *dividendo*, *intereses*,
    *comisión*, *ingreso/depósito*, *retirada*; importe en la columna *importe* o cantidad ×
    precio). Si el archivo trae dividendos, se desactivan los dividendos calculados
    automáticamente para no contarlos dos veces.
  - **Efectivo (pestaña):** aportaciones y retiradas de dinero, y dividendos, intereses y
    gastos que comunique el broker. Las aportaciones y retiradas no cuentan como ganancia: con
    ellas el informe muestra la **rentabilidad ponderada en el tiempo**, el capital aportado
    en la curva y las referencias reciben el mismo dinero en las mismas fechas.
  - **Varias divisas:** la cartera se lleva en dólares. Los activos que cotizan en otra divisa
    (p. ej. `SAP.DE` en euros o `VOD.L` en peniques) se anotan con su precio en esa divisa y se
    convierten con el tipo de cambio de Yahoo (`EURUSD=X`, `GBPUSD=X`…) del día de la
    operación; la valoración y la curva usan el de cada día. El informe indica qué tipos se
    usaron.
  - **Fracciones y compras en dólares:** se puede indicar la cantidad de acciones (con
    decimales) o un importe en $ («Dólares ($)»), que se convierte en acciones al precio
    elegido (hasta 6 decimales).
  - **Comisiones:** el botón *Ajustes de la cartera…* fija por cartera una comisión fija en $
    por operación, un porcentaje del importe y un mínimo. Con «Automática» marcada se aplica
    sola; desmarcándola se escribe la de esa operación.
  - **Avisos de la cartera** (en *Ajustes de la cartera…*): cuando una posición pierde un X %
    desde su coste medio, cuando un activo se aleja Y puntos de su peso objetivo o cuando la
    cartera cae un Z % desde su máximo. Se comprueban cada 30 minutos con el programa abierto,
    llegan como las alertas (notificación e historial) y cada uno se repite solo si la
    situación desaparece y vuelve.
  - **Eventos corporativos:** los splits ajustan la cantidad de acciones y los dividendos se
    cobran en efectivo en su fecha ex-dividendo (se puede desactivar). El informe los lista en
    «Eventos corporativos». Sin impuestos ni retenciones.
  - **Impuestos (simplificados):** en *Ajustes de la cartera…* se fija una **retención sobre
    dividendos** (se descuenta de cada cobro) y un **impuesto sobre ganancias** que se estima
    sobre el resultado neto de las ventas de cada año (se muestra, no se descuenta).
  - **Resultado de cada venta** frente al coste medio (también en la tabla de operaciones y en
    el CSV), resumen por año y un mini gráfico del **valor de cada posición en el tiempo**.
  - **Rebalanceo** (pestaña de la cartera): se indica el peso objetivo de cada activo (% del
    valor total; el resto queda en efectivo) y el programa calcula las compras y ventas para
    llegar a él (vende primero, admite fracciones y ajusta las compras al efectivo y a las
    comisiones). Los activos sin peso objetivo se venden. «Registrar estas operaciones» las
    anota como operaciones ficticias de hoy.
  - **Estadísticas del diario** en el informe: % de ventas con ganancia, factor de beneficio,
    ganancia y pérdida medias, tiempo medio mantenida, mejor y peor venta, resultado por activo
    y cuántas operaciones tienen motivo y revisión escritos (con aviso si hay pocas ventas).
  - **Diario de operaciones:** cada operación guarda su motivo y, después, una revisión
    (*Operaciones → Escribir revisión…*); ambos salen en el informe y en el CSV.
- **Comparar activos:** *Herramientas → Comparar activos…* (hasta 6 tickers; se rellena con el
  activo actual y la lista de seguimiento). Gráfico de rendimiento normalizado a 0 % desde la
  primera sesión común (6M, 1A, 3A, 5A o máximo) y tabla con rentabilidad, volatilidad anual,
  caída máxima, volumen medio y RSI 14.
- **Detalles (panel derecho):** precio, cambio, apertura/máximo/mínimo, volumen, rango de 52
  semanas, moneda, mercado, sector. Sin conexión se muestran los datos de la última barra
  guardada, indicándolo.
- **Fundamentales (pestaña del panel derecho):** capitalización, PER, beneficio por acción,
  precio/valor contable, dividendo y su rentabilidad, pay-out, márgenes, ROE, crecimiento y beta,
  cada uno con una explicación breve, y gráficos por año de ingresos, beneficio neto, BPA y
  dividendos cobrados. Se descargan solo al abrir la pestaña, se guardan (se actualizan una vez
  al día) y sin conexión se muestran los últimos guardados, indicándolo.
  - **Calendario:** próxima presentación de resultados (marcada «estimada» si la empresa aún no
    la ha confirmado), fecha ex-dividendo y fecha de pago, con cuántos días faltan. El
    *Resumen del día* lista las de los próximos 14 días de la lista de seguimiento, usando los
    datos ya guardados (sin descargas extra). Son las fechas que publica Yahoo Finance; la
    empresa puede cambiarlas.
- **Importar CSV:** *Archivo → Importar CSV…*. Columnas `date, open, high, low, close`
  (opcionales `volume`, `adj close`); también en español (`fecha; apertura; máximo; mínimo;
  cierre; volumen`) con coma decimal. Fechas `AAAA-MM-DD` o `DD/MM/AAAA`.
- **Sin conexión:** si ya se descargó un ticker antes, se muestran los datos guardados
  indicando que pueden no estar actualizados.

Fuente de datos: Yahoo Finance (no oficial, gratuita). Los datos pueden tener retrasos o
errores y no constituyen asesoramiento financiero.

## Actualizar

Dentro del programa: **Ayuda → Buscar actualizaciones…**. Muestra los cambios nuevos,
los instala y ofrece reiniciar. Además, al abrir el programa se comprueba en segundo plano
y, si hay una versión nueva, aparece «Actualización disponible» en la barra de estado
(desactivable en **Ayuda → Buscar actualizaciones al iniciar**).

Requisitos: haber instalado con `git clone` (no desde un ZIP) y tener Git en el PATH.
La actualización solo avanza la copia local hasta la versión de GitHub; si hay archivos
del programa modificados localmente, no hace nada para no perderlos.

Manualmente, desde la cmd:

```cmd
git pull
pip install -e ".[dev]"
```

## Pruebas y calidad

```bash
pytest                 # pruebas sin red (datos sintéticos)
pytest -m live         # pruebas reales contra Yahoo Finance (requiere Internet)
ruff check .
ruff format --check .
mypy
```

En Linux sin pantalla, las pruebas de interfaz usan `QT_QPA_PLATFORM=offscreen`
automáticamente.
