"""
Email Template Builder Module

Loads and formats email templates with dynamic data.
"""

from pathlib import Path
from typing import Dict, List


class EmailTemplateBuilder:
    """Builds email content from templates."""
    
    def __init__(self, template_dir: str = "config/templates"):
        """
        Initialize template builder.
        
        Args:
            template_dir: Directory containing template files
        """
        self.template_dir = Path(template_dir)
    
    def _load_template(self, template_name: str) -> str:
        """Load template file content."""
        template_path = self.template_dir / template_name
        
        if not template_path.exists():
            raise FileNotFoundError(f"Template not found: {template_path}")
        
        with open(template_path, 'r', encoding='utf-8') as f:
            return f.read()
    
    def _format_mga_list(self, mga_data: List[Dict[str, str]]) -> str:
        """
        Format MGA list for email.
        
        Args:
            mga_data: List of dicts with 'mga' and 'comentarios' keys
            
        Returns:
            Formatted string with all MGAs
        """
        if not mga_data:
            return "No se encontraron empresas disponibles."
        
        formatted_lines = []
        for item in mga_data:
            mga = item.get('mga', 'N/A')
            comentarios = item.get('comentarios', 'Sin requisitos especificados')
            formatted_lines.append(f"MGA: {mga}\nRequisitos: {comentarios}\n")
        
        return "\n".join(formatted_lines)
    
    def build_success_email(
        self,
        nombre_cliente: str,
        nombre_negocio: str,
        commodity: str,
        tipo_negocio: str,
        mga_data: List[Dict[str, str]]
    ) -> str:
        """
        Build success email with MGA list.
        
        Args:
            nombre_cliente: Client name
            nombre_negocio: Business name
            commodity: Commodity from PDF
            tipo_negocio: Business type identified
            mga_data: List of MGAs with requirements
            
        Returns:
            Formatted email body
        """
        template = self._load_template("email_success.txt")
        mga_list = self._format_mga_list(mga_data)
        
        return template.format(
            nombre_cliente=nombre_cliente,
            nombre_negocio=nombre_negocio,
            commodity=commodity,
            tipo_negocio=tipo_negocio,
            mga_list=mga_list
        )
    
    def build_not_found_email(
        self,
        nombre_cliente: str,
        nombre_negocio: str,
        commodity: str
    ) -> str:
        """
        Build not-found email.
        
        Args:
            nombre_cliente: Client name
            nombre_negocio: Business name
            commodity: Commodity that wasn't found
            
        Returns:
            Formatted email body
        """
        template = self._load_template("email_not_found.txt")
        
        return template.format(
            nombre_cliente=nombre_cliente,
            nombre_negocio=nombre_negocio,
            commodity=commodity
        )
    
    def build_subject(self, original_subject: str, business_name: str = None) -> str:
        """
        Build email subject line.
        
        Args:
            original_subject: Original email subject
            business_name: Optional business name to include
            
        Returns:
            Formatted subject
        """
        if business_name:
            return f"Re: {original_subject}"
        return f"Re: {original_subject}"


# Convenience function
def build_email_response(
    mga_data: List[Dict[str, str]],
    commodity: str,
    tipo_negocio: str,
    nombre_cliente: str = "Cliente",
    nombre_negocio: str = "su empresa",
    original_subject: str = "Submission New Venture"
) -> Dict[str, str]:
    """
    Build complete email response.
    
    Args:
        mga_data: List of MGAs (empty list = not found)
        commodity: Commodity from PDF
        tipo_negocio: Business type identified
        nombre_cliente: Client name
        nombre_negocio: Business name
        original_subject: Original email subject
        
    Returns:
        Dict with 'subject' and 'body' keys
    """
    builder = EmailTemplateBuilder()
    
    subject = builder.build_subject(original_subject, nombre_negocio)
    
    if mga_data:
        body = builder.build_success_email(
            nombre_cliente=nombre_cliente,
            nombre_negocio=nombre_negocio,
            commodity=commodity,
            tipo_negocio=tipo_negocio,
            mga_data=mga_data
        )
    else:
        body = builder.build_not_found_email(
            nombre_cliente=nombre_cliente,
            nombre_negocio=nombre_negocio,
            commodity=commodity
        )
    
    return {
        "subject": subject,
        "body": body
    }
