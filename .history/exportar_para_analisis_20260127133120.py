import pandas as pd

# Leer el archivo Excel
df = pd.read_excel(r'c:\Users\Desarrollo\Videos\Quotes\CHECK LIST (2).xlsb', 
                   sheet_name='MGA', 
                   engine='pyxlsb')

# Obtener todos los comentarios únicos ordenados por frecuencia
value_counts = df['COMENTARIOS'].value_counts()

# Crear un DataFrame con los comentarios y sus frecuencias
comentarios_df = pd.DataFrame({
    'COMENTARIO': value_counts.index,
    'FRECUENCIA': value_counts.values
})

# Guardar en CSV
comentarios_df.to_csv('comentarios_con_frecuencia.csv', index=False, encoding='utf-8-sig')

# Guardar en Excel para mejor visualización
comentarios_df.to_excel('comentarios_con_frecuencia.xlsx', index=False)

print(f"✓ Total de comentarios únicos: {len(comentarios_df)}")
print(f"✓ Archivos exportados:")
print(f"  - comentarios_con_frecuencia.csv")
print(f"  - comentarios_con_frecuencia.xlsx")
