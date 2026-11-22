# Monitor Deportivo — Pronósticos Automáticos (PWA)

Aplicación web progresiva (PWA) móvil de monitoreo deportivo y pronósticos automáticos operada con costo **\$0** usando **OddsHarvester**, **GitHub Actions**, **Supabase** y **Next.js (Vercel)**.

## Estructura del Proyecto

```text
Pronosticos/
├── pipeline/                 # Extracción, curación, traducción y grading en Python
│   ├── config.py             # Ligas objetivo, reglas de consenso y zona horaria
│   ├── utils.py              # Normalización de URLs, event_id y fechas UTC
│   ├── translator.py         # Diccionario de mercados técnicos -> español natural
│   ├── curate.py             # Reglas de selección (5-8 picks diarios) y deduplicación
│   ├── grade.py              # Motor de calificación (won/lost/void + casos borde)
│   ├── db.py                 # Persistencia en Supabase (service_role_key)
│   ├── fetch_morning.py      # Job matutino (07:00 AM America/Mazatlan)
│   ├── grade_night.py        # Job nocturno (11:30 PM y 05:30 AM America/Mazatlan)
│   └── tests/                # Pruebas unitarias (pytest)
├── supabase/
│   └── schema.sql            # Tablas matches, predictions, tipsters, job_runs + RLS
├── web/                      # Frontend Next.js + Tailwind PWA (Fase 4)
└── .github/workflows/        # morning_fetch.yml y night_grade.yml
```

## Ejecución local del pipeline

```powershell
# Ejecutar pruebas unitarias
.\pipeline\.venv\Scripts\python.exe -m pytest -v pipeline\tests\test_pipeline.py

# Prueba matutina sin escribir en BD
.\pipeline\.venv\Scripts\python.exe -m pipeline.fetch_morning --dry-run

# Carga real hacia Supabase (usa .env)
.\pipeline\.venv\Scripts\python.exe -m pipeline.fetch_morning

# Calificación nocturna
.\pipeline\.venv\Scripts\python.exe -m pipeline.grade_night
```

## Secretos requeridos en GitHub Actions

Configurar en **Settings → Secrets and variables → Actions**:
* `SUPABASE_URL`
* `SUPABASE_SERVICE_ROLE_KEY`
