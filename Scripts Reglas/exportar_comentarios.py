import pandas as pd
import json

# Leer el archivo Excel
df = pd.read_excel(r'c:\Users\Desarrollo\Videos\Quotes\CHECK LIST (2).xlsb', 
                   sheet_name='MGA', 
                   engine='pyxlsb')

# Información básica
info = {
    "total_filas": len(df),
    "columnas": df.columns.tolist(),
    "tiene_comentarios": 'COMENTARIOS' in df.columns
}

# Analizar comentarios
if 'COMENTARIOS' in df.columns:
    comentarios_no_nulos = df['COMENTARIOS'].dropna()
    
    info["total_comentarios_no_vacios"] = len(comentarios_no_nulos)
    info["comentarios_unicos"] = df['COMENTARIOS'].nunique()
    
    # Obtener frecuencias
    value_counts = df['COMENTARIOS'].value_counts()
    info["frecuencias"] = {}
    for comentario, count in value_counts.items():
        info["frecuencias"][str(comentario)] = int(count)
    
    # Exportar todos los comentarios únicos a CSV
    df_comentarios = df[['COMENTARIOS']].dropna().drop_duplicates()
    df_comentarios.to_csv('comentarios_unicos.csv', index=False, encoding='utf-8-sig')
    
    # Exportar todos los datos con comentarios
    df_con_comentarios = df[df['COMENTARIOS'].notna()]
    df_con_comentarios.to_csv('datos_completos_con_comentarios.csv', index=False, encoding='utf-8-sig')

# Guardar información en JSON
with open('analisis_info.json', 'w', encoding='utf-8') as f:
    json.dump(info, f, indent=2, ensure_ascii=False)

print("✓ Archivos exportados:")
print("  - comentarios_unicos.csv")
print("  - datos_completos_con_comentarios.csv")
print("  - analisis_info.json")
print(f"\nTotal de comentarios únicos encontrados: {info.get('comentarios_unicos', 0)}")
