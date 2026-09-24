# HR Enterprise V7.4 Enterprise

## تشغيل المستخدم النهائي
بعد بناء `HREnterpriseV74.exe` على Windows:

**المستخدم النهائي لا يحتاج Python أو pip أو PowerShell أو BAT أو Internet.**

فقط:

> Double Click → `HREnterpriseV74.exe`

- أول جهاز لا يجد HR Server على الشبكة يبدأ كـ Server تلقائيًا.
- الأجهزة التالية تكتشف السيرفر تلقائيًا عبر LAN وتفتح نفس قاعدة البيانات.
- إذا كان المنفذ 8899 مشغولًا، يتم اختيار منفذ متاح تلقائيًا ضمن 8899–8910 ويُعلن الجهاز المنفذ الجديد عبر Discovery.
- Internet غير مطلوب.
- لو تريد أجهزة متعددة ترى نفس البيانات، يجب أن تكون على نفس LAN/Wi‑Fi وقواعد Windows Firewall تسمح بالاتصال المحلي.

## أهم التحسينات V7.4
- Error Center حقيقي مع Request ID وStack Trace للمسؤول بدل Generic Error فقط.
- System Health: Database Integrity + Storage + Network + Port + Audit Chain.
- Health API مفصل على `/health`.
- Diagnostics API على `/diagnostics/test` للمسؤول.
- Network Center مع الأجهزة المتصلة وIP وآخر نشاط وLatency.
- Auto Server Discovery على الشبكة المحلية.
- Auto Port Fallback إذا كان 8899 مشغولًا.
- Daily automatic backup قابل للضبط من Settings.
- Excel Export: XLSX + CSV + HTML + PDF.
- HTML Export ملف HTML حقيقي مستقل، وليس Redirect إلى HTTP.
- Excel Paste Grid والتحقق قبل الاستيراد موجودان في Import Center.
- Folder ZIP + Folder Picker مباشر + محاولة Paste للملفات من Clipboard.
- Name-first folder matching؛ الكود ليس مطلوبًا للمطابقة الأساسية.
- Missing Documents Tracker.
- Document Versioning + SHA-256.
- Employee 360 + Previous/Next + Evaluation percentage + grade + trend.
- RBAC + Department Scope + Sensitive Data Masking.
- Bulk archive/restore/export + Advanced Filters + Saved Views.
- Logo Upload من Settings ويظهر في Login وSidebar.
- Audit Hash Chain + Backup/Restore.

## Import المجلدات
يمكنك تجهيز:

```
Employees/
  Ahmed Mohamed/
    ID.jpg
    Contract.pdf
    Qualification.pdf
  Mona Hassan/
    ID.jpg
    Contract.pdf
```

ثم من **Documents → Employee Folders**:
- ZIP
- أو اختيار المجلد مباشرة من Windows
- أو محاولة Ctrl+V للملفات في منطقة اللصق

المطابقة تعتمد على اسم المجلد، مع رفض التطابق غير الآمن للمراجعة اليدوية.

## الشيت
استخدم `Employees_Demo.xlsx` كنموذج عمل. يمكن أيضًا استخدام Excel Center → Paste، والـMapping محفوظ باسم Hospital Employee Template.

## بيانات أول تشغيل
Username: `admin`
Password: `<HR_BOOTSTRAP_PASSWORD>`

سيطلب النظام تغيير كلمة المرور في أول دخول.

## بناء EXE
بناء Windows EXE الحقيقي يجب أن يتم على جهاز Windows باستخدام `BUILD_WINDOWS_EXE.bat`. بعد البناء، الملف الوحيد الذي يحتاجه المستخدم النهائي هو:

`dist\HREnterpriseV74.exe`

لا يتم ادعاء وجود Windows EXE جاهز إذا لم يتم بناؤه على Windows فعليًا.
