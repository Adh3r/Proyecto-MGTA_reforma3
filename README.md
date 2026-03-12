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
- **VS Code** → https://code.visualstudio.com/
  Editor recomendado para trabajar en el proyecto.

Para comprobar que Python y Git están correctamente instalados, abrid PowerShell y ejecutad:

```bash
python --version
git --version
```

Deberíais ver algo como `Python 3.x.x` y `git version 2.x.x`.

---

## Configuración de VS Code (solo la primera vez)

### 1. Instalar la extensión de GitHub

1. Abrid VS Code
2. Pulsad `Ctrl+Shift+X` para abrir el panel de extensiones
3. Buscad **"GitHub Pull Requests"** e instaladla
4. Reiniciad VS Code

### 2. Conectar VS Code con vuestra cuenta de GitHub

1. Pulsad `Ctrl+Shift+P` para abrir la paleta de comandos
2. Escribid `Git: Clone` y pulsad Enter
3. VS Code os pedirá que iniciéis sesión en GitHub — seguid los pasos en el navegador
4. Una vez autenticados, no tendréis que volver a hacerlo

---

## Unirse al proyecto (solo la primera vez)

### Opción A — Desde VS Code (recomendado para novatos)

1. Abrid VS Code
2. Pulsad `Ctrl+Shift+P` → escribid `Git: Clone` → Enter
3. Pegad esta URL: `https://github.com/TU_USUARIO/MGTA_reforma.git`
4. Elegid una carpeta de vuestro ordenador donde guardar el proyecto
5. VS Code os preguntará si queréis abrir el repositorio clonado — decid que sí
6. Abrid la terminal integrada con `Ctrl+ñ` e instalad las librerías:

```bash
pip install -r requirements.txt
```

### Opción B — Desde la terminal

```bash
git clone https://github.com/TU_USUARIO/MGTA_reforma.git
cd MGTA_reforma
pip install -r requirements.txt
```

### Verificad que todo funciona

```bash
python src/main.py
```

Si se generan archivos en `data/processed/` y `output/figures/`, la instalación es correcta.

> **Nota sobre los datos:** los CSV de tráfico están en el repositorio dentro de `data/raw/`.
> Si no os aparecen, pedídmelos.

---

## Ramas de trabajo

El proyecto tiene dos ramas principales:

| Rama | Propósito |
|---|---|
| `main` | Código estable y revisado. No se toca directamente. |
| `feature/ilp-solver` | Desarrollo del bloque ILP — aquí es donde trabajáis vosotros. |

### Cambiar a la rama ILP desde VS Code

En la esquina inferior izquierda de VS Code veréis el nombre de la rama actual (probablemente `main`). Haced clic ahí y seleccionad `feature/ilp-solver` de la lista. Si no aparece, ejecutad en la terminal:

```bash
git fetch
git checkout feature/ilp-solver
```

---

## Flujo de trabajo diario

### Al empezar cada sesión

```bash
# Aseguraos de estar en la rama correcta y tener lo último
git checkout feature/ilp-solver
git pull
```

O desde VS Code: clic en la rama (esquina inferior izquierda) → seleccionad `feature/ilp-solver` → clic en el icono de sincronización en la barra inferior.

### Mientras trabajáis

Cada vez que terminéis algo que funciona, guardad vuestro progreso:

```bash
git add .
git commit -m "feat: descripción de qué habéis hecho"
git push origin feature/ilp-solver
```

O desde VS Code (`Ctrl+Shift+G`):
1. Clic en **+** junto a Cambios para añadir todo
2. Escribid el mensaje del commit
3. **Confirmar** → **Sincronizar cambios**

### Convención de mensajes de commit

| Prefijo | Cuándo usarlo | Ejemplo |
|---|---|---|
| `feat:` | Añadís algo nuevo | `feat: implementar función de coste escalonada` |
| `fix:` | Corregís un bug | `fix: corregir índice fuera de rango en parse_time` |
| `docs:` | Cambios en documentación | `docs: actualizar README con instrucciones ILP` |
| `test:` | Añadís o modificáis tests | `test: añadir casos límite para coste escalonado` |

---

## Tests automatizados

Ejecutadlos siempre antes de hacer push:

```bash
python -m pytest test/ -v
```

La salida esperada es `16 passed`. Si aparece algún `FAILED`, revisad el error antes de subir nada.

---

## Estructura del proyecto

```
MGTA_reforma/
│
├── data/
│   ├── raw/                    # CSV de tráfico (en el repositorio)
│   └── processed/              # El Excel y CSV final se generan aquí al ejecutar main.py
│
├── debug/                      # Excels intermedios para depuración
│
├── output/
│   └── figures/                # Los 4 gráficos PNG se generan aquí al ejecutar main.py
│
├── src/
│   ├── config.py               # ← PARÁMETROS DEL GDP (AAR, PAAR, horarios, costes...)
│   ├── lib_data_prep.py        # Fase 1: limpieza de datos y cálculo cinemático
│   ├── lib_gdp_core.py         # Fase 2: modelo de Newell y algoritmo RBS
│   ├── lib_excel_export.py     # Fase 3: generación del Excel de auditoría
│   ├── lib_ilp_solver.py       # Fase 2B: optimización ILP — (en desarrollo)
│   └── main.py                 # Punto de entrada: ejecuta el proyecto completo
│
├── test/
│   └── test_data_prep.py       # Tests automatizados de la Fase 1
│
├── .gitignore
├── requirements.txt
└── README.md
```

**Si solo queréis ejecutar el proyecto:** `python src/main.py`
**Si necesitáis cambiar parámetros** (capacidad, horarios, costes): editad solo `src/config.py`
**El trabajo del WP3 va en:** `src/lib_ilp_solver.py`

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

**La rama `feature/ilp-solver` no me aparece en VS Code**
Ejecutad `git fetch` en la terminal para que VS Code descargue la lista de ramas del servidor.
