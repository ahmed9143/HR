# HR Enterprise 11.2 — Network + PostgreSQL

## الهدف
نسخة Network Server واحدة على جهاز السيرفر، وكل أجهزة HR تتصل بها عبر الشبكة. عند وضع ملف `postgres_url.txt` بجوار `HR Enterprise Network Server.exe` يستخدم النظام PostgreSQL بدل SQLite.

## 1) PostgreSQL
- استخدم PostgreSQL 16+.
- أنشئ قاعدة `hr_enterprise` ومستخدمًا مخصصًا.
- نفّذ `postgresql/schema.sql` ثم شغّل `postgresql/verify.py`.
- عدّل كلمة المرور في `postgres_url.txt` ولا تضعها في GitHub.

مثال:
`postgresql://hr_admin:YOUR_PASSWORD@SERVER_IP:5432/hr_enterprise`

## 2) تشغيل السيرفر
ضع بجوار `HR Enterprise Network Server.exe`:
- `postgres_url.txt`
- لا تحتاج Python أو CMD أو PowerShell على جهاز المستخدم.

شغّل الـEXE مرة واحدة على جهاز السيرفر.

## 3) أجهزة الموظفين/HR
استخدم `HR Enterprise.exe` أو Client/Discovery. النظام يبحث عن HR Server على الشبكة ويعيد فتح الواجهة بدون فتح قاعدة البيانات محليًا.

## 4) MSI
`BUILD_NETWORK_MSI.bat` يبني:
`installer\HR Enterprise Network Server.msi`

يتطلب WiX Toolset على جهاز الـBuild فقط.

## 5) الأمان
- لا تضع كلمة مرور PostgreSQL داخل المستودع.
- افتح TCP 5432 فقط بين Network Server وPostgreSQL إذا كان PostgreSQL على جهاز منفصل.
- افتح منفذ HR (عادة 8899 أو المنفذ الذي يظهره النظام) لأجهزة HR فقط.
