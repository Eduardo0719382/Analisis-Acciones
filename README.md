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

## Uso

- **Buscar:** escriba un ticker (p. ej. `AAPL`) o el nombre de una empresa en el cuadro de
  búsqueda. Use ↑/↓ y Enter, o haga clic en un resultado. Con el cuadro vacío se muestran
  los símbolos recientes.
- **Intervalo:** Diario, Semanal o Mensual (los dos últimos se calculan a partir de los datos
  diarios).
- **Gráfico:** velas o línea (selector junto al intervalo). Rueda del ratón = zoom; arrastrar =
  desplazarse; la leyenda superior muestra apertura, máximo, mínimo, cierre, cambio y volumen
  de la barra bajo el cursor. El volumen aparece en un panel propio bajo el precio.
- **Indicadores:** botón *Indicadores*. Sobre el precio: SMA, EMA, Bandas de Bollinger,
  Ichimoku (con la nube proyectada 26 barras hacia delante y la Chikou 26 hacia atrás) y
  Supertrend (verde/rojo según la dirección). En paneles propios: RSI, MACD, ATR, Estocástico,
  RSI estocástico, ADX (+DI/-DI) y OBV; edite sus parámetros, ocúltelos o quítelos.
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
- **Alertas (pestaña del panel derecho):** precio por encima/debajo de X, cambio diario
  mayor/menor que X %, RSI por encima/debajo de X, cruces de EMAs, cruces MACD/señal y
  rupturas de máximo/mínimo de N barras. Se comprueban sobre barras diarias cerradas al iniciar
  el programa y cada 15 minutos mientras está abierto (o con «Comprobar ahora»). Avisan en la
  barra de estado, con una notificación de Windows y en el historial. Las alertas de nivel
  avisan una vez y se rearman cuando la condición deja de cumplirse.
- **Backtesting:** *Herramientas → Backtesting…* (Ctrl+B) sobre el activo e intervalo del
  gráfico. Estrategias: cruce de EMAs y reversión con RSI, con parámetros editables, capital,
  comisión (% y fija) y deslizamiento. Muestra capital final, rentabilidad, operaciones,
  ganadoras/perdedoras, % de acierto, caída máxima, factor de beneficio, comparación con
  comprar y mantener, curva de capital y lista de operaciones. Señal al cierre, ejecución en la
  apertura siguiente (sin ventaja de información futura).
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
- **Comparar activos:** *Herramientas → Comparar activos…* (hasta 6 tickers; se rellena con el
  activo actual y la lista de seguimiento). Gráfico de rendimiento normalizado a 0 % desde la
  primera sesión común (6M, 1A, 3A, 5A o máximo) y tabla con rentabilidad, volatilidad anual,
  caída máxima, volumen medio y RSI 14.
- **Detalles (panel derecho):** precio, cambio, apertura/máximo/mínimo, volumen, rango de 52
  semanas, moneda, mercado, sector. Sin conexión se muestran los datos de la última barra
  guardada, indicándolo.
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
