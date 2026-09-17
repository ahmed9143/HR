# HR Hospital — دليل التشغيل والتثبيت النهائي Offline

## 1) Build فقط
GitHub Actions هو مكان تنزيل Python وPackages وبناء ملفات Windows. جهاز المستشفى لا يحتاج Python أو pip أو Internet بعد استلام الـ EXE/Installer.

Artifacts المطلوبة:
- `HR Enterprise Setup.exe` — جهاز HR محلي.
- `HR Enterprise Network Server.exe` — سيرفر الشبكة داخل المستشفى.
- `HR Enterprise Network Server.msi` — بديل للتثبيت الشبكي.

## 2) أول تشغيل
تثبيت جديد تماماً:
- Username: `admin`
- Password: تُولَّد عشوائيًا عند أول تشغيل وتُكتب في الملف:
    `data/INITIAL_ADMIN_PASSWORD.txt`
    (أو اضبط `HR_BOOTSTRAP_PASSWORD` قبل التشغيل الأول — 12 حرفًا على الأقل).
    النظام يجبرك على تغييرها عند أول دخول، ثم يحذف الملف تلقائيًا.
    ⚠️ لم تعد هناك كلمة مرور افتراضية ثابتة.

أول دخول يطلب تغيير كلمة المرور. لا يتم Reset لكلمة مرور تثبيت قائم عند إعادة التشغيل أو التحديث.

## 3) Offline
كل التشغيل الأساسي محلي. SQLite موجودة في ProgramData على Windows، وليس داخل مجلد البرنامج، حتى لا تضيع البيانات عند تحديث الـ EXE.

لا تحذف مجلد بيانات HR عند Upgrade إذا كنت تريد الاحتفاظ بالبيانات.

## 4) شبكة المستشفى
شغّل `HR Enterprise Network Server.exe` على جهاز السيرفر. أجهزة المستخدمين تدخل على عنوان السيرفر داخل LAN. لا يلزم Internet.

## 5) ZKTeco
من `الإدارة → أجهزة البصمة`:
1. أضف اسم الجهاز.
2. IP.
3. Port (افتراضياً 4370).
4. Communication Password إن وجد.
5. Timeout.

مركز البصمة يعمل كالتالي:
- مراقبة Online/Offline.
- Background sync.
- Retry بعد فشل الاتصال.
- منع تشغيل Sync متزامن لنفس الجهاز.
- Raw punch deduplication.
- ربط ZK User ID بالموظف.
- معالجة Raw Punch إلى Attendance.
- Late / Early Leave / Overtime.
- Night/overnight shifts عند تعيين Shift بنهاية أقل من البداية.
- Leave/Holiday status.
- Device time وtime drift.
- Reconcile لمستخدمي الجهاز.
- Provisioning للموظفين إلى الجهاز.
- Sync history والأخطاء.

### مهم
Live Capture وFingerprint Template transfer ليستا مضمونة لكل موديلات ZKTeco. النظام يستخدمها فقط عندما تكون واجهة `pyzk` والموديل الفعلي يدعمانها. لا يتم اختراع نجاح وهمي.

## 6) Auto Sync
السيرفر يشغل Scheduler في الخلفية كل دقيقة. لا يحتاج أن تكون صفحة البصمة مفتوحة. إذا انقطع الجهاز، يظل HR شغالاً ويعيد المحاولة. عند عودة الجهاز، يتم سحب السجلات الموجودة على الجهاز وإدخالها مع dedup.

## 7) Attendance
المصدر الحقيقي هو `zk_attendance_raw`. بعد وصول البصمة ومعرفة الموظف، يعيد Attendance Engine بناء اليوم من الـ raw punches. هذا يمنع تلف الملخص إذا تمت إعادة المزامنة.

## 8) Backup
اعمل Backup قبل Upgrade أو نقل السيرفر. احتفظ بنسخة خارج الجهاز أيضاً. لا تحذف ProgramData أثناء إزالة البرنامج إذا كنت تريد البيانات.

## 9) ZKTeco troubleshooting
- Offline: تحقق من IP وPort 4370 وFirewall وPing واتصال الجهاز بالشبكة.
- Authentication/communication error: تحقق من Communication Password.
- Time drift: استخدم `ضبط الوقت` إذا كان موديل الجهاز يدعم `set_time`.
- User غير موجود: استخدم Reconcile.
- Punch غير مرتبط: اربط ZK User ID بالموظف ثم أعد المعالجة.
- لا تعتمد على الاسم في المطابقة؛ المطابقة الرسمية تكون عبر `zk_user_id`.

## 10) ترقية آمنة
لا تنقل قاعدة البيانات إلى مجلد البرنامج. لا تشغل نسخة Python على جهاز الإنتاج. حدّث الـ EXE/Installer فقط مع الحفاظ على Data directory.

## 11) ملاحظة الإنتاج
قبل الاعتماد النهائي في المستشفى، اختبر على جهاز ZKTeco الفعلي:
- اتصال.
- User موجود.
- بصمة دخول.
- بصمة خروج.
- Shift عادي.
- Night shift.
- جهاز Offline ثم Online.
- إعادة Sync مرتين.
- موظف غير مرتبط ثم ربطه.
- Device time.
- Backup/restore.
