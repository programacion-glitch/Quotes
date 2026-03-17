import json
import pandas as pd

# Leer el JSON con todos los comentarios
with open('comentarios_completos.json', 'r', encoding='utf-8') as f:
    comentarios = json.load(f)

# Crear DataFrame para análisis
df_analisis = pd.DataFrame(comentarios)

# Imprimir todos los comentarios
with open('ANALISIS_DETALLADO_TODOS_LOS_COMENTARIOS.md', 'w', encoding='utf-8') as f:
    f.write("# ANÁLISIS DETALLADO DE COMENTARIOS - HOJA MGA\n\n")
    f.write(f"**Total de comentarios únicos:** {len(comentarios)}\n\n")
    f.write("---\n\n")
    f.write("## LISTA COMPLETA DE COMENTARIOS (Ordenados por frecuencia)\n\n")
    
    for i, item in enumerate(comentarios, 1):
        f.write(f"### {i}. Frecuencia: {item['frecuencia']} veces\n")
        f.write(f"```\n{item['comentario']}\n```\n\n")

print("✓ Análisis detallado guardado en: ANALISIS_DETALLADO_TODOS_LOS_COMENTARIOS.md")
