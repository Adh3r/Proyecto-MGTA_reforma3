# MGTA — Simulador GDP · Barcelona LEBL

Simulador de Ground Delay Program para el aeropuerto de Barcelona El Prat.
A partir de los datos de tráfico del día, ejecuta el modelo de Newell, aplica el algoritmo RBS de Eurocontrol y genera automáticamente un Excel de auditoría completo con KPIs operacionales, económicos y ambientales.

---

## Requisitos previos

Antes de nada se necesita tener instalado en el ordenador:

- **Python 3.10 o superior** → https://www.python.org/downloads/
  Durante la instalación, marcad la opción **"Add Python to PATH"**.
- **Git** → https://git-scm.com/download/win
  Instalad con todas las opciones por defecto.
- **VS Code** → https://code.visualstudio.com/
  Editor recomendado para trabajar en el proyecto.

Para comprobar que Python y Git están correctamente instalados, abrir PowerShell y ejecutar:

```bash
python --version
git --version
```

Deberíais ver algo como `Python 3.x.x` y `git version 2.x.x`.

---

## Configuración de VS Code

### 1. Instalar la extensión de GitHub

1. Abrir VS Code
2. Pulsar `Ctrl+Shift+X` para abrir el panel de extensiones
3. Buscar **"GitHub Pull Requests"** e instaler
4. Reiniciar VS Code

### 2. Conectar VS Code con vuestra cuenta de GitHub

1. Pulsar `Ctrl+Shift+P` para abrir la paleta de comandos
2. escribir `Git: Clone` y pulsar Enter
3. VS Code pide que se incie sesión en GitHub
4. Una vez autenticados, no se tiene que volver a hacer

---

## Unirse al proyecto

### Opción A — Desde VS Code

1. Abrir VS Code
2. Pulsar `Ctrl+Shift+P` → escribir `Git: Clone` → Enter
3. Pegar esta URL: `https://github.com/TU_USUARIO/MGTA_reforma.git`
4. Elegir una carpeta de vuestro ordenador donde guardar el proyecto
5. VS Code pregunta si se quiere abrir el repositorio clonado — sí
6. Abrir la terminal integrada con `Ctrl+ñ` e instalar las librerías:

```bash
pip install -r requirements.txt
```

### Opción B — Desde la terminal

```bash
git clone https://github.com/TU_USUARIO/MGTA_reforma.git
cd MGTA_reforma
pip install -r requirements.txt
```

### Verificar que todo funciona

```bash
python src/main.py
```

Si se generan archivos en `data/processed/` y `output/figures/`, la instalación es correcta.

> **Nota sobre los datos:** los CSV de tráfico están en el repositorio dentro de `data/raw/`.
> Si no aparecen whats.

---

## Ramas de trabajo

El proyecto tiene dos ramas principales:

| Rama | Propósito |
|---|---|
| `main` | Código estable y revisado. No se toca directamente. |
| `feature/ilp-solver` | Desarrollo del bloque ILP |
| `otras` | Futuros WP |

### Cambiar a la rama ILP desde VS Code

En la esquina inferior izquierda de VS Code veréis el nombre de la rama actual (probablemente `main`). Haced clic ahí y seleccionad `feature/ilp-solver` de la lista. Si no aparece, se ejecuta en la terminal:

```bash
git fetch
git checkout feature/ilp-solver
```

---

## Flujo de trabajo diario

### Al empezar cada sesión

```bash
# Hay que asegurarse de estar en la rama correcta y tener lo último
git checkout feature/ilp-solver
git pull
```

O desde VS Code: clic en la rama (esquina inferior izquierda) → seleccionar `feature/ilp-solver` → clic en el icono de sincronización en la barra inferior.

### Mientras se trabaja

Cada vez que se termine algo que funciona, guardamos el progreso:

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

Se ejecutan siempre antes de hacer push:

```bash
python -m pytest test/ -v
```

La salida esperada es `16 passed`. Si aparece algún `FAILED`, se revisa el error antes de subir nada.

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

**Si solo se quiere ejecutar el proyecto:** `python src/main.py`
**Si solo se necesita cambiar parámetros** (capacidad, horarios, costes): editar solo `src/config.py`
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
Hay que asegurarse de ejecutar los scripts desde la carpeta `src/` o de que el IDE tiene `src/` en el path de Python.

**`PermissionError` al generar el Excel**
El archivo `auditoria_completa.xlsx` está abierto en Excel.

**`pip` no se reconoce como comando**
Python no se añadió al PATH durante la instalación.

**La rama `feature/ilp-solver` no me aparece en VS Code**
Se ejecuta `git fetch` en la terminal para que VS Code descargue la lista de ramas del servidor.
