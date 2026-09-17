# HR Enterprise — رفع وبناء Windows

## 1) رفع المشروع
ارفع **محتويات هذا المجلد** إلى جذر مستودع GitHub، وليس ملف ZIP داخل المستودع.

بعد أول Push سيعمل workflow:

`HR Enterprise Windows Build`

اسم التشغيل سيظهر بالـcommit SHA بدل `Add files via upload` حتى لا يختلط عليك اسم الـcommit مع اسم الـworkflow.

## 2) أين تجد النسخ
GitHub → Actions → HR Enterprise Windows Build → آخر Run ناجح → Artifacts.

الـArtifact يحتوي:
- `HR Enterprise.exe` — نسخة جهاز واحد/عميل تلقائية.
- `HR Enterprise Network Server.exe` — نسخة السيرفر للشبكة.
- `HR Enterprise Setup.exe` — Installer.

## 3) وضع جهاز واحد
ثبت `HR Enterprise Setup.exe` على الجهاز، ثم شغّل `HR Enterprise`.

البيانات تحفظ خارج مجلد البرنامج في Windows ProgramData، وليس بجوار الـEXE، حتى لا تتعرض للكتابة فوقها أثناء التحديث.

## 4) وضع الشبكة
على جهاز السيرفر شغّل `HR Enterprise Network Server.exe`.
على أجهزة المستخدمين شغّل `HR Enterprise.exe`.
العميل يحاول اكتشاف السيرفر على الشبكة قبل فتح قاعدة SQLite المحلية، لمنع مشكلة `database is locked` الناتجة عن فتح قاعدة مشتركة من أكثر من عملية.

## 5) ماذا يختبر GitHub Actions
قبل بناء الـEXE يتم تشغيل اختبارات المشروع. ثم:
- فحص schema وقواعد QR/contracts.
- بناء EXE.
- تشغيل EXE الحقيقي واختبار `/health`.
- بناء Network Server EXE.
- تشغيله واختبار `/health`.
- بناء Inno Setup installer.
- التأكد من وجود كل artifacts.

إذا فشل أي اختبار، **لن يتم اعتبار الـbuild ناجحًا**.
