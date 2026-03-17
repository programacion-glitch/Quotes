import pandas as pd
from collections import defaultdict

# Leer el archivo Excel
df = pd.read_excel(r'c:\Users\Desarrollo\Videos\Quotes\CHECK LIST (2).xlsb', 
                   sheet_name='MGA', 
                   engine='pyxlsb')

print("="*100)
print("ANÁLISIS DETALLADO DE COMENTARIOS")
print("="*100)
print(f"\nTotal de filas: {len(df)}")
print(f"Total de comentarios únicos: {df['COMENTARIOS'].nunique()}")
print(f"Total de comentarios no vacíos: {df['COMENTARIOS'].notna().sum()}")

print("\n" + "="*100)
print("TODOS LOS COMENTARIOS ÚNICOS CON SUS FRECUENCIAS:")
print("="*100)

value_counts = df['COMENTARIOS'].value_counts()
for i, (comentario, count) in enumerate(value_counts.items(), 1):
    print(f"\n{i}. [{count} vez/veces]")
    print(f"   {comentario}")

# Guardar en archivo de texto
with open('comentarios_detallados.txt', 'w', encoding='utf-8') as f:
    f.write("="*100 + "\n")
    f.write("ANÁLISIS DETALLADO DE COMENTARIOS\n")
    f.write("="*100 + "\n\n")
    f.write(f"Total de filas: {len(df)}\n")
    f.write(f"Total de comentarios únicos: {df['COMENTARIOS'].nunique()}\n")
    f.write(f"Total de comentarios no vacíos: {df['COMENTARIOS'].notna().sum()}\n\n")
    
    f.write("="*100 + "\n")
    f.write("TODOS LOS COMENTARIOS ÚNICOS CON SUS FRECUENCIAS:\n")
    f.write("="*100 + "\n\n")
    
    for i, (comentario, count) in enumerate(value_counts.items(), 1):
        f.write(f"{i}. [{count} vez/veces]\n")
        f.write(f"   {comentario}\n\n")

print("\n" + "="*100)
print("✓ Análisis guardado en: comentarios_detallados.txt")
print("="*100)
