"""User-facing Spanish strings, kept in one place."""

APP_TITLE = "Análisis de Acciones"

SEARCH_PLACEHOLDER = "Buscar ticker o empresa…"
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
