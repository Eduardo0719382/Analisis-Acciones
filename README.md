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

## Ejecutar

```bash
analisis-acciones
# o bien
python -m analisis_acciones
```

Los datos (base de datos SQLite y registros) se guardan en el directorio de datos del
usuario (`%LOCALAPPDATA%\AnalisisAcciones` en Windows). Puede cambiarse con la variable
`ANALISIS_ACCIONES_HOME` (véase `.env.example`).

## Actualizar

Dentro del programa: **Ayuda → Buscar actualizaciones…**. Muestra los cambios nuevos,
los instala y ofrece reiniciar.

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
pytest
ruff check .
ruff format --check .
mypy
```

En Linux sin pantalla, las pruebas de interfaz usan `QT_QPA_PLATFORM=offscreen`
automáticamente.
