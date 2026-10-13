# Análisis de Acciones

Aplicación de escritorio (Windows primero) para el análisis técnico de acciones:
gráficos, indicadores, listas de seguimiento y, más adelante, análisis por reglas,
alertas y backtesting.

> Herramienta de análisis. **No constituye asesoramiento financiero** y no ejecuta
> operaciones reales.

- Plan y alcance: [`PLAN.md`](PLAN.md)
- Decisiones de arquitectura: [`DECISIONS.md`](DECISIONS.md)
- Problemas encontrados y soluciones: [`PROBLEMS.md`](PROBLEMS.md)

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

## Uso (Fase 2)

- **Buscar:** escriba un ticker (p. ej. `AAPL`) o el nombre de una empresa en el cuadro de
  búsqueda. Use ↑/↓ y Enter, o haga clic en un resultado. Con el cuadro vacío se muestran
  los símbolos recientes.
- **Intervalo:** Diario, Semanal o Mensual (los dos últimos se calculan a partir de los datos
  diarios).
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
