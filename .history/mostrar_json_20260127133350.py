import json

# Leer el JSON
with open('comentarios_completos.json', 'r', encoding='utf-8') as f:
    comentarios = json.load(f)

# Mostrar todos los comentarios numerados
print("="*120)
print(f"LISTA COMPLETA DE {len(comentarios)} COMENTARIOS ÚNICOS (Ordenados por frecuencia)")
print("="*120)
print()

for i, item in enumerate(comentarios, 1):
    freq = item['frecuencia']
    comentario = item['comentario']
    print(f"{i:2d}. [{freq:3d} veces] {comentario}")

print()
print("="*120)
