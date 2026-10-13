# PyInstaller spec: one-folder, windowed build of Análisis de Acciones.
# Build:  pyinstaller packaging/analisis_acciones.spec --noconfirm
# The PySide6 hooks bundle QtWebEngine (QtWebEngineProcess, resources, locales).
from PyInstaller.utils.hooks import collect_data_files

datas = collect_data_files(
    "analisis_acciones",
    includes=["charts/web/*", "storage/migrations/*.sql"],
)

a = Analysis(
    ["launcher.py"],
    pathex=["../src"],
    datas=datas,
    hiddenimports=["tzdata"],
    excludes=["tkinter", "matplotlib", "IPython", "pytest"],
    noarchive=False,
)
# Slim the bundle: drop Qt modules the app never loads. QtWebEngine needs Core, Gui,
# Widgets, Network, OpenGL, Positioning, PrintSupport, Qml*, Quick, QuickWidgets, WebChannel
# and DBus (Linux), so those are kept. Verified by the --smoke-test run in CI.
UNUSED_QT = (
    "3D", "Quick3D", "QuickControls2", "QuickDialogs2", "QuickLayouts", "QuickParticles",
    "QuickShapes", "QuickTest", "QuickTimeline", "QuickVectorImage", "Charts",
    "DataVisualization", "Graphs", "Multimedia", "SpatialAudio", "Location", "Pdf", "Labs",
    "VirtualKeyboard", "Sensors", "SerialBus", "SerialPort", "Bluetooth", "Nfc",
    "RemoteObjects", "Scxml", "StateMachine", "TextToSpeech", "WebSockets", "WebView",
    "Designer", "Help", "UiTools", "Sql", "Test", "HttpServer", "Protobuf", "Grpc",
    "ShaderTools", "QmlDesignSupport", "QmlLocalStorage", "QmlXmlListModel", "QmlNetwork",
)


def _keep(entry):
    name = entry[0].replace("\\", "/")
    base = name.rsplit("/", 1)[-1]
    if "/qml/" in f"/{name}" or name.startswith("PySide6/Qt/qml"):
        return False
    if "/translations/" in f"/{name}" and not (
        base.endswith("_es.qm") or base.endswith("_en.qm") or "qtwebengine_locales" in name
    ):
        return False
    if "qtwebengine_locales" in name and not (base.startswith("es") or base.startswith("en")):
        return False
    return not any(f"Qt6{m}" in base or f"Qt{m}" in base for m in UNUSED_QT)


a.binaries = [b for b in a.binaries if _keep(b)]
a.datas = [d for d in a.datas if _keep(d)]

pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AnalisisAcciones",
    console=False,
    disable_windowed_traceback=False,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="AnalisisAcciones")
