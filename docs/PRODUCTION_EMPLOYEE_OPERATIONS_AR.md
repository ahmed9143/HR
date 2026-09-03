# مركز عمليات الموظفين — Production Operations

هذه الإضافة تجعل صفحة الموظفين نقطة تشغيل حقيقية للعمليات الجماعية، مع الحفاظ على طبقات HR Enterprise الموجودة.

## العمليات
- Bulk Users: ينشئ حساب Employee فقط للموظفين الذين لا يملكون حسابًا. كلمات المرور الجديدة فقط تظهر في CSV.
- Bulk QR: ينشئ QR للموظفين الذين لا يملكون QR فعالًا.
- Full Provision: ينشئ User + Temporary Password + QR + Employee Folder للموظفين الذين لا يملكون حسابًا، ثم ينزل ZIP شامل.
- Full Export: يصدر بيانات الموظفين والمستندات والصور وQR بدون كلمات مرور.
- Employee Folders: ينشئ مجلدًا مستقلًا لكل موظف.
- Employee Photos: مسار الصور يدعم الملفات على القرص وBLOB القديم داخل قاعدة البيانات، حتى لا تظهر الصور كمكسورة بعد الترحيل.

## ملف Bulk Provisioning
يحتوي على:
- employee_accounts.xlsx
- employee_accounts.csv
- QR/<employee>.png
- Employees/<employee>/employee.json
- Employees/<employee>/<category>/<documents>

كلمات المرور المؤقتة حساسة ويجب حفظ الملف في مكان آمن ثم حذفه بعد التسليم.

## QR
محرك QR مضمّن داخل `vendor/qrcode`، مع renderer PNG يعتمد على Python standard library، لذلك لا يعتمد إنشاء QR على وجود Pillow في بيئة التشغيل.

## الأمان
- لا يتم إعادة ضبط كلمات مرور الحسابات الموجودة تلقائيًا.
- الموظف الجديد يحصل على scope `self` و`employee_code` مرتبط بالحساب.
- العمليات الجماعية تحتاج الصلاحيات المناسبة وCSRF.
- كلمات المرور لا يمكن استرجاعها من الـ hash؛ لذلك الحسابات الموجودة تظهر كـ EXISTING ولا يتم اختراع كلمة مرور لها.
