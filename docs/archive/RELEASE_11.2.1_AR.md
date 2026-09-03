# HR Enterprise 11.2.1 — Enterprise Flex Final

## تم تنفيذ هذه الجولة

- Universal Excel Mapping أصبح مشتركًا بين قوالب الموظفين المحفوظة، وليس مرتبطًا بشيت واحد فقط.
- Leave Balance: Upload + Paste + Preview + Commit + تعديل يدوي + History + Export + Template.
- Employee Profile: QR + Photo + ID Card + User Account داخل نفس الملف.
- QR Identity: Generate / Regenerate / Revoke / Verify / Scan + Bulk + ZIP/Excel export.
- QR في قائمة الموظفين مع رابط البطاقة، وحالة المستخدم بجانب الموظف.
- إنشاء User من ملف الموظف باسم ثنائي تلقائي بعد تحويل الاسم العربي إلى username لاتيني، مع كلمة مرور تلقائية أو يدوية.
- إعادة إنشاء حساب الموظف تقوم بتحديث الحساب المرتبط بدل إنشاء حسابات مكررة.
- Employee Master Export يشمل Username / Role / User Status / QR ID / QR Status / QR File، بدون كلمات مرور.
- ID Card Designer: رفع Front/Back + سحب الصورة والاسم والـQR + حفظ الإحداثيات.
- Branding/Login: Logo + Login background + Font + Accent + Tagline.
- SQLite: WAL + busy timeout + backup آمن موجود في الـcore.
- Network: HR Enterprise Network Server EXE + MSI definition + PostgreSQL configuration.
- Build Network: تثبيت مسارات assets بشكل صريح لتفادي مشكلة `build\\network\\fonts`.
- Shifts: تعديل + حذف للورديات غير المرتبطة بموظفين، مع منع الحذف إذا كانت مرتبطة.

## اختبارات محلية ناجحة

- `python -m py_compile server.py v12_enterprise.py enterprise_completion.py HR_NETWORK_SERVER.py`
- `python TEST_V12_ENTERPRISE.py`
- `python TEST_FLEX_ACCEPTANCE.py`
- `python TEST_ID_DESIGNER.py`
- Final route smoke: `/employees`, `/qr/center`, `/qr/scan`, `/leave-balances`, `/import/mapping`, `/branding/id-card-template`

## بناء Windows

على Windows Build PC فقط:

1. `BUILD_ALL_WINDOWS.bat`
2. أو GitHub Actions workflow: `.github/workflows/windows-build.yml`

الناتج المتوقع:

- `dist\\HR Enterprise.exe`
- `dist\\network\\HR Enterprise Network Server.exe`
- `installer\\HR Enterprise Setup.exe`
- `installer\\HR Enterprise Network Server.msi`

## Network / PostgreSQL

ضع `postgres_url.txt` بجوار Network Server EXE، ولا تضع كلمة المرور داخل GitHub.

مثال موجود في `postgres_url.example.txt`.
