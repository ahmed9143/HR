# HR Enterprise 11.1.1 — التشغيل والتوزيع

## 1) Windows Desktop — جهاز واحد

بعد نجاح GitHub Actions:

1. افتح تبويب **Actions** في GitHub.
2. افتح آخر Run أخضر.
3. من **Artifacts** نزّل:
   - `HR Enterprise Windows 11.1.1`
4. استخدم `HR Enterprise Setup.exe`.
5. بعد التثبيت سيظهر اختصار **HR Enterprise** على سطح المكتب.
6. أول دخول:
   - Username: `admin`
   - Password: `<HR_BOOTSTRAP_PASSWORD>`
7. غيّر كلمة المرور فورًا.

البيانات لا تُحفظ داخل مجلد البرنامج. على Windows تُحفظ في:

`C:\ProgramData\HR Enterprise\Data`

وبالتالي تحديث الـEXE لا يمسح قاعدة البيانات.

## 2) Network — عدة أجهزة

استخدم جهازًا واحدًا كـ **HR Server**. لا تضع ملف SQLite على Network Share.

على جهاز السيرفر:

- شغّل `HR Enterprise Network Server.exe`.
- البرنامج يستمع على الشبكة ويستخدم قاعدة بيانات محلية على جهاز السيرفر.
- الـFirewall يتم فتحه أثناء التثبيت بواسطة صلاحيات Administrator.

على أجهزة الموظفين/HR:

- شغّل `HR Enterprise.exe`.
- وضع Auto Discovery يبحث عن سيرفر HR داخل الشبكة.
- بعد العثور عليه يفتح واجهة HR من السيرفر.

بهذا الشكل عدة أجهزة تتعامل مع **سيرفر واحد وقاعدة بيانات واحدة** بدل فتح SQLite نفسها عبر مشاركة ملفات Windows.

## 3) GitHub

المشروع يحتوي بالفعل على:

`.github/workflows/windows-build.yml`

كل Push إلى `main` يشغل:

- Python compilation
- Regression tests
- V9/V10/V11 tests
- Enterprise smoke test
- Windows EXE build
- Network Server EXE build
- Inno Setup installer
- Artifact upload

إذا فشل اختبار مهم، الـworkflow يفشل ولا يرفع نسخة ناجحة مزيفة.

## 4) Branding

من داخل النظام كـAdmin:

- Branding Manager
- Login Logo
- Sidebar/Company Logo
- Report Logo
- Favicon
- ID Card Designer

لا تحتاج تعديل `server.py` لتغيير الشعار.

## 5) QR / ID Cards

لكل موظف:

- Generate QR
- Stable QR
- Regenerate
- Revoke
- Verify
- Audit trail
- USB/keyboard-wedge scanner
- Printable ID Card
- Bulk ID Cards

الـQR يحتوي على token عشوائي فقط وليس الرقم القومي أو IBAN أو بيانات شخصية حساسة.

## 6) Database Lock

النسخة تستخدم:

- SQLite WAL
- 60-second busy timeout
- foreign keys
- controlled startup initialization
- persistent data خارج مجلد الـEXE

في Network Mode لا تتم مشاركة ملف SQLite بين الأجهزة؛ السيرفر وحده يفتح قاعدة البيانات.

## 7) PostgreSQL

ملفات PostgreSQL موجودة للمهاجرة/النشر المتقدم. النسخة Network الحالية لا تحتاج PostgreSQL لتشغيل عدة أجهزة لأن كل العملاء يتصلون بسيرفر HR واحد عبر HTTP.

إذا احتجت PostgreSQL production لاحقًا، يتم نقل طبقة البيانات بدل فتح SQLite عبر الشبكة.
