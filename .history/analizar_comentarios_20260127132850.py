import pandas as pd

# Leer el archivo Excel
df = pd.read_excel(r'c:\Users\Desarrollo\Videos\Quotes\CHECK LIST (2).xlsb', 
                   sheet_name='MGA', 
                   engine='pyxlsb')

print("=" * 80)
print("COLUMNAS DISPONIBLES:")
print("=" * 80)
for i, col in enumerate(df.columns, 1):
    print(f"{i}. {col}")

print("\n" + "=" * 80)
print(f"TOTAL DE FILAS: {len(df)}")
print("=" * 80)

# Verificar si existe la columna COMENTARIOS
if 'COMENTARIOS' in df.columns:
    print("\n" + "=" * 80)
    print("ANÁLISIS DE LA COLUMNA 'COMENTARIOS':")
    print("=" * 80)
    
    # Eliminar valores nulos
    comentarios_no_nulos = df['COMENTARIOS'].dropna()
    print(f"\nTotal de comentarios no vacíos: {len(comentarios_no_nulos)}")
    print(f"Total de comentarios únicos: {df['COMENTARIOS'].nunique()}")
    
    print("\n" + "=" * 80)
    print("FRECUENCIA DE COMENTARIOS:")
    print("=" * 80)
    value_counts = df['COMENTARIOS'].value_counts()
    for comentario, count in value_counts.items():
        print(f"\n[{count} ocurrencias] {comentario}")
    
    print("\n" + "=" * 80)
    print("MUESTRA DE DATOS (primeras 10 filas con comentarios):")
    print("=" * 80)
    df_con_comentarios = df[df['COMENTARIOS'].notna()].head(10)
    for idx, row in df_con_comentarios.iterrows():
        print(f"\nFila {idx + 2}:")
        print(f"  COMENTARIOS: {row['COMENTARIOS']}")
else:
    print("\n⚠️ No se encontró la columna 'COMENTARIOS'")
    print("\nBuscando columnas similares...")
    for col in df.columns:
        if 'coment' in col.lower() or 'comment' in col.lower():
            print(f"  - {col}")
