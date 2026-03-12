# MGTA — Simulador GDP · Barcelona LEBL

Simulador de Ground Delay Program para el aeropuerto de Barcelona El Prat.
A partir de los datos de tráfico del día, ejecuta el modelo de Newell, aplica el algoritmo RBS de Eurocontrol y genera automáticamente un Excel de auditoría completo con KPIs operacionales, económicos y ambientales.

---

## Requisitos previos

Antes de nada necesitáis tener instalado en vuestro ordenador:

- **Python 3.10 o superior** → https://www.python.org/downloads/
  Durante la instalación, marcad la opción **"Add Python to PATH"**.
- **Git** → https://git-scm.com/download/win
  Instalad con todas las opciones por defecto.

Para comprobar que ambos están correctamente instalados, abrid PowerShell y ejecutad:

```bash
python --version
git --version
```

Deberíais ver algo como `Python 3.x.x` y `git version 2.x.x`.

---

## Instalación del proyecto

```bash
# 1. Clonad el repositorio en vuestro ordenador
git clone https://github.com/TU_USUARIO/MGTA_reforma.git

# 2. Entrad en la carpeta del proyecto
cd MGTA_reforma

# 3. Instalad las librerías necesarias
pip install -r requirements.txt

# 4. Comprobad que todo funciona
python src/main.py
```

Si el paso 4 termina sin errores y aparecen archivos en `data/processed/` y `output/figures/`, la instalación es correcta.

> **Nota sobre los resultados:** los excel de resultados no os aparecerán al descargar porque al depender de el resto del código se presume que canviarán en cada caso de uso.

---

## Estructura del proyecto

```
MGTA_reforma/
│
├── data/
│   ├── raw/                    # Aquí van los CSV de tráfico (pedídmelos, no están en el repo)
│   └── processed/              # El Excel y CSV final se generan aquí al ejecutar main.py
│
├── debug/                      # Excels intermedios para depuración (ignorados por Git)
│
├── output/
│   └── figures/                # Los 4 gráficos PNG se generan aquí al ejecutar main.py
│
├── src/
│   ├── config.py               # ← PARÁMETROS DEL GDP (AAR, PAAR, horarios, costes...)
│   ├── lib_data_prep.py        # Fase 1: limpieza de datos y cálculo cinemático
│   ├── lib_gdp_core.py         # Fase 2: modelo de Newell y algoritmo RBS
│   ├── lib_excel_export.py     # Fase 3: generación del Excel de auditoría
│   ├── lib_ilp_solver.py       # Fase 2B: optimización ILP — en desarrollo
│   └── main.py                 # Punto de entrada: ejecuta el proyecto completo
│
├── test/
│   └── test_data_prep.py       # Tests automatizados de la Fase 1
│
├── .gitignore                  # Archivos que Git ignora (datos, outputs, caché...)
├── requirements.txt            # Lista de librerías necesarias
└── README.md                   # Este archivo
```

**Regla general:** si solo queréis ejecutar el proyecto, lanzad `python src/main.py` y no toquéis nada más.
Si necesitáis cambiar algún parámetro (capacidad del aeropuerto, horarios, costes), hacedlo únicamente en `src/config.py`.

---

## Flujo de trabajo en equipo

Usamos Git para que cada uno pueda trabajar sin pisar el trabajo de los demás.
La única regla importante: **nunca trabajéis directamente sobre la rama `main`**.

### Al empezar cada sesión de trabajo

```bash
# Aseguraos de tener la última versión del proyecto
git checkout main
git pull

# Cread vuestra rama de trabajo con un nombre descriptivo
git checkout -b feature/nombre-de-lo-que-vais-a-hacer
```

### Mientras trabajáis

```bash
# Ver qué archivos habéis modificado
git status

# Guardar vuestro progreso (haced esto cada vez que algo funcione)
git add .
git commit -m "feat: descripción breve de qué habéis hecho"
```

### Al terminar, para compartir vuestro trabajo

```bash
# Subid vuestra rama a GitHub
git push origin feature/nombre-de-lo-que-vais-a-hacer
```

En GitHub os aparecerá un botón verde **"Compare & pull request"**.
Pulsadlo, escribid una descripción breve de qué habéis hecho y avisadme para revisarlo antes de integrarlo en `main`.

### Convención de mensajes de commit

Usad siempre un prefijo para que el historial sea legible:

| Prefijo | Cuándo usarlo | Ejemplo |
|---|---|---|
| `feat:` | Añadís algo nuevo | `feat: implementar función de coste escalonada` |
| `fix:` | Corregís un bug | `fix: corregir índice fuera de rango en parse_time` |
| `docs:` | Cambios en documentación | `docs: actualizar README con instrucciones ILP` |
| `test:` | Añadís o modificáis tests | `test: añadir casos límite para coste escalonado` |

---

## Tests automatizados

Los tests verifican que la base del proyecto funciona correctamente.
Ejecutadlos siempre antes de hacer push para aseguraros de que no habéis roto nada:

```bash
python -m pytest test/ -v
```

La salida esperada es `16 passed`. Si aparece algún `FAILED`, revisad el error antes de subir nada.

---

## Librerías utilizadas

| Librería | Para qué se usa |
|---|---|
| `pandas` | Manipulación de datos tabulares |
| `numpy` | Operaciones matemáticas y arrays |
| `matplotlib` | Generación de gráficos |
| `openpyxl` | Exportación del Excel de auditoría |
| `pulp` | Solver de Programación Lineal Entera (ILP) |

Todas se instalan de una vez con `pip install -r requirements.txt`.

---

## Problemas frecuentes

**`ModuleNotFoundError: No module named 'config'`**
Aseguraos de ejecutar los scripts desde la carpeta `src/` o de que vuestro IDE tiene `src/` en el path de Python.

**`FileNotFoundError` al ejecutar `main.py`**
Los CSV de datos no están en el repositorio. Pedídmelos y colocadlos en `data/raw/`.

**`PermissionError` al generar el Excel**
El archivo `auditoria_completa.xlsx` está abierto en Excel. Cerradlo y volved a ejecutar.

**`pip` no se reconoce como comando**
Python no se añadió al PATH durante la instalación. Desinstalad Python y volved a instalarlo marcando la opción **"Add Python to PATH"**.
