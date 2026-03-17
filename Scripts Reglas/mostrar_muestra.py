import pandas as pd

# Leer el archivo estandarizado
df = pd.read_excel('CHECK LIST (2)_ESTANDARIZADO.xlsx', sheet_name='MGA')

print("="*120)
print("MUESTRA DE RESULTADOS - ARCHIVO ESTANDARIZADO")
print("="*120)
print()

# Mostrar primeros 20 registros con comentarios
df_con_comentarios = df[df['COMENTARIOS'].notna() & (df['COMENTARIOS'] != '-')].head(20)

for idx, row in df_con_comentarios.iterrows():
    print(f"═══ FILA {idx + 2} ═══════════════════════════════════════════════════════════════════════════")
    print(f"TIPO DE NEGOCIO: {row['TIPO DE NEGOCIO']}")
    print(f"MGA: {row['MGA']}")
    print(f"NEW VENTURE: {row['NEW VENTURE']}")
    print()
    print(f"COMENTARIO ORIGINAL:")
    print(f"  {row['COMENTARIOS']}")
    print()
    print(f"REGLA ESTANDARIZADA:")
    print(f"  {row['REGLA_ESTANDARIZADA']}")
    print()

print("="*120)
print("FIN DE LA MUESTRA")
print("="*120)
