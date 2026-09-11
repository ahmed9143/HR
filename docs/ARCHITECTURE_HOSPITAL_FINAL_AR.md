# HR Hospital — Final Architecture Profile

## الهدف
نظام HR صغير/متوسط لمستشفى محلية: سريع، واضح، قليل التعقيد، ولا توجد عملية ثقيلة تمسك HTTP request لوقت طويل.

## الوحدات الرئيسية
- Dashboard
- Employees
- Attendance & ZKTeco
- Leaves
- Shifts
- Payroll summary/export
- Documents
- QR & ID Cards
- Reports
- Excel Import/Export
- Administration

## ZKTeco
صفحة واحدة داخل الإدارة: `/zkteco/devices`، وبداخلها روابط/تبويبات للأجهزة، المزامنة، غير المرتبطين، وسجلات الحضور.

## Bulk jobs
كل العمليات الثقيلة تستخدم Job Manager داخل `stable_final.py`:
- Bulk Users
- Bulk QR
- QR Generate All / QR Bulk
- Full Provisioning
- Full Export
- Employee Folders

الواجهة لا تنتظر العملية؛ تعرض progress وتسمح بالتنقل. كل عنصر يعالج بشكل مستقل، والفشل في موظف لا يوقف باقي الموظفين.

## Payroll
هذا الملف يصف Payroll كملخص وحسابات HR/Export فقط. لا يوجد محرك مالي Enterprise ضخم ما لم يكن مطلوبًا مستقبلًا.

## Permissions
الأدوار العملية: SuperAdmin, Admin, HR, Manager, Attendance, Employee/Viewer حسب الصلاحيات الموجودة. أدوات التشخيص والشبكة والنسخ الاحتياطي تبقى Admin-only.

## Legacy modules
الملفات التاريخية V10/V11/V12/V13/V14 تبقى في الحزمة لأسباب التوافق والبيانات القديمة، لكن `stable_final.py` هو طبقة التشغيل الأخيرة التي تمنع التكرار في الـ sidebar وتفرض مسارات العمليات الثقيلة الآمنة.
