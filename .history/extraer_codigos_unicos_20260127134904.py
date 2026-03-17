import pandas as pd
from collections import Counter

# Leer el archivo estandarizado
df = pd.read_excel('CHECK LIST (2)_ESTANDARIZADO.xlsx', sheet_name='MGA')

# Extraer todos los códigos únicos
todos_los_codigos = []
for regla in df['REGLA_ESTANDARIZADA'].dropna():
    if regla and regla != '':
        codigos = str(regla).split('|')
        todos_los_codigos.extend(codigos)

# Contar frecuencia
frecuencia_codigos = Counter(todos_los_codigos)

print("="*100)
print(f"LISTA COMPLETA DE CÓDIGOS ESTANDARIZADOS ({len(frecuencia_codigos)} códigos únicos)")
print("="*100)
print()

# Organizar por categoría
categorias = {
    "EXPERIENCIA Y DOCUMENTACIÓN": [],
    "REQUISITOS DEL NEGOCIO": [],
    "COBERTURAS": [],
    "RESTRICCIONES (NO_)": [],
    "REQUISITOS FINANCIEROS": [],
    "FORMULARIOS Y APLICACIONES": [],
    "TIPOS DE TRAILER": [],
    "CONDICIONES ESPECIALES": [],
    "COMPAÑÍAS": [],
    "OTROS": []
}

for codigo, freq in sorted(frecuencia_codigos.items(), key=lambda x: x[1], reverse=True):
    # Categorizar
    if codigo.startswith(('CDL_', 'MVR', 'PERDIDAS_', 'IFTAS_', 'EIN_', 'REGISTRACIONES')):
        categorias["EXPERIENCIA Y DOCUMENTACIÓN"].append((codigo, freq))
    elif codigo.startswith(('BUSINESS_YEARS_', 'MIN_UNITS_', 'SOLO_NICO', 'NV_', 'POLIZA_')):
        categorias["REQUISITOS DEL NEGOCIO"].append((codigo, freq))
    elif codigo.startswith('COVERAGE_'):
        categorias["COBERTURAS"].append((codigo, freq))
    elif codigo.startswith('NO_'):
        categorias["RESTRICCIONES (NO_)"].append((codigo, freq))
    elif codigo.startswith(('DOWN_', 'MIN_PRICE_', 'SURCHARGE_')):
        categorias["REQUISITOS FINANCIEROS"].append((codigo, freq))
    elif codigo.startswith(('APP_', 'PREGUNTAS_', 'FORM_')):
        categorias["FORMULARIOS Y APLICACIONES"].append((codigo, freq))
    elif codigo.startswith('TRAILER_'):
        categorias["TIPOS DE TRAILER"].append((codigo, freq))
    elif codigo.startswith('COMPANY_'):
        categorias["COMPAÑÍAS"].append((codigo, freq))
    elif codigo.startswith(('ACEPTA_', 'OWNER_', 'INDUSTRY_', 'LICENSE_', 'CONTRATO_', 'SIN_', 'SOLO_', 'TEST_', 'CONDADOS_', 'CUSTOM_')):
        categorias["CONDICIONES ESPECIALES"].append((codigo, freq))
    else:
        categorias["OTROS"].append((codigo, freq))

# Mostrar por categoría
for categoria, codigos in categorias.items():
    if codigos:
        print(f"\n{'═' * 100}")
        print(f"📌 {categoria} ({len(codigos)} códigos)")
        print('═' * 100)
        for codigo, freq in sorted(codigos, key=lambda x: x[1], reverse=True):
            print(f"   {codigo:<40} →  {freq:3d} veces")

print("\n" + "="*100)
print("RESUMEN DE TODOS LOS CÓDIGOS (alfabéticamente)")
print("="*100)
for codigo in sorted(frecuencia_codigos.keys()):
    freq = frecuencia_codigos[codigo]
    print(f"   {codigo:<40} →  {freq:3d} veces")

print("\n" + "="*100)
print(f"TOTAL: {len(frecuencia_codigos)} códigos únicos utilizados")
print("="*100)

# Guardar en archivo
with open('LISTA_COMPLETA_CODIGOS.txt', 'w', encoding='utf-8') as f:
    f.write("LISTA COMPLETA DE CÓDIGOS ESTANDARIZADOS\n")
    f.write("="*100 + "\n\n")
    f.write(f"Total de códigos únicos: {len(frecuencia_codigos)}\n\n")
    
    for categoria, codigos in categorias.items():
        if codigos:
            f.write(f"\n{categoria} ({len(codigos)} códigos)\n")
            f.write('-' * 100 + '\n')
            for codigo, freq in sorted(codigos, key=lambda x: x[1], reverse=True):
                f.write(f"  {codigo:<40} →  {freq:3d} veces\n")
    
    f.write("\n" + "="*100 + "\n")
    f.write("LISTA ALFABÉTICA COMPLETA:\n")
    f.write("="*100 + "\n")
    for codigo in sorted(frecuencia_codigos.keys()):
        f.write(f"  {codigo}\n")

print("\n✓ Lista guardada en: LISTA_COMPLETA_CODIGOS.txt")
