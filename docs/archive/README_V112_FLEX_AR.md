# HR Enterprise 11.1.2 — Enterprise Flex

هذه النسخة مبنية على 11.1.1 Hardened وتضيف طبقة Admin/Flex بدون إزالة الوحدات القديمة.

## أهم الإضافات

- Employee Profile 360° مع صورة الموظف.
- رفع / استبدال / حذف صورة الموظف JPG/PNG/WEBP حتى 5MB.
- ظهور الصورة داخل Employee Directory والـProfile والـID Card.
- QR Identity ثابت وآمن: Generate / Regenerate / Revoke / Verify / Scanner / Audit.
- QR لا يحمل كلمة مرور أو رقم قومي أو راتب أو بيانات حساسة.
- شعار الشركة داخل QR عند توفره، مع الحفاظ على quiet-zone قابلة للطباعة.
- ID Card Designer: رفع Front/Back templates وتحديد أماكن Photo/Name/QR والحقول.
- ID Card Print + PDF + Bulk ID Cards.
- حساب User مرتبط مباشرة بالموظف مع Username/Role/Temporary Password وإجبار تغيير كلمة المرور.
- كلمات المرور لا تدخل أي Excel export.
- Leave Balance Center: تعديل مباشر + سبب التعديل + Audit history.
- Leave Balance Import من XLSX/CSV أو Paste مباشر من Excel.
- Auto mapping عربي/إنجليزي وPreview قبل Commit.
- Leave Balance Excel template/export.
- Employee Master Excel export مع User/QR metadata بدون passwords.
- Bulk QR ZIP يحتوي QR PNGs وemployees.xlsx.
- Shifts CRUD: إضافة / تعديل / حذف، مع منع حذف وردية مرتبطة بموظفين.
- Enterprise Admin Center.
- Branding وID templates بدون تعديل كود.
- Network MSI build definition + GitHub Actions artifact.
- إصلاح PyInstaller resource path للـfonts باستخدام absolute source path.

## Build validation

تم تشغيل:

- `python -m compileall -q .`
- `TEST_ENTERPRISE_STABLE.py`
- `TEST_FLEX_ACCEPTANCE.py`
- `TEST_ID_DESIGNER.py`

والثلاثة Acceptance tests تمر بنجاح في بيئة الاختبار المحلية.

## Windows artifacts

GitHub Actions يبني:

- `dist/HR Enterprise.exe`
- `dist/network/HR Enterprise Network Server.exe`
- `installer/HR Enterprise Setup.exe`
- `installer/HR Enterprise Network Server.msi`

الـMSI يتم بناؤه بواسطة WiX Toolset داخل GitHub Actions؛ لا يتم تخزين MSI مولد من Linux داخل هذا المصدر.
