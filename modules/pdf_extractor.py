"""
PDF Extractor Module

Extracts structured data from Blue Quote commercial auto insurance PDFs.
"""

import pdfplumber
import json
from typing import Dict, List, Optional, Any
from pathlib import Path


class BlueQuotePDFExtractor:
    """Extractor for Blue Quote PDF forms."""
    
    def __init__(self, pdf_path: str):
        """
        Initialize extractor.
        
        Args:
            pdf_path: Path to PDF file
        """
        self.pdf_path = Path(pdf_path)
        if not self.pdf_path.exists():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")
        
        self.data_map = {}
        self.type_vals = []
    
    def _load_pdf_annotations(self) -> Dict[str, Any]:
        """Load PDF form annotations into a dictionary."""
        data_map = {}
        
        with pdfplumber.open(self.pdf_path) as pdf:
            page = pdf.pages[0]
            
            if page.annots:
                for a in page.annots:
                    data = a.get('data', {})
                    key = data.get('T')
                    val = data.get('V')
                    
                    # Decode bytes if necessary
                    if isinstance(key, bytes):
                        try:
                            key = key.decode('utf-8')
                        except:
                            key = key.decode('latin-1', errors='ignore')
                    
                    if isinstance(val, bytes):
                        try:
                            val = val.decode('utf-8')
                        except:
                            val = val.decode('latin-1', errors='ignore')
                    
                    if key:
                        # Handle duplicate keys
                        if key not in data_map:
                            data_map[key] = val
                        else:
                            if not isinstance(data_map[key], list):
                                data_map[key] = [data_map[key]]
                            data_map[key].append(val)
        
        return data_map
    
    @staticmethod
    def _get_val(data_map: Dict, key: str, alt_keys: List[str] = None) -> Optional[str]:
        """Get value from data map, handling lists and trying alternative keys."""
        # Try primary key first
        val = data_map.get(key)
        if isinstance(val, list):
            val = val[0] if val else None
        
        # If not found and alt_keys provided, try alternatives
        if val is None and alt_keys:
            for alt in alt_keys:
                # Try exact match
                if alt in data_map:
                    val = data_map.get(alt)
                    break
                # Try partial match (for field names)
                for k, v in data_map.items():
                    if alt.lower() in str(k).lower():
                        val = v
                        break
                if val:
                    break
        
        if isinstance(val, list):
            return val[0] if val else None
        return val
    
    @staticmethod
    def _get_checkbox_group(data_map: Dict, mapping: Dict[str, str]) -> Optional[str]:
        """Get the value of the first checked checkbox from a group."""
        for key, output_val in mapping.items():
            val = BlueQuotePDFExtractor._get_val(data_map, key)
            if val:
                v_str = str(val)
                if '/Off' not in v_str and 'Off' != v_str:
                    return output_val
        return None
    
    @staticmethod
    def _get_checkbox_bool(data_map: Dict, key: str) -> bool:
        """Check if a boolean checkbox is checked."""
        val = BlueQuotePDFExtractor._get_val(data_map, key)
        if not val:
            return False
        v_str = str(val)
        return '/Off' not in v_str and 'Off' != v_str
    
    def extract(self) -> Dict:
        """
        Extract all data from the PDF.
        
        Returns:
            Dictionary with structured quote data
        """
        # Load annotations
        self.data_map = self._load_pdf_annotations()
        
        # Check if we have form data, if not try text extraction
        if not self.data_map or not self._get_val(self.data_map, '2', ['Business Name', 'business']):
            print("⚠️  No form fields found - attempting text extraction fallback")
            return self._extract_text_fallback()
        
        # Process type values for vehicles
        type_vals = self.data_map.get('0', [])
        if not isinstance(type_vals, list):
            type_vals = [type_vals] if type_vals else []
        self.type_vals = type_vals
        type_idx = 0
        
        # Extract data
        extracted = {
            "document_type": "Commercial Auto Quote Sheet",
            "agency_info": {
                "address": "2001 Timberloch Place Suite 500, The Woodlands, TX 77380",
                "direct_line": "281-895-1799 - 281-809-0112 Ext 113",
                "email": "Quotes@h2oins.com"
            },
            "applicant_info": self._extract_applicant_info(),
            "driver_information": self._extract_drivers(),
            "vehicles": {
                "tractors_trucks_pickup": self._extract_vehicles(type_vals),
                "trailers": self._extract_trailers(type_vals, len(self._extract_vehicles(type_vals)))
            },
            "coverages": self._extract_coverages()
        }
        
        return extracted

    def _extract_text_fallback(self) -> Dict:
        """Extract data from plain text using regex (fallback for flattened PDFs)."""
        import re
        
        text = ""
        with pdfplumber.open(self.pdf_path) as pdf:
            if pdf.pages:
                text = pdf.pages[0].extract_text() or ""
        
        # Helper to extract by regex
        def get_text_val(pattern: str, content: str) -> Optional[str]:
            match = re.search(pattern, content, re.IGNORECASE | re.DOTALL)
            if match:
                return match.group(1).strip().strip('_')
            return None

        # Regex patterns based on debug output
        business = get_text_val(r"Business Name:\s*(.*?)(?:_+$|\n|Phone:)", text)
        commodity = get_text_val(r"Commodities:\s*(.*?)(?:Years in business:|_+$|\n)", text)
        usdot = get_text_val(r"USDOT#:\s*(\d+)", text)
        email = get_text_val(r"Email:\s*([^\s\n]+)", text)
        
        return {
            "document_type": "Commercial Auto Quote Sheet (Text Extract)",
            "applicant_info": {
                "business_name": business,
                "commodities": commodity,
                "usdot": usdot,
                "email": email,
                "owners_name": get_text_val(r"Owners Name:\s*(.*?)(?:Business Name:)", text),
                "phone": get_text_val(r"Phone:\s*([\d-]+)", text),
            },
            "driver_information": [], # Placeholder - table extraction needed for full support
            "vehicles": {
                "tractors_trucks_pickup": [],
                "trailers": []
            },
            "coverages": {} # Placeholder
        }
    
    def _extract_applicant_info(self) -> Dict:
        """Extract applicant information with fallback field names."""
        return {
            "owners_name": self._get_val(self.data_map, '1', ['owner', 'Owner Name', 'owners_name']),
            "business_name": self._get_val(self.data_map, '2', ['Business Name', 'business', 'company', 'Business Legal Name']),
            "phone": self._get_val(self.data_map, '3', ['phone', 'Phone', 'telephone']),
            "fax": self._get_val(self.data_map, '4', ['fax', 'Fax']),
            "dba": self._get_val(self.data_map, '5', ['dba', 'DBA']),
            "mailing_address": self._get_val(self.data_map, '6', ['mailing', 'Mailing Address']),
            "email": self._get_val(self.data_map, '7', ['email', 'Email', 'e-mail']),
            "physical_address": self._get_val(self.data_map, '8', ['physical', 'Physical Address', 'address']),
            "usdot": self._get_val(self.data_map, '9', ['usdot', 'USDOT', 'US DOT', 'DOT']),
            "txdot": self._get_val(self.data_map, '10', ['txdot', 'TXDOT', 'TX DOT']),
            "mc": self._get_val(self.data_map, '11', ['mc', 'MC', 'MC#']),
            "current_carrier": self._get_val(self.data_map, '12', ['carrier', 'Current Carrier']),
            "years_continuous_coverage": self._get_val(self.data_map, '13', ['years', 'coverage']),
            "destinations": self._get_val(self.data_map, '14', ['destination', 'Destinations']),
            "exp_date": self._get_val(self.data_map, '15', ['exp', 'Exp Date', 'expiration']),
            "policy_number": self._get_val(self.data_map, '16', ['policy', 'Policy Number', 'Policy#']),
            "commodities": self._get_val(self.data_map, '17', ['commodit', 'Commodities', 'Commodity', 'cargo']),
            "years_in_business": self._get_val(self.data_map, '18', ['years in business', 'years_business']),
        }
    
    def _extract_drivers(self) -> List[Dict]:
        """Extract driver information dynamically."""
        drivers = []
        base_driver_id = 19
        driver_block_size = 11
        
        while True:
            name_id = str(base_driver_id)
            if name_id not in self.data_map or not self._get_val(self.data_map, name_id):
                break
            
            driver = {
                "name": self._get_val(self.data_map, str(base_driver_id)),
                "dob": self._get_val(self.data_map, str(base_driver_id + 1)),
                "doh": self._get_val(self.data_map, str(base_driver_id + 2)),
                "age": self._get_val(self.data_map, str(base_driver_id + 3)),
                "dl_number": self._get_val(self.data_map, str(base_driver_id + 4)),
                "state": self._get_val(self.data_map, str(base_driver_id + 5)),
                "class": self._get_val(self.data_map, str(base_driver_id + 6)),
                "exp_years": self._get_val(self.data_map, str(base_driver_id + 7)),
                "accidents": self._get_val(self.data_map, str(base_driver_id + 8)),
                "violations": self._get_val(self.data_map, str(base_driver_id + 9)),
                "excluded": self._get_val(self.data_map, str(base_driver_id + 10))
            }
            drivers.append(driver)
            base_driver_id += driver_block_size
        
        return drivers
    
    def _extract_vehicles(self, type_vals: List) -> List[Dict]:
        """Extract tractor/truck information."""
        vehicles = []
        base_vehicle_id = 74
        type_idx = 0
        
        while True:
            year_id = str(base_vehicle_id)
            if year_id not in self.data_map or not self._get_val(self.data_map, year_id):
                break
            
            veh_type = "Unknown"
            if type_idx < len(type_vals):
                veh_type = type_vals[type_idx]
                type_idx += 1
            
            vehicle = {
                "year": self._get_val(self.data_map, str(base_vehicle_id)),
                "make": self._get_val(self.data_map, str(base_vehicle_id + 1)),
                "vin": self._get_val(self.data_map, str(base_vehicle_id + 2)),
                "type": veh_type,
                "gvw": self._get_val(self.data_map, str(base_vehicle_id + 4)),
                "value": self._get_val(self.data_map, str(base_vehicle_id + 5))
            }
            vehicles.append(vehicle)
            base_vehicle_id += 6
        
        # Store type_idx for trailers
        self._vehicle_type_idx = type_idx
        return vehicles
    
    def _extract_trailers(self, type_vals: List, vehicle_count: int) -> List[Dict]:
        """Extract trailer information."""
        trailers = []
        base_trailer_id = 104
        type_idx = getattr(self, '_vehicle_type_idx', vehicle_count)
        
        while True:
            vin_id = str(base_trailer_id + 2)
            if str(base_trailer_id) not in self.data_map and vin_id not in self.data_map:
                break
            
            has_data = (self._get_val(self.data_map, str(base_trailer_id)) or
                       self._get_val(self.data_map, str(base_trailer_id + 1)) or
                       self._get_val(self.data_map, str(base_trailer_id + 2)))
            
            if not has_data:
                break
            
            trailer_type = "Unknown"
            if type_idx < len(type_vals):
                trailer_type = type_vals[type_idx]
                type_idx += 1
            
            trailer = {
                "year": self._get_val(self.data_map, str(base_trailer_id)),
                "make": self._get_val(self.data_map, str(base_trailer_id + 1)),
                "vin": self._get_val(self.data_map, str(base_trailer_id + 2)),
                "type": trailer_type,
                "gvw": self._get_val(self.data_map, str(base_trailer_id + 4)),
                "value": self._get_val(self.data_map, str(base_trailer_id + 5))
            }
            
            if trailer["vin"] or trailer["make"] or trailer["year"]:
                trailers.append(trailer)
            
            base_trailer_id += 6
        
        return trailers
    
    def _extract_coverages(self) -> Dict:
        """Extract coverage information."""
        return {
            "radius_of_operation": self._get_checkbox_group(self.data_map, {
                '134': '0-100', '135': '101-200', '136': '201-300',
                '137': '301-500', '138': 'Unlimited'
            }),
            "auto_liability_limits": self._get_checkbox_group(self.data_map, {
                '139': '$500K CSL', '140': '$750K CSL', '141': '$1M CSL', '142': 'Others'
            }),
            "general_liability": self._get_checkbox_group(self.data_map, {
                '148': '1,000,000', '149': '2,000,000'
            }),
            "physical_damage_deductible": self._get_checkbox_group(self.data_map, {
                '151': '1,000', '152': '2,500'
            }),
            "cargo_limit": self._get_checkbox_group(self.data_map, {
                '153': '$100,000', '154': '$250,000', '155': 'Others'
            }),
            "refrigeration_breakdown": self._get_checkbox_bool(self.data_map, '158'),
            "pip_med": self._get_checkbox_bool(self.data_map, '144'),
            "um_uim": self._get_checkbox_bool(self.data_map, '146'),
            "non_trucking_liability_limit": self._get_val(self.data_map, '150'),
            "trailer_interchange_limit": self._get_val(self.data_map, '159'),
            "additional_coverages": self._get_val(self.data_map, '160'),
            "cargo_limit_other": self._get_val(self.data_map, '156')
        }


# Convenience function for simple use cases
def extract_quote_data(pdf_path: str, output_path: Optional[str] = None) -> Dict:
    """
    Extract quote data from PDF and optionally save to JSON.
    
    Args:
        pdf_path: Path to PDF file
        output_path: Optional path to save JSON output
        
    Returns:
        Extracted data dictionary
    """
    extractor = BlueQuotePDFExtractor(pdf_path)
    data = extractor.extract()
    
    if output_path:
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        print(f"Extraction complete. Saved to {output_path}")
    
    return data
