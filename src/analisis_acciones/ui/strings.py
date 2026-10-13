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
PANEL_LOWER = "Indicadores / Volumen"
PANEL_DETAILS = "Detalles"
EMPTY_WATCHLIST = "La lista de seguimiento está vacía."
EMPTY_CHART = "Busque un ticker para ver su gráfico."
EMPTY_LOWER = "Aquí aparecerán el volumen y los indicadores en panel propio."
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
DATA_SUMMARY = (
    "{symbol} · {interval}\n\n"
    "{count} barras · {first} → {last}\n"
    "Último cierre: {close}\n\n"
    "El gráfico se añadirá en la Fase 3."
)
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
