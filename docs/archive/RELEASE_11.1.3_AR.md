# HR Enterprise 11.1.3 Enterprise Flex+

هذه النسخة مبنية على 11.1.2 Enterprise Flex وتجمع طبقة Enterprise/Flex الحالية مع إصلاحات البناء.

## الموجود فعليًا
- Employee 360 Profile مع صورة الموظف ورفع/استبدال/حذف الصورة.
- QR Identity: إصدار، تجديد، إلغاء، تحقق، Scanner USB، وتصدير QR ZIP.
- Employee User Account مرتبط بالموظف، Role، وإعادة تعيين كلمة المرور. كلمات المرور لا تدخل Excel.
- ID Card + PDF/Print + Bulk + رفع Template من داخل النظام.
- Leave Balance: تعديل مباشر، Import Excel، Paste، Preview، History، Export وTemplate.
- Excel mapping عربي/إنجليزي مرن.
- Shift: إضافة، تعديل، حذف مع منع حذف وردية مرتبطة بموظفين.
- RBAC وصلاحيات على السيرفر.
- Admin Center للتخصيص والـBranding والـTemplates.

## Build
GitHub Actions يبني:
1. HR Enterprise.exe
2. HR Enterprise Network Server.exe
3. HR Enterprise Setup.exe
4. HR Enterprise Network Server.msi

تم إصلاح سبب فشل Network build السابق: مسار fonts أصبح relative (`fonts;fonts`) بدل مسار مطلق هش.

## ملاحظة Network
نسخة Network الحالية تستخدم نفس محرك التطبيق/SQLite الموجود في المشروع. مسار PostgreSQL موجود للترقية الإنتاجية لكنه ليس شرطًا لتثبيت MSI الحالي.
