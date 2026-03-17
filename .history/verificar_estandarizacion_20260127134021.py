import pandas as pd
import json

# Leer el archivo estandarizado
df = pd.read_excel('CHECK LIST (2)_ESTANDARIZADO.xlsx', sheet_name='MGA')

print("="*100)
print("VERIFICACIÓN DE ARCHIVO ESTANDARIZADO")
print("="*100)
print()

# Información general
print("1. INFORMACIÓN GENERAL:")
print(f"   - Total de filas: {len(df)}")
print(f"   - Columnas: {', '.join(df.columns.tolist())}")
print()

# Estadísticas de reglas
print("2. ESTADÍSTICAS DE REGLAS ESTANDARIZADAS:")
total_con_reglas = df['REGLA_ESTANDARIZADA'].astype(bool).sum()
total_sin_reglas = len(df) - total_con_reglas
print(f"   - Filas con reglas: {total_con_reglas}")
print(f"   - Filas sin reglas (vacías o '-'): {total_sin_reglas}")
print()

# Análisis de códigos más frecuentes
print("3. CÓDIGOS MÁS FRECUENTES:")
all_codes = []
for regla in df['REGLA_ESTANDARIZADA'].dropna():
    if regla:
        codes = str(regla).split('|')
        all_codes.extend(codes)

from collections import Counter
code_freq = Counter(all_codes)
print()
for code, freq in code_freq.most_common(15):
    print(f"   {code}: {freq} veces")
print()

# Mostrar ejemplos de cada categoria
print("="*100)
print("4. EJEMPLOS DE TRANSFORMACIÓN POR TIPO DE NEGOCIO:")
print("="*100)
print()

# Agrupar por tipo de negocio
tipos_negocio = df['TIPO DE NEGOCIO'].unique()

for tipo in tipos_negocio[:5]:  # Primeros 5 tipos
    if pd.notna(tipo):
        df_tipo = df[(df['TIPO DE NEGOCIO'] == tipo) & (df['REGLA_ESTANDARIZADA'].astype(bool))]
        if len(df_tipo) > 0:
            print(f"TIPO: {tipo}")
            print("-" * 100)
            
            ejemplo = df_tipo.iloc[0]
            print(f"  MGA: {ejemplo['MGA']}")
            print(f"  NEW VENTURE: {ejemplo['NEW VENTURE']}")
            print(f"  COMENTARIO ORIGINAL:")
            print(f"    {ejemplo['COMENTARIOS']}")
            print(f"  REGLA ESTANDARIZADA:")
            print(f"    {ejemplo['REGLA_ESTANDARIZADA']}")
            print()

# Leer mapeo
with open('mapeo_reglas.json', 'r', encoding='utf-8') as f:
    mapeo = json.load(f)

print("="*100)
print(f"5. DICCIONARIO DE MAPEO: {len(mapeo)} reglas únicas mapeadas")
print("="*100)
print()

# Guardar reporte
with open('REPORTE_VERIFICACION.txt', 'w', encoding='utf-8') as f:
    f.write("="*100 + "\n")
    f.write("REPORTE DE VERIFICACIÓN - ESTANDARIZACIÓN DE REGLAS DE NEGOCIO\n")
    f.write("="*100 + "\n\n")
    
    f.write(f"Archivo generado: CHECK LIST (2)_ESTANDARIZADO.xlsx\n")
    f.write(f"Total de filas procesadas: {len(df)}\n")
    f.write(f"Filas con reglas estandarizadas: {total_con_reglas}\n")
    f.write(f"Filas sin reglas: {total_sin_reglas}\n\n")
    
    f.write("Columnas del archivo:\n")
    for col in df.columns:
        f.write(f"  - {col}\n")
    f.write("\n")
    
    f.write("Códigos de reglas más frecuentes:\n")
    for code, freq in code_freq.most_common(20):
        f.write(f"  {code}: {freq} veces\n")

print("✓ Reporte guardado en: REPORTE_VERIFICACION.txt")
print()
print("="*100)
print("✓ VERIFICACIÓN COMPLETADA")
print("="*100)
