"""User-facing Spanish strings, kept in one place."""

APP_TITLE = "Análisis de Acciones"

SEARCH_PLACEHOLDER = "Buscar ticker, empresa o cripto (BTC-USD)…"
SEARCH_CRYPTO = "criptomoneda"
SEARCH_NO_RESULTS = "Sin resultados"
SEARCH_SEARCHING = "Buscando…"
SEARCH_RECENT = "Recientes"
NO_SYMBOL = "—"
INDICATORS_BUTTON = "Indicadores"
TIMEFRAME_TOOLTIP = "Intervalo temporal"
COMING_SOON = "Disponible en una próxima fase"

PANEL_WATCHLIST = "Lista de seguimiento"
PANEL_CHART = "Gráfico"
PANEL_DETAILS = "Detalles"
EMPTY_WATCHLIST = "La lista de seguimiento está vacía."
EMPTY_CHART = "Busque un ticker para ver su gráfico."
EMPTY_DETAILS = "Seleccione un activo para ver sus datos."

STATUS_PROVIDER = "Proveedor: {name}"
STATUS_PROVIDER_NONE = "ninguno"
STATUS_LAST_UPDATE = "Última actualización: {when}"
STATUS_NEVER = "—"
STATUS_READY = "Listo"

MENU_FILE = "&Archivo"
MENU_VIEW = "&Ver"
MENU_HELP = "Ay&uda"
ACTION_QUIT = "&Salir"
ACTION_DARK_THEME = "Tema &oscuro"
ACTION_RESET_LAYOUT = "&Restablecer diseño"
ACTION_DISCLAIMER = "&Aviso legal"
ACTION_ABOUT = "A&cerca de"
ACTION_GUIDE = "&Guía de uso"
ACTION_SEARCH = "Buscar activo"
ACTION_REFRESH = "Actualizar datos del activo"
ACTION_INDICATORS = "Indicadores…"
ACTION_BACKUP = "Crear copia de &seguridad…"
ACTION_RESTORE = "&Restaurar copia de seguridad…"
BACKUP_FILTER = "Copia de seguridad (*.sqlite3);;Todos los archivos (*)"
BACKUP_SAVED = "Copia de seguridad guardada en {path}"
BACKUP_RESTORED = "Se restauró la copia de seguridad. Los datos anteriores se guardaron aparte."
RESTORE_CONFIRM = (
    "La copia contiene {watchlists} listas de seguimiento ({symbols} activos), {alerts} "
    "alertas y {portfolios} carteras simuladas ({trades} operaciones), además de la "
    "configuración y los datos de mercado guardados.\n\n"
    "Sustituirá TODOS los datos actuales al reiniciar el programa (los actuales se guardan "
    "aparte por si hiciera falta volver atrás). ¿Continuar?"
)
RESTORE_RESTART = "La copia se aplicará al reiniciar. ¿Reiniciar el programa ahora?"
ACTION_SOFTWARE_GRAPHICS = "Gráficos compatibles (sin aceleración)"
SOFTWARE_GRAPHICS_TIP = (
    "Dibuja los gráficos sin la tarjeta gráfica. Úselo si el programa se cierra solo o los "
    "gráficos aparecen en blanco. Se aplica al reiniciar el programa."
)
SOFTWARE_GRAPHICS_RESTART = "El modo de gráficos se aplicará la próxima vez que abra el programa."
UNCLEAN_EXIT_TITLE = "El programa se cerró de forma inesperada"
UNCLEAN_EXIT_TEXT = (
    "La última vez el programa no se cerró correctamente. Sus datos están a salvo (se guardan "
    "al momento).\n\nSi vuelve a ocurrir, los detalles técnicos están en la carpeta de "
    "registros:\n{log}\n(archivos analisis_acciones.log y crash.log)."
)
UNCLEAN_EXIT_SOFTWARE = (
    "Como ha ocurrido varias veces seguidas, se ha activado «Ver → Gráficos compatibles (sin "
    "aceleración)», que evita los fallos de algunas tarjetas gráficas. Puede desactivarlo en "
    "el mismo menú."
)
GUIDE_TITLE = "Guía de uso"

ABOUT_TEXT = (
    "<b>Análisis de Acciones</b> {version}<br><br>"
    "Herramienta de análisis técnico de acciones.<br>"
    "No ejecuta operaciones reales."
)

DISCLAIMER_TITLE = "Aviso legal"
DISCLAIMER_TEXT = (
    "Esta aplicación es una herramienta de análisis técnico con fines informativos "
    "y educativos.\n\n"
    "• No constituye asesoramiento financiero ni recomendación de compra o venta.\n"
    "• Las señales técnicas describen condiciones de los datos; no son predicciones.\n"
    "• Los datos de mercado proceden de proveedores externos y pueden contener "
    "retrasos, errores u omisiones.\n\n"
    "Usted es el único responsable de sus decisiones de inversión."
)
DISCLAIMER_ACCEPT = "Entiendo y acepto"
DISCLAIMER_REJECT = "Salir"

ERROR_TITLE = "Error"
STARTUP_ERROR = "No se pudo iniciar la aplicación."

ACTION_CHECK_UPDATES = "Buscar &actualizaciones…"
UPDATE_TITLE = "Actualizaciones"
UPDATE_CHECKING = "Buscando actualizaciones…"
UPDATE_UP_TO_DATE = "El programa está actualizado."
UPDATE_AVAILABLE = "Hay una actualización disponible ({count} cambio(s)):"
UPDATE_APPLYING = "Descargando e instalando la actualización…"
UPDATE_DONE = "Actualización instalada. Reinicie el programa para usar la nueva versión."
UPDATE_DEPS_REINSTALLED = "También se actualizaron las dependencias."
UPDATE_APPLY = "Actualizar"
UPDATE_RESTART = "Reiniciar ahora"
UPDATE_CLOSE = "Cerrar"
ACTION_CHECK_UPDATES_ON_STARTUP = "Buscar actualizaciones al &iniciar"
UPDATE_NOTICE = "Actualización disponible"
UPDATE_NOTICE_TOOLTIP = "Hay una nueva versión ({count} cambio(s)). Pulse para ver los detalles."

INTERVAL_LABELS = {
    "1m": "1 min", "5m": "5 min", "15m": "15 min", "30m": "30 min",
    "1h": "1 hora", "4h": "4 horas", "1D": "Diario", "1W": "Semanal", "1M": "Mensual",
}  # fmt: skip

ACTION_IMPORT_CSV = "&Importar CSV…"
IMPORT_CSV_TITLE = "Importar datos desde CSV"
IMPORT_CSV_FILTER = "Archivos CSV (*.csv *.txt);;Todos los archivos (*)"
IMPORT_CSV_NAME_PROMPT = "Nombre para esta serie (letras, números, '-', '_' o '.'):"

LOADING = "Cargando {symbol}…"
LOAD_ERROR = "No se pudo cargar {symbol}"
SESSION_IN_PROGRESS = "La última barra corresponde a la sesión en curso (aún no cerrada)."
STALE_DATA = "Sin conexión: se muestran datos guardados."
FROM_CACHE = "caché"

DETAIL_PRICE = "Precio"
DETAIL_CHANGE = "Cambio"
DETAIL_CHANGE_PCT = "Cambio %"
DETAIL_OPEN = "Apertura"
DETAIL_HIGH = "Máximo"
DETAIL_LOW = "Mínimo"
DETAIL_PREV_CLOSE = "Cierre anterior"
DETAIL_VOLUME = "Volumen"
DETAIL_52W_HIGH = "Máx. 52 semanas"
DETAIL_52W_LOW = "Mín. 52 semanas"
DETAIL_CURRENCY = "Moneda"
DETAIL_EXCHANGE = "Mercado"
DETAIL_SECTOR = "Sector"
DETAIL_INDUSTRY = "Industria"
DETAILS_LOADING = "Cargando detalles…"
DETAILS_SOURCE_QUOTE = "Cotización del proveedor: {when}"
DETAILS_SOURCE_BARS = "Datos de la última barra diaria: {when}"
MARKET_STATES = {
    "PRE": "Pre-apertura",
    "PREPRE": "Pre-apertura",
    "REGULAR": "Mercado abierto",
    "POST": "Post-cierre",
    "POSTPOST": "Post-cierre",
    "CLOSED": "Mercado cerrado",
}

CHART_LOAD_ERROR = (
    "No se pudo iniciar el motor del gráfico. Consulte el registro para más detalles."
)
CHART_NO_DATA = "No hay datos para mostrar."
CHART_RECOVERING = "El motor del gráfico se detuvo; recargándolo…"
CHART_RENDER_FAILED = (
    "El motor del gráfico ha fallado varias veces. Active «Ver → Gráficos compatibles (sin "
    "aceleración)» y reinicie el programa."
)
CHART_TYPE_TOOLTIP = "Tipo de gráfico"
CHART_TYPE_LABELS = {"candles": "Velas", "line": "Línea"}
LEGEND_OPEN = "A"
LEGEND_HIGH = "Máx"
LEGEND_LOW = "Mín"
LEGEND_CLOSE = "C"
LEGEND_VOLUME = "Vol"

INDICATORS_TITLE = "Indicadores"
INDICATORS_ADD = "Añadir"
INDICATORS_REMOVE = "Quitar"
INDICATORS_ACTIVE = "Indicadores en el gráfico:"
INDICATORS_PARAMS = "Parámetros"
INDICATORS_APPLY_PARAMS = "Aplicar parámetros"
INDICATORS_EMPTY = "Añada un indicador desde la lista superior."
INDICATORS_VISIBLE_TIP = "Marque o desmarque para mostrar u ocultar el indicador."
INDICATORS_FAILED = "No se pudieron calcular: {names}"
DIALOG_OK = "Aceptar"
DIALOG_CANCEL = "Cancelar"

WATCHLIST_MENU = "Opciones de la lista"
WATCHLIST_NEW = "Nueva lista…"
WATCHLIST_CRYPTO_EXAMPLE = "Crear lista de criptomonedas de ejemplo"
WATCHLIST_ALTCOIN_EXAMPLE = "Crear lista de altcoins de ejemplo"
WATCHLIST_RENAME = "Renombrar lista…"
WATCHLIST_DELETE = "Eliminar lista"
WATCHLIST_DELETE_CONFIRM = "¿Eliminar la lista «{name}» y todos sus activos?"
WATCHLIST_NAME_PROMPT = "Nombre de la lista:"
WATCHLIST_COL_SYMBOL = "Ticker"
WATCHLIST_COL_LAST = "Último"
WATCHLIST_COL_CHANGE = "Cambio"
WATCHLIST_ADD_CURRENT = "Añadir el activo del gráfico a la lista"
WATCHLIST_REMOVE = "Quitar de la lista"
WATCHLIST_UP = "Subir"
WATCHLIST_DOWN = "Bajar"
WATCHLIST_REFRESH = "Actualizar valores"
WATCHLIST_ALREADY = "{symbol} ya está en la lista."
WATCHLIST_NOTHING_OPEN = "Abra primero un activo en el gráfico."
WATCHLIST_ROW_TIP = "Último cierre diario: {date}"
EMPTY_WATCHLIST_HINT = "Abra un activo y pulse «+» para añadirlo."

TAB_DETAILS = "Detalles"
TAB_ANALYSIS = "Análisis"
ANALYSIS_EMPTY = "Abra un activo para analizarlo."
ANALYSIS_RUNNING = "Analizando…"
ANALYSIS_FAILED = "No se pudo completar el análisis. Consulte el registro."
ANALYSIS_SUMMARY = "{title} · datos hasta {date} ({bars} barras)"
ANALYSIS_PARTIAL_EXCLUDED = "Se excluye la barra de la sesión en curso (aún no cerrada)."
ANALYSIS_NO_SIGNALS = "Ninguna regla detectó condiciones destacables en la última barra."
ANALYSIS_BAR_DATE = "Barra evaluada: {date}"
ANALYSIS_DIRECTION = {
    "bullish": "Condición de carácter alcista",
    "bearish": "Condición de carácter bajista",
    "neutral": "Condición neutral / informativa",
}
ANALYSIS_DISCLAIMER = (
    "Señales descriptivas generadas por reglas fijas sobre datos históricos. "
    "No son predicciones ni recomendaciones de inversión."
)

TAB_ALERTS = "Alertas"
ALERT_NEW = "Nueva…"
ALERT_NEW_TITLE = "Nueva alerta"
ALERT_TOGGLE = "Pausar/Activar"
ALERT_DELETE = "Eliminar"
ALERT_CHECK_NOW = "Comprobar ahora"
ALERT_CREATE = "Crear alerta"
ALERT_SYMBOL = "Activo"
ALERT_CONDITION = "Condición"
ALERT_COL_CONDITION = "Alerta"
ALERT_COL_STATE = "Estado"
ALERT_COL_LAST = "Último aviso"
ALERT_ACTIVE = "Activa"
ALERT_PAUSED = "En pausa"
ALERT_HISTORY = "Historial de avisos"
ALERT_NO_HISTORY = "Todavía no se ha disparado ninguna alerta."
ALERT_CHECKING = "Comprobando alertas…"
ALERT_CHECKED = "Comprobadas {count} alertas; {fired} nuevas."
ALERT_PROBLEMS = "{count} incidencia(s) (pase el ratón para ver el detalle)."
ALERT_EOD_NOTE = (
    "Las alertas se evalúan sobre velas cerradas del intervalo elegido mientras el programa está "
    "abierto: diarias cada 15 minutos; intradía (1 hora, 15 min) cada 2 minutos. Una alerta de "
    "nivel avisa al cumplirse la condición y se rearma cuando deja de cumplirse."
)
ALERT_INTERVAL = "Velas"
ALERT_INTERVAL_CHOICES = {"1D": "Diarias", "1h": "De 1 hora", "15m": "De 15 minutos"}
ALERT_NOTIFY_TITLE = "Alerta: {description}"

MENU_TOOLS = "&Herramientas"
ACTION_BACKTEST = "&Backtesting…"
BT_NEED_DATA = "Abra primero un activo en el gráfico para probar estrategias sobre sus datos."
BT_TITLE = "Backtesting · {title}"
BT_STRATEGY = "Estrategia"
BT_COSTS = "Capital y costes"
BT_CAPITAL = "Capital inicial"
BT_COMMISSION = "Comisión"
BT_FIXED = "Comisión fija por orden"
BT_SLIPPAGE = "Deslizamiento"
BT_RUN = "Ejecutar backtest"
BT_FAILED = "No se pudo ejecutar el backtest. Consulte el registro."
BT_TIMING = (
    "Sin ventaja de información futura: las señales se calculan al cierre de cada barra y las "
    "órdenes se ejecutan en la apertura de la barra siguiente. Solo posiciones largas, con todo "
    "el capital disponible y acciones enteras."
)
BT_STATS = (
    ("initial", "Capital inicial"),
    ("final", "Capital final"),
    ("return", "Rentabilidad total"),
    ("trades", "Operaciones cerradas"),
    ("winning", "Ganadoras"),
    ("losing", "Perdedoras"),
    ("win_rate", "% de acierto"),
    ("drawdown", "Caída máxima"),
    ("profit_factor", "Factor de beneficio"),
    ("buy_hold", "Comprar y mantener"),
    ("exposure", "Tiempo invertido"),
    ("commissions", "Comisiones pagadas"),
)
BT_TRADE_COLUMNS = ["Entrada", "Precio", "Salida", "Precio", "Acciones", "Resultado"]
BT_EQUITY = "Estrategia"
BT_REFERENCE = (
    "{name}: rentabilidad {ret}, {trades} operaciones, caída máxima {drawdown}. Diferencia de "
    "la estrategia: {diff} de rentabilidad y {dd_diff} de caída máxima (positivo = menor caída)."
)
BT_BUY_HOLD = "Comprar y mantener"
BT_OPEN = "abierta"
BT_OPEN_NOTE = (
    "La última operación sigue abierta: se valora al último cierre y no cuenta en las estadísticas "
    "de operaciones cerradas."
)
BT_PF_UNDEFINED = "Factor de beneficio no definido: no hubo operaciones perdedoras."
BT_DISCLAIMER = (
    "Simulación sobre datos históricos con supuestos simplificados. Los resultados pasados no "
    "garantizan resultados futuros y no constituyen una recomendación de inversión."
)

ACTION_EXPORT_IMAGE = "Exportar gráfico como &imagen…"
ACTION_EXPORT_CSV = "Exportar &datos (CSV)…"
ACTION_EXPORT_PDF = "Exportar &informe (PDF)…"
EXPORT_NOTHING = "Abra primero un activo en el gráfico."
EXPORT_DONE = "Guardado: {path}"
EXPORT_FAILED = "No se pudo guardar el archivo: {error}"
EXPORT_IMAGE_FILTER = "Imagen PNG (*.png)"
EXPORT_CSV_FILTER = "CSV (*.csv)"
EXPORT_PDF_FILTER = "PDF (*.pdf)"
REPORT_GENERATED = "Generado el {when} con Análisis de Acciones {version}"
REPORT_INDICATORS = "Indicadores en el gráfico"
REPORT_ANALYSIS_DATE = "Datos hasta {date} ({bars} barras)."
BT_EXPORT = "Exportar resultados…"
BT_EXPORT_DONE = "Resultados guardados en: {files}"

MENU_DRAW = "Dibujo"
DRAW_HLINE = "Línea horizontal (soporte/resistencia)"
DRAW_TREND = "Línea de tendencia"
DRAW_FIB = "Retroceso de Fibonacci"
DRAW_NOTE = "Nota"
DRAW_UNDO = "Deshacer último dibujo"
DRAW_CLEAR = "Borrar todos los dibujos del activo"
DRAW_NOTE_PROMPT = "Texto de la nota:"
DRAW_NEED_SYMBOL = "Abra primero un activo para dibujar sobre él."
DRAW_HINTS = {
    "hline": ("Haga clic en el precio donde trazar la línea (Esc cancela).", ""),
    "trend": (
        "Haga clic en el primer punto de la línea (Esc cancela).",
        "Haga clic en el segundo punto.",
    ),
    "fib": (
        "Haga clic en el inicio del movimiento (100 %) (Esc cancela).",
        "Haga clic en el final del movimiento (0 %).",
    ),
    "note": ("Haga clic en la barra donde colocar la nota (Esc cancela).", ""),
}

ACTION_COMPARE = "&Comparar activos…"
CMP_TITLE = "Comparar activos"
CMP_SYMBOLS = "Activos:"
CMP_PLACEHOLDER = "AAPL, MSFT, NVDA (máximo 6)"
CMP_PERIOD = "Periodo:"
CMP_RUN = "Comparar"
CMP_EMPTY = "Indique al menos un ticker."
CMP_LOADING = "Cargando datos…"
CMP_COLUMNS = ["Activo", "Rentabilidad", "Volatilidad anual", "Caída máxima", "Volumen medio",
               "RSI 14"]  # fmt: skip
CMP_RANGE = "Periodo común: {start} → {end} ({sessions} sesiones)."
CMP_NOTE = (
    "Rendimiento normalizado a 0 % en la primera sesión común, con cierres diarios. Volatilidad: "
    "desviación típica anualizada de los rendimientos logarítmicos diarios (×√252; ×√365 en "
    "criptomonedas, que cotizan todos los días)."
)

TAB_PROJECTION = "Proyección"
PROJ_METHOD = "Método"
PROJ_CONE = "Cono de volatilidad"
PROJ_REGRESSION = "Canal de regresión"
PROJ_HORIZON = "Horizonte"
PROJ_LOOKBACK = "Ventana histórica"
PROJ_BARS_SUFFIX = " barras"
PROJ_SHOW = "Mostrar en el gráfico"
PROJ_RUN = "Calcular proyección"
PROJ_RUNNING = "Calculando y comprobando en el historial…"
PROJ_EMPTY = "Abra un activo y pulse «Calcular proyección»."
PROJ_STALE = "Los datos del gráfico cambiaron: vuelva a calcular la proyección."
PROJ_MEDIAN = "Mediana (P50)"
PROJ_HEADER = "{method}: rango estimado dentro de {horizon} barras (desde {base})"
PROJ_NO_CALIBRATION = "Historial insuficiente para comprobar la fiabilidad del método."
PROJ_CALIBRATION = (
    "Comprobación histórica ({samples} pruebas, cada {step} barras, usando solo datos "
    "anteriores a cada fecha): el precio real {horizon} barras después quedó dentro del "
    "rango P5–P95 el {in90:.0f} % de las veces (ideal: 90 %) y dentro de P25–P75 el "
    "{in50:.0f} % (ideal: 50 %). Error mediano frente a la mediana: {error:.1f} %."
)
PROJ_DISCLAIMER = (
    "Rangos estadísticos basados en el comportamiento pasado, no predicciones. El precio "
    "puede salir del rango; los movimientos extremos son más frecuentes de lo que suponen "
    "estos modelos. No es una recomendación de inversión."
)

TAB_ELLIOTT = "Elliott"
ELL_THRESHOLD = "Umbral ZigZag"
ELL_AUTO = "Automático"
ELL_SHOW = "Mostrar en el gráfico"
ELL_RUN = "Buscar ondas"
ELL_RUNNING = "Buscando ondas…"
ELL_EMPTY = "Abra un activo y pulse «Buscar ondas»."
ELL_STALE = "Los datos del gráfico cambiaron: vuelva a buscar las ondas."
ELL_SUMMARY = (
    "Umbral {threshold:.1f} %: {pivots} giros, {past} cuentas pasadas y {current} cuentas "
    "posibles en curso. Un umbral mayor busca ondas de mayor grado."
)
ELL_CURRENT_GROUP = "Posibles cuentas en curso"
ELL_PAST_GROUP = "Ondas pasadas detectadas"
ELL_NONE = "(ninguna cumple las reglas)"
ELL_IMPULSE = "Impulso {direction} 1-2-3-4-5"
ELL_IMPULSE_PARTIAL = "Impulso {direction} {waves}"
ELL_CORRECTION = "Corrección {direction} A-B-C"
ELL_CORRECTION_PARTIAL = "Corrección {direction} {waves}"
ELL_UP = "alcista"
ELL_DOWN = "bajista"
ELL_ITEM = "{name} · {start} → {end} · {score}"
ELL_SCORE = "{passed}/{total} pautas"
ELL_NO_GUIDES = "pautas aún no evaluables"
ELL_RULES = "Reglas (obligatorias):"
ELL_GUIDES = "Pautas de Fibonacci y alternancia (orientativas):"
ELL_TARGETS = "Niveles de referencia si la cuenta es correcta:"
ELL_INVALIDATION = "La cuenta queda invalidada si el precio supera {price}."
ELL_INVALIDATION_DOWN = "La cuenta queda invalidada si el precio cae por debajo de {price}."
ELL_LAST_POINT = "El último punto es provisional: el tramo actual puede seguir extendiéndose."
ELL_DISCLAIMER = (
    "Las ondas de Elliott son una interpretación: el mismo gráfico admite varias cuentas "
    "válidas y la detección automática depende del umbral. Solo se muestran cuentas que cumplen "
    "las reglas clásicas. No es una predicción ni una recomendación de inversión."
)

TAB_PATTERNS = "Patrones"
PAT_THRESHOLD = "Umbral de giros"
PAT_SHOW_LEVELS = "Soportes y resistencias en el gráfico"
PAT_SHOW_PATTERNS = "Patrones en el gráfico"
PAT_RUN = "Buscar patrones"
PAT_RUNNING = "Buscando patrones…"
PAT_EMPTY = "Abra un activo y pulse «Buscar patrones»."
PAT_STALE = "Los datos del gráfico cambiaron: vuelva a buscar los patrones."
PAT_SUMMARY = (
    "Giros con umbral {threshold:.1f} %, tolerancia {tolerance:.1f} %: {levels} niveles y "
    "{patterns} patrones."
)
PAT_TRACK = (
    "Historial en este activo: de {total} patrones confirmados con resultado, {hit} alcanzaron "
    "su objetivo y {failed} se invalidaron antes."
)
PAT_TRACK_NONE = "Aún no hay patrones confirmados con resultado en este activo."
PAT_LEVELS_GROUP = "Soportes y resistencias"
PAT_FORMING_GROUP = "Patrones en formación"
PAT_PAST_GROUP = "Patrones pasados"
PAT_NONE = "(ninguno)"
PAT_SUPPORT = "Soporte"
PAT_RESISTANCE = "Resistencia"
PAT_LEVEL_ITEM = "{role} {price} · {touches} toques · último {last}"
PAT_LEVEL_DETAILS = (
    "{role} en {price} (zona {low}–{high}).\n{touches} giros del precio en esta zona entre "
    "{first} y {last}. Cuantos más toques, más relevante suele ser el nivel; un nivel roto "
    "suele cambiar de papel (la resistencia pasa a soporte y viceversa)."
)
PAT_ITEM = "{name} · {start} → {end} · {status}"
PAT_STATUS = {
    "forming": "en formación",
    "confirmed": "confirmado, objetivo pendiente",
    "target": "objetivo alcanzado",
    "invalidated": "invalidado",
}
PAT_CONDITIONS = "Condiciones comprobadas:"
PAT_BREAKOUT = "Ruptura confirmada al cierre del {date}."
PAT_NO_BREAKOUT = (
    "Sin ruptura todavía: el patrón solo se confirma cuando el precio cierra más allá de la "
    "línea de ruptura."
)
PAT_INVALIDATION = "Nivel de invalidación: {price}."
PAT_DISCLAIMER = (
    "Detección automática con reglas fijas; los patrones fallan con frecuencia (vea el "
    "historial de arriba). Los objetivos son la medida clásica del patrón, no una predicción. "
    "No es una recomendación de inversión."
)

CREATE_LEVEL_ALERTS = "Crear alertas de precio"
CREATE_LEVEL_ALERTS_TIP = (
    "Crea alertas de cierre por encima/debajo de los niveles de la selección (objetivos e "
    "invalidación). Se comprueban con las demás alertas."
)
LEVEL_ALERTS_CREATED = "Se crearon {count} alertas de precio para {symbol} (pestaña Alertas)."
LEVEL_ALERTS_UNAVAILABLE = "Las alertas no están disponibles en esta sesión."

ACTION_SCANNER = "&Escáner de la lista…"
ACTION_EXHAUSTION_COMPARE = "&Agotamiento en varios activos…"
ACTION_EXHAUSTION_PROVEN = "Avisar de agotamiento solo donde anticipó giros"
ACTION_EXHAUSTION_PROVEN_TIP = (
    "El escaneo diario avisa de señales de agotamiento solo en los activos cuyo historial muestra "
    "que precedieron giros claramente más a menudo que un día normal (10 casos o más, 10 puntos "
    "de diferencia y p < 0,05). El escáner y la pestaña Agotamiento las siguen mostrando todas."
)
EXC_TITLE = "Señales de agotamiento en varios activos"
EXC_RUN = "Comparar"
EXC_HORIZON = "A {h} sesiones"
EXC_COLUMNS = [
    "Activo", "Ahora",
    "Subidas: casos", "Subidas: % que bajó", "Subidas: p (azar)", "Subidas: lectura",
    "Bajadas: casos", "Bajadas: % que subió", "Bajadas: p (azar)", "Bajadas: lectura",
]  # fmt: skip
EXC_SUMMARY_UP = (
    "Agotamiento de las subidas: anticipó bajadas en {useful} de {total} activos ({names}); la "
    "subida siguió más de lo normal en {cont}."
)
EXC_SUMMARY_DOWN = (
    "Agotamiento de las bajadas: anticipó rebotes en {useful} de {total} activos ({names}); la "
    "bajada siguió más de lo normal en {cont}."
)
EXC_NOTE = (
    "Para cada activo: veces pasadas con señales de agotamiento (sin solapar, solo con los datos "
    "de cada fecha) y % en que el precio giró después, frente a un día normal de la misma "
    "tendencia. «Anticipó» exige 10 casos, 10 puntos de diferencia y p < 0,05. Con muchos "
    "activos, alguno saldrá «bien» por casualidad. Usa los umbrales de la pestaña Agotamiento. "
    "Doble clic abre el activo. No es una predicción ni una recomendación."
)
SCAN_TITLE = "Escáner"
SCAN_SYMBOLS = "Tickers:"
SCAN_PLACEHOLDER = "Tickers separados por comas (máximo {max})"
SCAN_PROGRESS = "Analizando {symbol} ({done} de {total})…"
SCAN_CANCEL = "Cancelar"
SCAN_CANCELLED = "Escaneo cancelado: se muestran los {count} activos analizados."
SCAN_RUN = "Escanear"
SCAN_EMPTY = "Escriba al menos un ticker."
SCAN_RUNNING = "Escaneando {count} activos… (puede tardar si hay que descargar datos)"
SCAN_DONE = (
    "{count} activos analizados con barras diarias cerradas. Doble clic en una fila para abrirla."
)
SCAN_FILTER = "Mostrar:"
SCAN_FILTERS = {
    "all": "Todos",
    "patterns": "Con patrones en formación o rupturas recientes",
    "bullish": "Con más señales alcistas que bajistas",
    "bearish": "Con más señales bajistas que alcistas",
    "elliott": "Con posible cuenta de Elliott en curso",
    "exhaustion": "Con señales de agotamiento de la tendencia",
}
SCAN_COLUMNS = (
    "Ticker",
    "Cierre",
    "Cambio %",
    "RSI 14",
    "Alcistas",
    "Bajistas",
    "Patrones",
    "Elliott",
    "Soporte %",
    "Resistencia %",
    "PER",
    "Div. %",
    "Cap. (mil M)",
    "Crec. ingr. %",
    "Margen %",
    "Agotamiento",
)
SCAN_FUNDAMENTALS = "Incluir fundamentales"
SCAN_EXH_UP = "subida {met}/{total}"
SCAN_EXH_DOWN = "bajada {met}/{total}"
SCAN_EXH_TIP = (
    "Señales de agotamiento de la tendencia (pestaña Agotamiento): no indican cuándo terminará."
)
SCAN_FUNDAMENTALS_TIP = (
    "Descarga el PER y la rentabilidad por dividendo de cada activo (se guardan un día). "
    "El escaneo tarda más la primera vez."
)
SCAN_MAX_PE = "PER máx.:"
SCAN_MIN_YIELD = "Div. mín.:"
SCAN_MIN_CAP = "Capitalización mín.:"
SCAN_MIN_GROWTH = "Crec. ingresos mín.:"
SCAN_MIN_MARGIN = "Margen neto mín.:"
SCAN_CAP_SUFFIX = " mil M"
SCAN_NO_LIMIT = "sin límite"
SCAN_FUNDAMENTALS_HINT = (
    "Los filtros de PER y dividendo necesitan «Incluir fundamentales» y volver a escanear."
)
SCAN_FUNDAMENTALS_NOTE = (
    "PER = precio / beneficio de los últimos 12 meses; con pérdidas o sin dato no pasa el "
    "filtro de PER. Div. % = dividendo anual / precio. Cap. = capitalización en miles de "
    "millones. Crec. ingr. = ingresos frente al mismo periodo del año anterior. Margen = "
    "beneficio neto / ventas. Datos de Yahoo Finance."
)
SCAN_NOTE = (
    "Cada fila resume las mismas reglas de las pestañas Análisis, Patrones y Elliott. "
    "«Soporte»/«Resistencia» = distancia en % al nivel más cercano. Es una descripción de los "
    "datos, no una recomendación de inversión."
)

SCAN_EXPORT = "Exportar"
SCAN_EXPORT_HTML = "Informe visual (HTML, se abre en el navegador)…"
SCAN_EXPORT_PDF = "Informe visual (PDF, para imprimir o enviar)…"
SCAN_EXPORT_CSV = "Datos (CSV, para hojas de cálculo)…"
SCAN_EXPORT_FILTER_NOTE = "Filtro aplicado: {name}."
SCAN_EXPORT_SAVED = "Guardado en {path}"
SCAN_EXPORT_FAILED = "No se pudo guardar el archivo: {error}"
SCAN_EXPORT_WORKING = "Generando PDF…"

ACTION_DAILY_SCAN = "Escaneo diario automático de la lista"
ACTION_LAST_DAILY_SCAN = "Ver el último escaneo diario…"
DAILY_SCAN_EVENT = "{symbol} · escaneo diario"
CALENDAR_EVENT = "{symbol} · calendario"
ACTION_CALENDAR_NOTICES = "Avisos de resultados y dividendos…"
CALENDAR_NOTICES_PROMPT = (
    "Avisar con cuántos días de antelación de la presentación de resultados y de la fecha "
    "ex-dividendo de los activos de la lista (0 = no avisar).\n\nSe comprueba junto con el "
    "escaneo diario automático (debe estar activado) y cada fecha se avisa una vez."
)
DAILY_SCAN_DONE = "Escaneo diario: {count} novedades en {symbols} activos."
DAILY_SCAN_NONE = "Escaneo diario: sin novedades respecto a la sesión anterior ({count} activos)."
DAILY_SCAN_FAILED = "Escaneo diario: no se pudo analizar ningún activo (¿sin conexión?)."

ACTION_PATTERN_BACKTEST = "Backtesting de &patrones…"
PBT_TITLE = "Backtesting de patrones"
PBT_RUN = "Simular"
PBT_MAX_BARS = "Plazo máximo:"
PBT_LONG_ONLY = "Solo compras (sin ventas cortas)"
PBT_COMMISSION = "Comisión %:"
PBT_SLIPPAGE = "Deslizamiento %:"
PBT_PATTERNS = "Patrones"
PBT_RUNNING = (
    "Simulando {count} activos… Cada patrón se comprueba con los datos de su día, puede "
    "tardar unos segundos por activo."
)
PBT_DONE = "{trades} operaciones en {symbols} activos."
PBT_TAB_SUMMARY = "Resumen visual"
PBT_TAB_TRADES = "Operaciones"
PBT_TRADE_COLUMNS = (
    "Ticker",
    "Patrón",
    "Operación",
    "Entrada",
    "Precio",
    "Salida",
    "Precio",
    "Motivo",
    "Resultado %",
)

DRAW_INTRADAY = (
    "Los dibujos se guardan por fecha de sesión: están disponibles en los gráficos diario, "
    "semanal y mensual."
)

ACTION_VOLUME_PROFILE = "Perfil de volumen"
VOLUME_PROFILE_TIP = (
    "Volumen negociado en cada franja de precio durante las últimas {bars} barras. POC = precio "
    "con más volumen; VA = zona donde se negoció el 70 % del volumen."
)

ACTION_SUMMARY = "&Resumen del día…"
SUMMARY_TITLE = "Resumen del día"
SUMMARY_ON_START = "Mostrar al iniciar el programa"
SUMMARY_REFRESH = "Actualizar"
SUMMARY_LOADING = "Cargando {count} activos…"

TEMPLATE_LABEL = "Plantilla:"
TEMPLATE_LOAD = "Cargar"
TEMPLATE_SAVE = "Guardar como…"
TEMPLATE_DELETE = "Eliminar"
TEMPLATE_BUILTIN = "{name} (predefinida)"
TEMPLATE_NAME_PROMPT = "Nombre de la plantilla (se guardan los indicadores de la lista):"

ACTION_BENCHMARK = "Comparar con índice ({symbol})"
ACTION_BENCHMARK_CHOOSE = "Índice de referencia…"
BENCHMARK_PROMPT = (
    "Ticker del índice o ETF de referencia (por ejemplo SPY = S&P 500, QQQ = Nasdaq 100, "
    "DIA = Dow Jones, IWM = Russell 2000, ^GSPC = índice S&P 500):"
)
BENCHMARK_SUMMARY = (
    "Desde {start}: {asset} {asset_ret} % · {bench} {bench_ret} % · diferencia {diff} puntos "
    "(la línea de {bench} parte del precio de {asset} en esa fecha)."
)
BENCHMARK_NO_OVERLAP = "No hay fechas comunes con {bench} para comparar."
BENCHMARK_FAILED = "No se pudo cargar {bench}: {error}"

ACTION_PORTFOLIO = "Cartera &simulada…"
PF_TITLE = "Cartera simulada"
PF_PORTFOLIO = "Cartera:"
PF_NEW = "Nueva cartera…"
PF_NEW_NAME = "Nombre de la cartera:"
PF_NEW_CASH = "Capital inicial (ficticio):"
PF_DELETE = "Eliminar cartera"
PF_DELETE_CONFIRM = "¿Eliminar «{name}» y todas sus operaciones? No se puede deshacer."
PF_NEW_TRADE = "Nueva operación ficticia"
PF_SYMBOL = "Ticker"
PF_SIDE = "Operación"
PF_BUY = "Compra"
PF_SELL = "Venta"
PF_QUANTITY = "Cantidad"
PF_PRICE = "Precio"
PF_PRICE_CLOSE = "Cierre del día"
PF_PRICE_TIP = (
    "Precio por acción en la divisa en que cotiza el activo (p. ej. euros para SAP.DE, "
    "peniques para VOD.L). La cartera lo convierte a dólares con el tipo de cambio del día."
)
PF_DATE = "Fecha"
PF_COMMISSION = "Comisión"
PF_NOTE = "Nota:"
PF_ADD = "Registrar"
PF_SAVING = "Registrando la operación…"
PF_LOADING = "Calculando la cartera…"
PF_DELETE_TRADE = "Eliminar operación seleccionada"
PF_TAB_SUMMARY = "Resumen"
PF_TAB_TRADES = "Operaciones"
PF_TRADE_COLUMNS = (
    "Fecha",
    "Ticker",
    "Operación",
    "Cantidad",
    "Precio",
    "Comisión ($)",
    "Importe ($)",
    "Resultado ($)",
    "Motivo",
    "Revisión",
)
PF_MODE_SHARES = "Acciones"
PF_MODE_DOLLARS = "Dólares ($)"
PF_AMOUNT = "Importe ($)"
PF_COMMISSION_AUTO = "Automática"
PF_COMMISSION_AUTO_TIP = (
    "Marcada: se aplica la comisión configurada en la cartera. Desmarcada: escriba la comisión "
    "de esta operación."
)
PF_COSTS = "Ajustes de la cartera…"
PF_COSTS_TITLE = "Ajustes de la cartera"
PF_ALERTS_TITLE = "Avisos de la cartera"
PF_ALERTS_INTRO = (
    "Se comprueban cada 30 minutos mientras el programa está abierto y llegan como las alertas. "
    "Cada aviso se da una vez y vuelve a armarse cuando la situación desaparece. 0 = sin aviso."
)
PF_ALERT_LOSS = "Una posición pierde desde su coste medio:"
PF_ALERT_DRIFT = "Un activo se aleja de su peso objetivo:"
PF_ALERT_DRAWDOWN = "La cartera cae desde su máximo:"
PF_ALERT_OFF = "no avisar"
PF_POINTS = " puntos"
PORTFOLIO_EVENT = "Cartera «{name}»"
PF_COSTS_INTRO = (
    "Comisión de cada operación nueva = fija + porcentaje del importe, con un mínimo. Las "
    "operaciones ya registradas conservan su comisión."
)
PF_COSTS_FIXED = "Comisión fija por operación ($):"
PF_COSTS_PCT = "Porcentaje del importe (%):"
PF_COSTS_MIN = "Comisión mínima ($):"
PF_COSTS_DIVIDENDS = "Cobrar dividendos en efectivo (los splits se aplican siempre)"
PF_TAXES_TITLE = "Impuestos (simulación simplificada)"
PF_TAXES_WITHHOLDING = "Retención sobre dividendos (%):"
PF_TAXES_GAINS = "Impuesto sobre ganancias (%):"
PF_TAXES_INTRO = (
    "La retención se descuenta de cada dividendo cobrado. El impuesto sobre ganancias es una "
    "estimación sobre el resultado neto de las ventas de cada año: se muestra en el informe "
    "pero no se descuenta del efectivo. Consulte la fiscalidad real de su país."
)
PF_COSTS_SUMMARY = "Comisión: {text}"
PF_COSTS_NONE = "sin comisión"
PF_NOTE_PLACEHOLDER = "Motivo de la operación (diario): por qué compra o vende"
PF_REVIEW = "Escribir revisión…"
PF_REVIEW_PROMPT = (
    "Revisión de la operación (qué salió bien o mal, qué aprendió). Máximo 500 caracteres:"
)
PF_DISCLAIMER = (
    "Cartera de práctica: las operaciones son ficticias y no se envían a ningún broker. Con "
    "«Cierre del día» se usa el precio de cierre de esa fecha. Admite fracciones de acción y "
    "compras por importe en dólares; aplica splits y dividendos. No permite ventas en corto ni "
    "gastar más efectivo del disponible. No es asesoramiento financiero."
)
PF_ITEM = "{name} · capital inicial {cash}"
PF_TAB_REBALANCE = "Rebalanceo"
PF_TAB_CASH = "Efectivo"
CASH_INTRO = (
    "Aportaciones y retiradas de dinero, y los dividendos, intereses y gastos que le comunique "
    "su broker. Las aportaciones y retiradas no cuentan como ganancia: la rentabilidad del "
    "informe se pondera en el tiempo. Importes en dólares."
)
CASH_KIND = "Tipo"
CASH_AMOUNT = "Importe"
CASH_SYMBOL_HINT = "solo para dividendos"
CASH_ADD = "Añadir movimiento"
CASH_DELETE = "Eliminar movimiento seleccionado"
CASH_COLUMNS = ("Fecha", "Tipo", "Activo", "Importe ($)", "Nota")
PF_COMPARE = "Comparar con:"
PF_COMPARE_TIP = (
    "Hasta 3 índices o activos de referencia separados por comas (p. ej. SPY, QQQ, ^IBEX). "
    "Cada uno se calcula con el mismo capital inicial y las mismas fechas que la cartera."
)
PF_IMPORT = "Importar operaciones (CSV)…"
PF_IMPORT_FILTER = "CSV (*.csv *.txt);;Todos los archivos (*)"
PF_IMPORT_READING = "Leyendo el archivo y buscando tipos de cambio…"
PF_IMPORT_DONE = "Importadas {count} operaciones en «{name}»."
IMP_TITLE = "Importar operaciones de su broker"
IMP_COUNT = "{count} operaciones listas para importar · {errors} filas descartadas (ver abajo)."
IMP_CASH = (
    "Capital inicial mínimo para que el historial sea posible: {needed} $ (la cartera «{name}» "
    "tiene {cash} $)."
)
IMP_CASH_ROWS = (
    "{count} movimientos de efectivo (dividendos, intereses, comisiones, aportaciones o retiradas)."
)
IMP_DIVIDENDS_OFF = (
    "El archivo trae los dividendos cobrados: se desactivarán los dividendos calculados "
    "automáticamente en esta cartera para no contarlos dos veces."
)
IMP_NO_COMMISSION = "El archivo no tiene columna de comisión: se importan con comisión 0."
IMP_COLUMNS = ("Fecha", "Ticker", "Operación", "Cantidad", "Precio", "Comisión ($)", "Nota")
IMP_ERRORS = "Filas descartadas y avisos:"
IMP_NO_ERRORS = "Ninguna."
IMP_INTO_CURRENT = "Añadir a la cartera actual («{name}»)"
IMP_INTO_NEW = "Crear una cartera nueva con estas operaciones"
IMP_NEW_NAME = "Nombre:"
IMP_NEW_CASH = "Capital inicial:"
IMP_DEFAULT_NAME = "Importada"
IMP_IMPORT = "Importar"
RB_INTRO = (
    "Indique qué peso (% del valor total) quiere para cada activo; lo que no asigne queda en "
    "efectivo. Los activos que tenga sin peso objetivo se venden. El plan usa el último cierre, "
    "admite fracciones, vende primero y ajusta las compras al efectivo y a las comisiones. Es "
    "una simulación: no es una recomendación de inversión."
)
RB_TARGET_COLUMNS = ("Ticker", "Peso objetivo %")
RB_ADD_ROW = "Añadir"
RB_REMOVE_ROW = "Quitar"
RB_SAVE = "Guardar pesos y calcular"
RB_TOTAL = "Asignado: {total} % · efectivo objetivo: {cash} %"
RB_TOTAL_INVALID = "Hay algún peso que no es un número."
RB_BAD_WEIGHT = "El peso de {symbol} no es un número válido."
RB_PLAN_TITLE = "Operaciones necesarias"
RB_PLAN_COLUMNS = (
    "Activo",
    "Peso actual",
    "Objetivo",
    "Operación",
    "Cantidad",
    "Precio ($)",
    "Importe ($)",
)
RB_CALCULATING = "Calculando el plan…"
RB_NOTHING = "La cartera ya está en sus pesos objetivo (diferencias menores de 0,5 puntos)."
RB_SUMMARY = (
    "{count} operaciones · comisiones {commissions} $ · efectivo después {cash} $ "
    "(objetivo {cash_pct} %)."
)
RB_SCALED = "Las compras se han reducido para que quepan en el efectivo con las comisiones."
RB_APPLY = "Registrar estas operaciones"
RB_APPLY_CONFIRM = (
    "Se registrarán {count} operaciones ficticias con fecha de hoy al último cierre. ¿Continuar?"
)
RB_APPLYING = "Registrando las operaciones…"

TAB_FUNDAMENTALS = "Fundamentales"
TAB_EXHAUSTION = "Agotamiento"
EXH_EMPTY = "Abra un activo para ver si su tendencia muestra señales de agotamiento."
EXH_TITLE = "{symbol} · última barra cerrada del {when}"
EXH_UP_SIGNAL = (
    "▼ La subida muestra señales de agotamiento ({met} de {total}). Puede seguir subiendo: "
    "las señales no dicen cuándo terminará."
)
EXH_UP_QUIET = "▲ Tendencia alcista sin señales claras de agotamiento ({met} de {total})."
EXH_DOWN_SIGNAL = (
    "▲ La bajada muestra señales de agotamiento ({met} de {total}). Puede seguir bajando: "
    "las señales no dicen cuándo terminará."
)
EXH_DOWN_QUIET = "▼ Tendencia bajista sin señales claras de agotamiento ({met} de {total})."
EXH_HISTORY_TITLE = "Qué pasó antes en este activo con {n} o más señales:"
EXH_FELL = "bajó"
EXH_ROSE = "subió"
EXH_OUTCOME = (
    "A {h} sesiones: {move} en {against} de {events} casos ({pct} %), variación mediana "
    "{median} %. En cualquier día de la misma tendencia {move} el {base} %."
)
EXH_CHANCE = "Esa diferencia puede deberse al azar."
EXH_NOT_CHANCE = "Es poco probable que esa diferencia se deba solo al azar."
EXH_NO_CASES = "A {h} sesiones: no hubo casos anteriores comparables."
EXH_READ_NONE = "Sin historial suficiente para comparar."
EXH_READ_FEW = "Muy pocos casos: el historial no permite sacar conclusiones."
EXH_READ_USEFUL_UP = (
    "En este activo, estas señales han precedido bajadas bastante más a menudo que un día "
    "cualquiera. Aun así, muchas veces la subida continuó."
)
EXH_READ_USEFUL_DOWN = (
    "En este activo, estas señales han precedido rebotes bastante más a menudo que un día "
    "cualquiera. Aun así, muchas veces la bajada continuó."
)
EXH_READ_CONTINUE_UP = (
    "En este activo, tras estas señales la subida continuó incluso más a menudo de lo normal: "
    "no han servido para anticipar bajadas."
)
EXH_READ_CONTINUE_DOWN = (
    "En este activo, tras estas señales la bajada continuó incluso más a menudo de lo normal: "
    "no han servido para anticipar rebotes."
)
EXH_READ_NO_EDGE = (
    "En este activo estas señales no han anticipado los giros mejor que un día cualquiera "
    "(la diferencia es pequeña o puede deberse al azar)."
)
EXH_READ_MIXED = (
    "Resultados contradictorios según el plazo: el historial no permite sacar una conclusión."
)
EXH_BRIEF = "A {h} sesiones: {move} en {against} de {events} casos ({pct} %)."
EXH_DEFAULT_COMPARE = "Con los umbrales por defecto ({n} o más señales):"
EXH_CUSTOM = (
    "Umbrales personalizados: RSI {hi} / {lo}, {atr} ATR de la media, volumen bajo el {vol} %, "
    "movimiento de {z} desviaciones, {n} señales necesarias."
)
EXH_MARKERS = "Marcar en el gráfico las veces anteriores"
EXH_MARKERS_TIP = (
    "▼ encima de la vela: comienzo de señales de agotamiento de una subida. ▲ debajo: de una "
    "bajada. El número es cuántas condiciones se cumplían."
)
EXH_PARAMS_BUTTON = "Umbrales…"
EXH_PARAMS_TITLE = "Umbrales del agotamiento"
EXH_PARAMS_INTRO = (
    "Cambie los valores para ver cómo cambia el historial de este activo. Se usan también en el "
    "escáner y en el escaneo diario. Valores más exigentes dan menos casos (y menos fiables)."
)
EXH_P_RSI_HIGH = "RSI de sobrecompra (subidas)"
EXH_P_RSI_LOW = "RSI de sobreventa (bajadas)"
EXH_P_ATR = "Distancia a la media de 50 (en ATR)"
EXH_P_VOLUME = "Volumen de 10 sesiones por debajo de (× el de 50)"
EXH_P_Z = "Movimiento inusual (desviaciones típicas)"
EXH_P_THRESHOLD = "Condiciones necesarias (de 6)"
EXH_PARAMS_DEFAULTS = "Valores por defecto"
EXH_NOTE = (
    "Casos sin solapar, calculados solo con los datos que había en cada fecha. Es una "
    "descripción del pasado, no una predicción ni una recomendación de compra o venta."
)
FUND_EMPTY = "Abra un activo para ver sus datos fundamentales."
FUND_LOADING = "Cargando datos fundamentales de {symbol}…"
FUND_UNAVAILABLE = "No hay datos fundamentales para series importadas de CSV."
