# HR Enterprise V8.0 — Hardening Edition

## التشغيل للمستخدم النهائي
1. ابنِ EXE مرة واحدة على جهاز البناء باستخدام `BUILD_WINDOWS_EXE.bat`.
2. انسخ `HREnterpriseV80.exe` إلى كل جهاز Windows.
3. المستخدم يضغط مرتين فقط على EXE. لا Python ولا pip ولا PowerShell ولا Internet مطلوبة.

## الشبكة المحلية
- أول جهاز يبدأ ولا يجد خادمًا موجودًا يصبح الخادم بعد Election آمن ضد بدء جهازين معًا.
- الأجهزة الأخرى تكتشف الخادم عبر LAN UDP Discovery.
- إذا كان 8899 مشغولًا يتم اختيار منفذ تلقائيًا حتى 8920.
- بيانات الخادم تحفظ في Windows `C:\ProgramData\HR Enterprise\Data`، وليس بجوار EXE.
- كل جهاز عميل يحفظ بصمة الخادم التي وثقها أول مرة، وأي تغيير في البصمة يظهر كتحذير بدل الاتصال الصامت.

## مهم بخصوص الإنترنت
البرنامج لا يحتاج Internet. تعدد الأجهزة يحتاج LAN/Wi-Fi مشتركة بين الأجهزة والخادم.

## البيانات
- SQLite WAL
- ملفات الموظفين خارج قاعدة البيانات
- SHA-256 للمستندات
- Backup ZIP مع manifest وفحص checksums
- Audit Hash Chain
- Session revocation / live permission refresh

## Import
- Excel / CSV
- Paste Grid
- ZIP لمجلدات الموظفين
- Folder Picker مباشر
- Clipboard file paste من المتصفح
- Native Windows Explorer clipboard bridge داخل EXE إذا كان pywin32 متاحًا في البناء
- Name-first matching مع مراجعة للحالات غير الآمنة

## Export
XLSX + CSV + Standalone HTML + PDF. HTML ملف مستقل ولا يعيد توجيه المستخدم إلى HTTP.

## Diagnostics
المستخدم يرى Request ID عند الخطأ. المسؤول يرى `/diagnostics/errors`.
`/health` العام يعرض أقل قدر من المعلومات، أما التفاصيل فتحتاج صلاحية داخل `/system/health.json`.

## الحساب الافتراضي
`admin / Admin@123` في أول تشغيل، ويجب تغيير كلمة المرور فورًا.


## V8.0 Enterprise Ultimate — إضافات رئيسية
- Daily Late Limit Ledger: حد يومي ثابت + مستخدم + متبقي + تجاوز، مع حفظ مستقل يمنع فقدان الحد.
- Holiday Calendar.
- Enterprise Center للمستندات والاعتمادات والتدريب والأصول والموافقات.
- Live access validation عند كل طلب حساس.
- SQL scope filtering للحضور بدل جلب 1000 سجل ثم التصفية في Python.
- Database indexes للـAttendance/Leaves/Documents/Payroll/Audit والتنبيهات.
- File signature validation للملفات المرفوعة.
- Payroll lock server-side.
- Leave/Overtime approval scope enforcement.
- Public health محدود، والتفاصيل في System Health بعد تسجيل الدخول.

### ملاحظة أمنية
الـLAN الافتراضي ما زال HTTP لتسهيل التشغيل الداخلي. للبيئات الحساسة يمكن تشغيل Reverse Proxy/HTTPS أو تزويد الخادم بشهادة TLS محلية قبل التوزيع الإنتاجي.

## V8.2 — استيراد عدة مجلدات بدون ZIP

من **مركز الاستيراد** أو **استيراد مجلدات الموظفين** أصبح بإمكانك:

1. اختيار `Employee_Folders` كاملًا مرة واحدة.
2. أو الضغط على `إضافة مجلد` واختيار أكثر من مجلد موظف منفصل في نفس العملية.
3. الضغط على `استيراد الكل مرة واحدة`.
4. النظام يطابق كل مجلد بالموظف، ويعرض المطابق والمحتاج للمراجعة.
5. كل عملية تحصل على رقم Import Run ويمكن مراجعتها من `سجل استيراد المجلدات`.
6. يمكن عمل `Rollback` للعملية نفسها فقط، مع استعادة المستندات السابقة التي تم استبدالها.

### مثال

```text
Employee_Folders/
├── 38 - شيماء.../
├── 86 - رضوان.../
└── 7 - سمر...
```

أو اختيار هذه المجلدات بشكل منفصل:

```text
38 - شيماء...
86 - رضوان...
7 - سمر...
```

ثم استيرادهم جميعًا في طلب واحد.


## V8.3 Enterprise Intelligence Suite
تمت إضافة HR Intelligence/Alerts، My HR Self-Service، Matching Center، Atomic Excel Import، Excel Paste Grid upgrades، Bulk Actions موسعة، Connected Devices/Heartbeat، وLogo variants، مع الحفاظ على Automatic Excel Mapping.
