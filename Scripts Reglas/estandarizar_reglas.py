import pandas as pd
import re
import json

def estandarizar_comentario(comentario):
    """
    Convierte un comentario de texto libre a formato de código estandarizado.
    """
    if pd.isna(comentario) or comentario == '-':
        return ''
    
    comentario_str = str(comentario).strip()
    reglas = []
    
    # 1. CDL con años de experiencia
    cdl_match = re.search(r'CDL.*?(\d+)\s*año[s]?\s*de\s*experiencia', comentario_str, re.IGNORECASE)
    if cdl_match:
        years = cdl_match.group(1)
        reglas.append(f'CDL_YEARS_{years}')
    elif 'CDL' in comentario_str.upper():
        reglas.append('CDL_REQUIRED')
    
    # 2. MVR
    mvr_match = re.search(r'MVR\s*de\s*(\d+)\s*año[s]?', comentario_str, re.IGNORECASE)
    if mvr_match:
        years = mvr_match.group(1)
        reglas.append(f'MVR_YEARS_{years}')
    elif 'MVR' in comentario_str.upper():
        reglas.append('MVR')
    
    # 3. Pérdidas
    if re.search(r'pérdidas\s*limpias', comentario_str, re.IGNORECASE):
        reglas.append('PERDIDAS_LIMPIAS')
    elif re.search(r'(\d+)\s*años\s*de\s*pérdidas', comentario_str, re.IGNORECASE):
        years_match = re.search(r'(\d+)\s*años\s*de\s*pérdidas', comentario_str, re.IGNORECASE)
        reglas.append(f'PERDIDAS_{years_match.group(1)}_AÑOS')
    elif re.search(r'pérdidas\s*\(', comentario_str, re.IGNORECASE) or 'pérdidas' in comentario_str.lower():
        reglas.append('PERDIDAS_SI_APLICA')
    
    # 4. IFTAS
    if 'IFTAS' in comentario_str.upper():
        reglas.append('IFTAS_SI_APLICA')
    
    # 5. EIN
    if 'EIN' in comentario_str.upper():
        reglas.append('EIN_REQUIRED')
    
    # 6. Registraciones
    if re.search(r'registracion(es)?', comentario_str, re.IGNORECASE):
        reglas.append('REGISTRACIONES')
    
    # 7. Años en el negocio
    business_years = re.search(r'(\d+)\+?\s*año[s]?\s*en\s*el\s*negocio', comentario_str, re.IGNORECASE)
    if business_years:
        years = business_years.group(1)
        reglas.append(f'BUSINESS_YEARS_{years}+')
    
    # 8. Unidades mínimas
    min_units = re.search(r'[Mm]in\s*(\d+)\s*unidad(es)?', comentario_str, re.IGNORECASE)
    if min_units:
        units = min_units.group(1)
        reglas.append(f'MIN_UNITS_{units}')
    elif re.search(r'(\d+)\+\s*unidad(es)?', comentario_str, re.IGNORECASE):
        units_match = re.search(r'(\d+)\+\s*unidad(es)?', comentario_str, re.IGNORECASE)
        reglas.append(f'MIN_UNITS_{units_match.group(1)}')
    
    # 9. Solo NICO
    if re.search(r'[Ss]olo\s*(con\s*)?NICO', comentario_str):
        reglas.append('SOLO_NICO')
    
    # 10. New Venture
    if 'NV' in comentario_str and not 'NV-' in comentario_str:
        if 'solo' in comentario_str.lower() and 'nico' in comentario_str.lower():
            reglas.append('NV_SOLO_NICO')
        else:
            reglas.append('NV_SPECIAL_REQUIREMENTS')
    
    # 11. Coberturas específicas
    if re.search(r'[Ss]olo\s*para\s*coberturas\s*como\s*(APD|MTC|GL)', comentario_str):
        coverage_match = re.findall(r'(APD|MTC|GL)', comentario_str.upper())
        if coverage_match:
            reglas.append(f'COVERAGE_{",".join(set(coverage_match))}')
    elif 'Solo AL' in comentario_str:
        reglas.append('COVERAGE_AL')
    elif 'Solo DUAL' in comentario_str or 'DUAL' in comentario_str:
        reglas.append('COVERAGE_DUAL')
    
    # 12. Down payment
    down_match = re.search(r'[Dd]own\s*del\s*(\d+)%', comentario_str)
    if down_match:
        percent = down_match.group(1)
        reglas.append(f'DOWN_{percent}%')
    
    # 13. Precio mínimo
    price_match = re.search(r'precios\s*empiezan\s*sobre\s*\$(\d+)K', comentario_str, re.IGNORECASE)
    if price_match:
        price = price_match.group(1)
        reglas.append(f'MIN_PRICE_{price}K')
    
    # 14. Aplicación/Formularios
    if re.search(r'[Dd]iligenciar\s*apps?\s*(y\s*preguntas)?', comentario_str):
        reglas.append('APP_DILIGENCIADA')
        if 'preguntas' in comentario_str.lower():
            reglas.append('PREGUNTAS_REQUIRED')
    elif re.search(r'[Ll]lenar\s*(app|formulario)', comentario_str):
        reglas.append('APP_DILIGENCIADA')
    
    # 15. Preguntas específicas
    if 'Auto Hauler' in comentario_str:
        reglas.append('PREGUNTAS_AUTO_HAULER')
    if 'UIIA' in comentario_str:
        reglas.append('PREGUNTAS_UIIA')
    
    # 16. Formularios específicos
    form_match = re.search(r'FORM\s*(\w+)', comentario_str, re.IGNORECASE)
    if form_match:
        form_id = form_match.group(1)
        reglas.append(f'FORM_{form_id}')
    
    # 17. Restricciones NO
    if re.search(r'[Nn]o\s*ir\s*al\s*botadero', comentario_str):
        reglas.append('NO_BOTADERO')
    if re.search(r'[Nn]o\s*dump', comentario_str):
        reglas.append('NO_DUMP')
    if 'NO REEFER' in comentario_str.upper():
        reglas.append('NO_REEFER')
    if 'No MTC' in comentario_str:
        reglas.append('NO_MTC')
    
    # 18. Solo tipos específicos
    if re.search(r'[Ss]olo\s*local', comentario_str):
        reglas.append('SOLO_LOCAL')
    if re.search(r'[Ss]olo.*[Tt]ruck.*[Tt]railer', comentario_str):
        reglas.append('SOLO_TRUCK_TRAILER')
    if re.search(r'[Ss]olo.*flotas', comentario_str):
        reglas.append('SOLO_FLOTAS')
    
    # 19. Tipos de trailer específicos
    if 'Lowboy' in comentario_str:
        reglas.append('TRAILER_LOWBOY')
    if 'End dump' in comentario_str or 'Enddump' in comentario_str:
        reglas.append('TRAILER_ENDDUMP')
    if 'Sandbox' in comentario_str or 'Sand box' in comentario_str:
        reglas.append('TRAILER_SANDBOX')
    if 'Dry Van' in comentario_str:
        reglas.append('TRAILER_DRY_VAN')
    
    # 20. Condiciones especiales
    if re.search(r'no\s*son\s*fertilizantes', comentario_str, re.IGNORECASE):
        reglas.append('NO_FERTILIZANTES')
    if re.search(r'acepta.*bosque', comentario_str, re.IGNORECASE):
        reglas.append('ACEPTA_BOSQUE')
    if re.search(r'vertedero', comentario_str, re.IGNORECASE):
        reglas.append('ACEPTA_VERTEDERO')
    if re.search(r'dueño.*min\s*30\s*años', comentario_str, re.IGNORECASE):
        reglas.append('OWNER_MIN_30_YEARS')
    if re.search(r'experiencia.*industria.*\+?3\s*años', comentario_str, re.IGNORECASE):
        reglas.append('INDUSTRY_EXP_3+')
    if 'póliza activa' in comentario_str.lower():
        reglas.append('POLIZA_ACTIVA')
    if re.search(r'licencia\s*de\s*TX', comentario_str, re.IGNORECASE):
        reglas.append('LICENSE_TX_REQUIRED')
    if 'contrato' in comentario_str.lower():
        reglas.append('CONTRATO_REQUIRED')
    if 'SIN RAMPA' in comentario_str.upper():
        reglas.append('SIN_RAMPA')
    if 'sobrecargo' in comentario_str.lower():
        surcharge_match = re.search(r'sobrecargo\s*del\s*(\d+)%', comentario_str, re.IGNORECASE)
        if surcharge_match:
            reglas.append(f'SURCHARGE_{surcharge_match.group(1)}%')
    
    # 21. Compañías específicas - Canal, Bulldog, One80
    if 'Canal' in comentario_str:
        reglas.append('COMPANY_CANAL')
    if 'Bulldog' in comentario_str:
        reglas.append('COMPANY_BULLDOG')
    if 'one80' in comentario_str.lower():
        reglas.append('COMPANY_ONE80')
    
    # 22. Test drive
    if 'test drive' in comentario_str.lower():
        reglas.append('TEST_DRIVE')
    
    # 23. Condados prohibidos
    if 'condados prohibidos' in comentario_str.lower():
        reglas.append('CONDADOS_PROHIBIDOS')
    
    # Si no se encontró ninguna regla específica pero hay contenido
    if not reglas and comentario_str and comentario_str != '-':
        reglas.append('CUSTOM_RULE')
    
    return '|'.join(reglas) if reglas else ''


def main():
    """
    Script principal para estandarizar las reglas de negocio.
    """
    print("="*100)
    print("ESTANDARIZACIÓN DE REGLAS DE NEGOCIO - HOJA MGA")
    print("="*100)
    print()
    
    # Leer el archivo Excel original
    print("1. Leyendo archivo Excel...")
    df = pd.read_excel(r'c:\Users\Desarrollo\Videos\Quotes\CHECK LIST (2).xlsb', 
                       sheet_name='MGA', 
                       engine='pyxlsb')
    
    print(f"   ✓ {len(df)} filas leídas")
    print(f"   ✓ Columnas: {', '.join(df.columns.tolist())}")
    print()
    
    # Crear diccionario de mapeo
    print("2. Creando diccionario de mapeo...")
    mapeo = {}
    comentarios_unicos = df['COMENTARIOS'].dropna().unique()
    
    for comentario in comentarios_unicos:
        if comentario != '-':
            codigo = estandarizar_comentario(comentario)
            mapeo[str(comentario)] = codigo
    
    # Guardar mapeo en JSON
    with open('mapeo_reglas.json', 'w', encoding='utf-8') as f:
        json.dump(mapeo, f, indent=2, ensure_ascii=False)
    
    print(f"   ✓ {len(mapeo)} reglas mapeadas")
    print(f"   ✓ Guardado en: mapeo_reglas.json")
    print()
    
    # Aplicar estandarización
    print("3. Aplicando estandarización...")
    df['REGLA_ESTANDARIZADA'] = df['COMENTARIOS'].apply(estandarizar_comentario)
    
    print(f"   ✓ Columna REGLA_ESTANDARIZADA agregada")
    print()
    
    # Mostrar estadísticas
    print("4. Estadísticas:")
    total_filas = len(df)
    con_reglas = df['REGLA_ESTANDARIZADA'].astype(bool).sum()
    sin_reglas = total_filas - con_reglas
    
    print(f"   - Total de filas: {total_filas}")
    print(f"   - Filas con reglas estandarizadas: {con_reglas}")
    print(f"   - Filas sin reglas (vacías o '-'): {sin_reglas}")
    print()
    
    # Guardar el archivo actualizado
    print("5. Guardando archivo actualizado...")
    
    # Guardar como XLSX (más compatible)
    output_file = 'CHECK LIST (2)_ESTANDARIZADO.xlsx'
    df.to_excel(output_file, sheet_name='MGA', index=False, engine='openpyxl')
    
    print(f"   ✓ Guardado como: {output_file}")
    print()
    
    # Crear archivo CSV adicional para fácil revisión
    csv_file = 'CHECK LIST_MGA_ESTANDARIZADO.csv'
    df.to_csv(csv_file, index=False, encoding='utf-8-sig')
    print(f"   ✓ Guardado también como: {csv_file}")
    print()
    
    # Mostrar ejemplos de transformación
    print("="*100)
    print("EJEMPLOS DE TRANSFORMACIÓN (primeros 10 con reglas):")
    print("="*100)
    print()
    
    df_con_reglas = df[df['REGLA_ESTANDARIZADA'].astype(bool)].head(10)
    for idx, row in df_con_reglas.iterrows():
        print(f"Fila {idx + 2}:")
        print(f"  TIPO DE NEGOCIO: {row['TIPO DE NEGOCIO']}")
        print(f"  MGA: {row['MGA']}")
        print(f"  COMENTARIO ORIGINAL: {row['COMENTARIOS']}")
        print(f"  REGLA ESTANDARIZADA: {row['REGLA_ESTANDARIZADA']}")
        print()
    
    print("="*100)
    print("✓ PROCESO COMPLETADO EXITOSAMENTE")
    print("="*100)
    print()
    print("Archivos generados:")
    print(f"  1. {output_file} - Archivo Excel con reglas estandarizadas")
    print(f"  2. {csv_file} - Versión CSV para revisión")
    print(f"  3. mapeo_reglas.json - Diccionario de mapeo de reglas")


if __name__ == "__main__":
    main()
