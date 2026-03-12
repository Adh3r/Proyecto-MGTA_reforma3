Markdown

# ✈️ MGTA — Simulador GDP Barcelona (LEBL)

¡Buenas! Bienvenidos al repositorio del proyecto. Aquí tenemos el simulador del Ground Delay Program (GDP) para el aeropuerto de Barcelona. El código se encarga de aplicar las restricciones, simular las colas y generar automáticamente tanto los gráficos de resultados como el Excel final de auditoría.

Para no volvernos locos pasándonos archivos `.zip` por WhatsApp y pisándonos el trabajo, vamos a centralizarlo todo aquí usando Git. A continuación os explico cómo ponerlo a funcionar en vuestros PCs.

---

## 🛠️ 1. Lo que necesitas instalar

Antes de descargar el código, asegúrate de tener estas dos cosas:

1. **Git**: Si no lo tienes, descárgalo e instálalo (siguiente, siguiente, siguiente...) desde https://git-scm.com/download/win.
2. **Python**: Asegúrate de tener Python instalado y añadido al PATH de tu ordenador.

---

## 🚀 2. Cómo descargar y arrancar el proyecto

Abrid la terminal (podéis usar la que viene integrada abajo en VS Code) y seguid estos pasos:

1. **Clonar el repositorio** (descargarlo a vuestro PC):
   ```bash
   git clone [https://github.com/TU_USUARIO/MGTA_reforma.git](https://github.com/TU_USUARIO/MGTA_reforma.git)
   cd MGTA_reforma

    Instalar las librerías necesarias (pandas, matplotlib, etc.):
    Bash

    pip install -r requirements.txt

    ⚠️ IMPORTANTE: Los datos crudos (CSVs)
    Los archivos de Excel originales (LEBL_10AUG2025.csv y fleet_cat_seat.csv) pesan demasiado y no se suben a GitHub. Pedídmelo por WhatsApp o Discord y metedlos a mano en la carpeta data/raw/ antes de ejecutar nada.

    ¡Hacer la prueba de fuego!
    Ejecutad el simulador para ver si todo funciona:
    Bash

    python src/main.py

    Si al terminar veis que han aparecido archivos nuevos en las carpetas data/processed/ y output/figures/, ¡enhorabuena, lo tenéis todo bien configurado!

🚦 3. Reglas para trabajar en equipo (Git Flow)

Para que no haya conflictos de código, tenemos una regla de oro:
❌ Nadie trabaja ni hace cambios directamente en la rama main. Cada vez que vayáis a programar algo nuevo (un gráfico, arreglar un bug, etc.), hacedlo en una rama separada. Podéis hacerlo con los botones de VS Code o con la terminal:
Bash

# 1. Antes de empezar a trabajar, asegúrate de tener la última versión de todo
git checkout main
git pull

# 2. Crea tu propia rama para trabajar (cambia el nombre por lo que vayas a hacer)
git checkout -b feature/nombre-de-tu-tarea

# ... TRABAJAS EN TU CÓDIGO, GUARDAS TUS ARCHIVOS ...

# 3. Cuando termines y funcione, guarda los cambios en Git
git add .
git commit -m "feat: descripción corta de lo que has hecho"

# 4. Sube tu rama a GitHub
git push origin feature/nombre-de-tu-tarea

Prefijos para los Commits:
Por llevar un orden, empezad los mensajes del commit con una de estas palabras:

    feat: si habéis añadido algo nuevo (ej: feat: nuevo gráfico de equidad).

    fix: si habéis arreglado un error (ej: fix: corregido solapamiento de texto en barras).

    docs: si habéis tocado el README o comentarios.

Una vez hagáis el push, en la web de GitHub os saldrá un botón verde gigante que dice "Compare & pull request". Pulsadlo, dejad un comentario de lo que habéis hecho y avisad por el grupo para que le echemos un ojo y lo juntemos con el código principal (main).
✅ 4. Tests: No rompas lo que ya funciona

Antes de subir vuestra rama, pasad los tests automatizados para aseguraros de que vuestro nuevo código no ha roto la limpieza de datos ni las matemáticas del GDP:
Bash

python -m pytest test/ -v

Si la consola se pone verde y dice passed, vía libre para subir. Si hay algún FAILED en rojo, toca revisar qué ha fallado antes de hacer el push.
📂 5. Mapa del Proyecto (Estructura)

Para que sepáis dónde está cada cosa:
Plaintext

MGTA_reforma/
├── data/
│   ├── raw/               # CSVs originales (INTOCABLES - Añadir manualmente)
│   └── processed/         # Entregables finales (Excel de auditoría, CSV final)
├── debug/                 # Excels intermedios para buscar fallos
├── output/
│   └── figures/           # Gráficos PNG que sacaremos para el PowerPoint
├── src/
│   ├── config.py          # ⚙️ Fuente única de verdad: parámetros LVP, costes, etc.
│   ├── lib_data_prep.py   # Fase 1: Limpieza de datos y cálculo de distancias
│   ├── lib_gdp_core.py    # Fase 2: Matemáticas GDP (Newell, RBS, retrasos)
│   ├── lib_excel_export.py# Fase 3: Construcción del Excel maestro
│   ├── lib_ilp_solver.py  # Fase 2B: Optimización avanzada (en desarrollo)
│   └── main.py            # 🚀 Punto de entrada: ejecuta todo el pipeline en orden
├── test/
│   └── test_data_prep.py  # Archivos de pruebas automatizadas
├── .gitignore             # Archivos que GitHub debe ignorar
└── requirements.txt       # Lista de librerías de Python

    Tip rápido: Si queréis cambiar la hora a la que empieza el GDP o los costes por minuto para ver qué pasa, no toquéis el código; cambiadlo directamente en src/config.py.
