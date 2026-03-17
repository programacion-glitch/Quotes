import pandas as pd
from collections import Counter

# Leer el archivo estandarizado
df = pd.read_excel('CHECK LIST (2)_ESTANDARIZADO.xlsx', sheet_name='MGA')

# Extraer todos los códigos únicos
todos_los_codigos = set()
for regla in df['REGLA_ESTANDARIZADA'].dropna():
    if regla and regla != '':
        codigos = str(regla).split('|')
        todos_los_codigos.update(codigos)

# Contar frecuencia
frecuencia_codigos = Counter()
for regla in df['REGLA_ESTANDARIZADA'].dropna():
    if regla and regla != '':
        codigos = str(regla).split('|')
        frecuencia_codigos.update(codigos)

# Ordenar alfabéticamente
codigos_ordenados = sorted(todos_los_codigos)

print("CÓDIGOS ÚNICOS EXISTENTES EN EL ARCHIVO")
print("="*80)
print(f"Total: {len(codigos_ordenados)} códigos únicos\n")

for i, codigo in enumerate(codigos_ordenados, 1):
    freq = frecuencia_codigos[codigo]
    print(f"{i:2d}. {codigo:<45} ({freq:3d} veces)")

print("\n" + "="*80)
