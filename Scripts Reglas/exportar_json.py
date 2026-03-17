import pandas as pd
import json

# Leer el archivo Excel
df = pd.read_excel(r'c:\Users\Desarrollo\Videos\Quotes\CHECK LIST (2).xlsb', 
                   sheet_name='MGA', 
                   engine='pyxlsb')

# Obtener todos los comentarios con sus frecuencias
value_counts = df['COMENTARIOS'].value_counts()

# Crear lista de comentarios para JSON
comentarios_lista = []
for comentario, freq in value_counts.items():
    comentarios_lista.append({
        "comentario": str(comentario),
        "frecuencia": int(freq)
    })

# Guardar en JSON
with open('comentarios_completos.json', 'w', encoding='utf-8') as f:
    json.dump(comentarios_lista, f, indent=2, ensure_ascii=False)

print(f"✓ Guardados {len(comentarios_lista)} comentarios en comentarios_completos.json")

# También mostrar en consola
print("\n" + "="*120)
print("LISTA COMPLETA DE COMENTARIOS:")
print("="*120 + "\n")

for i, item in enumerate(comentarios_lista, 1):
    print(f"{i:2d}. [{item['frecuencia']:3d} veces] {item['comentario']}")
