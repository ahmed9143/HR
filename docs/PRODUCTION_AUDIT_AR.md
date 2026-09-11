# HR Enterprise 11.2.2 — Production Audit

## الحالة

**Security Hardened / Regression Tested** — هذه الحزمة ليست بديلًا عن اختبارها على نسخة من قاعدة البيانات الحقيقية قبل الإنتاج.

## أهم الإصلاحات

### 1. First-run Admin Security
- لم تعد كلمة المرور `Admin@123` موجودة في كود التشغيل.
- أول تشغيل يقبل `HR_BOOTSTRAP_PASSWORD` (12 حرفًا على الأقل).
- إذا لم يتم تعيين المتغير، يتم توليد كلمة مرور عشوائية قوية مرة واحدة وحفظها في `INITIAL_ADMIN_PASSWORD.txt` داخل مجلد البيانات.
- يتم إجبار المسؤول على تغيير كلمة المرور عند أول دخول.
- الحساب الموجود بالفعل لا يتم Reset له عند إعادة تشغيل النظام.

### 2. Employee Account Isolation
- بوابة الموظف تعتمد على `employee_code` المرتبط بالحساب ثم نطاق الوصول، ولا تثق في `emp_code` يرسله المستخدم لتحديد بياناته.
- صفحة ملف الموظف تتحقق من `emp_allowed()` قبل عرض البيانات.
- طلبات My HR تستخدم كود الموظف المستنتج من جلسة الحساب.
- إنشاء حسابات الموظفين لا يسمح لحسابات الموظفين العادية بإنشاء Admin/SuperAdmin.

### 3. File Security
- رفع الملفات يتحقق من الامتداد **وتوقيع الملف**.
- نفس التحقق مطبق في استيراد مجلدات الموظفين.
- تنزيل الملفات يتحقق من نطاق الموظف قبل القراءة.
- مسارات التخزين تمر عبر حماية تمنع Path Traversal.
- Native Clipboard Bridge أصبح مربوطًا بجلسة المستخدم وبصلاحية الوصول للموظف، والتوكن One-Time.

### 4. Session / Browser Security
- Session cookie: `HttpOnly` + `SameSite=Lax`، و`Secure` عند HTTPS.
- إضافة Security Headers منها CSP و`X-Content-Type-Options` و`X-Frame-Options` و`Referrer-Policy`.
- انتهاء الجلسة يتم التحقق منه server-side.
- تعطيل الحساب أو تغيير الصلاحيات يلغي صلاحية الجلسة القديمة.
- CSRF مطلوب في العمليات التي تغير البيانات.

### 5. Architecture / Regression
- تم الحفاظ على طبقات V9/V10/V11/Enterprise/V12 بدل حذف Features موجودة.
- تم اختبار الـ routes والـ feature layers بعد التعديلات.
- تم حذف `__pycache__` من حزمة الإصدار.

## الاختبارات المنفذة

- `TEST_FINAL.py` — PASS
- `TEST_ENTERPRISE_STABLE.py` — PASS
- `TEST_ID_DESIGNER.py` — PASS
- `TEST_V12_ENTERPRISE.py` — PASS
- `TEST_V11_ACCEPTANCE.py` — 0 failures
- `TEST_V10_COMPLETE.py` — PASS
- `TEST_V90_COMPLETE.py` — PASS
- `TEST_MULTI_FOLDER_IMPORT.py` — PASS
- Python `compileall` — PASS
- SQLite `integrity_check` — PASS

## قبل Production

1. خذ Backup كامل لقاعدة البيانات وملفات الموظفين.
2. جرّب الحزمة على Clone من الـ Data الحقيقية، وليس على النسخة الأصلية.
3. اختبر حساب Employee وحساب HR وحساب Manager وحساب Admin.
4. اختبر أن Employee A لا يستطيع الوصول إلى بيانات Employee B.
5. اختبر Upload / Download / QR / ID Card / Payroll / Leave.
6. بعد تغيير كلمة مرور Admin، احذف `INITIAL_ADMIN_PASSWORD.txt` إن كان قد تم إنشاؤه.
7. لا ترفع مجلد `data` الذي يحتوي على قاعدة بيانات حقيقية إلى GitHub أو أي مستودع عام.

## First Run

يفضل تشغيل النظام مع:

`HR_BOOTSTRAP_PASSWORD=<strong-password-at-least-12-chars>`

مثال Windows CMD:

`set HR_BOOTSTRAP_PASSWORD=ضع-كلمة-مرور-قوية-هنا`

ثم شغل النظام. غيّر كلمة المرور بعد الدخول واحذف ملف كلمة المرور الأولية إذا تم إنشاؤه.
