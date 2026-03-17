import pandas as pd
import re
from difflib import SequenceMatcher

# Función para calcular similaridad
def similar(a, b):
    return SequenceMatcher(None, a, b).ratio()

# Leer el archivo Excel original
df = pd.read_excel(r'c:\Users\Desarrollo\Videos\Quotes\CHECK LIST (2).xlsb', 
                   sheet_name='MGA', 
                   engine='pyxlsb')

# Obtener todos los comentarios únicos
comentarios_unicos = df['COMENTARIOS'].dropna().unique()

print(f"ANÁLISIS COMPLETO DE {len(comentarios_unicos)} COMENTARIOS ÚNICOS")
print("="*120)

# Guardar lista completa en archivo
with open('analisis_completo_comentarios.txt', 'w', encoding='utf-8') as f:
    f.write("="*120 + "\n")
    f.write(f"LISTA COMPLETA DE {len(comentarios_unicos)} COMENTARIOS ÚNICOS\n")
    f.write("="*120 + "\n\n")
    
    value_counts = df['COMENTARIOS'].value_counts()
    
    for i, comentario in enumerate(value_counts.index, 1):
        freq = value_counts[comentario]
        linea = f"{i}. [{freq:3d} veces] {comentario}\n"
        f.write(linea)
        print(linea.strip())

print("\n✓ Análisis guardado en: analisis_completo_comentarios.txt")

# Identificar palabras clave frecuentes
print("\n" + "="*120)
print("PALABRAS CLAVE MÁS FRECUENTES EN LOS COMENTARIOS:")
print("="*120)

from collections import Counter

# Extraer palabras clave
palabras = []
for comentario in comentarios_unicos:
    # Convertir a string y dividir en palabras
    texto = str(comentario).upper()
    # Extraer palabras importantes (más de 2 caracteres)
    palabras.extend([p for p in re.findall(r'\b[A-ZÁÉÍÓÚÑa-záéíóúñ]{3,}\b', texto)])

frecuencia_palabras = Counter(palabras)
print("\nTop 20 palabras más frecuentes:")
for palabra, freq in frecuencia_palabras.most_common(20):
    print(f"  {palabra}: {freq} veces")

# Guardar palabras clave
with open('palabras_clave.txt', 'w', encoding='utf-8') as f:
    f.write("PALABRAS CLAVE MÁS FRECUENTES:\n")
    f.write("="*60 + "\n\n")
    for palabra, freq in frecuencia_palabras.most_common(50):
        f.write(f"{palabra}: {freq} veces\n")

print("\n✓ Palabras clave guardadas en: palabras_clave.txt")
