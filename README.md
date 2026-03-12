# MGTA — Simulador GDP Barcelona (LEBL)

Simulador de Ground Delay Program para LEBL. Genera los gráficos y el Excel de auditoría automáticamente.

---

## Lo que necesitas instalar

**Git** — para trabajar juntos sin mandarnos zips por WhatsApp.
Descárgalo en https://git-scm.com/download/win e instálalo con las opciones por defecto.

**Las librerías de Python** — una vez tengas el proyecto clonado:
```bash
pip install -r requirements.txt
```

---

## Cómo unirte al proyecto

```bash
git clone https://github.com/TU_USUARIO/MGTA_reforma.git
cd MGTA_reforma
pip install -r requirements.txt
python src/main.py
```

Si se generan archivos en `data/processed/` y `output/figures/` es que todo funciona.

> Los CSV de datos no están en el repo porque pesan demasiado.
> Pedídmelos y los ponéis en `data/raw/`.

---

## Cómo trabajar

La única regla: **no trabajéis directamente en `main`**, cada uno en su rama.

```bash
# Al empezar, bajad lo último
git checkout main
git pull

# Cread vuestra rama
git checkout -b feature/lo-que-vais-a-hacer

# Cuando terminéis algo que funciona, guardadlo
git add .
git commit -m "feat: descripción de qué habéis hecho"

# Subidlo
git push origin feature/lo-que-vais-a-hacer
```

En GitHub os aparecerá un botón verde **"Compare & pull request"**. Pulsadlo y avisadme para revisarlo.

Prefijos de commit: `feat:` para cosas nuevas, `fix:` para bugs, `docs:` para documentación.

---

## Tests

Antes de subir nada, ejecutad los tests:

```bash
python -m pytest test/ -v
```

Si veis `16 passed`, todo bien. Si hay algún `FAILED`, arregladlo antes de hacer push.

---

## Estructura

```
MGTA_reforma3/
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

Para ejecutar el proyecto: `python src/main.py`. Para cambiar parámetros: `config.py`.
