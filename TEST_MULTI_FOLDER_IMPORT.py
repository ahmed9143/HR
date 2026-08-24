import re, os, sys
sys.path.insert(0, os.path.dirname(__file__))
import server

employees=[
    {'emp_code':'38','name':'شيماء القداح محمود الشربيني'},
    {'emp_code':'86','name':'رضوان عبد الهادى كمال رضوان'},
    {'emp_code':'7','name':'سمر محمد'},
]
paths=[
    '38 - شيماء القداح محمود الشربيني/contract.pdf',
    '86 - رضوان عبد الهادى كمال رضوان/id.jpg',
    '7 - سمر محمد/qualification.pdf',
    'Employee_Folders/38 - شيماء القداح محمود الشربيني/contract.pdf',
]
for p in paths:
    parts=[x.strip() for x in p.replace('\\','/').split('/') if x.strip()]
    matched=None
    for part in parts[:-1]:
        emp,kind,name=server.resolve_folder_employee(part,employees)
        if emp:
            matched=(emp,kind,name,part)
            break
    assert matched, f'No match: {p}'

# Short numeric codes must work.
assert server.resolve_folder_employee('7 - سمر محمد',employees)[0]=='7'
assert server.resolve_folder_employee('26 - غير موجود',employees)[0] is None
print('PASS: multiple independent folder paths + wrapped root + short codes')
