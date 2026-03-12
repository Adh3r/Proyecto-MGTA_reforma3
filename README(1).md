# MGTA — Simulador GDP Barcelona (LEBL)

Simulador de Ground Delay Program para el aeropuerto de Barcelona basado en el modelo de Newell y el algoritmo RBS de Eurocontrol.

---

## Instalación

```bash
# 1. Clona el repositorio (solo la primera vez)
git clone https://github.com/TU_USUARIO/MGTA_reforma.git
cd MGTA_reforma

# 2. Instala las dependencias
pip install -r requirements.txt

# 3. Ejecuta el proyecto
python src/main.py
```

---

## Estructura del proyecto

```
MGTA_reforma/
├── data/
│   ├── raw/                   # CSVs originales (INTOCABLES)
│   └── processed/             # Entregables finales generados
├── debug/                     # Excels intermedios de depuración
├── output/
│   └── figures/               # Gráficos PNG generados
├── src/
│   ├── config.py              # Fuente única de verdad: constantes y parámetros
│   ├── lib_data_prep.py       # Fase 1: Limpieza y cinemática
│   ├── lib_gdp_core.py        # Fase 2: Newell, RBS y exportación
│   ├── lib_excel_export.py    # Fase 3: construcción del Excel maestro
│   ├── lib_ilp_solver.py      # Fase 2B: optimización ILP (en desarrollo)
│   └── main.py                # Punto de entrada: ejecuta todo
├── test/
│   └── test_data_prep.py      # Tests automatizados
├── .gitignore
└── requirements.txt
```

---

## Ejecutar los tests

```bash
python -m pytest test/ -v
```

---

## Guía de colaboración con GitHub

### Conceptos clave (para novatos)

| Término | Analogía | Qué significa |
|---|---|---|
| **Repositorio** | Carpeta del proyecto en la nube | Donde vive todo el código compartido |
| **Commit** | Punto de guardado | Una foto del estado del código en un momento |
| **Branch** | Copia de trabajo | Tu espacio personal para hacer cambios sin afectar al resto |
| **Push** | Subir | Enviar tus commits a GitHub |
| **Pull** | Bajar | Descargar los cambios que hicieron tus compañeros |
| **Pull Request** | Propuesta de cambio | Pedir que tus cambios se mezclen con el código principal |
| **Merge** | Fusionar | Combinar tu branch con el código principal |
| **Conflict** | Choque | Dos personas editaron la misma línea — hay que resolverlo manualmente |

---

### Configuración inicial (solo una vez por persona)

**Paso 1 — Instala Git**
Descarga desde https://git-scm.com/download/win e instala con las opciones por defecto.

**Paso 2 — Configura tu identidad**
```bash
git config --global user.name "Tu Nombre"
git config --global user.email "tu@email.com"
```

**Paso 3 — El responsable del proyecto crea el repositorio en GitHub**
1. Ve a https://github.com → "New repository"
2. Nombre: `MGTA_reforma` → Private → Create
3. En la carpeta local del proyecto, ejecuta:

```bash
cd "Proyecto MGTA_reforma3"
git init
git add .
git commit -m "feat: estructura inicial del proyecto"
git branch -M main
git remote add origin https://github.com/TU_USUARIO/MGTA_reforma.git
git push -u origin main
```

**Paso 4 — Los compañeros clonan el repositorio**
```bash
git clone https://github.com/TU_USUARIO/MGTA_reforma.git
cd MGTA_reforma
pip install -r requirements.txt
```

**Paso 5 — Invita a tus compañeros**
En GitHub → Settings → Collaborators → Add people → escribe su usuario de GitHub.

---

### Flujo de trabajo diario (el más importante)

El error más común es trabajar todos directamente en `main`. Esto causa conflictos constantemente.
La solución es que **cada persona trabaje en su propia branch**.

```
main          ──────────────────────────────────────────► (código estable)
               \                          /
feature/newell  ──── commit ── commit ───   (tu rama de trabajo)
```

**Al empezar a trabajar cada día:**
```bash
# 1. Asegúrate de tener lo último del servidor
git checkout main
git pull

# 2. Crea tu rama de trabajo con un nombre descriptivo
git checkout -b feature/mejora-newell
#                    ↑
#             Describe qué estás haciendo
```

**Mientras trabajas (cada vez que terminas algo que funciona):**
```bash
# Ver qué archivos has modificado
git status

# Añadir los archivos que quieres guardar
git add src/lib_gdp_core.py
# O para añadir todo de una vez:
git add .

# Hacer el commit con un mensaje descriptivo
git commit -m "fix: corregir cálculo de h_noreg cuando la cola no se disuelve"
#                ↑
#   Prefijos recomendados:
#   feat:  nueva funcionalidad
#   fix:   corrección de bug
#   docs:  cambios en documentación
#   test:  añadir o modificar tests
```

**Cuando terminas y quieres compartir tu trabajo:**
```bash
# Subir tu rama a GitHub
git push origin feature/mejora-newell

# En GitHub → "Compare & pull request" → descripción de qué hiciste → Create
# Un compañero revisa el código y hace merge a main
```

**Para bajarte el trabajo que hicieron los demás:**
```bash
git checkout main
git pull
```

---

### Qué NO subir a GitHub — el archivo .gitignore

Algunos archivos no deben estar en el repositorio:
- Los CSVs de datos (pueden ser grandes o confidenciales)
- Los archivos generados (Excel, PNG) — se regeneran ejecutando el código
- Carpetas de entorno virtual de Python

Crea un archivo `.gitignore` en la raíz del proyecto con este contenido:

```
# Datos crudos (demasiado grandes o confidenciales)
data/raw/
data/processed/

# Archivos generados (se crean ejecutando main.py)
output/
debug/

# Python
__pycache__/
*.pyc
*.pyo
.env
venv/
.venv/

# Sistemas operativos
.DS_Store
Thumbs.db
```

> ⚠️ **Importante**: Los datos crudos no estarán en el repositorio.
> Compártelos una sola vez por otro medio (Drive, email) y cada persona
> los pone en su carpeta `data/raw/` local.

---

### Resolver un conflicto (cuando dos personas editan lo mismo)

Git te avisará con un mensaje como `CONFLICT (content): Merge conflict in src/lib_gdp_core.py`.
Abre el archivo y verás algo así:

```python
<<<<<<< HEAD
    COST_AIR_MIN = 100   # Tu versión
=======
    COST_AIR_MIN = 120   # La versión de tu compañero
>>>>>>> feature/actualizar-costes
```

Decide cuál es correcta (o combina ambas), elimina las líneas con `<<<<`, `====` y `>>>>`, guarda y haz un commit nuevo. Así de simple.

---

### Comandos de referencia rápida

```bash
git status                    # Ver qué ha cambiado
git log --oneline             # Historial de commits resumido
git diff                      # Ver exactamente qué líneas cambiaron
git stash                     # Guardar cambios temporalmente sin commitear
git stash pop                 # Recuperar los cambios guardados con stash
git checkout -- archivo.py    # Descartar cambios en un archivo (¡irreversible!)
```
