# HR Enterprise 11.2.3 — CLEAN FINAL

## رفع المشروع إلى GitHub
فك الضغط ثم ارفع **محتويات هذا المجلد مباشرة** إلى جذر repository `ahmed9143/HR`.
يجب أن يظهر `.github`, `server.py`, `requirements.txt` في جذر الريبو.

## Windows Build
GitHub Actions سيقوم تلقائياً بـ:
1. تثبيت Python/dependencies.
2. تشغيل اختبارات regression.
3. تشغيل startup + enterprise smoke tests.
4. بناء Desktop EXE.
5. بناء Network Server EXE.
6. اختبار EXE فعلياً.
7. بناء Inno Setup installer.
8. رفع الـEXE والـinstaller كـArtifacts.

مهم: تم نقل كود Enterprise smoke test إلى `ci/enterprise_smoke.py` لتجنب مشاكل اقتباس PowerShell التي كانت تسبب:
`SyntaxError: '(' was never closed`.

## التشغيل المحلي
- Desktop: `BUILD_WINDOWS_EXE.bat`
- Network server: `BUILD_NETWORK_EXE.bat`
- Installer: `BUILD_INSTALLER.bat`

## آخر تحديث أمني/تشغيلي — V11.2.5
تم إغلاق طبقة GET Scope النهائية، وتأمين تنزيلات المستندات وبطاقات ID/PDF، وإضافة Employee Onboarding وPermission Matrix وتحسين Employee Profile 360° مع الصورة وQR في الجزء العلوي. توليد QR وتعديل/رفع صورة الموظف متاحان للـAdmin/SuperAdmin فقط. جميع اختبارات Scope وEnterprise وSupplies الحالية PASS.

## التشغيل النهائي بدون Python أو إنترنت على جهاز المستشفى

- جهاز المستشفى النهائي **لا يحتاج Python ولا pip ولا Internet**.
- استخدم `HR Enterprise Setup.exe` من GitHub Actions؛ الـ installer يثبت ملف EXE الجاهز.
- أول دخول بعد تثبيت جديد:
  - Username: `admin`
  - Password: تُولَّد عشوائيًا عند أول تشغيل وتُكتب في الملف:
    `data/INITIAL_ADMIN_PASSWORD.txt`
    (أو اضبط `HR_BOOTSTRAP_PASSWORD` قبل التشغيل الأول — 12 حرفًا على الأقل).
    النظام يجبرك على تغييرها عند أول دخول، ثم يحذف الملف تلقائيًا.
    ⚠️ لم تعد هناك كلمة مرور افتراضية ثابتة.
- في أول دخول سيطلب النظام تغيير كلمة المرور. هذا مقصود للحماية.
- تغيير كلمة المرور لا يعيدها النظام تلقائياً في أي تشغيل لاحق.
- لو كانت قاعدة بيانات قديمة موجودة، لا يتم تغيير كلمة مرور `admin` تلقائياً.
- مكتبة ZKTeco يتم تضمينها داخل الـ EXE؛ لا تحتاج تثبيت `pyzk` على جهاز المستشفى.
- `requirements.txt` مطلوب **فقط على جهاز البناء/GitHub Actions**، وليس على جهاز التشغيل النهائي.

### التشغيل بدون إنترنت

بعد تثبيت الـ EXE، التطبيق يعمل محلياً باستخدام قاعدة SQLite والملفات المضمنة. الإنترنت غير مطلوب للتشغيل أو تسجيل الدخول أو الموظفين أو الحضور أو QR أو التقارير. الاتصال الخارجي مطلوب فقط إذا اخترت أنت ربط خدمة خارجية، وهو ليس جزءاً من التشغيل الأساسي.
