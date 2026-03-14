# MGTA — Simulador GDP · Barcelona LEBL

Simulador de Ground Delay Program (GDP) para el aeropuerto de Barcelona El Prat (LEBL).

A partir de los datos de tráfico del día, el simulador:
1. Ejecuta el **modelo de Newell** para detectar cuándo y cuánto colapsa la capacidad.
2. Aplica el **algoritmo RBS** de Eurocontrol para asignar slots a los vuelos.
3. Calcula **KPIs operacionales, económicos y ambientales** (modelo CO2 Delgado et al., 2025).
4. Genera un **Excel de auditoría** con 7 pestañas formateadas y **4 gráficos PNG**.
5. Ejecuta un **análisis de sensibilidad** sobre el radio de cobertura (R) y el freeze horizon (HFile), generando heatmaps para identificar los valores óptimos.

---

## Arquitectura del proyecto

```
MGTA_reforma/
│
├── data/
│   ├── raw/                        # CSV de tráfico de entrada (nunca se modifican)
│   └── processed/                  # Excel y CSV de resultados (se generan al ejecutar)
│
├── output/
│   └── figures/
│       ├── 1_diagrama_newell.png   # Curvas acumuladas de demanda y capacidad
│       ├── 2_balance_capacidad.png # Demanda horaria vs. tráfico real servido
│       ├── 3_impacto_economico.png # Coste Do-Nothing vs. GDP
│       ├── 4_equidad_aerolineas.png# Retraso medio por aerolínea (Top 10)
│       └── heatmaps/               # Un PNG por KPI del análisis de sensibilidad
│
├── src/
│   ├── config.py                   # ← PARÁMETROS DEL GDP (AAR, PAAR, horarios, costes)
│   ├── emissions_fuel_model.py     # Modelo CO2 de Delgado et al. (2025) — no modificar
│   ├── lib_data_prep.py            # Fase 1: limpieza de datos + cálculo de distancia y CO2
│   ├── lib_gdp_core.py             # Fase 2: Newell, etiquetado de vuelos, RBS, KPIs
│   ├── lib_excel_export.py         # Fase 3: generación del Excel de auditoría (7 pestañas)
│   ├── lib_visualization.py        # Fase 3: gráficos PNG base + heatmaps de sensibilidad
│   ├── lib_sensitivity.py          # Fase 4: análisis de sensibilidad R × HFile
│   ├── lib_compression.py           # Fase 2B: optimización ILP — EN DESARROLLO 
│   └── main.py                     # Punto de entrada: orquesta las 4 fases en orden
│
├── test/
│   ├── test_data_prep.py           # 16 tests de la Fase 1 (preparación de datos)
│   └── test_excel_export.py        # 9 tests del Excel (integridad de pestañas y columnas)
│
├── .gitignore
├── requirements.txt
└── README.md
```

### Flujo de las 4 fases

```
[FASE 1] lib_data_prep
    Leer CSVs → filtrar llegadas LEBL → unir con catálogo de flota
    → convertir tiempos → calcular distancia → calcular CO2 por vuelo

[FASE 2] lib_gdp_core
    Modelo de Newell → etiquetado de vuelos (candidato/exento)
    → generar matriz de slots → algoritmo RBS → calcular retrasos

[FASE 3] lib_excel_export + lib_visualization
    Excel de auditoría (7 pestañas) + 4 gráficos PNG

[FASE 4] lib_sensitivity
    42 simulaciones (6 radios × 7 HFile) → 6 heatmaps PNG + CSV de resultados
```

### Dependencias entre módulos

```
main.py
 ├── lib_data_prep      (no depende de otros módulos del proyecto)
 ├── lib_gdp_core       (importa: config)
 ├── lib_excel_export   (importa: config, lib_gdp_core)
 ├── lib_visualization  (importa: lib_gdp_core)
 └── lib_sensitivity    (importa: config, lib_gdp_core, lib_visualization)
```

> **Regla de diseño:** las dependencias van siempre "hacia abajo" en este diagrama.
> Ningún módulo importa a `main.py`. Esto evita los imports circulares.

---

## Requisitos previos

- **Python 3.10 o superior** → https://www.python.org/downloads/
  Durante la instalación, marcad la opción **"Add Python to PATH"**.
- **Git** → https://git-scm.com/download/win — instalad con todas las opciones por defecto.
- **VS Code** → https://code.visualstudio.com/ (recomendado)

Para verificar que están instalados correctamente:

```bash
python --version   # debe mostrar Python 3.x.x
git --version      # debe mostrar git version 2.x.x
```

---

## Configuración inicial (solo la primera vez)

### 1. Clonar el repositorio

**Desde VS Code:**
1. `Ctrl+Shift+P` → escribid `Git: Clone` → Enter
2. Pegad la URL del repositorio y elegid una carpeta local
3. Cuando VS Code pregunte si queréis abrir el repositorio clonado, decid que sí

**Desde la terminal:**
```bash
git clone https://github.com/TU_USUARIO/MGTA_reforma.git
cd MGTA_reforma
```

### 2. Instalar las librerías

```bash
pip install -r requirements.txt
```

### 3. Verificar que todo funciona

```bash
python src/main.py
```

Si se generan archivos en `data/processed/` y `output/figures/`, la instalación es correcta.

> **Nota sobre los datos:** los CSV de tráfico (`data/raw/`) están en el repositorio.
> Si no aparecen, pedídlos al responsable del proyecto.

---

## Ejecutar el proyecto

```bash
python src/main.py
```

Esto ejecuta las 4 fases completas. Al terminar, encontraréis:

| Archivo | Descripción |
|---|---|
| `data/processed/vuelos_finales_gdp.csv` | Tabla de resultados del escenario base |
| `data/processed/auditoria_completa.xlsx` | Excel de auditoría con 7 pestañas formateadas |
| `data/processed/sensitivity_grid.csv` | Resultados de las 42 simulaciones de sensibilidad |
| `output/figures/*.png` | 4 gráficos del escenario base |
| `output/figures/heatmaps/*.png` | 6 heatmaps del análisis de sensibilidad |

### Cambiar los parámetros del GDP

Todos los parámetros están centralizados en `src/config.py`. Para cambiar la capacidad del aeropuerto, el horario del GDP o los costes, solo hay que editar ese archivo:

```python
# src/config.py
AAR:     int = 44    # Aviones/hora en operación normal → cámbialo aquí
PAAR:    int = 20    # Aviones/hora durante LVP
H_START: int = 360   # 06:00 UTC → inicio de la regulación
H_END:   int = 780   # 13:00 UTC → fin de la regulación
```

### Ejecutar un módulo de forma aislada (modo debug)

Cada módulo puede ejecutarse de forma independiente para pruebas:

```bash
python src/lib_data_prep.py     # Genera debug/DEBUG_01_preprocesado.xlsx
python src/lib_gdp_core.py      # Genera debug/DEBUG_02_etiquetado_gdp.xlsx
python src/lib_visualization.py # Genera output/figures/TEST_VISUALS/
python src/lib_sensitivity.py   # Ejecuta análisis de sensibilidad completo
```

---

## Tests automatizados

Ejecutad los tests siempre antes de hacer push:

```bash
python -m pytest test/ -v
```

La salida esperada es **43 passed** (16 de preparación de datos + 9 del Excel + 18 del gdp).
Si aparece algún `FAILED`, revisad el error antes de subir nada.

### Qué cubren los tests

| Archivo | Qué verifica |
|---|---|
| `test_data_prep.py` | Conversión de tiempos, filtrado de vuelos, cálculo de distancias |
| `test_excel_export.py` | Longitud de listas en parámetros, columnas del DataFrame, generación completa del Excel |

---

## Ramas de trabajo

| Rama | Propósito |
|---|---|
| `main` | Código estable y revisado. No se modifica directamente. |
| `Working-Branch` | Desarrollo del bloque de compresión — aquí es donde trabaja el equipo. |

### Cambiar de rama

**Desde VS Code:** clic en el nombre de la rama (esquina inferior izquierda) → seleccionad la rama deseada.

**Desde la terminal:**
```bash
git fetch
git checkout Working-Branch
```

---

## Flujo de trabajo diario

### Al empezar cada sesión

```bash
git checkout feature/Working-Branch
git pull
```

### Al terminar algo que funciona

```bash
git add .
git commit -m "feat: descripción de lo que habéis hecho"
git push origin feature/Working-Branch
```

**Desde VS Code** (`Ctrl+Shift+G`): clic en **+** junto a Cambios → escribid el mensaje → **Confirmar** → **Sincronizar cambios**.

### Convención de mensajes de commit

| Prefijo | Cuándo usarlo | Ejemplo |
|---|---|---|
| `feat:` | Añadís algo nuevo | `feat: implementar función de coste escalonada` |
| `fix:` | Corregís un bug | `fix: corregir índice fuera de rango en parse_time` |
| `docs:` | Documentación | `docs: actualizar README con módulo de sensibilidad` |
| `test:` | Tests | `test: añadir tests para asignar_slots_rbs` |

---

## Trabajo pendiente — rama feature/Working-Branch

El bloque ILP está definido en `src/lib_compression.py` con la interfaz que debe respetar:

```python
def asignar_slots_ilp(
    df_regulados: pd.DataFrame,
    df_slots: pd.DataFrame,
    params: dict,
) -> pd.DataFrame:
    """
    Debe devolver df_regulados con la columna 'assigned_slot' rellena.
    Misma interfaz que asignar_slots_rbs() para que sean intercambiables.
    """
```

Una vez implementado, se conecta al pipeline añadiendo un parámetro `algoritmo='ILP'`
a `ejecutar_nucleo_gdp()` en `lib_gdp_core.py`. El resto del sistema (KPIs, Excel,
heatmaps) funciona sin cambios porque solo necesita la columna `assigned_slot`.

---

## Librerías utilizadas

| Librería | Para qué se usa |
|---|---|
| `pandas` | Manipulación de datos tabulares (DataFrames) |
| `numpy` | Operaciones matemáticas vectorizadas sobre arrays |
| `matplotlib` | Generación de gráficos PNG |
| `seaborn` | Heatmaps del análisis de sensibilidad |
| `openpyxl` | Generación del Excel de auditoría con formato |
| `pulp` | Solver de Programación Lineal Entera (para el sistema de compresión) |
| `pytest` | Ejecución de tests automatizados |

Todas se instalan de una vez con `pip install -r requirements.txt`.

---

## Problemas frecuentes

**`ModuleNotFoundError: No module named 'config'`**
Ejecutad los scripts desde la carpeta `src/`, no desde la raíz del proyecto:
```bash
cd src
python main.py
```

**`FileNotFoundError` al ejecutar `main.py`**
Los CSV de datos no están en la carpeta `data/raw/`. Pedídlos y colocadlos ahí.

**`PermissionError` al generar el Excel**
El archivo `auditoria_completa.xlsx` está abierto en Excel. Cerradlo y volved a ejecutar.

**`pip` no se reconoce como comando**
Python no se añadió al PATH. Desinstalad Python y reinstalad marcando **"Add Python to PATH"**.

**La rama `feature/Working-Branch` no aparece en VS Code**
Ejecutad `git fetch` en la terminal para que VS Code descargue la lista de ramas del servidor.

**El análisis de sensibilidad tarda mucho**
Son 42 simulaciones completas. En un ordenador normal tarda entre 30 segundos y 2 minutos.
Es normal — no está colgado.