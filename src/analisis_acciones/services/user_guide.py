"""In-app user guide (Ayuda → Guía de uso): static Spanish HTML, no scripts.

Task-oriented: what each part of the program does, how to read it and its
limits, plus a glossary. Keep it in step with the README "Uso" section.
"""

from __future__ import annotations

from analisis_acciones.services.scan_report import STYLE

GUIDE_STYLE = """
body { padding: 16px 22px; max-width: 980px; margin: 0 auto; line-height: 1.5; }
h1 { font-size: 22px; }
h2 { font-size: 17px; margin-top: 26px; padding-top: 8px; border-top: 1px solid var(--border); }
h3 { font-size: 14px; margin: 14px 0 4px; }
nav.toc { background: var(--card); border: 1px solid var(--border); border-radius: 10px;
  padding: 10px 16px; columns: 2; column-gap: 28px; font-size: 13.5px; }
nav.toc a { display: block; padding: 2px 0; color: var(--ink); text-decoration: none; }
nav.toc a:hover { text-decoration: underline; }
.steps { padding-left: 20px; } .steps li { margin: 3px 0; }
.tip { background: var(--up-bg); border-radius: 8px; padding: 8px 12px; font-size: 13px; }
.warnbox { background: var(--flat-bg); border-radius: 8px; padding: 8px 12px; font-size: 13px; }
kbd { border: 1px solid var(--border); border-bottom-width: 2px; border-radius: 4px;
  padding: 0 5px; font-size: 12px; background: var(--card); }
dl.gloss dt { font-weight: 700; margin-top: 8px; } dl.gloss dd { margin: 2px 0 0 0; }
.up { color: var(--up); } .down { color: var(--down); }
"""

SECTIONS: list[tuple[str, str, str]] = [
    (
        "inicio",
        "Primeros pasos",
        """
<ol class="steps">
<li>Escriba un ticker (por ejemplo <b>AAPL</b>) o el nombre de una empresa en el cuadro de
búsqueda y pulse <kbd>Enter</kbd>. Con el cuadro vacío se muestran los símbolos recientes.</li>
<li>Elija el <b>intervalo</b> (15 minutos, 1 hora, diario, semanal o mensual) y el tipo de
gráfico (velas o línea).</li>
<li>Pulse <b>+</b> en el panel izquierdo para guardar el activo en su <b>lista de
seguimiento</b>. Un clic en la lista abre el activo; ⟳ actualiza los precios.</li>
<li>Explore las pestañas del panel derecho: Detalles, Análisis, Proyección, Elliott, Patrones,
Fundamentales y Alertas.</li>
</ol>
<p class="tip">Los datos se guardan en su equipo. Sin conexión se muestran los últimos guardados
y el programa indica que pueden no estar actualizados.</p>""",
    ),
    (
        "colores",
        "Cómo leer colores y símbolos",
        """
<ul>
<li><span class="up">▲ Azul</span> = alcista (sube, señal a favor de subida).</li>
<li><span class="down">▼ Rojo</span> = bajista (baja, señal a favor de bajada).</li>
<li>Gris = neutral o sin dato. «—» significa que el dato no está disponible: nunca se
inventa.</li>
</ul>
<p>Los colores siempre van acompañados de un símbolo o una palabra, para poder leerlos también
con daltonismo o en blanco y negro.</p>""",
    ),
    (
        "grafico",
        "El gráfico",
        """
<ul>
<li><b>Zoom:</b> rueda del ratón. <b>Desplazarse:</b> arrastrar. La leyenda superior muestra
apertura, máximo, mínimo, cierre, cambio y volumen de la barra bajo el cursor.</li>
<li><b>Indicadores:</b> botón <i>Indicadores</i>. Sobre el precio: medias (SMA, EMA), Bandas de
Bollinger, Ichimoku, Supertrend, VWAP y Fibonacci automático. En paneles propios: RSI, MACD,
ATR, Estocástico, RSI estocástico, ADX y OBV. Cada uno tiene parámetros editables.</li>
<li><b>Plantillas:</b> en la ventana de indicadores, «Plantilla» carga conjuntos listos
(Tendencia, Momento, Volatilidad, Intradía, Ichimoku) o los suyos («Guardar como…»).</li>
<li><b>Dibujo:</b> líneas horizontales, líneas de tendencia, retrocesos de Fibonacci y notas.
<kbd>Esc</kbd> cancela. Se guardan por activo (en gráficos diario, semanal y mensual).</li>
<li><b>Comparar con un índice:</b> <i>Ver → Comparar con índice</i> dibuja el índice de
referencia (SPY por defecto) partiendo del mismo precio. <i>Ver → Índice de referencia…</i>
lo cambia.</li>
<li><b>Perfil de volumen:</b> <i>Ver → Perfil de volumen</i> muestra cuánto se negoció en cada
franja de precio, con el POC (precio con más volumen) y la zona de valor.</li>
</ul>""",
    ),
    (
        "pestanas",
        "Las pestañas del panel derecho",
        """
<h3>Detalles</h3>
<p>Último precio, cambio, máximos y mínimos, volumen e información de la empresa.</p>
<h3>Análisis</h3>
<p>Reglas fijas y explicables sobre la última barra cerrada (tendencia con medias, RSI, cruces,
volumen, volatilidad, rupturas). Cada señal indica la regla y los valores que la producen. Son
descripciones de los datos, no recomendaciones.</p>
<h3>Proyección</h3>
<p>Rangos estadísticos para las próximas barras (cono de volatilidad o canal de regresión) con
percentiles P5–P95. Incluye una <b>calibración histórica</b>: cuántas veces el precio real acabó
dentro del rango en el pasado. Es un abanico de escenarios con supuestos explícitos, <b>no una
predicción</b>.</p>
<h3>Elliott</h3>
<p>«Buscar ondas» localiza impulsos 1-2-3-4-5 y correcciones A-B-C pasadas que cumplen las
reglas clásicas, y las posibles cuentas en curso con el nivel que las invalidaría. Suele haber
varias interpretaciones posibles.</p>
<h3>Patrones</h3>
<p>Soportes y resistencias (con el número de toques) y patrones chartistas: doble techo/suelo,
hombro-cabeza-hombro, triángulos y banderas. Un patrón solo se confirma al cerrar más allá de su
línea de ruptura; antes aparece «en formación». Se indica el objetivo clásico y el nivel de
invalidación, y cuántas veces funcionaron los patrones pasados de ese activo.</p>
<h3>Fundamentales</h3>
<p>PER, beneficio por acción, dividendo, márgenes, ROE, crecimiento, beta y gráficos anuales de
ingresos, beneficio y dividendos. El <b>calendario</b> muestra la próxima presentación de
resultados (marcada «estimada» si no está confirmada), la fecha ex-dividendo y la de pago.</p>
<h3>Alertas</h3>
<p>Avisos de precio, cambio diario, RSI, cruces y rupturas, sobre velas diarias, de 1 hora o de
15 minutos. Avisan en la barra de estado, con una notificación de Windows y en el historial.
Desde Elliott y Patrones se pueden crear alertas en sus objetivos e invalidaciones.</p>""",
    ),
    (
        "resumen",
        "Resumen del día",
        """
<p><i>Ver → Resumen del día…</i> (<kbd>Ctrl</kbd>+<kbd>D</kbd>). Estado del mercado, qué activos
de su lista suben y bajan, una tarjeta por activo, los avisos recientes y los próximos
resultados y dividendos (de los datos fundamentales ya guardados). Pulse un activo para abrirlo
en el gráfico.</p>""",
    ),
    (
        "escaner",
        "Escáner y escaneo diario",
        """
<p><i>Herramientas → Escáner de la lista…</i> (<kbd>Ctrl</kbd>+<kbd>E</kbd>) aplica las reglas
del programa a toda la lista (hasta 50 activos): señales, patrones, Elliott y distancia a
soporte y resistencia. Se puede filtrar, ordenar y exportar a un informe visual (HTML o PDF) o a
CSV.</p>
<p>Con <b>Incluir fundamentales</b> añade PER, rentabilidad por dividendo, capitalización,
crecimiento de ingresos y margen neto, y permite filtrar por <b>PER máximo</b>, <b>dividendo
mínimo</b>, <b>capitalización mínima</b>, <b>crecimiento de ingresos mínimo</b> y <b>margen neto
mínimo</b>. Un activo sin el dato no pasa un filtro activo.</p>
<p>El <b>escaneo diario automático</b> (en el mismo menú) revisa la lista una vez al día y avisa
solo de lo nuevo: patrones que aparecen o se rompen y señales nuevas.</p>
<p>Junto al escaneo diario llegan los <b>avisos de resultados y dividendos</b>: por defecto 3
días antes de la presentación de resultados y de la fecha ex-dividendo de cada activo de la
lista. Los días se cambian en <i>Herramientas → Avisos de resultados y dividendos…</i> (0 = no
avisar).</p>""",
    ),
    (
        "backtesting",
        "Backtesting",
        """
<p><i>Herramientas → Backtesting…</i> (<kbd>Ctrl</kbd>+<kbd>B</kbd>) prueba una estrategia
(cruce de medias o RSI) sobre el pasado del activo, con comisión y deslizamiento. La señal se
calcula al cierre y se ejecuta en la apertura siguiente, sin usar información del futuro.</p>
<p><i>Herramientas → Backtesting de patrones…</i> hace lo mismo con los patrones chartistas en
varios activos a la vez.</p>
<p class="warnbox">Un buen resultado pasado no garantiza resultados futuros. Desconfíe de
muestras pequeñas (pocas operaciones).</p>""",
    ),
    (
        "cartera",
        "Cartera simulada",
        """
<p><i>Herramientas → Cartera simulada…</i> para practicar <b>sin dinero real</b>.</p>
<ol class="steps">
<li>Escriba el ticker, elija Compra o Venta y si indica <b>Acciones</b> (admite decimales) o
<b>Dólares ($)</b>: con dólares se compran las acciones (o fracciones) que permite ese
importe.</li>
<li>Deje «Cierre del día» para usar el precio de cierre de esa fecha, o escriba un precio.</li>
<li>La comisión es <b>Automática</b> según la cartera (botón <i>Comisiones, dividendos
e impuestos…</i>: fija en $, porcentaje y mínimo). Desmarque «Automática» para escribir otra.</li>
<li>Escriba el <b>motivo</b> en «Nota»: es su diario de operaciones. Más tarde, en la pestaña
<i>Operaciones</i>, <i>Escribir revisión…</i> guarda qué aprendió.</li>
</ol>
<p>Los <b>splits</b> ajustan la cantidad de acciones y los <b>dividendos</b> se cobran en
efectivo en su fecha ex-dividendo; aparecen en «Eventos corporativos». No se modelan impuestos
ni retenciones. No permite ventas en corto ni gastar más efectivo del disponible.</p>
<p><b>Divisas:</b> la cartera se lleva en dólares; un activo en euros o en peniques se anota
con su precio en esa divisa y se convierte con el tipo de cambio del día.</p>
<p>En la pestaña <b>Rebalanceo</b> indica el peso que quiere para cada activo y el programa
calcula qué comprar y vender para llegar a él; puede registrar esas operaciones de una vez.</p>
<p>El informe incluye las <b>estadísticas del diario</b>: porcentaje de ventas con ganancia,
factor de beneficio, ganancia y pérdida medias, tiempo medio mantenida, mejor y peor venta y
resultado por activo.</p>""",
    ),
    (
        "otros",
        "Comparar, importar y exportar",
        """
<ul>
<li><i>Herramientas → Comparar activos…</i>: rendimiento normalizado de hasta 6 tickers con
rentabilidad, volatilidad y caída máxima.</li>
<li><i>Archivo → Importar CSV…</i>: sus propios datos (columnas fecha, apertura, máximo, mínimo,
cierre y volumen opcional; también en español con coma decimal).</li>
<li><i>Archivo → Exportar…</i>: imagen del gráfico (PNG), datos (CSV) o informe (PDF).</li>
<li><i>Archivo → Crear copia de seguridad…</i> guarda todo (listas, alertas, carteras,
configuración) en un archivo; en otro PC, <i>Archivo → Restaurar copia de seguridad…</i> lo
carga al reiniciar.</li>
<li><i>Ayuda → Buscar actualizaciones…</i> comprueba si hay una versión nueva.</li>
</ul>""",
    ),
    (
        "atajos",
        "Atajos de teclado",
        """
<table><tbody>
<tr><td><kbd>F1</kbd></td><td>Esta guía</td></tr>
<tr><td><kbd>Ctrl</kbd>+<kbd>D</kbd></td><td>Resumen del día</td></tr>
<tr><td><kbd>Ctrl</kbd>+<kbd>E</kbd></td><td>Escáner de la lista</td></tr>
<tr><td><kbd>Ctrl</kbd>+<kbd>B</kbd></td><td>Backtesting</td></tr>
<tr><td><kbd>↑</kbd> <kbd>↓</kbd> <kbd>Enter</kbd></td><td>Elegir en la búsqueda</td></tr>
<tr><td><kbd>Supr</kbd></td><td>Quitar el activo seleccionado de la lista</td></tr>
<tr><td><kbd>Esc</kbd></td><td>Cancelar un dibujo</td></tr>
</tbody></table>""",
    ),
    (
        "glosario",
        "Glosario",
        """
<dl class="gloss">
<dt>Vela</dt><dd>Barra con apertura, máximo, mínimo y cierre de un periodo.</dd>
<dt>SMA / EMA</dt><dd>Media móvil simple / exponencial del cierre de las últimas N barras. La
exponencial da más peso a lo reciente.</dd>
<dt>RSI</dt><dd>Índice de fuerza relativa (0–100). Por encima de 70 se suele llamar
«sobrecompra» y por debajo de 30 «sobreventa»; no indica por sí solo un giro.</dd>
<dt>MACD</dt><dd>Diferencia entre dos medias exponenciales y su línea de señal; los cruces
indican cambios de impulso.</dd>
<dt>Bandas de Bollinger</dt><dd>Media de 20 barras ± 2 desviaciones típicas.</dd>
<dt>ATR</dt><dd>Rango verdadero medio: cuánto se mueve el precio por barra (volatilidad).</dd>
<dt>Ichimoku</dt><dd>Sistema de líneas y una «nube» (entre Senkou A y B) proyectada hacia
delante; el precio sobre la nube suele leerse como tendencia alcista.</dd>
<dt>VWAP</dt><dd>Precio medio ponderado por volumen.</dd>
<dt>Fibonacci</dt><dd>Niveles de retroceso (23,6 %, 38,2 %, 50 %, 61,8 %, 78,6 %) de un
movimiento.</dd>
<dt>Soporte / resistencia</dt><dd>Precio donde la cotización giró varias veces hacia arriba /
hacia abajo.</dd>
<dt>Ondas de Elliott</dt><dd>Teoría que describe tendencias en 5 ondas (impulso) seguidas de 3
(corrección). Es interpretativa.</dd>
<dt>PER</dt><dd>Precio / beneficio por acción de los últimos 12 meses.</dd>
<dt>Rentabilidad por dividendo</dt><dd>Dividendo anual por acción / precio.</dd>
<dt>Fecha ex-dividendo</dt><dd>Desde ese día la acción cotiza sin el derecho al próximo
dividendo: hay que tenerla antes.</dd>
<dt>Split</dt><dd>División de cada acción en varias (por ejemplo 4 por 1); el valor total no
cambia.</dd>
<dt>Comisión</dt><dd>Coste que cobra el intermediario por operar.</dd>
<dt>Deslizamiento</dt><dd>Diferencia entre el precio esperado y el de ejecución.</dd>
<dt>Caída máxima (drawdown)</dt><dd>Mayor pérdida desde un máximo anterior.</dd>
<dt>Factor de beneficio</dt><dd>Ganancias brutas / pérdidas brutas de las operaciones.</dd>
<dt>Percentil (P5, P95…)</dt><dd>Valor por debajo del cual queda ese porcentaje de los
escenarios.</dd>
</dl>""",
    ),
    (
        "limites",
        "Límites y avisos",
        """
<div class="warnbox">
<p><b>Este programa no es asesoramiento financiero.</b> Describe datos y reglas; no dice qué
comprar ni vender, y ninguna señal, patrón o proyección garantiza lo que hará el precio.</p>
<p>Los datos proceden de Yahoo Finance y pueden tener retrasos, errores u omisiones. Las fechas
de resultados y dividendos las publica la empresa y pueden cambiar.</p>
<p>La cartera simulada y el backtesting no incluyen impuestos y simplifican los costes
reales.</p>
</div>""",
    ),
]


def guide_html() -> str:
    toc = "".join(f'<a href="#{key}">{title}</a>' for key, title, _body in SECTIONS)
    body = "".join(
        f'<section id="{key}"><h2>{title}</h2>{content}</section>'
        for key, title, content in SECTIONS
    )
    return f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Guía de uso</title><style>{STYLE}{GUIDE_STYLE}</style></head>
<body id="arriba">
<h1>Guía de uso de Análisis de Acciones</h1>
<p class="intro">Qué hace cada parte del programa, cómo leerla y sus límites. Pulse un apartado
para ir a él.</p>
<nav class="toc">{toc}</nav>
{body}
<footer>Análisis de Acciones · No es asesoramiento financiero.</footer>
</body></html>"""
