# Email Templates

## Usage

These templates are used for automatic email responses.

### Variables Available

**email_success.txt** - Successful MGA match
- `{nombre_cliente}` - Client name (from email)
- `{nombre_negocio}` - Business name (from PDF)
- `{commodity}` - Commodity extracted from PDF
- `{tipo_negocio}` - Business type identified
- `{mga_list}` - Formatted list of MGAs with requirements

**email_not_found.txt** - Commodity not found
- `{nombre_cliente}` - Client name (from email)
- `{nombre_negocio}` - Business name (from PDF)
- `{commodity}` - Commodity that wasn't found

### MGA List Format

The `{mga_list}` will be formatted as:

```
MGA: [Company Name]
Requisitos: [Requirements text]

MGA: [Company Name]
Requisitos: [Requirements text]

...
```

### Example Subject Lines

**Success**: `Re: Submission New Venture - [Business Name]`
**Not Found**: `Re: Submission New Venture - [Business Name] - Información Adicional Requerida`
