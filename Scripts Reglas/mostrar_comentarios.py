import pandas as pd

# Leer el CSV con los comentarios
df_comentarios = pd.read_csv('comentarios_con_frecuencia.csv', encoding='utf-8-sig')

# Mostrar todos los comentarios
print("="*100)
print(f"TOTAL DE COMENTARIOS ÚNICOS: {len(df_comentarios)}")
print("="*100)
print()

for idx, row in df_comentarios.iterrows():
    print(f"{idx+1:2d}. [{row['FRECUENCIA']:3d} vez/veces] {row['COMENTARIO']}")

print()
print("="*100)
