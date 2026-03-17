import pdfplumber
import json
import re

def extract_quote_data(pdf_path, output_path):
    print(f"Opening {pdf_path}...")
    try:
        with pdfplumber.open(pdf_path) as pdf:
            page = pdf.pages[0]
            
            # Map of annotation Key (T) to Value (V)
            # We must be careful as some keys might be duplicated or encoded
            data_map = {}
            if page.annots:
                for a in page.annots:
                    data = a.get('data', {})
                    key = data.get('T')
                    val = data.get('V')
                    
                    if isinstance(key, bytes):
                        try:
                            key = key.decode('utf-8', errors='ignore')
                        except:
                            pass
                    if isinstance(val, bytes):
                        try:
                            val = val.decode('utf-8', errors='ignore')
                        except:
                            pass
                    
                    if key:
                        # Normalize key if needed
                        if key not in data_map:
                             data_map[key] = val
                        else:
                            # If duplicate key, we might need a list or careful handling
                            # For now, simplest approach: store as list if duplicate
                            if not isinstance(data_map[key], list):
                                data_map[key] = [data_map[key]]
                            data_map[key].append(val)

            # --- Extract Static Fields ---
            extracted = {
                "document_type": "Commercial Auto Quote Sheet",
                "agency_info": {
                     # These are likely static text, not form fields in this specific PDF, 
                     # or we'd need to extract by text parsing if they change. 
                     # For now, we keep them static or could extract if they were fields.
                    "address": "2001 Timberloch Place Suite 500, The Woodlands, TX 77380",
                    "direct_line": "281-895-1799 - 281-809-0112 Ext 113",
                    "email": "Quotes@h2oins.com"
                },
                "applicant_info": {
                    "owners_name": get_val(data_map, '1'),
                    "business_name": get_val(data_map, '2'),
                    "phone": get_val(data_map, '3'),
                    "fax": get_val(data_map, '4'),
                    "dba": get_val(data_map, '5'),
                    "mailing_address": get_val(data_map, '6'),
                    "email": get_val(data_map, '7'),
                    "physical_address": get_val(data_map, '8'),
                    "usdot": get_val(data_map, '9'),
                    "txdot": get_val(data_map, '10'),
                    "mc": get_val(data_map, '11'),
                    "current_carrier": get_val(data_map, '12'),
                    "years_continuous_coverage": get_val(data_map, '13'),
                    "destinations": get_val(data_map, '14'),
                    "exp_date": get_val(data_map, '15'),
                    "policy_number": get_val(data_map, '16'),
                    "commodities": get_val(data_map, '17'),
                    "years_in_business": get_val(data_map, '18'),
                },
                "driver_information": [],
                "vehicles": {
                    "tractors_trucks_pickup": [],
                    "trailers": []
                },
                "coverages": {
                     # Coverage parsing can be tricky with checkboxes; simplified for now
                     "auto_liability_limits": get_val(data_map, '214'), # Check ID in future
                     "cargo_limit": None 
                }
            }

            # --- Dynamic Driver Extraction ---
            # Drivers start at 19, block size 11
            # 19: Name, 20: DOB, 21: DOH, 22: Age, 23: DL, 24: State, 25: Class, 26: Exp, 27: Acc, 28: Vio, 29: Excl
            base_driver_id = 19
            driver_block_size = 11
            
            while True:
                name_id = str(base_driver_id)
                if name_id not in data_map or not get_val(data_map, name_id):
                    # Check next one just in case of gap or if first one is empty
                    # stricter check: if Name is empty, assume end of list
                    break
                
                driver = {
                    "name": get_val(data_map, str(base_driver_id)),
                    "dob": get_val(data_map, str(base_driver_id + 1)),
                    "doh": get_val(data_map, str(base_driver_id + 2)),
                    "age": get_val(data_map, str(base_driver_id + 3)),
                    "dl_number": get_val(data_map, str(base_driver_id + 4)),
                    "state": get_val(data_map, str(base_driver_id + 5)),
                    "class": get_val(data_map, str(base_driver_id + 6)),
                    "exp_years": get_val(data_map, str(base_driver_id + 7)),
                    "accidents": get_val(data_map, str(base_driver_id + 8)),
                    "violations": get_val(data_map, str(base_driver_id + 9)),
                    "excluded": get_val(data_map, str(base_driver_id + 10))
                }
                extracted["driver_information"].append(driver)
                base_driver_id += driver_block_size

            # --- Dynamic Vehicle Extraction ---
            # Tractors start at 74, block size 6 (approx)
            # 74: Year, 75: Make, 76: VIN, 77: Type?? (Log said Type was '0', need to handle carefully), 78: GVW, 79: Value
            # Warning: 'Type' field might have key '0'. If so, we need to grab the n-th '0' key if stored in list
            
            # Helper to consume '0' keys if they are stored as list
            type_vals = data_map.get('0', [])
            if not isinstance(type_vals, list):
                type_vals = [type_vals] if type_vals else []
            type_idx = 0

            base_vehicle_id = 74
            vehicle_block_size = 7 # 74,75,76,77(skip?),0(Type),78,79 ?? Check IDs carefully
            # Actually inspecting log: 74, 75, 76, 78, 79. Type (0) is in between?
            # IDs seen: 74, 75, 76. Then 78, 79.
            # So 77 is missing or is the '0'.
            
            # Let's assume indices iterate.
            while True:
                year_id = str(base_vehicle_id)
                if year_id not in data_map or not get_val(data_map, year_id):
                    break
                
                # Try to get Type from the '0' list if available, else generic
                veh_type = "Unknown"
                if type_idx < len(type_vals):
                    veh_type = type_vals[type_idx]
                    type_idx += 1
                
                vehicle = {
                    "year": get_val(data_map, str(base_vehicle_id)),
                    "make": get_val(data_map, str(base_vehicle_id + 1)),
                    "vin": get_val(data_map, str(base_vehicle_id + 2)),
                    "type": veh_type, 
                    "gvw": get_val(data_map, str(base_vehicle_id + 4)), # 78
                    "value": get_val(data_map, str(base_vehicle_id + 5)) # 79
                }
                extracted["vehicles"]["tractors_trucks_pickup"].append(vehicle)
                # Next vehicle?
                # If first was 74..79. Next is likely 80..85
                base_vehicle_id += 6 # Adjust step based on observed pattern

            # --- Trailers ---
            # Trailer IDs start around 106?
            # Log shows: 106 (VIN), 0 (Type).
            # It seems Trailer section might be different layout or just continued.
            # Need to find start of Trailer section. From log `106` is NON-OWNED TRAILER
            # This is likely the VIN field for the first trailer row.
            
            # Let's implement a search for the Trailer block
            # Assuming starts at 106 for VIN?
            # Wait, if 106 is VIN, where are Year/Make?
            # Maybe 104, 105?
            # Log shows 104: None, 105: None.
            
            base_trailer_id = 104 # Hypothetical start
            while True:
                # Check existance of VIN or Year
                # If 106 is VIN, let's look for it
                vin_id = str(base_trailer_id + 2)
                if str(base_trailer_id) not in data_map and vin_id not in data_map:
                     break
                
                # Check if we have data in this row
                has_data =  get_val(data_map, str(base_trailer_id)) or \
                            get_val(data_map, str(base_trailer_id+1)) or \
                            get_val(data_map, str(base_trailer_id+2))
                            
                if not has_data:
                     # Check if we are really done or just empty row
                     # verify with specific known ID context if possible
                     if base_trailer_id > 200: break # Safety break
                
                # Trailer type
                trailer_type = "Unknown"
                if type_idx < len(type_vals):
                    trailer_type = type_vals[type_idx]
                    type_idx += 1

                if has_data:
                    trailer = {
                        "year": get_val(data_map, str(base_trailer_id)),
                        "make": get_val(data_map, str(base_trailer_id + 1)),
                        "vin": get_val(data_map, str(base_trailer_id + 2)),
                        "type": trailer_type,
                        "gvw": get_val(data_map, str(base_trailer_id + 4)),
                        "value": get_val(data_map, str(base_trailer_id + 5))
                    }
                    extracted["vehicles"]["trailers"].append(trailer)
                
                base_trailer_id += 6

            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(extracted, f, indent=4)
            print(f"Extraction complete. Saved to {output_path}")

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

def get_val(data_map, key):
    val = data_map.get(key)
    if isinstance(val, list):
        return val[0] if val else None
    return val

if __name__ == "__main__":
    pdf_file = "20260126 BLUE QUOTE.pdf"
    output_json = "extracted_quote_auto.json"
    extract_quote_data(pdf_file, output_json)
