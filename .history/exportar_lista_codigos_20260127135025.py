import pandas as pd
import json

# Leer el archivo estandarizado
df = pd.read_excel('CHECK LIST (2)_ESTANDARIZADO.xlsx', sheet_name='MGA')

# Extraer todos los códigos únicos
todos_los_codigos = set()
frecuencia = {}

for regla in df['REGLA_ESTANDARIZADA'].dropna():
    if regla and regla != '':
        codigos = str(regla).split('|')
        for codigo in codigos:
            todos_los_codigos.add(codigo)
            frecuencia[codigo] = frecuencia.get(codigo, 0) + 1

# Ordenar alfabéticamente
codigos_ordenados = sorted(todos_los_codigos)

# Crear archivo markdown
with open('TODOS_LOS_CODIGOS.md', 'w', encoding='utf-8') as f:
    f.write("# Todos los Códigos Estandarizados\n\n")
    f.write(f"**Total de códigos únicos:** {len(codigos_ordenados)}\n\n")
    f.write("---\n\n")
    f.write("## Lista Completa (Orden Alfabético)\n\n")
    
    for i, codigo in enumerate(codigos_ordenados, 1):
        freq = frecuencia[codigo]
        f.write(f"{i}. `{codigo}` - Usado {freq} veces\n")
    
    f.write("\n---\n\n")
    f.write("## Lista por Frecuencia\n\n")
    
    codigos_por_freq = sorted(frecuencia.items(), key=lambda x: x[1], reverse=True)
    for codigo, freq in codigos_por_freq:
        f.write(f"- `{codigo}` → {freq} veces\n")

# También guardar en JSON simple
datos = {
    "total_codigos": len(codigos_ordenados),
    "codigos": codigos_ordenados,
    "frecuencias": frecuencia
}

with open('codigos_existentes.json', 'w', encoding='utf-8') as f:
    json.dump(datos, f, indent=2, ensure_ascii=False)

print(f"✓ Total de códigos únicos: {len(codigos_ordenados)}")
print(f"✓ Archivos generados:")
print(f"  - TODOS_LOS_CODIGOS.md")
print(f"  - codigos_existentes.json")
