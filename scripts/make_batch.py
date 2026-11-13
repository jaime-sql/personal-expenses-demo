import json

batch_ops = [
    # ----------------------------------------------------
    # SLIDE 1: PORTADA (slide 'p')
    # ----------------------------------------------------
    {"op": "delete-element", "element": "i0"},
    {"op": "delete-element", "element": "i1"},
    {"op": "set-background", "slide": "p", "color": "#0B132B"},
    # Top accent line
    {"op": "add-shape", "slide": "p", "shape_type": "RECTANGLE", "x": 30, "y": 25, "width": 660, "height": 4, "background_color": "#00B4D8"},
    # Pill badge
    {"op": "add-shape", "slide": "p", "shape_type": "ROUND_RECTANGLE", "x": 30, "y": 45, "width": 260, "height": 26, "background_color": "#162238", "outline_color": "#00B4D8", "outline_weight": 1.0},
    {"op": "add-textbox", "slide": "p", "text": "⚡ DEMO EN VIVO & TALLER TÉCNICO", "x": 30, "y": 47, "width": 260, "height": 22, "font_size": 11, "bold": True, "color": "#00B4D8", "alignment": "center"},
    # Main Title
    {"op": "add-textbox", "slide": "p", "text": "De Gmail a Databricks & Power BI\ncon Antigravity", "x": 30, "y": 85, "width": 660, "height": 95, "font_size": 34, "bold": True, "color": "#FFFFFF", "font_family": "Roboto"},
    # Subtitle
    {"op": "add-textbox", "slide": "p", "text": "Pipeline de Gastos Financieros en Tiempo Real: Ingesta Segura con Enmascaramiento PII,\nMedallion Architecture en Unity Catalog y Analítica de Negocio Multiplataforma.", "x": 30, "y": 195, "width": 660, "height": 55, "font_size": 14, "color": "#90E0EF", "font_family": "Roboto", "line_spacing": 130},
    # Presenter & Event Bar
    {"op": "add-shape", "slide": "p", "shape_type": "ROUND_RECTANGLE", "x": 30, "y": 285, "width": 660, "height": 75, "background_color": "#132238", "outline_color": "#1E3A5F", "outline_weight": 1.0},
    {"op": "add-textbox", "slide": "p", "text": "Presentador: Jaime García\nData Engineer & Cloud Solutions Architect", "x": 45, "y": 298, "width": 340, "height": 50, "font_size": 13, "bold": True, "color": "#FFFFFF", "font_family": "Roboto"},
    {"op": "add-textbox", "slide": "p", "text": "Evento: CONCAPAN 2026\nGoogle AI Pro | Databricks Serverless | Power BI", "x": 380, "y": 298, "width": 290, "height": 50, "font_size": 12, "color": "#00B4D8", "font_family": "Roboto", "alignment": "right"},
    {"op": "set-notes", "slide": "p", "text": "Bienvenidos a la sesión de Data Engineering & AI en vivo para CONCAPAN 2026. Hoy veremos el ciclo completo de un dato transaccional real, desde el correo hasta la toma de decisiones en Power BI, protegido y orquestado con IA."},

    # ----------------------------------------------------
    # SLIDE 2: AGENDA & QUÉ VEREMOS HOY
    # ----------------------------------------------------
    {"op": "add-slide", "layout": "BLANK", "id": "SLIDE_AGENDA"},
    {"op": "set-background", "slide": "SLIDE_AGENDA", "color": "#F4F6F9"},
    {"op": "add-textbox", "slide": "SLIDE_AGENDA", "text": "¿Qué Veremos Hoy? — El Flujo de Datos en 6 Actos", "x": 30, "y": 22, "width": 660, "height": 38, "font_size": 24, "bold": True, "color": "#0B132B", "font_family": "Roboto"},
    {"op": "add-textbox", "slide": "SLIDE_AGENDA", "text": "Demostración en vivo: arquitectura moderna de datos construida paso a paso con Antigravity", "x": 30, "y": 60, "width": 660, "height": 22, "font_size": 12, "color": "#4A5568", "font_family": "Roboto"},
    # Card 1
    {"op": "add-shape", "slide": "SLIDE_AGENDA", "shape_type": "ROUND_RECTANGLE", "x": 30, "y": 92, "width": 206, "height": 265, "background_color": "#FFFFFF", "outline_color": "#CBD5E1", "outline_weight": 1.0},
    {"op": "add-shape", "slide": "SLIDE_AGENDA", "shape_type": "RECTANGLE", "x": 30, "y": 92, "width": 206, "height": 40, "background_color": "#0B132B"},
    {"op": "add-textbox", "slide": "SLIDE_AGENDA", "text": "1. Ingesta & Privacidad", "x": 30, "y": 100, "width": 206, "height": 25, "font_size": 13, "bold": True, "color": "#00B4D8", "alignment": "center"},
    {"op": "add-textbox", "slide": "SLIDE_AGENDA", "text": "• Extracción en vivo desde Gmail API (Alertas bancarias).\n• Anonimización PII por Regex: tarjetas (**43), cuentas y personas protegidas.\n• Normalización UTC ISO 8601.\n• Landing crudo JSONL en Unity Catalog Volumes.", "x": 42, "y": 142, "width": 182, "height": 200, "font_size": 11, "color": "#2D3748", "line_spacing": 135},
    # Card 2
    {"op": "add-shape", "slide": "SLIDE_AGENDA", "shape_type": "ROUND_RECTANGLE", "x": 256, "y": 92, "width": 206, "height": 265, "background_color": "#FFFFFF", "outline_color": "#CBD5E1", "outline_weight": 1.0},
    {"op": "add-shape", "slide": "SLIDE_AGENDA", "shape_type": "RECTANGLE", "x": 256, "y": 92, "width": 206, "height": 40, "background_color": "#0B132B"},
    {"op": "add-textbox", "slide": "SLIDE_AGENDA", "text": "2. Medallion Spark ETL", "x": 256, "y": 100, "width": 206, "height": 25, "font_size": 13, "bold": True, "color": "#00B4D8", "alignment": "center"},
    {"op": "add-textbox", "slide": "SLIDE_AGENDA", "text": "• Orquestación en Databricks con Job Serverless optimizado.\n• Delta Silver: 1,108 transacciones limpias y enriquecidas ($86K).\n• Tagging temático CONCAPAN: viáticos, transporte y hoteles.\n• Delta Gold: resúmenes agregados diarios.", "x": 268, "y": 142, "width": 182, "height": 200, "font_size": 11, "color": "#2D3748", "line_spacing": 135},
    # Card 3
    {"op": "add-shape", "slide": "SLIDE_AGENDA", "shape_type": "ROUND_RECTANGLE", "x": 482, "y": 92, "width": 206, "height": 265, "background_color": "#FFFFFF", "outline_color": "#CBD5E1", "outline_weight": 1.0},
    {"op": "add-shape", "slide": "SLIDE_AGENDA", "shape_type": "RECTANGLE", "x": 482, "y": 92, "width": 206, "height": 40, "background_color": "#0B132B"},
    {"op": "add-textbox", "slide": "SLIDE_AGENDA", "text": "3. Visualización & CI/CD", "x": 482, "y": 100, "width": 206, "height": 25, "font_size": 13, "bold": True, "color": "#00B4D8", "alignment": "center"},
    {"op": "add-textbox", "slide": "SLIDE_AGENDA", "text": "• Dashboard Lakeview interactivo con filtros por Año, Mes y Día.\n• CI/CD automático con GitHub Actions al pushear código.\n• Portal público en GitHub Pages.\n• Conexión directa a Power BI con SQL Warehouse de Databricks.", "x": 494, "y": 142, "width": 182, "height": 200, "font_size": 11, "color": "#2D3748", "line_spacing": 135},
    # Footer
    {"op": "add-textbox", "slide": "SLIDE_AGENDA", "text": "⚡ Tiempo de ejecución e implementación completa: ~1 hora y 10 minutos (100% auditable y reproducible)", "x": 30, "y": 368, "width": 660, "height": 20, "font_size": 10, "color": "#718096", "alignment": "center"},
    {"op": "set-notes", "slide": "SLIDE_AGENDA", "text": "Explicar los 3 pilares del proyecto: Ingesta segura con protección de datos personales, orquestación Medallion con Spark Connect en Databricks, y el consumo analítico tanto en Lakeview como en Power BI."},

    # ----------------------------------------------------
    # SLIDE 3: ARQUITECTURA TÉCNICA END-TO-END
    # ----------------------------------------------------
    {"op": "add-slide", "layout": "BLANK", "id": "SLIDE_ARCH"},
    {"op": "set-background", "slide": "SLIDE_ARCH", "color": "#0B132B"},
    {"op": "add-textbox", "slide": "SLIDE_ARCH", "text": "Arquitectura Técnica del Pipeline de Datos", "x": 30, "y": 20, "width": 660, "height": 35, "font_size": 24, "bold": True, "color": "#FFFFFF", "font_family": "Roboto"},
    {"op": "add-textbox", "slide": "SLIDE_ARCH", "text": "Diseño desacoplado, seguro y serverless sobre Unity Catalog y Databricks Free Edition", "x": 30, "y": 55, "width": 660, "height": 20, "font_size": 12, "color": "#90E0EF", "font_family": "Roboto"},
    # 5 Process Blocks
    {"op": "add-shape", "slide": "SLIDE_ARCH", "shape_type": "ROUND_RECTANGLE", "x": 30, "y": 88, "width": 118, "height": 195, "background_color": "#162238", "outline_color": "#00B4D8", "outline_weight": 1.0},
    {"op": "add-textbox", "slide": "SLIDE_ARCH", "text": "1. FUENTE\nGmail API", "x": 32, "y": 95, "width": 114, "height": 35, "font_size": 11, "bold": True, "color": "#00B4D8", "alignment": "center"},
    {"op": "add-textbox", "slide": "SLIDE_ARCH", "text": "Alertas de compra:\n• BAC\n• Cuscatlán\n• Promerica\n• BI\n• Credicomer\nOAuth 2.0 seguro", "x": 36, "y": 135, "width": 106, "height": 140, "font_size": 10, "color": "#E2E8F0", "line_spacing": 125},

    {"op": "add-shape", "slide": "SLIDE_ARCH", "shape_type": "ROUND_RECTANGLE", "x": 165, "y": 88, "width": 118, "height": 195, "background_color": "#162238", "outline_color": "#00B4D8", "outline_weight": 1.0},
    {"op": "add-textbox", "slide": "SLIDE_ARCH", "text": "2. INGESTA\nPython CLI", "x": 167, "y": 95, "width": 114, "height": 35, "font_size": 11, "bold": True, "color": "#00B4D8", "alignment": "center"},
    {"op": "add-textbox", "slide": "SLIDE_ARCH", "text": "• Enmascaramiento PII en vivo (**43)\n• Parser regex multiformato\n• Normalización fecha UTC ISO 8601", "x": 171, "y": 135, "width": 106, "height": 140, "font_size": 10, "color": "#E2E8F0", "line_spacing": 125},

    {"op": "add-shape", "slide": "SLIDE_ARCH", "shape_type": "ROUND_RECTANGLE", "x": 300, "y": 88, "width": 120, "height": 195, "background_color": "#162238", "outline_color": "#48CAE4", "outline_weight": 1.0},
    {"op": "add-textbox", "slide": "SLIDE_ARCH", "text": "3. BRONZE\nUC Volumes", "x": 302, "y": 95, "width": 116, "height": 35, "font_size": 11, "bold": True, "color": "#48CAE4", "alignment": "center"},
    {"op": "add-textbox", "slide": "SLIDE_ARCH", "text": "Almacenamiento:\n/Volumes/workspace/\npersonal_expenses/\nlanding/gmail/\nArchivos JSONL inmutables", "x": 306, "y": 135, "width": 108, "height": 140, "font_size": 10, "color": "#E2E8F0", "line_spacing": 125},

    {"op": "add-shape", "slide": "SLIDE_ARCH", "shape_type": "ROUND_RECTANGLE", "x": 437, "y": 88, "width": 125, "height": 195, "background_color": "#162238", "outline_color": "#48CAE4", "outline_weight": 1.0},
    {"op": "add-textbox", "slide": "SLIDE_ARCH", "text": "4. SILVER/GOLD\nSpark Connect", "x": 439, "y": 95, "width": 121, "height": 35, "font_size": 11, "bold": True, "color": "#48CAE4", "alignment": "center"},
    {"op": "add-textbox", "slide": "SLIDE_ARCH", "text": "Delta Silver:\nconcapan_charges\n(1,108 rows, $86.1K)\nDelta Gold:\nconcapan_gold_summary\nServerless Job", "x": 443, "y": 135, "width": 113, "height": 140, "font_size": 10, "color": "#E2E8F0", "line_spacing": 125},

    {"op": "add-shape", "slide": "SLIDE_ARCH", "shape_type": "ROUND_RECTANGLE", "x": 579, "y": 88, "width": 111, "height": 195, "background_color": "#1E2D4A", "outline_color": "#00B4D8", "outline_weight": 1.0},
    {"op": "add-textbox", "slide": "SLIDE_ARCH", "text": "5. ANALÍTICA\nLakeview & PBI", "x": 581, "y": 95, "width": 107, "height": 35, "font_size": 11, "bold": True, "color": "#00B4D8", "alignment": "center"},
    {"op": "add-textbox", "slide": "SLIDE_ARCH", "text": "• Databricks Lakeview con filtros dinámicos\n• Power BI vía SQL Warehouse DirectQuery\n• GitHub Pages", "x": 585, "y": 135, "width": 99, "height": 140, "font_size": 10, "color": "#E2E8F0", "line_spacing": 125},

    # Highlights banner
    {"op": "add-shape", "slide": "SLIDE_ARCH", "shape_type": "ROUND_RECTANGLE", "x": 30, "y": 298, "width": 660, "height": 78, "background_color": "#132238", "outline_color": "#1E3A5F", "outline_weight": 1.0},
    {"op": "add-textbox", "slide": "SLIDE_ARCH", "text": "🔒 PRIVACIDAD EN VIVO: El script aplica enmascaramiento regex para que ninguna pantalla pública filtre datos sensibles.\n🚀 CI/CD DECLARATIVO: GitHub Actions ejecuta pruebas unitarias y sincroniza notebooks y dashboards automáticamente.\n💰 COMPUTE EFICIENTE: 100% sobre Databricks Free Edition Serverless con Unity Catalog gobernado.", "x": 45, "y": 305, "width": 630, "height": 65, "font_size": 10.5, "color": "#CAF0F8", "line_spacing": 130},
    {"op": "set-notes", "slide": "SLIDE_ARCH", "text": "Detalle de la arquitectura. Resaltar cómo se resolvió el problema del timestamp parsing de email RFC 2822 a ISO 8601 UTC en la ingesta para que Spark lo procese sin errores."},

    # ----------------------------------------------------
    # SLIDE 4: ACCESO EDUCATIVO GOOGLE AI PRO & ANTIGRAVITY
    # ----------------------------------------------------
    {"op": "add-slide", "layout": "BLANK", "id": "SLIDE_EDU"},
    {"op": "set-background", "slide": "SLIDE_EDU", "color": "#F4F6F9"},
    {"op": "add-textbox", "slide": "SLIDE_EDU", "text": "Acceso Educativo: Google AI Pro & Antigravity", "x": 30, "y": 22, "width": 660, "height": 38, "font_size": 24, "bold": True, "color": "#0B132B", "font_family": "Roboto"},
    {"op": "add-textbox", "slide": "SLIDE_EDU", "text": "Oportunidad para estudiantes y docentes universitarios: modelos de frontera sin costo", "x": 30, "y": 60, "width": 660, "height": 22, "font_size": 12, "color": "#4A5568", "font_family": "Roboto"},
    # Left container: How to activate
    {"op": "add-shape", "slide": "SLIDE_EDU", "shape_type": "ROUND_RECTANGLE", "x": 30, "y": 90, "width": 420, "height": 280, "background_color": "#FFFFFF", "outline_color": "#CBD5E1", "outline_weight": 1.0},
    {"op": "add-textbox", "slide": "SLIDE_EDU", "text": "Paso a Paso para Estudiantes y Docentes:", "x": 45, "y": 100, "width": 390, "height": 25, "font_size": 14, "bold": True, "color": "#0B132B"},
    {"op": "add-textbox", "slide": "SLIDE_EDU", "text": "1. Correo Institucional (.edu o universitario):\n   Acceso a los programas educativos de Google Workspace for Education y cuotas ampliadas para proyectos de investigación y docencia.\n\n2. Google AI Studio & Gemini Pro:\n   Acceso a modelos Gemini 1.5 y 2.0 Pro con ventanas de contexto de hasta 2 millones de tokens para análisis masivo de datos y código.\n\n3. Antigravity Developer Assistant:\n   Asistente agéntico de Google DeepMind conectado a terminal, Databricks y GitHub para acelerar pipelines y análisis de datos.\n\n4. Escaneo y Activación Rápida:\n   Escanea el código QR de la derecha para ingresar al portal oficial.", "x": 45, "y": 130, "width": 390, "height": 225, "font_size": 11, "color": "#2D3748", "line_spacing": 125},
    # Right container: QR Box
    {"op": "add-shape", "slide": "SLIDE_EDU", "shape_type": "ROUND_RECTANGLE", "x": 470, "y": 90, "width": 220, "height": 280, "background_color": "#FFFFFF", "outline_color": "#CBD5E1", "outline_weight": 1.0},
    {"op": "add-textbox", "slide": "SLIDE_EDU", "text": "ACTIVAR ACCESO", "x": 470, "y": 102, "width": 220, "height": 20, "font_size": 12, "bold": True, "color": "#0B132B", "alignment": "center"},
    {"op": "add-textbox", "slide": "SLIDE_EDU", "text": "Google AI for Developers\nai.google.dev", "x": 470, "y": 280, "width": 220, "height": 40, "font_size": 11, "bold": True, "color": "#2B6CB0", "alignment": "center"},
    {"op": "add-textbox", "slide": "SLIDE_EDU", "text": "Apunta la cámara de tu móvil para ingresar", "x": 470, "y": 325, "width": 220, "height": 25, "font_size": 9.5, "color": "#718096", "alignment": "center"},
    {"op": "set-notes", "slide": "SLIDE_EDU", "text": "Invitar a los estudiantes y docentes a usar sus cuentas universitarias para obtener acceso a Google AI Studio y Antigravity."},

    # ----------------------------------------------------
    # SLIDE 5: PORTALES Y RECURSOS EN VIVO (QR CODES)
    # ----------------------------------------------------
    {"op": "add-slide", "layout": "BLANK", "id": "SLIDE_QR"},
    {"op": "set-background", "slide": "SLIDE_QR", "color": "#0B132B"},
    {"op": "add-textbox", "slide": "SLIDE_QR", "text": "Portales en Vivo: Escanea desde tu Celular", "x": 30, "y": 20, "width": 660, "height": 35, "font_size": 24, "bold": True, "color": "#FFFFFF", "font_family": "Roboto"},
    {"op": "add-textbox", "slide": "SLIDE_QR", "text": "Acceso inmediato a la web pública, el dashboard de Databricks y el repositorio del proyecto", "x": 30, "y": 55, "width": 660, "height": 20, "font_size": 12, "color": "#90E0EF", "font_family": "Roboto"},
    # 3 QR Cards
    {"op": "add-shape", "slide": "SLIDE_QR", "shape_type": "ROUND_RECTANGLE", "x": 30, "y": 85, "width": 206, "height": 285, "background_color": "#162238", "outline_color": "#00B4D8", "outline_weight": 1.0},
    {"op": "add-textbox", "slide": "SLIDE_QR", "text": "🌐 PORTAL DEMO WEB", "x": 30, "y": 95, "width": 206, "height": 22, "font_size": 12, "bold": True, "color": "#00B4D8", "alignment": "center"},
    {"op": "add-textbox", "slide": "SLIDE_QR", "text": "GitHub Pages en Vivo", "x": 30, "y": 118, "width": 206, "height": 18, "font_size": 10, "color": "#CADCFC", "alignment": "center"},
    {"op": "add-textbox", "slide": "SLIDE_QR", "text": "jaime-sql.github.io/\npersonal-expenses-demo/", "x": 35, "y": 305, "width": 196, "height": 45, "font_size": 9.5, "bold": True, "color": "#90E0EF", "alignment": "center"},

    {"op": "add-shape", "slide": "SLIDE_QR", "shape_type": "ROUND_RECTANGLE", "x": 256, "y": 85, "width": 206, "height": 285, "background_color": "#162238", "outline_color": "#00B4D8", "outline_weight": 1.0},
    {"op": "add-textbox", "slide": "SLIDE_QR", "text": "📊 LAKEVIEW DASHBOARD", "x": 256, "y": 95, "width": 206, "height": 22, "font_size": 12, "bold": True, "color": "#00B4D8", "alignment": "center"},
    {"op": "add-textbox", "slide": "SLIDE_QR", "text": "Databricks Free Edition", "x": 256, "y": 118, "width": 206, "height": 18, "font_size": 10, "color": "#CADCFC", "alignment": "center"},
    {"op": "add-textbox", "slide": "SLIDE_QR", "text": "CONCAPAN 2026\nExpenses & Travel Analytics", "x": 261, "y": 305, "width": 196, "height": 45, "font_size": 9.5, "bold": True, "color": "#90E0EF", "alignment": "center"},

    {"op": "add-shape", "slide": "SLIDE_QR", "shape_type": "ROUND_RECTANGLE", "x": 482, "y": 85, "width": 206, "height": 285, "background_color": "#162238", "outline_color": "#00B4D8", "outline_weight": 1.0},
    {"op": "add-textbox", "slide": "SLIDE_QR", "text": "💻 REPOSITORIO GITHUB", "x": 482, "y": 95, "width": 206, "height": 22, "font_size": 12, "bold": True, "color": "#00B4D8", "alignment": "center"},
    {"op": "add-textbox", "slide": "SLIDE_QR", "text": "Código, CI/CD y Playbook", "x": 482, "y": 118, "width": 206, "height": 18, "font_size": 10, "color": "#CADCFC", "alignment": "center"},
    {"op": "add-textbox", "slide": "SLIDE_QR", "text": "github.com/jaime-sql/\npersonal-expenses-demo", "x": 487, "y": 305, "width": 196, "height": 45, "font_size": 9.5, "bold": True, "color": "#90E0EF", "alignment": "center"},
    {"op": "set-notes", "slide": "SLIDE_QR", "text": "Dar tiempo a los asistentes para escanear los 3 códigos QR desde sus teléfonos móviles para interactuar directamente con la demo."},

    # ----------------------------------------------------
    # SLIDE 6: DINÁMICA INTERACTIVA POWER BI
    # ----------------------------------------------------
    {"op": "add-slide", "layout": "BLANK", "id": "SLIDE_POWERBI"},
    {"op": "set-background", "slide": "SLIDE_POWERBI", "color": "#F4F6F9"},
    {"op": "add-textbox", "slide": "SLIDE_POWERBI", "text": "Reto en Vivo: Conecta Power BI a Unity Catalog", "x": 30, "y": 20, "width": 660, "height": 38, "font_size": 24, "bold": True, "color": "#0B132B", "font_family": "Roboto"},
    {"op": "add-textbox", "slide": "SLIDE_POWERBI", "text": "Instrucciones para el equipo de datos: replicar el dashboard conectándose a las tablas Gold ya procesadas", "x": 30, "y": 56, "width": 660, "height": 22, "font_size": 12, "color": "#4A5568", "font_family": "Roboto"},
    # Left Box: Connection Specs
    {"op": "add-shape", "slide": "SLIDE_POWERBI", "shape_type": "ROUND_RECTANGLE", "x": 30, "y": 86, "width": 320, "height": 280, "background_color": "#FFFFFF", "outline_color": "#CBD5E1", "outline_weight": 1.0},
    {"op": "add-shape", "slide": "SLIDE_POWERBI", "shape_type": "RECTANGLE", "x": 30, "y": 86, "width": 320, "height": 35, "background_color": "#0B132B"},
    {"op": "add-textbox", "slide": "SLIDE_POWERBI", "text": "PARÁMETROS DE CONEXIÓN", "x": 30, "y": 94, "width": 320, "height": 22, "font_size": 12, "bold": True, "color": "#00B4D8", "alignment": "center"},
    {"op": "add-textbox", "slide": "SLIDE_POWERBI", "text": "• Conector: Azure Databricks nativo (Power BI Desktop)\n• Server Hostname:\n  dbc-6b5953ee-73b5.cloud.databricks.com\n• HTTP Path:\n  /sql/1.0/warehouses/de62669408c45fc9\n• Catálogo: workspace\n• Schema: personal_expenses\n• Tablas Destino:\n  1. concapan_gold_summary (Métricas agregadas)\n  2. concapan_silver_charges (Transacciones detalle)\n• Modo de Datos: DirectQuery o Import", "x": 42, "y": 128, "width": 296, "height": 225, "font_size": 10.5, "color": "#1A202C", "line_spacing": 125},
    # Right Box: Deliverables Challenge
    {"op": "add-shape", "slide": "SLIDE_POWERBI", "shape_type": "ROUND_RECTANGLE", "x": 370, "y": 86, "width": 320, "height": 280, "background_color": "#FFFFFF", "outline_color": "#CBD5E1", "outline_weight": 1.0},
    {"op": "add-shape", "slide": "SLIDE_POWERBI", "shape_type": "RECTANGLE", "x": 370, "y": 86, "width": 320, "height": 35, "background_color": "#0B132B"},
    {"op": "add-textbox", "slide": "SLIDE_POWERBI", "text": "ENTREGABLES DEL RETO", "x": 370, "y": 94, "width": 320, "height": 22, "font_size": 12, "bold": True, "color": "#00B4D8", "alignment": "center"},
    {"op": "add-textbox", "slide": "SLIDE_POWERBI", "text": "1. Tarjetas KPI Principales:\n   • Gasto Total: $86,087.12 USD\n   • Viáticos & Traslados CONCAPAN: $21,200.00 USD\n   • Transacciones Procesadas: 1,108\n\n2. Gráficos Ejecutivos:\n   • Distribución por Eje Operativo (event_tag).\n   • Desembolsos por Entidad Bancaria.\n\n3. Interactividad:\n   • Segmentadores dinámicos por Año, Mes y Día.\n   • Tabla de auditoría detallada de cargos.", "x": 382, "y": 128, "width": 296, "height": 225, "font_size": 10.5, "color": "#1A202C", "line_spacing": 125},
    {"op": "set-notes", "slide": "SLIDE_POWERBI", "text": "Lanzar el reto al equipo de datos. Demostrar que Unity Catalog permite la gobernanza centralizada donde Databricks y Power BI consultan exactamente la misma capa Silver y Gold."},

    # ----------------------------------------------------
    # SLIDE 7: CIERRE Y CONCLUSIONES
    # ----------------------------------------------------
    {"op": "add-slide", "layout": "BLANK", "id": "SLIDE_CLOSING"},
    {"op": "set-background", "slide": "SLIDE_CLOSING", "color": "#0B132B"},
    {"op": "add-textbox", "slide": "SLIDE_CLOSING", "text": "El Futuro de la Ingeniería de Datos con IA", "x": 30, "y": 25, "width": 660, "height": 38, "font_size": 25, "bold": True, "color": "#FFFFFF", "font_family": "Roboto", "alignment": "center"},
    {"op": "add-textbox", "slide": "SLIDE_CLOSING", "text": "De semanas de desarrollo tradicional a minutos de orquestación ágil y gobernada", "x": 30, "y": 62, "width": 660, "height": 22, "font_size": 13, "color": "#90E0EF", "font_family": "Roboto", "alignment": "center"},
    # 3 Summary Cards
    {"op": "add-shape", "slide": "SLIDE_CLOSING", "shape_type": "ROUND_RECTANGLE", "x": 30, "y": 100, "width": 206, "height": 170, "background_color": "#162238", "outline_color": "#00B4D8", "outline_weight": 1.0},
    {"op": "add-textbox", "slide": "SLIDE_CLOSING", "text": "⚡ VELOCIDAD", "x": 30, "y": 115, "width": 206, "height": 25, "font_size": 14, "bold": True, "color": "#00B4D8", "alignment": "center"},
    {"op": "add-textbox", "slide": "SLIDE_CLOSING", "text": "Pipeline completo (Ingesta, ETL Spark, Medallion, Lakeview, CI/CD y Web Portal) construido y validado en ~1 hora y 10 minutos.", "x": 42, "y": 148, "width": 182, "height": 110, "font_size": 11, "color": "#E2E8F0", "line_spacing": 130},

    {"op": "add-shape", "slide": "SLIDE_CLOSING", "shape_type": "ROUND_RECTANGLE", "x": 256, "y": 100, "width": 206, "height": 170, "background_color": "#162238", "outline_color": "#00B4D8", "outline_weight": 1.0},
    {"op": "add-textbox", "slide": "SLIDE_CLOSING", "text": "🔒 PRIVACIDAD & GOBIERNO", "x": 256, "y": 115, "width": 206, "height": 25, "font_size": 14, "bold": True, "color": "#00B4D8", "alignment": "center"},
    {"op": "add-textbox", "slide": "SLIDE_CLOSING", "text": "Enmascaramiento preventivo de PII para demostraciones en vivo. Unity Catalog como repositorio único de seguridad y linaje.", "x": 268, "y": 148, "width": 182, "height": 110, "font_size": 11, "color": "#E2E8F0", "line_spacing": 130},

    {"op": "add-shape", "slide": "SLIDE_CLOSING", "shape_type": "ROUND_RECTANGLE", "x": 482, "y": 100, "width": 206, "height": 170, "background_color": "#162238", "outline_color": "#00B4D8", "outline_weight": 1.0},
    {"op": "add-textbox", "slide": "SLIDE_CLOSING", "text": "🚀 INTEROPERABILIDAD", "x": 482, "y": 115, "width": 206, "height": 25, "font_size": 14, "bold": True, "color": "#00B4D8", "alignment": "center"},
    {"op": "add-textbox", "slide": "SLIDE_CLOSING", "text": "Arquitectura abierta: las mismas tablas Delta sirven a Databricks Lakeview y a Power BI corporativo simultáneamente.", "x": 494, "y": 148, "width": 182, "height": 110, "font_size": 11, "color": "#E2E8F0", "line_spacing": 130},

    # Q&A Banner
    {"op": "add-shape", "slide": "SLIDE_CLOSING", "shape_type": "ROUND_RECTANGLE", "x": 30, "y": 290, "width": 660, "height": 80, "background_color": "#132238", "outline_color": "#00B4D8", "outline_weight": 1.0},
    {"op": "add-textbox", "slide": "SLIDE_CLOSING", "text": "¡Muchas Gracias! — Sesión de Preguntas y Respuestas\nCONCAPAN 2026 | Jaime García\nRepositorio: github.com/jaime-sql/personal-expenses-demo", "x": 45, "y": 305, "width": 630, "height": 55, "font_size": 13, "bold": True, "color": "#00B4D8", "alignment": "center", "line_spacing": 130},
    {"op": "set-notes", "slide": "SLIDE_CLOSING", "text": "Cierre de la presentación. Agradecer a la audiencia y abrir espacio para preguntas sobre la arquitectura, Databricks Free Edition, Unity Catalog o la integración con Power BI y Google AI Studio."}
]

with open(r'C:\Users\jaime\.gemini\antigravity\scratch\personal-expenses-demo\scripts\generate_slides_batch.json', 'w', encoding='utf-8') as f:
    json.dump(batch_ops, f, indent=2, ensure_ascii=False)

print(f"Generated batch with {len(batch_ops)} operations")
