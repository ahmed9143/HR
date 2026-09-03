# HR Enterprise 8.0.1 — Folder Import Fix

## Fixed
- Direct Windows folder import no longer treats the selected root folder (for example `Employee_Folders`) as an employee.
- ZIP imports now support an optional wrapper folder such as `Employee_Folders/Employee Name/file.pdf`.
- Short employee codes such as `7 - Name` and `26 - Name` are now matched by code.
- Nested files/subfolders under each employee folder are preserved for document import.

## Verified
- 109 employee folders matched to 109 employee records from the supplied upload workbook.
- 0 unmatched folders in the supplied demo package.
